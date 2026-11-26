import io
import json
import os
import sys
import uuid
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import soundfile as sf
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from api.routes import studio
from api.services.studio_history import StudioLibrary


class HistoryTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.old = self.root / "temp"
        self.old.mkdir()
        self.jobs = [self.root / name for name in ("uploads", "jobs", "outputs")]
        for path in self.jobs:
            path.mkdir()
        self.library = StudioLibrary(self.root / "studio", self.old, self.jobs)
        mocked = patch.object(studio, "library", self.library)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.app = FastAPI()
        self.app.include_router(studio.router)
        self.client = TestClient(self.app, base_url="http://localhost", client=("127.0.0.1", 45000))
        self.base = "/api/studio"
        self.history = self.base + "/history"
        data = io.BytesIO()
        t = np.arange(24000) / 24000
        sf.write(data, .21*np.sin(2*np.pi*381*t), 24000, format="WAV", subtype="PCM_24")
        self.wav = data.getvalue()

    def upload(self, client=None):
        res = (client or self.client).post(self.base + "/tracks", files={"file": ("곡.wav", self.wav, "audio/wav")})
        self.assertEqual(res.status_code, 201, res.text)
        return res.json()["id"]

    def test_render_versions_persist_and_delete_actual_files(self):
        key = self.upload()
        url = self.base + "/tracks/" + key + "/render"
        self.client.post(url, json={}).raise_for_status()
        first = self.client.post(url, json={"clarity": 70})
        self.client.post(url, json={"clarity": 35}).raise_for_status()
        self.assertEqual(self.client.post(url, json={"clarity": 70}).content, first.content)
        other_instance = StudioLibrary(self.library.root, self.old, self.jobs)
        row, = other_instance.list("local")
        self.assertEqual((row["name"], len(row["versions"])), ("곡", 2))
        version = next(v for v in row["versions"] if v["recipe"]["clarity"] == 70)
        download = self.history + "/" + key + "/versions/" + version["id"]
        self.assertEqual(self.client.get(download).content, first.content)
        folder = self.library.home("local") / key
        (folder / "vocals.wav").write_bytes(self.wav)
        (folder / "instrumental.wav").write_bytes(self.wav)
        self.assertTrue(self.client.post(self.history + "/" + key + "/open").json()["hasStems"])
        self.assertEqual(self.client.delete(download).status_code, 204)
        self.assertEqual(self.client.get(download).status_code, 404)
        self.assertFalse((folder / "versions" / version["id"]).exists())
        self.assertTrue((folder / "source.wav").exists())
        self.assertEqual(self.client.post(url + "?archive_only=true", json={}).status_code, 204)
        self.assertEqual(self.client.post(url + "?archive_only=true", json={}).status_code, 204)
        final, = self.library.list("local")
        self.assertEqual(len(final["versions"]), 2)
        dry = next(v for v in final["versions"] if not any(v["recipe"].values()))
        self.assertEqual(self.client.get(self.history + "/" + key + "/versions/" + dry["id"]).content,
                         self.client.post(url, json={}).content)
        self.assertEqual(self.client.post(self.history + "/delete", json={"ids": [key]}).json()["deleted"], [key])
        self.assertFalse(folder.exists())
        self.assertEqual(self.client.get(self.base + "/tracks/" + key + "/audio").status_code, 404)

    def test_library_example_prefers_local_music_and_reuses_cached_track(self):
        music = self.root / "테스트 곡.wav"
        music.write_bytes(self.wav)
        url = self.base + "/examples/library"
        with patch.object(studio, "sample_songs", return_value=[music]):
            first = self.client.get(url).raise_for_status().json()
            self.assertEqual((first["name"], first["example"]), ("테스트 곡", "library"))
            self.assertEqual(self.client.get(url).json()["id"], first["id"])
        with patch.object(studio, "sample_songs", return_value=[]):
            self.assertEqual(self.client.get(url).raise_for_status().json()["id"],
                             self.client.get(self.base + "/examples/clipped").json()["id"])

    def test_quantized_saved_render_and_legacy_recipe_identity(self):
        key = self.upload()
        url = self.base + "/tracks/" + key + "/render"
        legacy = {"clarity": 5}
        original = self.client.post(url, json=legacy).raise_for_status().content
        neutral = {**legacy, "fullness": 0, "bits": 0, "dither": True}
        self.assertEqual(self.client.post(url, json=neutral).raise_for_status().content, original)
        row, = self.library.list("local")
        version, = row["versions"]
        self.assertFalse({"bits", "dither", "fullness"}.intersection(version["recipe"]))

        settings = {"fullness": 71, "bits": 8, "dither": True}
        preview = self.client.post(url + "?preview=true", json=settings).raise_for_status()
        saved = self.client.post(url, json=settings).raise_for_status()
        self.assertEqual(preview.content, saved.content)
        codes, _ = sf.read(io.BytesIO(saved.content), dtype="int32")
        self.assertTrue(np.all((codes & 0x00ffffff) == 0))
        self.assertGreater(np.max(np.abs(codes)), 1 << 25)
        row, = self.library.list("local")
        version = next(v for v in row["versions"] if v["recipe"].get("bits"))
        self.assertTrue(all(version["recipe"][k] == v for k, v in settings.items()))
        self.assertEqual(self.client.post(url, json={"bits": 10}).status_code, 422)

    def test_stem_pair_region_preview_and_vocal_export(self):
        backing_file = io.BytesIO()
        t = np.arange(30000) / 24000
        backing = np.stack((.12*np.sin(2*np.pi*239*t), .08*np.cos(2*np.pi*733*t)), axis=1)
        sf.write(backing_file, backing, 24000, format="WAV", subtype="FLOAT")
        pair = self.client.post(self.base + "/tracks/stem-pair", files={
            "vocals": ("v.wav", self.wav, "audio/wav"),
            "instrumental": ("i.wav", backing_file.getvalue(), "audio/wav"),
        })
        pair.raise_for_status()
        info = pair.json()
        self.assertEqual((info["stemPair"], info["channels"], info["vocalChannels"], info["duration"]),
                         (True, 2, 1, 1.25))
        url = self.base + "/tracks/" + info["id"]
        original, rate = sf.read(io.BytesIO(self.client.get(url + "/audio").content), always_2d=True)
        settings = {"clarity": 80, "region": {"start": .25, "end": .75}}
        preview = self.client.post(url + "/render?preview=true", json=settings)
        preview.raise_for_status()
        levels = json.loads(preview.headers["X-Audio-Metrics"])["regionLevels"]
        self.assertEqual((levels["start"], levels["end"]), (.25, .75))
        self.assertTrue(np.isfinite([levels["originalLufs"], levels["processedLufs"]]).all())
        voice = self.client.post(url + "/render", json={**settings, "output": "vocals"})
        voice.raise_for_status()
        row, = self.library.list("local")
        self.assertEqual(row["versions"], [])
        self.assertEqual(self.client.post(url + "/render", json=settings).content, preview.content)
        mixed, _ = sf.read(io.BytesIO(preview.content), always_2d=True)
        vocal, _ = sf.read(io.BytesIO(voice.content), always_2d=True)
        np.testing.assert_allclose(mixed, (backing + vocal)*info["mixGain"], rtol=0, atol=3e-7)
        outside = (t < .25) | (t >= .75)
        np.testing.assert_allclose(mixed[outside], original[outside], rtol=0, atol=1.3e-7)
        self.assertGreater(np.max(np.abs(mixed[~outside]-original[~outside])), .001)
        row, = self.library.list("local")
        self.assertEqual(row["versions"][0]["recipe"]["region"], settings["region"])
        self.assertTrue(self.client.post(self.history + "/" + info["id"] + "/open").json()["stemPair"])
        for region in ({"start": .5, "end": .5}, {"start": .9, "end": 2}):
            self.assertEqual(self.client.post(url + "/render", json={"region": region}).status_code, 422)
        key = self.upload()
        self.assertEqual(self.client.post(self.base + "/tracks/" + key + "/render",
                                          json={"output": "vocals"}).status_code, 422)

    def test_legacy_files_and_busy_snapshot(self):
        old = self.old / "aisoundfix-studio-abc12345"
        key = uuid.uuid4().hex
        track = old / key
        track.mkdir(parents=True)
        (track / "source.wav").write_bytes(self.wav)
        (track / "track.json").write_text(json.dumps({"id": key, "name": "archive"}))
        untouched = old / "user-notes"
        untouched.mkdir()
        job = self.jobs[0] / "real_af10bcec"
        job.mkdir()
        (job / "input.wav").write_bytes(self.wav)
        (job / "input_mastered_final.wav").write_bytes(self.wav)
        extra = self.jobs[2] / job.name
        extra.mkdir()
        (extra / "intermediate.wav").write_bytes(self.wav)
        rows = self.client.get(self.history).json()["items"]
        job_id = next(row["id"] for row in rows if row["id"] != key)
        self.assertEqual(self.client.get(self.history + "/" + job_id + "/files/previous").content, self.wav)
        self.client.post(self.history + "/" + job_id + "/open").raise_for_status()
        self.assertEqual(len(self.library.list("local")), 2)
        newer = self.upload()
        table = {job.name: {"status": "processing"}}
        self.app.state.legacy_jobs = (table,)
        self.assertEqual(self.client.post(self.history + "/delete", json={"ids": [job_id]}).json()["failed"], [job_id])
        table[job.name]["status"] = "done"
        with self.library.lock("local", key):
            result = self.client.post(self.history + "/delete", json={"ids": [key, job_id]}).json()
        self.assertEqual(result, {"deleted": [job_id], "failed": [key]})
        self.assertFalse(any(p.exists() for p in (job, extra, self.library.home("local") / job_id)))
        self.assertNotIn(job.name, table)
        self.client.post(self.history + "/delete", json={"ids": [key]}).raise_for_status()
        self.assertFalse(track.exists())
        self.assertTrue(untouched.is_dir())
        self.assertEqual([row["id"] for row in self.library.list("local")], [newer])

    def test_hosted_browsers_and_local_library_are_separate(self):
        local = self.upload()
        first, second = TestClient(self.app), TestClient(self.app)
        remote = self.upload(first)
        self.assertEqual([r["id"] for r in first.get(self.history).json()["items"]], [remote])
        self.assertEqual(second.get(self.history).json()["items"], [])
        self.assertEqual(second.get(self.base + "/tracks/" + remote + "/audio").status_code, 404)
        first.post(self.history + "/delete", json={"ids": [local]}).raise_for_status()
        self.assertEqual(self.client.get(self.history, headers={"Origin":"https://elsewhere.example"}).status_code, 403)
        self.assertEqual([r["id"] for r in self.client.get(self.history).json()["items"]], [local])

    def test_copies_of_a_legacy_session_share_one_row_and_one_file_size(self):
        key = uuid.uuid4().hex
        first = self.old / "aisoundfix-studio-abcdef12" / key
        other = self.old / "aisoundfix-studio-abcdef34" / key
        first.mkdir(parents=True)
        other.mkdir(parents=True)
        (first / "source.wav").write_bytes(self.wav)
        (first / "track.json").write_text(json.dumps({"id": key, "name": "old"}))
        for path in first.iterdir():
            os.link(path, other / path.name)
        row, = self.library.list("local")
        self.assertEqual(row["bytes"], sum(p.stat().st_size for p in first.iterdir()))
        self.client.post(self.history + "/delete", json={"ids": [key]}).raise_for_status()
        self.assertFalse(first.exists() or other.exists())
