import sys
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.worker.pipeline.stages.sound_lab import ghost_bass, rhythm_focus, velvet_room


class SoundLabTests(unittest.TestCase):
    def test_virtual_bass_creates_upper_harmonics(self):
        rate = 16000
        time = np.arange(2 * rate) / rate
        tone = (.25 * np.sin(2 * np.pi * 55 * time)).astype("float32")[:, None]
        residual = (ghost_bass(tone, rate, .8) - tone)[rate//2:3*rate//2, 0]
        amplitudes = np.abs(np.fft.rfft(residual)) * 2 / rate
        self.assertGreater(amplitudes[110], .05)
        self.assertGreater(amplitudes[165], .02)
        self.assertLess(amplitudes[55], .001)

    def test_rhythm_increases_attack_to_sustain_ratio_and_preserves_panning(self):
        rate = 16000
        time = np.arange(4 * rate) / rate
        hits = np.zeros(len(time), dtype=bool)
        for start in range(rate // 4, len(time), rate // 4):
            hits[start:start+rate//80] = True
        noise = np.random.default_rng(31).normal(0, .22, len(time))
        mono = .12 * np.sin(2 * np.pi * 330 * time) + hits * noise
        stereo = np.column_stack((mono, mono * .4)).astype("float32")
        result = rhythm_focus(stereo, rate, .8)
        np.testing.assert_allclose(result[:, 1], .4 * result[:, 0], atol=1e-6)

        def ratio(x):
            return np.sqrt(np.mean(x[hits]**2) / np.mean(x[~hits]**2))

        self.assertGreater(ratio(result[:, 0]), 1.6 * ratio(mono))

    def test_velvet_has_a_delayed_repeatable_decorrelated_tail(self):
        rate = 24000
        impulse = np.zeros((2 * rate, 2), dtype="float32")
        impulse[0] = .5
        wet = velvet_room(impulse, rate, .7) - impulse
        self.assertFalse(np.any(wet[:round(.018 * rate)]))
        self.assertGreater(np.linalg.norm(wet[rate//10:rate//2]), .01)
        self.assertLess(abs(np.corrcoef(wet.T)[0, 1]), .4)
        np.testing.assert_array_equal(wet, velvet_room(impulse, rate, .7) - impulse)

    def test_short_silence_and_zero_intensity(self):
        for rate, channels, size in [(8000, 1, 1), (48000, 2, 317), (96000, 1, 601)]:
            sound = np.zeros((size, channels), dtype="float32")
            for effect in (ghost_bass, rhythm_focus, velvet_room):
                with self.subTest(rate=rate, effect=effect.__name__):
                    np.testing.assert_array_equal(effect(sound, rate, 1), sound)
                    tone = sound.copy()
                    tone[0] = .3
                    np.testing.assert_array_equal(effect(tone, rate, 0), tone)

    def test_hot_bypass_delta_uses_the_master_ceiling_gain(self):
        from backend.worker.pipeline.studio import peak_db, render_audio

        rate = 48000
        time = np.arange(rate) / rate
        dry = (.99 * np.sin(2 * np.pi * 997 * time)).astype("float32")[:, None]
        with TemporaryDirectory() as work:
            folder = Path(work)
            sf.write(folder / "source.wav", dry, rate, subtype="FLOAT")
            output, _, stats = render_audio(folder, 0, 0, 0, 0)
        wav = BytesIO()
        sf.write(wav, output, rate, format="WAV", subtype="PCM_24")
        wav.seek(0)
        pcm, _ = sf.read(wav, dtype="float32", always_2d=True)
        self.assertLess(stats["ceilingGain"], 1)
        self.assertLessEqual(peak_db(pcm), -.995)
        np.testing.assert_allclose(pcm, stats["ceilingGain"] * dry, rtol=0, atol=1.3e-7)


if __name__ == "__main__":
    unittest.main()
