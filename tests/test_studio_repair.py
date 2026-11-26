import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from api.routes.studio import Recipe, prepare_track
from worker.pipeline import studio
from worker.pipeline.stages import peak_repair
from worker.pipeline.stages.band_repair import repair_band, spectral_edge


class StudioRepairTests(unittest.TestCase):
    def test_quantizer_preserves_the_master_true_peak_ceiling(self):
        rate = 48000
        raw = np.sin(2 * np.pi * 50 * np.arange(rate) / rate)
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sf.write(folder / "source.wav", raw, rate, subtype="FLOAT")
            wet, _, stats = studio.render_audio(folder, 0, 0, 0, 0, bits=8, dither=True)
        self.assertLessEqual(studio.peak_db(wet), -1)
        self.assertLessEqual(stats["truePeak"], -1)
        np.testing.assert_array_equal(wet * 128, np.rint(wet * 128))

    def test_fullness_lifts_bass_and_spatial_width_keeps_the_centre(self):
        rate = 24000
        time = np.arange(rate) / rate
        centre = .13 * np.sin(2 * np.pi * 50 * time)
        side = .07 * np.sin(2 * np.pi * 3000 * time)
        source = np.column_stack((centre + side, centre - side))
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sf.write(folder / "source.wav", source, rate, subtype="FLOAT")
            fullness, _, _ = studio.render_audio(folder, 0, 0, 0, 0, fullness=100)
            both, _, _ = studio.render_audio(folder, 0, 0, 100, 0, fullness=100)
        # Skip the initial filter state transient for steady-state measurements.
        frames = slice(rate // 2, None)
        assert 1.56 < np.std(fullness.mean(axis=1)[frames]) / np.std(centre[frames]) < 1.59
        np.testing.assert_allclose(both.mean(axis=1), fullness.mean(axis=1), atol=4e-8)
        ratio = np.std((both[:, 0] - both[:, 1])[frames]) / (2 * np.std(side[frames]))
        assert 1.79 < ratio < 1.81

    def test_peak_recipe_is_local_and_survives_block_boundaries(self):
        rate = 32000
        t = np.arange(rate * 2) / rate
        original = (.44 * np.sin(2*np.pi*179*t) * (.8 + .2*np.sin(2*np.pi*2*t))).astype("float32")
        original = np.column_stack((original, original * .84))
        clipped = np.clip(original, -.35, .35)
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / "input.wav"
            sf.write(source, clipped, rate, subtype="FLOAT")
            with patch.object(peak_repair, "BLOCK", 4096):
                meta = prepare_track(folder, source, "clipped")
            self.assertEqual(meta["analysis"]["kind"], "peaks")
            self.assertEqual(meta["analysis"]["preview"], {"start": 0, "end": 2})
            self.assertTrue(meta["recommended"]["repair"])
            processed, output_rate, _ = studio.render_audio(folder, **meta["recommended"])
            dry, _, _ = studio.render_audio(folder, **Recipe().model_dump())
            self.assertEqual(output_rate, rate)
            np.testing.assert_array_equal(dry, clipped)
            np.testing.assert_array_equal(processed[original == clipped], clipped[original == clipped])
            self.assertLess(np.linalg.norm(processed-original), np.linalg.norm(clipped-original))
            again = peak_repair.prepare_peak_repair(folder, clipped, rate)
            self.assertEqual(meta["analysis"], again)
            whole, _ = sf.read(folder / "peaks.wav", dtype="float32", always_2d=True)
            np.testing.assert_allclose(processed, whole, rtol=0, atol=2e-7)

    def test_clean_short_mono_keeps_dry_default_and_no_peak_cache(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / "input.flac"
            sf.write(source, np.zeros(103), 48000, subtype="PCM_24")
            meta = prepare_track(folder, source, "silence")
            self.assertEqual(meta["analysis"], {"kind": "none"})
            self.assertFalse(any(meta["recommended"].values()))
            self.assertFalse((folder / "peaks.wav").exists())
            self.assertEqual(spectral_edge(np.zeros((103, 1)), 48000), 0)
            out, _, _ = studio.render_audio(folder, **meta["recommended"])
            np.testing.assert_array_equal(out, np.zeros((103, 1)))

    def test_dc_offset_floor_is_not_reconstructed_in_the_wrong_direction(self):
        x = np.linspace(.2, .6, 1000, dtype="float32")[:, None]
        for first in (150, 300, 450):
            x[first:first+8] = .1
        self.assertEqual(peak_repair.find_rails(x), [[None, None]])
        self.assertEqual(peak_repair.find_rails(-x), [[None, None]])

    def test_optional_band_repair_uses_original_rate_and_cached_full_length_audio(self):
        rate = 48000
        audio = np.random.default_rng(12).normal(0, .025, (rate+17, 1)).astype("float32")
        delta = np.roll(audio, 2, axis=0) * .2
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sf.write(folder / "source.wav", audio, rate, subtype="FLOAT")
            (folder / "track.json").write_text(json.dumps({"analysis": {"kind": "band", "edgeHz": 8000}}))
            with patch.object(studio, "apollo_delta", return_value=delta) as model:
                dry, _, _ = studio.render_audio(folder, 0, 0, 0, 0)
                model.assert_not_called()
                first, out_rate, _ = studio.render_audio(folder, 0, 0, 0, 0, repair=True)
                second, _, _ = studio.render_audio(folder, 0, 0, 0, 0, repair=True)
                model.assert_called_once()
            np.testing.assert_array_equal(dry, audio)
            np.testing.assert_array_equal(first, second)
            np.testing.assert_array_equal(first, repair_band(audio, delta, rate, 8000))
            self.assertGreater(np.linalg.norm(first-dry), .001)
            self.assertEqual((out_rate, first.shape), (rate, audio.shape))


if __name__ == "__main__":
    unittest.main()
