"""Run in the project venv: python scripts/restoration_study/run.py {codecs,peaks,controls,phase}."""

import argparse
import csv
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
from scipy import signal
import soundfile as sf

from stimuli import RATE, ROOT, listening_clips, original_mix

sys.path.insert(0, str(ROOT / "backend"))
from repairs import phase_preserving, rail_mask, repair_peaks, spectral_edge, upper_band_mix
from api.routes.studio import prepare_track
from worker.pipeline.studio import apollo_delta, render_audio


def corpus():
    for path in sorted((ROOT / "vendor/Apollo/asserts").glob("*khz/sample*/ori_wav.wav")):
        x, rate = sf.read(path, always_2d=True, dtype="float32")
        if rate != RATE or x.shape != (6 * RATE, 2):
            raise ValueError(f"Unexpected reference format in {path}")
        name = path.parents[1].name + "-" + path.parent.name
        yield name, "apollo", (.8 * x / np.abs(x).max()).astype(np.float32)
    yield "studio-original", "original", original_mix()


def band_powers(x):
    f, _, z = signal.stft(x.T, RATE, nperseg=2048, noverlap=1024, boundary=None, padded=False)
    power = np.abs(z)**2  # channel, frequency, time
    edges = (np.geomspace(80 + 1/.00437, 20000 + 1/.00437, 33) - 1/.00437)
    return np.stack([power[:, (f >= lo) & (f < hi), :].sum(axis=1)
                     for lo, hi in zip(edges[:-1], edges[1:])]).astype(np.float64)


class Reference:
    def __init__(self, reference):
        self.x = reference.astype(np.float64)
        self.energy = np.sum(self.x**2)
        ref = band_powers(reference)
        self.floor = ref.max() * 1e-7
        self.frames = ref.sum(axis=(0, 1)) > ref.sum(axis=(0, 1)).max() * 1e-4
        self.bands = 10*np.log10(np.maximum(ref[:, :, self.frames], self.floor))

    def score(self, y):
        if not np.isfinite(y).all() or y.shape != self.x.shape:
            raise ValueError("Invalid candidate")
        y64 = y.astype(np.float64)
        energy = np.sum(y64**2)
        gain = np.sum(y64 * self.x) / self.energy
        error = np.sum((y64 - gain * self.x)**2)
        sdr = 10*np.log10(gain**2 * self.energy / error) if error > 1e-22 else np.inf
        bands = band_powers(y)[:, :, self.frames] * (self.energy / energy)
        db = 10*np.log10(np.maximum(bands, self.floor))
        return {"si_sdr_db": round(float(sdr), 5),
                "band_rmse_db": round(float(np.mean((db-self.bands)**2)**.5), 5)}


def alignment_lag(observed, reference):
    # Inspect a loud interior block; evaluate candidates on the same container timeline.
    margin, block = 1536, 8192
    centers = np.arange(margin, len(reference) - margin - block, block)
    powers = np.stack([np.mean(reference[a:a+block]**2, axis=0) for a in centers])
    best, channel = np.unravel_index(np.argmax(powers), powers.shape)
    start = centers[best]
    cross = signal.correlate(observed[start-margin:start+block+margin, channel],
                             reference[start:start+block, channel], mode="valid", method="fft")
    return int(np.argmax(cross)) - margin


def ffmpeg(args, **kwargs):
    return subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args],
                          capture_output=True, check=True, **kwargs)


def next_codec_pass(folder, samples, encoder, kbps, extension):
    wav = folder / "repeat.wav"
    coded = folder / ("repeat." + extension)
    sf.write(wav, samples, RATE, subtype="FLOAT")
    ffmpeg(["-i", str(wav), "-ar", str(RATE), "-c:a", encoder, "-b:a", f"{kbps}k", str(coded)])
    raw = ffmpeg(["-i", str(coded), "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"]).stdout
    decoded = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)[:len(samples)]
    if len(decoded) != len(samples) or abs(alignment_lag(decoded, samples)) > 2:
        raise ValueError("Cannot compare codec generations on the same timeline")
    return decoded


def codec_cases(name, group, ref, work, phase=False):
    score = Reference(ref)
    original = work / "reference.wav"
    sf.write(original, ref, RATE, subtype="FLOAT")
    conditions = [("mp3-48", "libmp3lame", 48, "mp3"), ("mp3-128", "libmp3lame", 128, "mp3"),
                  ("aac-64", "aac", 64, "m4a"), ("clean", "", 0, "wav")]
    for case, encoder, kbps, extension in conditions:
        if phase and not encoder:
            continue
        folder = work / case
        folder.mkdir()
        source = original
        if encoder:
            source = folder / ("encoded." + extension)
            ffmpeg(["-i", str(original), "-ar", str(RATE), "-c:a", encoder, "-b:a", f"{kbps}k", str(source)])
        metadata = prepare_track(folder, source, name)
        # Freeze the baseline that generated the published measurements and listening files.
        legacy = {"clarity": 36, "deess": 35, "width": 0, "restore": 0}
        if encoder and 0 < metadata["bitrate"] <= 64:
            legacy.update(clarity=22, deess=25, restore=55)
        observed, rate = sf.read(folder / "source.wav", dtype="float32", always_2d=True)
        if rate != RATE or not len(ref) <= len(observed) < len(ref) + 2048:
            raise ValueError(f"Unexpected decoder timeline {name} {case}: {observed.shape}")
        lag = alignment_lag(observed[:len(ref)], ref)
        if abs(lag) > 2:
            raise ValueError(f"Unaligned codec file {name} {case}: {lag} samples")
        # Preserve the production input for the model. Trim only encoder end padding when scoring.
        delta = apollo_delta(folder, observed, rate)
        edge = spectral_edge(observed, rate)
        high = upper_band_mix(observed, delta, rate, .9*edge)
        if phase:
            twice = next_codec_pass(folder, observed, encoder, kbps, extension)
            thrice = next_codec_pass(folder, twice, encoder, kbps, extension)
            model_gain, learned = phase_preserving(observed, observed+delta, twice, thrice, rate)
            extra = (high - observed) * (.12/.55)
            variants = {"input": observed, "phase_model": model_gain, "phase_model_high": model_gain+extra,
                        "repeat": learned, "repeat_high": learned+extra}
        else:
            current, _, _ = render_audio(folder, **legacy)
            variants = {"input": observed, "current": current, "apollo55": observed + .55*delta,
                        "apollo100": observed + delta,
                        "high6k": upper_band_mix(observed, delta, rate, 6000), "edge": high}
        for method, samples in variants.items():
            yield {"clip": name, "group": group, "case": case, "method": method,
                   "bitrate": metadata["bitrate"], "preset_restore": legacy["restore"],
                   "edge_hz": edge, "lag_samples": lag, **score.score(samples[:len(ref)])}
        if group == "original" and case == "mp3-48":
            if phase:
                keys = ("input", "phase_model_high", "repeat", "repeat_high")
            else:
                keys = ("input", "current", "edge", "apollo55")
            listening_clips("phase" if phase else "codec", {"reference": ref, **{
                k: variants[k][:len(ref)] for k in keys}})


def standard_declip(observed):
    command = ["-f", "f32le", "-ar", str(RATE), "-ac", "2", "-i", "pipe:0",
               "-af", "adeclip", "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"]
    raw = ffmpeg(command, input=observed.astype("<f4").tobytes()).stdout
    result = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
    if result.shape != observed.shape or abs(alignment_lag(result, observed)) > 2:
        raise ValueError("Unexpected FFmpeg adeclip timeline")
    return result


def peak_cases(name, group, ref):
    score = Reference(ref)
    for case, quantile in (("clip-2pct", .98), ("clip-6pct", .94), ("clean", 1.)):
        threshold = np.quantile(np.abs(ref), quantile)
        observed = np.clip(ref, -threshold, threshold).astype(np.float32)
        damaged = observed != ref
        input_error = np.sum((observed[damaged].astype(np.float64) - ref[damaged])**2)
        variants = {"input": observed, "ffmpeg": standard_declip(observed), **repair_peaks(observed, RATE)}
        for method, result in variants.items():
            recovered = ""
            if damaged.any():
                error = np.sum((result[damaged].astype(np.float64) - ref[damaged])**2)
                recovered = round(float(10*np.log10(input_error/max(error, 1e-25))), 5)
            outside = np.abs(result[~damaged] - observed[~damaged])
            yield {"clip": name, "group": group, "case": case, "method": method,
                   "damaged_pct": round(float(damaged.mean()*100), 4),
                   "peak_error_reduction_db": recovered,
                   "outside_max_delta": float(outside.max()), **score.score(result)}
        if group == "original" and case == "clip-6pct":
            listening_clips("peaks", {"reference": ref, **{k: variants[k]
                            for k in ("input", "ffmpeg", "self_calibrated")}})


def control_cases(name, group, ref, work):
    # Intended low-pass mastering and lossy encoding after clipping are two
    # common ways a plausible detector can mistake file history.
    fir = signal.firwin(513, 8000, fs=RATE, window=("kaiser", 9))
    intentional = signal.fftconvolve(ref, fir[:, None], mode="same", axes=0).astype(np.float32)
    threshold = np.quantile(np.abs(ref), .94)
    clipped = np.clip(ref, -threshold, threshold).astype(np.float32)
    source = work / "clipped.wav"
    sf.write(source, clipped, RATE, subtype="FLOAT")
    encoded = work / "export.mp3"
    ffmpeg(["-i", str(source), "-c:a", "libmp3lame", "-b:a", "128k", str(encoded)])
    raw = ffmpeg(["-i", str(encoded), "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"]).stdout
    lossy = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
    for case, audio in (("intentional-lowpass", intentional), ("clipped-then-mp3", lossy)):
        mask, _ = rail_mask(audio)
        yield {"clip": name, "group": group, "case": case,
               "edge_hz": spectral_edge(audio, RATE), "detected_flat_samples": int(mask.sum())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=["codecs", "peaks", "controls", "phase"])
    args = parser.parse_args()
    csv_path = ROOT / "docs" / ("restoration-" + args.experiment + ".csv")
    rows = []
    for name, group, reference in corpus():
        print(f"{args.experiment} {name}", flush=True)
        with tempfile.TemporaryDirectory(prefix="restoration-study-") as tmp:
            if args.experiment in {"codecs", "phase"}:
                rows.extend(codec_cases(name, group, reference, Path(tmp), phase=args.experiment == "phase"))
            elif args.experiment == "peaks":
                rows.extend(peak_cases(name, group, reference))
            else:
                rows.extend(control_cases(name, group, reference, Path(tmp)))
    if len({r["clip"] for r in rows if r["group"] == "apollo"}) != 15:
        raise ValueError("Expected all 15 Apollo author-provided references")
    tmp_csv = csv_path.with_suffix(".csv.part")
    with tmp_csv.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_csv, csv_path)
    print(f"Saved {len(rows)} rows to {csv_path}", flush=True)


if __name__ == "__main__":
    main()
