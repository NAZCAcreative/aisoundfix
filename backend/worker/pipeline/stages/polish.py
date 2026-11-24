from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import lfilter

from .dsp_utils import apply_sos, bandpass_sos, envelope, high_shelf_coeffs, peaking_coeffs


def _deess(data: np.ndarray, sr: int, low: float = 4000.0, high: float = 9000.0,
           threshold_db: float = -24.0, ratio: float = 4.0, time_ms: float = 8.0) -> np.ndarray:
    """Split-band de-esser: gain-reduce only the 4-9kHz sibilance band during peaks."""
    sos = bandpass_sos(low, high, sr)
    sibilant = apply_sos(data, sos)
    rest = data - sibilant

    abs_sib = np.max(np.abs(sibilant), axis=1)
    env = envelope(abs_sib, sr, time_ms)
    env_db = 20 * np.log10(env + 1e-9)
    over_db = np.clip(env_db - threshold_db, 0, None)
    gain_reduction_db = over_db * (1 - 1 / ratio)
    gain = 10 ** (-gain_reduction_db / 20)

    return rest + sibilant * gain[:, None]


def _mid_side_eq(data: np.ndarray, sr: int, presence_db: float = 2.5, declutter_db: float = -2.0, width_db: float = 2.5) -> np.ndarray:
    """Mid: vocal presence boost. Side: low-mid declutter + high-shelf width."""
    if data.shape[1] < 2:
        return data
    l, r = data[:, 0], data[:, 1]
    mid = (l + r) / 2
    side = (l - r) / 2

    b, a = peaking_coeffs(4000.0, presence_db, sr, q=1.0)
    mid = lfilter(b, a, mid)

    b, a = peaking_coeffs(350.0, declutter_db, sr, q=1.0)
    side = lfilter(b, a, side)

    b, a = high_shelf_coeffs(8000.0, width_db, sr)
    side = lfilter(b, a, side)

    return np.stack([mid + side, mid - side], axis=1)


def run_polish(
    audio_path: str,
    deess_threshold_db: float = -24.0,
    deess_ratio: float = 4.0,
    presence_db: float = 2.5,
    declutter_db: float = -2.0,
    width_db: float = 2.5,
) -> str:
    print(f"[Stage] Polishing (de-ess + mid-side presence/clarity/width): {audio_path}")

    data, sr = sf.read(audio_path, dtype="float32", always_2d=True)

    processed = _deess(data, sr, threshold_db=deess_threshold_db, ratio=deess_ratio)
    processed = _mid_side_eq(processed, sr, presence_db=presence_db, declutter_db=declutter_db, width_db=width_db)

    peak = np.max(np.abs(processed))
    if peak > 0.99:
        processed = processed * (0.99 / peak)

    out_path = str(Path(audio_path).with_name(Path(audio_path).stem + "_polished.wav"))
    sf.write(out_path, processed, sr)
    return out_path
