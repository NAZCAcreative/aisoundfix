"""Restore short, repeated clipping plateaus using intact peaks in the recording."""

import numpy as np
import soundfile as sf


BLOCK = 262144


def runs(mask):
    changes = np.flatnonzero(np.diff(mask.astype(np.int8), prepend=0, append=0))
    return changes[::2], changes[1::2]


def find_rails(audio):
    rails = []
    for x in audio.T:
        limits = []
        low, high = x.min(), x.max()
        for polarity, level in ((-1, low), (1, high)):
            count = sustained = 0
            if polarity * level > 1e-5 and low != high:
                for start in range(0, len(x), BLOCK):
                    end = min(start + BLOCK, len(x))
                    left = max(0, start - 1)
                    hits = x[left:end+2] == level
                    if not hits.any():
                        continue
                    count += np.count_nonzero(hits[start-left:end-left])
                    first, last = runs(hits)
                    starts = first + left
                    sustained += np.count_nonzero((starts >= start) & (starts < end) & (last-first >= 3))
            limits.append(float(level) if sustained >= 3 and count < .20 * len(x) else None)
        rails.append(limits)
    return rails


def mask_at_rails(audio, rails):
    mask = np.zeros_like(audio, dtype=bool)
    for ch, limits in enumerate(rails):
        for level in limits:
            if level is not None:
                mask[:, ch] |= audio[:, ch] == level
    return mask


def flank_fit(source, target, valid, starts, ends):
    """Fit the other channel to the damaged channel on one flank of each gap."""
    def sums(values):
        prefix = np.r_[0., np.cumsum(values * valid, dtype=np.float64)]
        return prefix[ends] - prefix[starts]

    count = sums(np.ones(len(source)))
    n = np.maximum(count, 1)
    sx, sy = sums(source), sums(target)
    vx = np.maximum(0, sums(source * source) - sx * sx / n)
    vy = np.maximum(0, sums(target * target) - sy * sy / n)
    cov = sums(source * target) - sx * sy / n
    slope = cov / np.maximum(vx, 1e-12)
    offset = (sy - slope * sx) / n
    corr = cov / np.sqrt(np.maximum(vx * vy, 1e-24))
    trusted = (count >= 16) & (np.abs(corr) >= .92) & (np.abs(slope) <= 3)
    return slope, offset, trusted


def peak_estimates(audio, mask, ch, rate):
    """Interpolate each short plateau using the two flanks and trusted stereo cues."""
    x = audio[:, ch]
    starts, ends = runs(mask[:, ch])
    lengths = ends - starts
    valid = (starts >= 2) & (ends + 1 < len(x)) & (lengths <= round(.002 * rate))
    starts, ends, lengths = starts[valid], ends[valid], lengths[valid]
    if not len(starts):
        return np.array([], dtype=int), np.array([]), np.array([]), lengths
    start = np.repeat(starts, lengths)
    end = np.repeat(ends, lengths)
    offsets = np.repeat(np.cumsum(lengths) - lengths, lengths)
    idx = start + np.arange(len(start)) - offsets
    span = end - start + 1
    t = (idx - start + 1) / span
    left, right = x[start - 1], x[end]
    cubic = ((2*t**3 - 3*t*t + 1)*left + (t**3 - 2*t*t + t)*span*(left - x[start-2])
             + (-2*t**3 + 3*t*t)*right + (t**3 - t*t)*span*(x[end+1] - right))
    combined = cubic.copy()
    if audio.shape[1] == 2:
        other = 1 - ch
        side = audio[:, other]
        intact = ~mask.any(axis=1)
        context = round(.0025 * rate)
        a, b, past = flank_fit(side, x, intact, np.maximum(0, starts-context), starts)
        c, d, future = flank_fit(side, x, intact, ends, np.minimum(len(x), ends+context))
        other_clipped = np.r_[0, np.cumsum(mask[:, other])]
        trusted = (past & future & (a*c > 0)
                   & (other_clipped[starts] == other_clipped[ends]))
        weight = .8 * np.repeat(trusted, lengths)
        pred = ((1-t) * (np.repeat(a, lengths)*side[idx] + np.repeat(b, lengths))
                + t * (np.repeat(c, lengths)*side[idx] + np.repeat(d, lengths)))
        combined += weight * (pred - cubic)
    rail = x[idx]
    sign = np.sign(rail)

    def constrained_delta(estimate):
        return sign * np.clip(sign * (estimate - rail), 0, 1.5 * np.abs(rail))

    return idx, constrained_delta(cubic), constrained_delta(combined), lengths


def blocks(audio, rate):
    # Enough context for the longest eligible plateau, its slopes and both stereo fits.
    margin = round(.002 * rate) + round(.0025 * rate) + 4
    for start in range(0, len(audio), BLOCK):
        end = min(start + BLOCK, len(audio))
        left = max(0, start - margin)
        yield audio[left:end+margin], left, start, end


def calibration(audio, rails, rate):
    shape = (audio.shape[1], 3)
    counts = np.zeros(shape, dtype=np.int64)
    energy = np.zeros(shape)
    dot = np.zeros(shape)
    for observed, left, start, end in blocks(audio, rate):
        missing = mask_at_rails(observed, rails)
        pseudo = observed.copy()
        for ch, (low, high) in enumerate(rails):
            np.clip(observed[:, ch], low*.82 if low is not None else -np.inf,
                    high*.82 if high is not None else np.inf, out=pseudo[:, ch])
        pseudo_mask = (pseudo != observed) | missing
        for ch in range(audio.shape[1]):
            idx, _, delta, lengths = peak_estimates(pseudo, pseudo_mask, ch, rate)
            if not len(idx):
                continue
            # A pseudo-peak with any truly clipped samples cannot provide a target.
            first = np.r_[0, np.cumsum(lengths)[:-1]]
            intact = ~np.repeat(np.logical_or.reduceat(missing[idx, ch], first), lengths)
            use = intact & (idx + left >= start) & (idx + left < end)
            bins = np.repeat(np.digitize(lengths, [5, 13]), lengths)[use]
            d = delta[use]
            target = observed[idx[use], ch] - pseudo[idx[use], ch]
            counts[ch] += np.bincount(bins, minlength=3)
            energy[ch] += np.bincount(bins, weights=d*d, minlength=3)
            dot[ch] += np.bincount(bins, weights=d*target, minlength=3)
    gains = np.ones(shape)
    valid = (counts >= 32) & (energy > 1e-10)
    gains[valid] = np.clip(dot[valid] / energy[valid], .4, 1.6)
    return gains


def prepare_peak_repair(folder, audio, rate):
    rails = find_rails(audio)
    if not any(level is not None for limits in rails for level in limits):
        return None
    gains = calibration(audio, rails, rate)
    bin_size = max(1, round(rate / 4))
    energy = np.zeros((len(audio) + bin_size - 1) // bin_size)
    count = 0
    pending = folder / "peaks.part.wav"
    try:
        with sf.SoundFile(pending, "w", rate, audio.shape[1], subtype="FLOAT") as output:
            for observed, left, start, end in blocks(audio, rate):
                mask = mask_at_rails(observed, rails)
                corrected = audio[start:end].copy()
                for ch in range(audio.shape[1]):
                    idx, _, mix, lengths = peak_estimates(observed, mask, ch, rate)
                    if not len(idx):
                        continue
                    indices = idx + left
                    first = np.r_[0, np.cumsum(lengths)[:-1]]
                    changed = np.maximum.reduceat(np.abs(mix), first) > 0
                    count += int(np.count_nonzero(changed & (indices[first] >= start) & (indices[first] < end)))
                    use = (indices >= start) & (indices < end)
                    frames = indices[use]
                    groups = np.repeat(np.digitize(lengths, [5, 13]), lengths)[use]
                    delta = mix[use] * gains[ch, groups]
                    corrected[frames-start, ch] += delta
                    np.add.at(energy, frames // bin_size, delta**2)
                output.write(corrected)
        if not count or not energy.any():
            return None
        pending.replace(folder / "peaks.wav")
    finally:
        pending.unlink(missing_ok=True)
    span = min(len(audio), 6 * rate)
    bins = min(len(energy), max(1, round(span / bin_size)))
    best = np.convolve(energy, np.ones(bins), mode="valid").argmax()
    start = int(min(best * bin_size, len(audio) - span))
    return {"kind": "peaks", "peakCount": count,
            "preview": {"start": start / rate, "end": (start + span) / rate}}
