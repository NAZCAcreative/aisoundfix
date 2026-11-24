import pathlib
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

if sys.platform == "win32":
    pathlib.PosixPath = pathlib.WindowsPath  # resemble-enhance's hparams.yaml was serialized on Linux

RESEMBLE_ENHANCE_DIR = Path(__file__).resolve().parents[4] / "vendor" / "resemble-enhance"
if str(RESEMBLE_ENHANCE_DIR) not in sys.path:
    sys.path.insert(0, str(RESEMBLE_ENHANCE_DIR))

_device = "cuda" if torch.cuda.is_available() else "cpu"


def run_vocal_enhance(audio_path: str, nfe: int = 32, solver: str = "midpoint", lambd: float = 0.5, tau: float = 0.5) -> str:
    print(f"[Stage] Enhancing vocal clarity (denoise + CFM restoration): {audio_path}")

    from resemble_enhance.enhancer.inference import enhance

    data, sr = sf.read(audio_path, dtype="float32", always_2d=True)  # [samples, channels]
    channels = data.shape[1]
    mono = data.mean(axis=1)

    # Resemble Enhance is a mono model (its own reference app.py mono-sums before
    # processing). Running L/R independently was tried and rejected: the CFM
    # sampler amplifies tiny inter-channel differences non-linearly, decorrelating
    # L/R far beyond the original mix (measured width ratio 0.24 -> 0.96) and
    # producing an artificial phasey/wide artifact instead of preserving the
    # original stereo image.
    dwav = torch.from_numpy(mono)
    wav, new_sr = enhance(dwav, sr, _device, nfe=nfe, solver=solver, lambd=lambd, tau=tau)
    enhanced_mono = wav.cpu().numpy()
    n = len(enhanced_mono)

    if channels >= 2:
        # Mid-side reconstruction: replace only the mono content with the
        # enhanced version, keep the original (untouched) side signal so the
        # real stereo width survives without model-induced decorrelation.
        side = (data[:n, 0] - data[:n, 1]) / 2
        left = enhanced_mono + side
        right = enhanced_mono - side
        enhanced = np.stack([left, right], axis=1)
    else:
        enhanced = enhanced_mono[:, None]

    out_path = str(Path(audio_path).with_name(Path(audio_path).stem + "_enhanced.wav"))
    sf.write(out_path, enhanced, new_sr)
    return out_path
