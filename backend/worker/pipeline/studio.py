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
from .stages.dsp_utils import apply_biquad, peaking_coeffs, true_peak_db
from .stages.polish import _deess
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


def apollo_delta(folder, source, rate):
    cached = folder / "apollo-delta.wav"
    with GPU_LOCK:
        if not cached.is_file():
            work = folder / "apollo-input.wav"
            decode_file(folder / "source.wav", work, source.shape[1], 44100)
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
                 bass: int = 0, rhythm: int = 0, velvet: int = 0, repair: bool = False):
    analysis = {}
    if repair:
        analysis = json.loads((folder / "track.json").read_text(encoding="utf-8")).get("analysis", {})
    kind = analysis.get("kind")
    source = "peaks.wav" if kind == "peaks" else "source.wav"
    sound, rate = sf.read(folder / source, dtype="float32", always_2d=True)
    if kind == "band":
        sound = band_version(folder, sound, rate, analysis["edgeHz"])
    elif restore:
        sound += apollo_delta(folder, sound, rate) * (restore / 100)
    if clarity:
        amount = clarity / 100
        for freq, db, q in [(300, -3.5 * amount, .85), (3400, 5 * amount, 1.0)]:
            b, a = peaking_coeffs(min(freq, rate * .42), db, rate, q)
            sound = apply_biquad(sound, b, a).astype("float32")
    if deess:
        high = min(9200, rate * .45)
        sound = _deess(sound, rate, low=min(4200, high * .53), high=high,
                       threshold_db=-21 - .20 * deess, ratio=1 + .07 * deess).astype("float32")
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
    peak = peak_db(sound)
    ceiling_gain = 1.0
    if peak > -1:
        ceiling_gain = float(10 ** ((-1 - peak) / 20))
        sound *= ceiling_gain
        peak = -1
    stats = measurements(sound, rate, peak)
    stats["ceilingGain"] = ceiling_gain
    return sound, rate, stats


def separate_audio(folder):
    with GPU_LOCK:
        markers = [folder / "vocals.wav", folder / "instrumental.wav"]
        if not all(path.is_file() for path in markers):
            run_stem_separate(str(folder / "source.wav"))
        if not all(path.is_file() for path in markers):
            raise RuntimeError("두 스템을 모두 생성하지 못했습니다.")
