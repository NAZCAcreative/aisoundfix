from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

from .dsp_utils import apply_biquad, envelope, high_shelf_coeffs, limit_true_peak


def _compress(data: np.ndarray, sr: int, threshold_db: float, ratio: float = 3.0, time_ms: float = 40.0) -> np.ndarray:
    abs_max = np.max(np.abs(data), axis=1)
    env = envelope(abs_max, sr, time_ms)
    env_db = 20 * np.log10(env + 1e-9)
    over_db = np.clip(env_db - threshold_db, 0, None)
    gain_reduction_db = over_db * (1 - 1 / ratio)
    gain = 10 ** (-gain_reduction_db / 20)
    return data * gain[:, None]


def run_demo_filter(audio_path: str, shelf_freq: float = 6500.0, shelf_gain_db: float = 5.0, loudness_boost_db: float = 1.0) -> str:
    """Replicates the frontend DEMO mode's Web Audio filter chain (highshelf +
    compressor) as real DSP, layered on top of the honest restoration pipeline.
    The demo's brightness/loudness boost tested well perceptually (loudness
    bias) — this stacks that character on top of V2's actual fidelity
    improvements.

    The input here is already mastered (~-14 LUFS from run_mastering), unlike
    the demo which filters raw uploaded audio. A fixed compressor threshold
    tuned for raw audio would sit below an already-loud signal almost
    everywhere and net-quieten it despite the "louder" intent, so loudness is
    explicitly re-targeted at the end instead of relying on a peak clamp.
    """
    print(f"[Stage] Applying demo-style perceptual filter (+{shelf_gain_db}dB shelf @ {shelf_freq}Hz + compressor): {audio_path}")

    data, sr = sf.read(audio_path, dtype="float32", always_2d=True)

    meter = pyln.Meter(sr)
    input_lufs = meter.integrated_loudness(data)

    b, a = high_shelf_coeffs(shelf_freq, shelf_gain_db, sr)
    processed = apply_biquad(data, b, a)
    # Threshold relative to the input's own loudness (not a fixed absolute
    # value) so the compressor behaves consistently regardless of how loud
    # the upstream mastering already made the signal.
    processed = _compress(processed, sr, threshold_db=input_lufs + 6.0)

    target_lufs = min(input_lufs + loudness_boost_db, -9.0)  # stay off a brickwall
    processed_loudness = meter.integrated_loudness(processed)
    processed = pyln.normalize.loudness(processed, processed_loudness, target_lufs)

    processed = limit_true_peak(processed, ceiling_db=-1.0)

    out_path = str(Path(audio_path).with_name(Path(audio_path).stem + "_demofilter.wav"))
    sf.write(out_path, processed, sr)
    return out_path
