import sys
import numpy as np
import soundfile as sf

for f in sys.argv[1:]:
    data, sr = sf.read(f)
    peak = np.max(np.abs(data))
    print(f, "peak:", peak, "peak dB:", 20 * np.log10(peak + 1e-12))
