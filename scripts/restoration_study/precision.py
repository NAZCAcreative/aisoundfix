"""Measure PCM24 quantization and the boundaries of a local de-esser edit."""

import io
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from worker.pipeline.stages.pcm24 import write_pcm24
from worker.pipeline.studio import render_audio


def quantization():
    rate = 48000
    t = np.arange(2 * rate) / rate
    tone = (1e-7 * np.sin(2 * np.pi * 997 * t)).astype("float32")[:, None]
    lsb = 2.0 ** -23
    rng = np.random.default_rng(42)
    for mode in ("libsndfile float", "nearest", "TPDF + nearest"):
        stream = io.BytesIO()
        if mode == "libsndfile float":
            sf.write(stream, tone, rate, format="WAV", subtype="PCM_24")
        else:
            data = tone
            if mode == "TPDF + nearest":
                data = tone + lsb * (rng.random(tone.shape) - rng.random(tone.shape))
            write_pcm24(stream, data, rate)
        stream.seek(0)
        decoded, _ = sf.read(stream)
        error = (decoded - tone[:, 0]) / lsb
        print(f"{mode:18s} bias={np.mean(error):+.5f} LSB   "
              f"RMS={np.mean(error**2)**.5:.5f} LSB   "
              f"corr={np.corrcoef(tone[:, 0], error)[0,1]:+.5f}")


def edit_boundaries():
    path = ROOT / "frontend/research/restoration/peaks-reference.flac"
    dry, rate = sf.read(path, dtype="float32", always_2d=True)
    settings = dict(clarity=0, deess=70, width=0, restore=0)
    start, end = 5.51, 6.48
    a, b = round(start * rate), round(end * rate)
    with TemporaryDirectory() as tmp:
        folder = Path(tmp)
        sf.write(folder / "source.wav", dry, rate, subtype="FLOAT")
        wet, _, _ = render_audio(folder, **settings)
        localized, _, _ = render_audio(folder, region={"start": start, "end": end}, **settings)
    residual = wet[a:b] - dry[a:b]
    fade = min(round(.005 * rate), len(residual)//2)
    linear = residual.copy()
    ramp = np.linspace(0, 1, fade)[:, None]
    linear[:fade] *= ramp
    linear[-fade:] *= ramp[::-1]
    for name, edit in (("hard edit", residual), ("linear", linear),
                       ("regional render", localized[a:b] - dry[a:b])):
        # The unprocessed residual immediately outside the selection is zero.
        boundary = np.max(np.abs(edit[[0, -1]]))
        first_step = np.max(np.abs(edit[[1, -2]] - edit[[0, -1]]))
        print(f"{name:18s} boundary residual={boundary:.9f} FS   "
              f"adjacent residual step={first_step:.9f} FS")
    print("outside samples changed:", np.count_nonzero(localized[:a] != dry[:a])
          + np.count_nonzero(localized[b:] != dry[b:]))
    print("inside samples changed:", np.count_nonzero(localized[a:b] != dry[a:b]))


if __name__ == "__main__":
    quantization()
    edit_boundaries()
