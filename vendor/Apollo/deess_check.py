import sys
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

def analyze(path, low=4000, high=9000):
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    nyq = sr / 2
    sos = butter(2, [low/nyq, high/nyq], btype="band", output="sos")
    band = sosfilt(sos, mono)

    frame = int(0.02 * sr)
    n = len(band) // frame
    rms = np.array([np.sqrt(np.mean(band[i*frame:(i+1)*frame]**2) + 1e-12) for i in range(n)])
    rms_db = 20 * np.log10(rms + 1e-12)

    p50 = np.percentile(rms_db, 50)
    p99 = np.percentile(rms_db, 99)
    print(f"{path}\n  4-9kHz median: {p50:.2f} dB, peak(99pct): {p99:.2f} dB, crest(peak-median): {p99-p50:.2f} dB")

if __name__ == "__main__":
    for p in sys.argv[1:]:
        analyze(p)
