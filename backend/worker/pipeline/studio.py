"""Signal processing shared by studio monitoring and WAV export."""

import json
import math
import subprocess
import threading
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.signal import resample_poly

from .stages.artifact_restore import run_artifact_restore
from .stages.band_repair import repair_band
from .stages.dsp_utils import apply_biquad, low_shelf_coeffs, peaking_coeffs, true_peak_db
from .stages.polish import _deess
from .stages.pcm24 import quantize_samples
from .stages.sound_lab import ghost_bass, rhythm_focus, velvet_room
from .stages.stem_separate import run_stem_separate


GPU_LOCK = threading.Lock()
BAND_LOCK = threading.Lock()


def peak_db(audio):
    block = 131072
    if len(audio) <= block:
        return true_peak_db(audio)
    # Ignore the padding of each internal FFT/filter boundary when metering.
    peak = 0.0
    for start in range(0, len(audio), block):
        end = min(start + block, len(audio))
        left = max(0, start - 32)
        upsampled = resample_poly(audio[left:end + 32], 4, 1, axis=0)
        centre = upsampled[(start - left) * 4:(end - left) * 4]
        peak = max(peak, np.max(np.abs(centre)))
    return 20 * np.log10(peak + 1e-12)


def loudness(audio, rate):
    if len(audio) < math.ceil(rate * 0.4) or not np.any(audio):
        return None
    value = pyln.Meter(rate).integrated_loudness(audio)
    return round(float(value), 2) if np.isfinite(value) else None


def measurements(audio, rate, peak):
    return {"lufs": loudness(audio, rate),
            "truePeak": round(float(peak), 2) if peak > -150 else None}


def decode_file(source, destination, channels, rate=None):
    args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-map", "0:a:0", "-map_metadata", "-1",
            "-ac", str(channels), "-c:a", "pcm_f32le"]
    if rate:
        args.extend(["-ar", str(rate)])
    subprocess.run([*args, str(destination)], capture_output=True, check=True)


def apollo_delta(folder, source, rate, source_name="source.wav"):
    cached = folder / "apollo-delta.wav"
    with GPU_LOCK:
        if not cached.is_file():
            work = folder / "apollo-input.wav"
            decode_file(folder / source_name, work, source.shape[1], 44100)
            original, _ = sf.read(work, dtype="float32", always_2d=True)
            if len(original) < 1024 or np.max(np.abs(original)) < 1e-7:
                residual = np.zeros_like(source)
            else:
                restored_file = run_artifact_restore(str(work), subtype="FLOAT")
                restored, _ = sf.read(restored_file, dtype="float32", always_2d=True)
                residual = restored - original
                if rate != 44100:
                    factor = math.gcd(rate, 44100)
                    residual = resample_poly(residual, rate // factor, 44100 // factor, axis=0)
                if len(residual) < len(source):
                    residual = np.pad(residual, ((0, len(source) - len(residual)), (0, 0)))
                residual = residual[:len(source)]
            temp = folder / "apollo-delta.part.wav"
            sf.write(temp, residual, rate, subtype="FLOAT")
            temp.replace(cached)
    return sf.read(cached, dtype="float32", always_2d=True)[0]


def band_version(folder, sound, rate, edge):
    cached = folder / "band-repaired.wav"
    with BAND_LOCK:
        if not cached.is_file():
            delta = apollo_delta(folder, sound, rate)
            repaired = repair_band(sound, delta, rate, edge)
            if not np.isfinite(repaired).all():
                raise ValueError("고역을 복원하지 못했습니다.")
            pending = folder / "band-repaired.part.wav"
            try:
                sf.write(pending, repaired, rate, subtype="FLOAT")
                pending.replace(cached)
            finally:
                pending.unlink(missing_ok=True)
            return repaired
    return sf.read(cached, dtype="float32", always_2d=True)[0]


def render_audio(folder: Path, clarity: int, deess: int, width: int, restore: int,
                 bass: int = 0, rhythm: int = 0, velvet: int = 0, repair: bool = False,
                 region=None, output="mix", fullness=0, bits=0, dither=False):
    metadata = folder / "track.json"
    info = json.loads(metadata.read_text(encoding="utf-8")) if metadata.is_file() else {}
    paired = info.get("stemPair", False)
    analysis = info.get("analysis", {}) if repair else {}
    kind = analysis.get("kind")
    dry_name = "vocals.wav" if paired else "source.wav"
    source = "peaks.wav" if kind == "peaks" else dry_name
    sound, rate = sf.read(folder / source, dtype="float32", always_2d=True)
    if kind == "band":
        sound = band_version(folder, sound, rate, analysis["edgeHz"])
    elif restore:
        sound += apollo_delta(folder, sound, rate, dry_name) * (restore / 100)
    if clarity:
        amount = clarity / 100
        for freq, db, q in [(300, -3.5 * amount, .85), (3400, 5 * amount, 1.0)]:
            b, a = peaking_coeffs(min(freq, rate * .42), db, rate, q)
            sound = apply_biquad(sound, b, a).astype("float32")
    if deess:
        high = min(9200, rate * .45)
        sound = _deess(sound, rate, low=min(4200, high * .53), high=high,
                       threshold_db=-21 - .20 * deess, ratio=1 + .07 * deess).astype("float32")
    if fullness:
        b, a = low_shelf_coeffs(min(220, rate * .42), 4 * fullness / 100, rate, slope=1)
        sound = apply_biquad(sound, b, a).astype("float32")
    if width and sound.shape[1] == 2:
        side = (sound[:, 0] - sound[:, 1]) * (.004 * width)
        sound[:, 0] += side
        sound[:, 1] -= side
    if rhythm:
        sound = rhythm_focus(sound, rate, rhythm / 100)
    if bass:
        sound = ghost_bass(sound, rate, bass / 100)
    if velvet:
        sound = velvet_room(sound, rate, velvet / 100)
    if not np.isfinite(sound).all():
        raise ValueError("처리 결과를 확인할 수 없습니다.")
    # Keep filter history leading into the excerpt, then blend only the chosen
    # samples. Limit the wet excerpt before blending so other frames stay dry.
    start, end = 0, len(sound)
    if region:
        start, end = (round(region[key] * rate) for key in ("start", "end"))
        if not 0 <= start < end <= len(sound):
            raise ValueError("유효하지 않은 보정 구간입니다.")
    wet = sound[start:end]
    peak = peak_db(wet)
    ceiling_gain = 1.0
    # For an imported pair the dry mix already has fixed headroom. A bypass
    # must reproduce that mix even when the dry vocal alone is above -1 dBTP.
    bypass_pair = paired and output == "mix" and not any((kind in ("peaks", "band"), clarity,
                                                          deess, width, restore, rhythm, bass, velvet,
                                                          fullness, bits))
    ceiling_db = -1.
    if bits:
        # Each phase of the 4x true-peak interpolator has coefficient L1 norm
        # below 2.25. Reserve its worst-case rounding/dither overshoot so the
        # final samples can remain on the exact quantization grid.
        max_error = (1.5 if dither else .5) / (1 << (bits - 1))
        ceiling_db = 20 * math.log10(10 ** (-1 / 20) - 2.25 * max_error)
    if peak > ceiling_db and not bypass_pair:
        ceiling_gain = float(10 ** ((ceiling_db - peak) / 20))
        wet *= ceiling_gain
    if bits:
        quantize_samples(wet, bits, dither)
    if region:
        dry, _ = sf.read(folder / dry_name, dtype="float32", always_2d=True)
        fade = min(round(.005 * rate), len(wet) // 2)
        if fade:
            # Complementary amplitudes preserve identical dry/wet audio. A
            # half cosine also eases the change of gain at both boundaries.
            phase = np.linspace(0, np.pi, fade, dtype="float64")
            ramp = ((1 - np.cos(phase)) * .5).astype("float32")[:, None]
            if start:
                wet[:fade] = dry[start:start+fade] + ramp * (wet[:fade] - dry[start:start+fade])
            if end < len(dry):
                wet[-fade:] = dry[end-fade:end] + ramp[::-1] * (wet[-fade:] - dry[end-fade:end])
        dry[start:end] = wet
        sound = dry
    if paired and output == "mix":
        backing, _ = sf.read(folder / "instrumental.wav", dtype="float32", always_2d=True)
        sound = (sound + backing) * np.float32(info["mixGain"])
    peak = peak_db(sound) if paired or region or bits else peak + 20 * math.log10(ceiling_gain)
    stats = measurements(sound, rate, peak)
    if region:
        original_path = folder / ("vocals.wav" if output == "vocals" else "source.wav")
        reference, _ = sf.read(original_path, start=start, stop=end, dtype="float32", always_2d=True)
        stats["regionLevels"] = {
            **region,
            "originalLufs": loudness(reference, rate),
            "processedLufs": loudness(sound[start:end], rate),
        }
    # The monitor removes a whole-file gain when testing for an audible change.
    # A gain confined to an excerpt or vocal stem is part of the actual edit.
    stats["ceilingGain"] = 1.0 if region or (paired and output == "mix") else ceiling_gain
    return sound, rate, stats


def separate_audio(folder):
    with GPU_LOCK:
        markers = [folder / "vocals.wav", folder / "instrumental.wav"]
        if not all(path.is_file() for path in markers):
            run_stem_separate(str(folder / "source.wav"))
        if not all(path.is_file() for path in markers):
            raise RuntimeError("두 스템을 모두 생성하지 못했습니다.")
