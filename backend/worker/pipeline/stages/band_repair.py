"""Bandwidth-limited MP3 restoration with stereo-linked magnitude correction."""

import numpy as np
from scipy import signal
from scipy.ndimage import gaussian_filter


def spectral_edge(audio, rate):
    window, hop = 2048, 1024
    if len(audio) < window or rate / 2 < 6500:
        return 0
    frames = 1 + (len(audio) - window) // hop
    power = np.zeros(window // 2 + 1)
    for first in range(0, frames, 256):
        count = min(256, frames - first)
        samples = audio[first*hop:(first+count-1)*hop+window]
        freq, chunk = signal.welch(samples, rate, nperseg=window, noverlap=hop, axis=0)
        power += count * chunk.mean(axis=1)
    edges = np.arange(0, min(20000, rate / 2) + 1, 500)
    # At very high sample rates a 500 Hz band may contain no FFT bins.
    if rate / window > 500:
        return 0
    bands = [power[(freq >= a) & (freq < b)].mean() / frames for a, b in zip(edges[:-1], edges[1:])]
    levels = 10 * np.log10(np.maximum(bands, 1e-20))
    candidates = []
    for i in range(9, len(bands)-3):
        before = levels[i-2:i].mean()
        drop = before - levels[i+1:i+3].mean()
        if before > levels.max()-52 and drop >= 20 and levels[i+2:].max() < before-16:
            candidates.append((drop, edges[i]))
    return int(max(candidates)[1]) if candidates else 0


def model_magnitude_repair(observed, model, rate):
    def spectrum(x):
        return signal.stft(x.T, rate, nperseg=1024, noverlap=768)[2]

    def magnitude(z):
        return np.sqrt(gaussian_filter(np.mean(np.abs(z)**2, axis=0), (.8, 1.0)))

    y = spectrum(observed)
    level = magnitude(y)
    floor = max(float(level.max() * .0001), 1e-10)
    ratio = magnitude(spectrum(model)) / np.maximum(level, floor)
    gain = 1 + .45 * (np.clip(ratio, .55, 1.5) - 1)
    gain[level < floor] = 1
    _, correction = signal.istft(y * (gain-1)[None, :, :], rate, nperseg=1024, noverlap=768)
    return (observed + correction.T[:len(observed)]).astype(np.float32)


def repair_band(audio, delta, rate, edge):
    if len(audio) < 2048 or not 0 < edge < rate / 2:
        return audio.copy()
    highpass = signal.butter(4, .9 * edge, fs=rate, btype="highpass", output="sos")
    result = np.empty_like(audio)
    # Hop-aligned windows retain the original sample clock and bound STFT memory.
    block, context = 524288, 4096
    for start in range(0, len(audio), block):
        end = min(start + block, len(audio))
        left = max(0, start - context)
        right = min(len(audio), end + context)
        observed, residual = audio[left:right], delta[left:right]
        shaped = model_magnitude_repair(observed, observed + residual, rate)
        shaped += (.12 * signal.sosfiltfilt(highpass, residual, axis=0)).astype(np.float32)
        result[start:end] = shaped[start-left:end-left]
    return result
