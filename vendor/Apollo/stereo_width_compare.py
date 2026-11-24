import sys
import numpy as np
import soundfile as sf

def analyze(path):
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    if data.shape[1] < 2:
        print(f"{path}: mono, no stereo width")
        return
    l, r = data[:, 0], data[:, 1]
    side = (l - r) / 2
    mid = (l + r) / 2
    side_rms = np.sqrt(np.mean(side ** 2) + 1e-12)
    mid_rms = np.sqrt(np.mean(mid ** 2) + 1e-12)
    ratio = side_rms / (mid_rms + 1e-12)
    print(f"{path}\n  mid RMS: {mid_rms:.5f}  side RMS: {side_rms:.5f}  width ratio: {ratio:.3f}")

if __name__ == "__main__":
    for p in sys.argv[1:]:
        analyze(p)
