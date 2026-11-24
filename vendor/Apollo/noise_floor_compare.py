import sys
import numpy as np
import soundfile as sf

def analyze(path):
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)

    frame = int(0.05 * sr)
    n_frames = len(mono) // frame
    rms = np.array([
        np.sqrt(np.mean(mono[i*frame:(i+1)*frame] ** 2) + 1e-12)
        for i in range(n_frames)
    ])
    rms_db = 20 * np.log10(rms + 1e-12)

    noise_floor_db = np.percentile(rms_db, 10)
    peak_db = np.percentile(rms_db, 99)

    print(f"\n{path}")
    print(f"  noise floor (10th pct RMS): {noise_floor_db:6.2f} dB")
    print(f"  peak level  (99th pct RMS): {peak_db:6.2f} dB")
    print(f"  dynamic range:              {peak_db - noise_floor_db:6.2f} dB")

if __name__ == "__main__":
    for p in sys.argv[1:]:
        analyze(p)
