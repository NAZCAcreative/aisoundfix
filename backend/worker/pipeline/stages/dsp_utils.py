"""Shared biquad EQ / envelope-follower building blocks (RBJ Audio EQ Cookbook)."""

import numpy as np
from scipy.signal import butter, lfilter, resample_poly, sosfilt


def high_shelf_coeffs(freq: float, gain_db: float, sr: int, slope: float = 0.9):
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * freq / sr
    alpha = np.sin(w0) / 2 * np.sqrt((A + 1 / A) * (1 / slope - 1) + 2)
    cos_w0 = np.cos(w0)
    sqrt_A = np.sqrt(A)

    b0 = A * ((A + 1) + (A - 1) * cos_w0 + 2 * sqrt_A * alpha)
    b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
    b2 = A * ((A + 1) + (A - 1) * cos_w0 - 2 * sqrt_A * alpha)
    a0 = (A + 1) - (A - 1) * cos_w0 + 2 * sqrt_A * alpha
    a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
    a2 = (A + 1) - (A - 1) * cos_w0 - 2 * sqrt_A * alpha

    return np.array([b0, b1, b2]) / a0, np.array([a0, a1, a2]) / a0


def low_shelf_coeffs(freq: float, gain_db: float, sr: int, slope: float = 0.9):
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * freq / sr
    alpha = np.sin(w0) / 2 * np.sqrt((A + 1 / A) * (1 / slope - 1) + 2)
    cos_w0 = np.cos(w0)
    sqrt_A = np.sqrt(A)

    b0 = A * ((A + 1) - (A - 1) * cos_w0 + 2 * sqrt_A * alpha)
    b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0)
    b2 = A * ((A + 1) - (A - 1) * cos_w0 - 2 * sqrt_A * alpha)
    a0 = (A + 1) + (A - 1) * cos_w0 + 2 * sqrt_A * alpha
    a1 = -2 * ((A - 1) + (A + 1) * cos_w0)
    a2 = (A + 1) + (A - 1) * cos_w0 - 2 * sqrt_A * alpha

    return np.array([b0, b1, b2]) / a0, np.array([a0, a1, a2]) / a0


def peaking_coeffs(freq: float, gain_db: float, sr: int, q: float = 1.0):
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * freq / sr
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)

    b0 = 1 + alpha * A
    b1 = -2 * cos_w0
    b2 = 1 - alpha * A
    a0 = 1 + alpha / A
    a1 = -2 * cos_w0
    a2 = 1 - alpha / A

    return np.array([b0, b1, b2]) / a0, np.array([a0, a1, a2]) / a0


def apply_biquad(data: np.ndarray, b, a) -> np.ndarray:
    """data: [samples, channels] -> filtered [samples, channels]."""
    return np.stack([lfilter(b, a, data[:, ch]) for ch in range(data.shape[1])], axis=1)


def bandpass_sos(low: float, high: float, sr: int, order: int = 2):
    nyq = sr / 2
    return butter(order, [low / nyq, high / nyq], btype="band", output="sos")


def apply_sos(data: np.ndarray, sos) -> np.ndarray:
    return np.stack([sosfilt(sos, data[:, ch]) for ch in range(data.shape[1])], axis=1)


def envelope(abs_x: np.ndarray, sr: int, time_ms: float) -> np.ndarray:
    alpha = np.exp(-1.0 / (sr * time_ms / 1000.0))
    return lfilter([1 - alpha], [1, -alpha], abs_x)


def true_peak_db(data: np.ndarray, oversample: int = 4) -> float:
    """Inter-sample (true) peak via oversampling, per EBU R128 / ITU-R BS.1770."""
    oversampled = resample_poly(data, oversample, 1, axis=0)
    peak = np.max(np.abs(oversampled))
    return 20 * np.log10(peak + 1e-12)


def limit_true_peak(data: np.ndarray, ceiling_db: float = -1.0, oversample: int = 4) -> np.ndarray:
    """Scale down (if needed) so the true peak sits at or below ceiling_db dBTP.
    A naive sample-domain clamp (e.g. `if peak > 0.99`) misses inter-sample
    overshoot that lossy encoders (mp3/AAC) are known to amplify further."""
    tp_db = true_peak_db(data, oversample)
    if tp_db <= ceiling_db:
        return data
    gain_db = ceiling_db - tp_db
    return data * (10 ** (gain_db / 20))
