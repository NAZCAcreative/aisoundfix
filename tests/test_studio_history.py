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
