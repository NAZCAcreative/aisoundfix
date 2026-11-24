"""Creative effects for the studio. Audio arrays are [frames, channels]."""

from functools import lru_cache

import numpy as np
from scipy.fft import next_fast_len
from scipy.ndimage import median_filter
from scipy.signal import hilbert, istft, oaconvolve, resample_poly, sosfilt, stft

from .dsp_utils import bandpass_sos


def ghost_bass(audio, rate, amount):
    """Mix envelope-preserving second and third harmonics of two bass bands."""
    if len(audio) < 2 or rate < 800:
        return audio
    # Only the low band is nonlinear. Its harmonics fit in a ~2 kHz work rate.
    factor = max(1, rate // 2000)
    work_rate = rate / factor
    center = resample_poly(audio.mean(axis=1), 1, factor)
    harmonics = np.zeros_like(center)
    guard = round(.08 * work_rate)
    for low, high in [(32, 65), (65, 110)]:
        bass = sosfilt(bandpass_sos(low, high, work_rate), center)
        padded = np.pad(bass, (guard, guard))
        analytic = hilbert(padded, N=next_fast_len(len(padded)))[guard:guard + len(bass)]
        phase = analytic / np.maximum(np.abs(analytic), .004)
        second = analytic * phase
        harmonics += (.85 * second.real + .55 * (second * phase).real).astype("float32")
    audible = sosfilt(bandpass_sos(88, 360, work_rate), harmonics)
    wet = resample_poly(audible.astype("float32"), factor, 1)[:len(audio)]
    return audio + (amount * wet[:, None])


def rhythm_focus(audio, rate, amount):
    """FitzGerald-style median HPSS with a shared stereo soft mask."""
    frame = int(2 ** np.clip(round(np.log2(.046 * rate)), 7, 13))
    hop = frame // 4
    core = 256 * hop
    # Context on each side covers both the median radius and overlap-add.
    margin = 8 * hop + frame
    result = np.empty_like(audio)
    for start in range(0, len(audio), core):
        end = min(start + core, len(audio))
        left, right = max(0, start - margin), min(len(audio), end + margin)
        block = audio[left:right]
        if len(block) < frame:
            block = np.pad(block, ((0, frame - len(block)), (0, 0)))
        _, _, spectra = stft(block.T, nperseg=frame, noverlap=frame-hop)
        magnitude = np.sqrt(np.mean(np.abs(spectra) ** 2, axis=0))
        horizontal = median_filter(magnitude, size=(1, 17), mode="nearest")
        vertical = median_filter(magnitude, size=(17, 1), mode="nearest")
        mask = vertical ** 2 / (vertical ** 2 + horizontal ** 2 + 1e-20)
        _, percussive = istft(spectra * mask, nperseg=frame, noverlap=frame-hop)
        hits = percussive.T[start-left:end-left]
        result[start:end] = (1 - .85 * amount) * audio[start:end] + 1.35 * amount * hits
    return result


@lru_cache(maxsize=12)
def _velvet_ir(rate, channel):
    """Sparse signed rectangular pulses, widening as the tail darkens."""
    rng = np.random.default_rng(7316 + channel)
    length = max(2, round(1.35 * rate))
    cell = max(1, round(rate / 1500))
    cells = np.arange(round(.018 * rate), length - cell, cell)
    starts = cells + rng.integers(0, cell, size=len(cells))
    time = (starts - .018 * rate) / rate
    widths = np.maximum(1, np.rint(rate * (.000025 + .00085 * time) *
                                   rng.uniform(.5, 1.5, len(cells))).astype(int))
    end = np.minimum(length, starts + widths)
    bloom = (1 - np.exp(-np.maximum(time, 0) / .045)) * np.exp(-5.6 * time)
    weights = rng.choice([-1, 1], len(cells)) * bloom / np.sqrt(widths)
    edges = np.zeros(length + 1)
    np.add.at(edges, starts, weights)
    np.add.at(edges, end, -weights)
    ir = np.cumsum(edges[:-1])
    ir = sosfilt(bandpass_sos(min(135, rate * .12), min(6800, rate * .43), rate), ir)
    return (ir / max(np.linalg.norm(ir), 1e-12)).astype("float32")


def velvet_room(audio, rate, amount):
    """Parallel dark-velvet reverb. Keep the master and A/B timeline aligned."""
    output = audio.copy()
    fade = min(len(audio), max(1, round(.025 * rate)))
    for channel in range(audio.shape[1]):
        ir = _velvet_ir(rate, channel)
        wet = oaconvolve(audio[:, channel], ir)[:len(audio)]
        wet[:round(.018 * rate)] = 0
        wet[-fade:] *= np.linspace(1, 0, fade, dtype="float32")
        output[:, channel] += .76 * amount * wet
    return output
