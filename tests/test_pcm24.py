import io
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from worker.pipeline.stages.pcm24 import write_pcm24


def test_pcm24_rounding_boundaries_and_channel_layout():
    scale = 1 << 23
    codes = np.array([[-scale, scale-1], [0, 1], [-3.8, -.3],
                      [2.6, .49], [4.5, 3.5], [-scale-1, scale]])
    expected = np.array([[-scale, scale-1], [0, 1], [-4, 0],
                         [3, 0], [4, 4], [-scale, scale-1]])
    stream = io.BytesIO()
    write_pcm24(stream, codes / scale, 48000)
    stream.seek(0)
    with sf.SoundFile(stream) as f:
        assert (f.samplerate, f.channels, f.subtype) == (48000, 2, "PCM_24")
        np.testing.assert_array_equal(f.read(dtype="int32") >> 8, expected)
