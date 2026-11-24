"""Comparison variants used in the original restoration study."""

import numpy as np
from scipy import signal
from scipy.ndimage import gaussian_filter

from worker.pipeline.stages.band_repair import model_magnitude_repair, spectral_edge
from worker.pipeline.stages.peak_repair import calibration, find_rails, mask_at_rails, peak_estimates


def upper_band_mix(audio, delta, rate, cutoff):
    if not cutoff:
        return audio.copy()
    highpass = signal.butter(4, cutoff, fs=rate, btype="highpass", output="sos")
    residual = signal.sosfiltfilt(highpass, delta, axis=0)
    return (audio + 0.55 * residual).astype(np.float32)


def phase_preserving(observed, model, recoded, recoded_twice, rate):
    """Estimate stereo-linked magnitude corrections. Keep the observed complex phase."""
    def spectrum(x):
        return signal.stft(x.T, rate, nperseg=1024, noverlap=768)[2]

    y = spectrum(observed)

    def magnitude(z):
        return np.sqrt(gaussian_filter(np.mean(np.abs(z)**2, axis=0), (.8, 1.0)))

    def apply_gain(gain):
        _, correction = signal.istft(y * (gain - 1)[None, :, :], rate, nperseg=1024, noverlap=768)
        return (observed + correction.T[:len(observed)]).astype(np.float32)

    level = magnitude(y)
    floor = max(float(level.max() * .0001), 1e-10)
    # Use the known preceding generation of the same signal as a pseudo-target.
    next_level = magnitude(spectrum(recoded))
    last_level = magnitude(spectrum(recoded_twice))
    first_loss, next_loss = level - next_level, next_level - last_level
    frequencies = np.fft.rfftfreq(1024, 1/rate)
    edges = np.r_[0, np.geomspace(120, 20000, 18), rate/2 + 1]
    gain = np.ones_like(level)
    for lo, hi in zip(edges[:-1], edges[1:]):
        band = (frequencies >= lo) & (frequencies < hi)
        if not np.any(band):
            continue
        x, target = next_loss[band], first_loss[band]
        energy = np.sum(x*x, dtype=np.float64)
        coefficient = np.clip(np.sum(x*target, dtype=np.float64) / (energy + 1e-12), 0, .8)
        gain[band] += np.clip(coefficient * target / np.maximum(level[band], floor), -.25, .25)
    return model_magnitude_repair(observed, model, rate), apply_gain(gain)


def rail_mask(audio):
    rails = find_rails(audio)
    return mask_at_rails(audio, rails), rails


def repair_peaks(audio, rate):
    mask, rails = rail_mask(audio)
    cubic, stereo, calibrated = (audio.copy() for _ in range(3))
    if mask.any():
        gains = calibration(audio, rails, rate)
        for ch in range(audio.shape[1]):
            idx, curve, combined, lengths = peak_estimates(audio, mask, ch, rate)
            groups = np.repeat(np.digitize(lengths, [5, 13]), lengths)
            cubic[idx, ch] += curve
            stereo[idx, ch] += combined
            calibrated[idx, ch] += combined * gains[ch, groups]
    return {"cubic": cubic, "stereo": stereo, "self_calibrated": calibrated}
