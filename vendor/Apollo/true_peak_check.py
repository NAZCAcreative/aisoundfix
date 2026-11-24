import sys
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

def check(path, oversample=4):
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    sample_peak = np.max(np.abs(data))
    sample_peak_db = 20 * np.log10(sample_peak + 1e-12)

    oversampled = resample_poly(data, oversample, 1, axis=0)
    true_peak = np.max(np.abs(oversampled))
    true_peak_db = 20 * np.log10(true_peak + 1e-12)

    print(f"{path}")
    print(f"  sample peak: {sample_peak_db:6.2f} dBFS")
    print(f"  true peak (4x oversampled): {true_peak_db:6.2f} dBTP")
    print(f"  inter-sample overshoot: {true_peak_db - sample_peak_db:5.2f} dB")
    if true_peak_db > -1.0:
        print(f"  *** EXCEEDS -1 dBTP broadcast standard (Spotify/Apple Music target) ***")

if __name__ == "__main__":
    for p in sys.argv[1:]:
        check(p)
