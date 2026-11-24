import sys
import numpy as np
import soundfile as sf
import pyloudnorm as pyln

def analyze(path):
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    meter = pyln.Meter(sr)
    lufs = meter.integrated_loudness(data)

    mono = data.mean(axis=1)
    frame = int(0.05 * sr)
    n_frames = len(mono) // frame
    rms = np.array([
        np.sqrt(np.mean(mono[i*frame:(i+1)*frame] ** 2) + 1e-12)
        for i in range(n_frames)
    ])
    rms_db = 20 * np.log10(rms + 1e-12)
    dyn_range = np.percentile(rms_db, 99) - np.percentile(rms_db, 10)

    spec = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(len(mono), d=1.0/sr)
    hi_mask = (freqs >= 6000) & (freqs < 16000)
    lo_mask = (freqs >= 200) & (freqs < 2000)
    hi_energy = 10 * np.log10(np.mean(spec[hi_mask] ** 2) + 1e-12)
    lo_energy = 10 * np.log10(np.mean(spec[lo_mask] ** 2) + 1e-12)

    print(f"\n{path}")
    print(f"  integrated loudness: {lufs:6.2f} LUFS")
    print(f"  dynamic range (99-10pct RMS): {dyn_range:6.2f} dB")
    print(f"  brightness (6-16kHz vs 200-2kHz): {hi_energy - lo_energy:6.2f} dB")

if __name__ == "__main__":
    for p in sys.argv[1:]:
        analyze(p)
