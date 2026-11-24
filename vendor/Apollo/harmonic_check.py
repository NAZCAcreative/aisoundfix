import sys
import numpy as np
import soundfile as sf

def analyze(path):
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    spec = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(len(mono), d=1.0/sr)

    fund_mask = (freqs >= 200) & (freqs < 800)
    harm2_mask = (freqs >= 400) & (freqs < 1600)  # 2nd harmonic region

    fund_db = 10 * np.log10(np.mean(spec[fund_mask] ** 2) + 1e-12)
    harm_db = 10 * np.log10(np.mean(spec[harm2_mask] ** 2) + 1e-12)

    print(f"{path}\n  fundamental (200-800Hz): {fund_db:.2f} dB, harmonic region (400-1600Hz): {harm_db:.2f} dB")

if __name__ == "__main__":
    for p in sys.argv[1:]:
        analyze(p)
