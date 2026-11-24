import sys
import numpy as np
import soundfile as sf

def band_energy_db(path, bands):
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    n = len(mono)
    spec = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(n, d=1.0 / sr)

    print(f"\n{path}")
    print(f"  sr={sr}, duration={n/sr:.1f}s")
    for lo, hi in bands:
        mask = (freqs >= lo) & (freqs < hi)
        energy = np.mean(spec[mask] ** 2) if mask.any() else 0
        db = 10 * np.log10(energy + 1e-12)
        print(f"  {lo:>6}-{hi:<6} Hz: {db:7.2f} dB (rel)")

if __name__ == "__main__":
    bands = [(0, 2000), (2000, 4000), (4000, 8000), (8000, 12000), (12000, 16000), (16000, 20000), (20000, 22050)]
    for p in sys.argv[1:]:
        band_energy_db(p, bands)
