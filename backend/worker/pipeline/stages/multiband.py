from pathlib import Path

import numpy as np
import soundfile as sf

from .dsp_utils import apply_sos, bandpass_sos, envelope

# Subtractive band-split: low = lowpass(x), high = highpass(x), mid = x - low - high.
# low+mid+high always sums back to x exactly (no crossover phase/ripple issues),
# so each band can be compressed independently and safely re-summed.


def _lowpass_sos(freq, sr, order=4):
    from scipy.signal import butter
    return butter(order, freq / (sr / 2), btype="low", output="sos")


def _highpass_sos(freq, sr, order=4):
    from scipy.signal import butter
    return butter(order, freq / (sr / 2), btype="high", output="sos")


def _band_compress(band: np.ndarray, sr: int, threshold_db: float, ratio: float, time_ms: float = 30.0, makeup_db: float = 0.0) -> np.ndarray:
    abs_max = np.max(np.abs(band), axis=1)
    env = envelope(abs_max, sr, time_ms)
    env_db = 20 * np.log10(env + 1e-9)
    over_db = np.clip(env_db - threshold_db, 0, None)
    gain_reduction_db = over_db * (1 - 1 / ratio)
    gain = 10 ** ((-gain_reduction_db + makeup_db) / 20)
    return band * gain[:, None]


def run_multiband_compress(
    audio_path: str,
    low_split: float = 150.0,
    high_split: float = 4000.0,
) -> str:
    """3-band compression so a loud bass hit can't duck the vocal/mid band the
    way a single wideband compressor does — each band gets independently
    tuned gain reduction, which is what actually improves perceived
    separation between elements instead of the whole mix pumping together."""
    print(f"[Stage] Multiband compression (<{low_split}Hz / {low_split}-{high_split}Hz / >{high_split}Hz): {audio_path}")

    data, sr = sf.read(audio_path, dtype="float32", always_2d=True)

    low = apply_sos(data, _lowpass_sos(low_split, sr))
    high = apply_sos(data, _highpass_sos(high_split, sr))
    mid = data - low - high

    low = _band_compress(low, sr, threshold_db=-20.0, ratio=4.0, makeup_db=1.0)
    mid = _band_compress(mid, sr, threshold_db=-18.0, ratio=2.0, makeup_db=0.5)
    high = _band_compress(high, sr, threshold_db=-22.0, ratio=3.0, makeup_db=0.0)

    processed = low + mid + high

    peak = np.max(np.abs(processed))
    if peak > 0.99:
        processed = processed * (0.99 / peak)

    out_path = str(Path(audio_path).with_name(Path(audio_path).stem + "_multiband.wav"))
    sf.write(out_path, processed, sr)
    return out_path


def run_harmonic_exciter(
    audio_path: str,
    low: float = 200.0,
    high: float = 800.0,
    drive: float = 3.0,
    mix: float = 0.15,
) -> str:
    """Adds subtle 2nd/3rd-order harmonics derived from the vocal fundamental
    range via soft saturation (tanh waveshaping), mixed back in at low level.
    This is a different kind of 'clarity' than EQ: EQ reshapes existing
    energy, an exciter adds new harmonic content on top for perceived
    warmth/presence — the classic analog-console character."""
    print(f"[Stage] Harmonic exciter ({low}-{high}Hz, drive={drive}, mix={mix:.0%}): {audio_path}")

    data, sr = sf.read(audio_path, dtype="float32", always_2d=True)

    sos = bandpass_sos(low, high, sr, order=2)
    band = apply_sos(data, sos)

    saturated = np.tanh(drive * band) / np.tanh(drive)
    harmonic_content = saturated - band
    processed = data + mix * harmonic_content

    peak = np.max(np.abs(processed))
    if peak > 0.99:
        processed = processed * (0.99 / peak)

    out_path = str(Path(audio_path).with_name(Path(audio_path).stem + "_exciter.wav"))
    sf.write(out_path, processed, sr)
    return out_path
