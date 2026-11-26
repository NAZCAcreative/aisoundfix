"""Round audio to signed PCM codes in bounded blocks."""

import numpy as np
import soundfile as sf


def _pcm_codes(samples, scale, rng=None):
    scaled = samples.astype(np.float64) * scale
    if rng is not None:
        scaled += rng.random(samples.shape) - rng.random(samples.shape)
    return np.clip(np.rint(scaled), -scale, scale - 1).astype(np.int32)


def quantize_samples(audio, bits, dither=False):
    """Replace samples in-place with points on the requested PCM grid."""
    scale = 1 << (bits - 1)
    # Repeatable TPDF keeps preview, archived mixes and vocal stems consistent.
    rng = np.random.default_rng(7283) if dither else None
    for start in range(0, len(audio), 65536):
        block = audio[start:start + 65536]
        block[:] = _pcm_codes(block, scale, rng) / scale


def write_pcm24(destination, audio, rate):
    # libsndfile accepts left-aligned int32 when writing 24-bit PCM. Passing
    # floats directly can truncate rather than round. Work a block at a time.
    scale = 1 << 23
    with sf.SoundFile(destination, "w", samplerate=rate, channels=audio.shape[1],
                      format="WAV", subtype="PCM_24") as wav:
        for start in range(0, len(audio), 65536):
            wav.write(_pcm_codes(audio[start:start + 65536], scale) << 8)
