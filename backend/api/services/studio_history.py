"""Disk-backed studio conversions and discovery of earlier local work folders."""

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from filelock import AsyncFileLock, FileLock


TRACK = re.compile(r"[0-9a-f]{32}")
VERSION = re.compile(r"[0-9a-f]{64}")
SESSION = re.compile(r"aisoundfix-studio-[a-z0-9_]{8}")
JOB = re.compile(r"(?:real|stem|upgrade(?:v[234])?)_[0-9a-f]{8}")
AUDIO = {".wav", ".flac", ".m4a", ".mp3"}


def linked(path):
    flags = path.lstat()
    return stat.S_ISLNK(flags.st_mode) or bool(getattr(flags, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def direct_directory(parent, path):
    return (path.parent == parent and path.is_dir() and not linked(path)
            and path.resolve() == path.absolute())


def file_ok(path):
    return path.is_file() and not linked(path)


def read_json(path):
    if file_ok(path):
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    return {}


def files_in(folder, strict=True):
    for item in folder.iterdir():
        if linked(item):
            if strict:
                raise OSError("연결된 경로가 포함된 작업입니다.")
            continue
        if item.is_dir():
            yield from files_in(item, strict)
        elif item.is_file():
            yield item


def erase(folder):
    # Check the entire tree before unlinking anything. Keep the identity file until last for retries.
    files = list(files_in(folder))
    for item in sorted(files, key=lambda p: (p.name == "track.json", p.name == "version.json")):
        item.unlink(missing_ok=True)
    for parent, _, _ in os.walk(folder, topdown=False):
        Path(parent).rmdir()


def version_id(recipe):
    payload = json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(b"studio-1/" + payload).hexdigest()


@dataclass
class Entry:
    id: str
    tracks: list = field(default_factory=list)
    jobs: list = field(default_factory=list)

    @property
    def folders(self):
        return self.tracks + self.jobs

    def previous_files(self):
        found = {}
        for folder in self.jobs:
            for path in sorted(folder.iterdir()):
                if not file_ok(path) or path.suffix.lower() not in AUDIO:
                    continue
                if path.stem == "input":
                    found.setdefault("input", path)
                elif path.stem.endswith("_final"):
                    found.setdefault("previous", path)
        for folder in self.folders:
            for part in ("vocals", "instrumental"):
                path = folder / (part + ".wav")
                if file_ok(path):
                    found.setdefault(part, path)
        return found

    def describe(self):
        meta = read_json(self.tracks[0] / "track.json") if self.tracks else {}
        downloads = self.previous_files()
        versions = []
        if self.tracks:
            root = self.tracks[0] / "versions"
            if direct_directory(self.tracks[0], root):
                for folder in root.iterdir():
                    if VERSION.fullmatch(folder.name) and direct_directory(root, folder) and file_ok(folder / "master.wav"):
                        try:
                            info = read_json(folder / "version.json")
                        except (OSError, ValueError):
                            continue
                        if info.get("id") == folder.name:
                            versions.append(info)
        versions.sort(key=lambda v: (v["createdAt"], v["id"]), reverse=True)
        size = 0
        updated = 0
        seen = set()
        for folder in self.folders:
            for path in files_in(folder, strict=False):
                info = path.stat()
                identity = (info.st_dev, info.st_ino) if info.st_ino else path
                if identity not in seen:
                    seen.add(identity)
                    size += info.st_size
                updated = max(updated, info.st_mtime)
        name = meta.get("name") or ("이전 변환 · " + self.jobs[0].name if self.jobs else self.id)
        return {"id": self.id, "name": name, "example": bool(meta.get("example")),
                "format": meta.get("format") or next((p.suffix[1:].upper() for p in downloads.values()), ""),
                "duration": meta.get("duration"), "updatedAt": updated, "bytes": size, "versions": versions,
                "canOpen": any(file_ok(p / "source.wav") for p in self.tracks) or "input" in downloads or "previous" in downloads,
                "files": {key: p.suffix[1:].upper() for key, p in downloads.items() if key != "input"}}


class StudioLibrary:
    def __init__(self, root, temp, job_roots):
        self.root = Path(root).absolute()
        self.temp = Path(temp).absolute()
        self.job_roots = tuple(Path(p).absolute() for p in job_roots)

    def home(self, scope):
        if scope != "local" and not VERSION.fullmatch(scope):
            raise ValueError("Invalid workspace")
        home = self.root / scope
        home.mkdir(parents=True, exist_ok=True)
        if not direct_directory(self.root, home):
            raise OSError("작업 저장 경로를 확인하세요.")
        return home

    def lock(self, scope, key, *, asynchronous=False):
        # Keep locks outside the audio folder so a deletion can hold the lock until it finishes.
        locks = self.root / ".locks"
        locks.mkdir(parents=True, exist_ok=True)
        slot = hashlib.sha256((scope + key).encode()).hexdigest()
        path = locks / (slot + ".lock")
        return AsyncFileLock(path, run_in_executor=False) if asynchronous else FileLock(path)

    def entries(self, scope, key=None):
        if key is not None and not TRACK.fullmatch(key):
            raise ValueError("Invalid track")
        found = {}
        roots = [self.home(scope)]
        if scope == "local":
            roots.extend(p for p in self.temp.glob("aisoundfix-studio-*")
                         if SESSION.fullmatch(p.name) and direct_directory(self.temp, p))
        for root in roots:
            for folder in ([root / key] if key else root.iterdir()):
                if not TRACK.fullmatch(folder.name) or not direct_directory(root, folder):
                    continue
                try:
                    if read_json(folder / "track.json").get("id") != folder.name:
                        continue
                except (OSError, ValueError):
                    continue
                found.setdefault(folder.name, Entry(folder.name)).tracks.append(folder)
        if scope == "local":
            for root in self.job_roots:
                if not direct_directory(root.parent, root):
                    continue
                for folder in root.iterdir():
                    if JOB.fullmatch(folder.name) and direct_directory(root, folder):
                        ident = uuid.uuid5(uuid.NAMESPACE_URL, "aisoundfix/job/" + folder.name).hex
                        if key is None or key == ident:
                            found.setdefault(ident, Entry(ident)).jobs.append(folder)
        return found

    def list(self, scope):
        rows = []
        for entry in self.entries(scope).values():
            try:
                rows.append(entry.describe())
            except FileNotFoundError:
                continue  # An upload or deletion in another tab can complete during the scan.
        return sorted(rows, key=lambda row: (row["updatedAt"], row["id"]), reverse=True)

    def promote(self, scope, entry, prepare):
        """Reopened legacy work is made durable before any new render is committed."""
        destination = self.home(scope) / entry.id
        if entry.tracks and entry.tracks[0] == destination:
            return destination
        with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".open-") as tmp:
            stage = Path(tmp) / entry.id
            stage.mkdir()
            if entry.tracks:
                source = next((p for p in entry.tracks if file_ok(p / "source.wav")), None)
                if source is None:
                    raise FileNotFoundError("이 작업의 원본이 남아 있지 않습니다.")
                for path in files_in(source):
                    target = stage / path.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        os.link(path, target)
                    except OSError:
                        shutil.copy2(path, target)
            else:
                old = entry.previous_files()
                source = old.get("input") or old.get("previous")
                if source is None:
                    raise FileNotFoundError("이 작업의 음원이 남아 있지 않습니다.")
                prepare(stage, source, "이전 변환 · " + entry.jobs[0].name)
            stage.replace(destination)
        return destination

    def save_version(self, folder, recipe, wav, stats):
        key = version_id(recipe)
        root = folder / "versions"
        root.mkdir(exist_ok=True)
        if not direct_directory(folder, root):
            raise OSError("보정본 경로를 확인하세요.")
        destination = root / key
        with tempfile.TemporaryDirectory(dir=root, prefix=".render-") as tmp:
            stage = Path(tmp) / key
            stage.mkdir()
            (stage / "master.wav").write_bytes(wav)
            info = {"id": key, "createdAt": time.time(), "recipe": recipe, "stats": stats, "bytes": len(wav)}
            (stage / "version.json").write_text(json.dumps(info), encoding="utf-8")
            stage.replace(destination)

    def delete(self, scope, entry):
        allowed = {self.home(scope)}
        if scope == "local":
            allowed.update(self.job_roots)
        for folder in entry.folders:
            parent = folder.parent
            legacy = scope == "local" and SESSION.fullmatch(parent.name) and direct_directory(self.temp, parent)
            if not (parent in allowed or legacy) or not direct_directory(parent, folder):
                raise OSError("작업 저장 경로를 확인하세요.")
            if folder in entry.tracks and (folder.name != entry.id or read_json(folder / "track.json").get("id") != entry.id):
                raise OSError("작업 식별자가 일치하지 않습니다.")
            if folder in entry.jobs and not JOB.fullmatch(folder.name):
                raise OSError("이전 작업 식별자가 일치하지 않습니다.")
            list(files_in(folder))
        for folder in reversed(entry.folders):
            erase(folder)
