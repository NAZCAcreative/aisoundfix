"""Make blind listening stimuli and measure their decoded sample errors."""

import csv
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
LISTEN = ROOT / "frontend/research/quantization"
SOURCE = ROOT / "frontend/research/restoration/peaks-reference.flac"


def quantize(audio, bits, rng=None):
    scale = 1 << (bits - 1)
    scaled = audio * scale
    if rng is not None:
        scaled += rng.random(audio.shape) - rng.random(audio.shape)
    return np.rint(scaled).clip(-scale, scale - 1).astype(np.int32)


def export(name, codes, bits, rate):
    path = LISTEN / (name + ".flac")
    # FLAC-24 transports all four integer grids exactly, including 12-bit.
    samples = codes << (32 - bits)
    sf.write(path, samples, rate, subtype="PCM_24")
    decoded, actual_rate = sf.read(path, dtype="int32", always_2d=True)
    if actual_rate != rate or not np.array_equal(decoded, samples):
        raise ValueError(f"Lossless transport failed for {path.name}")
    return decoded.astype(np.float64) / (1 << 31)


def measure(reference, output):
    error = output - reference
    signal_power = np.mean(reference**2)
    error_power = np.mean(error**2)
    return {
        "snr_db": round(10*np.log10(signal_power/error_power), 3) if error_power else "inf",
        "error_rms_dbfs": round(10*np.log10(error_power), 3) if error_power else "-inf",
        "zero_pct": round(100*np.mean(output == 0), 3),
        "reference_gain": round(np.mean(output * reference) / signal_power, 4),
    }


def main():
    audio, rate = sf.read(SOURCE, always_2d=True)
    time = np.arange(len(audio)) / rate
    fade_db = -72 * np.clip((time - 2) / 6, 0, 1)
    LISTEN.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (name, stimulus) in enumerate((("music", audio), ("fade", audio * 10**(fade_db[:, None]/20)))):
        reference = export(name+"-reference", quantize(stimulus, 24), 24, rate)
        for bits in (24, 16, 12, 8):
            for method in ("round", "tpdf"):
                rng = np.random.default_rng([20261125, i, bits]) if method == "tpdf" else None
                codes = quantize(reference, bits, rng)
                output = export(f"{name}-{bits}-{method}", codes, bits, rate)
                if bits == 24 and method == "round" and not np.array_equal(output, reference):
                    raise ValueError("The hidden reference differs from its source")
                for window, start in (("full", 0), ("last_2s", 6*rate)):
                    rows.append(dict(stimulus=name, bits=bits, method=method, window=window,
                                     **measure(reference[start:], output[start:])))
    with (ROOT / "docs/bit-depth-results.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
