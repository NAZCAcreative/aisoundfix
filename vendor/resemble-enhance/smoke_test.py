import pathlib
import sys
import time
from pathlib import Path

import soundfile as sf
import torch

if sys.platform == "win32":
    pathlib.PosixPath = pathlib.WindowsPath  # hparams.yaml was serialized on Linux

sys.path.insert(0, str(Path(__file__).resolve().parent))

from resemble_enhance.enhancer.inference import denoise, enhance

def main(in_wav, out_denoised, out_enhanced):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("device:", device)

    data, sr = sf.read(in_wav, dtype="float32", always_2d=True)
    dwav = torch.from_numpy(data.mean(axis=1))

    t0 = time.time()
    wav1, new_sr = denoise(dwav, sr, device)
    print(f"denoise: {time.time()-t0:.1f}s, sr={new_sr}")
    sf.write(out_denoised, wav1.cpu().numpy(), new_sr)

    t1 = time.time()
    wav2, new_sr = enhance(dwav, sr, device, nfe=32, solver="midpoint", lambd=0.5, tau=0.5)
    print(f"enhance: {time.time()-t1:.1f}s, sr={new_sr}")
    sf.write(out_enhanced, wav2.cpu().numpy(), new_sr)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
