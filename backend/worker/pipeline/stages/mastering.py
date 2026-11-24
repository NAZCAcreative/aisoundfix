from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

from .dsp_utils import apply_biquad, envelope, high_shelf_coeffs, limit_true_peak


def _apply_compression(
    data: np.ndarray, sr: int, threshold_db: float = -18.0, ratio: float = 3.0, time_ms: float = 30.0, makeup_db: float = 2.5
) -> np.ndarray:
    # Stereo-linked: one gain curve derived from the loudest channel per sample,
    # so gain reduction doesn't shift the stereo image.
    abs_max = np.max(np.abs(data), axis=1)
    env = envelope(abs_max, sr, time_ms)
    env_db = 20 * np.log10(env + 1e-9)
    over_db = np.clip(env_db - threshold_db, 0, None)
    gain_reduction_db = over_db * (1 - 1 / ratio)
    gain = 10 ** ((-gain_reduction_db + makeup_db) / 20)
    return data * gain[:, None]


def run_mastering(
    audio_path: str,
    target_lufs: float = -14.0,
    target_peak_db: float = -1.0,
    brightness_db: float = 3.0,
    compression_ratio: float = 3.0,
) -> str:
    print(
        f"[Stage] Broadcast Mastering to {target_lufs} LUFS "
        f"(+{brightness_db}dB high shelf, {compression_ratio}:1 comp): {audio_path}"
    )

    data, sr = sf.read(audio_path, dtype="float32", always_2d=True)  # [samples, channels]

    b, a = high_shelf_coeffs(8000.0, brightness_db, sr)
    polished = apply_biquad(data, b, a)
    polished = _apply_compression(polished, sr, ratio=compression_ratio)

    meter = pyln.Meter(sr)
    loudness = meter.integrated_loudness(polished)
    mastered = pyln.normalize.loudness(polished, loudness, target_lufs)

    mastered = limit_true_peak(mastered, ceiling_db=target_peak_db)

    out_path = str(Path(audio_path).with_name(Path(audio_path).stem + "_mastered.wav"))
    sf.write(out_path, mastered, sr)
    return out_path
