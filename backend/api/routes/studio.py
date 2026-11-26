import io
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import numpy as np
import soundfile as sf
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from filelock import Timeout

from common.config import Config, BASE_DIR
from ..services.studio_history import StudioLibrary, direct_directory, erase, file_ok, read_json, version_id, VERSION
from worker.pipeline.studio import decode_file, measurements, peak_db, render_audio, separate_audio
from worker.pipeline.stages.band_repair import spectral_edge
from worker.pipeline.stages.peak_repair import prepare_peak_repair
from worker.pipeline.stages.pcm24 import write_pcm24


router = APIRouter(prefix="/api/studio")
logger = logging.getLogger(__name__)
library = StudioLibrary(os.getenv("AISOUNDFIX_STUDIO_DIR") or BASE_DIR / "data" / "studio",
                        tempfile.gettempdir(), (Config.UPLOAD_DIR, Config.JOBS_DIR, Config.OUTPUT_DIR))
_render_slots = threading.BoundedSemaphore(2)
EXAMPLES = {
    "midnight": ("assets/midnight-circuit.mp3", "Midnight Circuit"),
    "compressed": ("assets/midnight-circuit-48k.mp3", "Midnight Circuit · 48 kbps"),
    "clipped": ("research/restoration/peaks-input.flac", "드럼 피크 복원"),
}


class TimeRange(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)


class Recipe(BaseModel):
    repair: bool = False
    clarity: int = Field(default=0, ge=0, le=100)
    deess: int = Field(default=0, ge=0, le=100)
    width: int = Field(default=0, ge=0, le=100)
    restore: int = Field(default=0, ge=0, le=100)
    bass: int = Field(default=0, ge=0, le=100)
    rhythm: int = Field(default=0, ge=0, le=100)
    velvet: int = Field(default=0, ge=0, le=100)
    fullness: int = Field(default=0, ge=0, le=100)
    bits: Literal[0, 8, 12, 16, 24] = 0
    dither: bool = False
    region: TimeRange | None = None
    output: Literal["mix", "vocals"] = "mix"


def workspace(request, response=None):
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin != f"{request.url.scheme}://{request.url.netloc}"):
        raise HTTPException(403, "스튜디오에서 요청하세요.")
    loopback = {"127.0.0.1", "::1", "localhost"}
    if request.client and request.client.host in loopback and request.url.hostname in loopback:
        return "local"
    token = request.cookies.get("studio_library", "")
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        if response is None:
            return None
        token = secrets.token_hex(32)
        response.set_cookie("studio_library", token, max_age=365*86400, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", path="/api/studio")
    return hashlib.sha256(token.encode()).hexdigest()


def entry_for(scope, key):
    entry = library.entries(scope, key).get(key) if scope else None
    if entry is None:
        raise HTTPException(404, "기록에서 이 작업을 찾을 수 없습니다.")
    return entry


def request_scope(request):
    scope = workspace(request)
    if scope is None:
        raise HTTPException(404, "기록에서 이 작업을 찾을 수 없습니다.")
    return scope


class LeasedFile(FileResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.lease.release()


async def send_file(request, key, select):
    scope = request_scope(request)
    lease = library.lock(scope, key, asynchronous=True)
    await lease.acquire()
    try:
        path, filename = await run_in_threadpool(lambda: select(entry_for(scope, key)))
        if not path or not file_ok(path):
            raise HTTPException(404, "저장된 파일을 찾을 수 없습니다.")
        response = LeasedFile(path, filename=filename, headers={"Cache-Control": "private, no-store"})
        response.lease = lease
        return response
    except BaseException:
        await lease.release()
        raise


def saved_version(folder, key):
    if not VERSION.fullmatch(key):
        raise HTTPException(404, "보정본을 찾을 수 없습니다.")
    root = folder / "versions"
    target = root / key
    if direct_directory(folder, root) and direct_directory(root, target) and file_ok(target / "master.wav"):
        return target
    return None


def prepare_track(folder, source, name, example=None):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=channels,bit_rate,codec_name", "-of", "json", str(source)],
        capture_output=True, check=True,
    )
    streams = json.loads(probe.stdout).get("streams", [])
    if not streams:
        raise ValueError("재생할 오디오 트랙이 없습니다.")
    stream = streams[0]
    channels = min(2, int(stream["channels"]))
    decoded = folder / "source.wav"
    decode_file(source, decoded, channels)
    audio, rate = sf.read(decoded, always_2d=True, dtype="float32")
    if len(audio) == 0 or not np.isfinite(audio).all():
        raise ValueError("유효한 오디오 샘플이 없습니다.")
    bitrate = round(int(stream.get("bit_rate") or 0) / 1000)
    codec = stream.get("codec_name", "")
    analysis = {"kind": "none"}
    if codec.startswith("pcm_") or codec in {"flac", "alac"}:
        analysis = prepare_peak_repair(folder, audio, rate) or analysis
    elif codec == "mp3" and bitrate == 48:
        edge = spectral_edge(audio, rate)
        if edge:
            analysis = {"kind": "band", "edgeHz": edge}
    recommended = {"repair": analysis["kind"] == "peaks", "clarity": 0, "deess": 0,
                   "width": 0, "restore": 0}
    info = {
        "id": folder.name, "name": name, "example": example,
        "format": source.suffix[1:].upper(), "bitrate": bitrate, "rate": rate,
        "channels": channels, "duration": len(audio) / rate, "recommended": recommended, "analysis": analysis,
        "metrics": measurements(audio, rate, peak_db(audio)),
    }
    return save_track(folder, info)


def save_track(folder, info):
    pending = folder / "track.part.json"
    pending.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    pending.replace(folder / "track.json")
    return info


@router.get("/health")
def health():
    return {"status": "ready"}


def sample_songs():
    data = BASE_DIR / "data"
    folder = data / "sound"
    if not direct_directory(data, folder):
        return []
    extensions = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".aac", ".aif", ".aiff"}
    return sorted((p for p in folder.iterdir() if p.suffix.lower() in extensions and file_ok(p)),
                  key=lambda p: p.name.casefold())


@router.get("/sample-songs")
def list_sample_songs():
    return {"songs": [{"name": p.stem, "url": "/api/studio/sample-songs/" + quote(p.name, safe="")}
                      for p in sample_songs()]}


@router.get("/sample-songs/{filename}")
def sample_song_audio(filename: str):
    for path in sample_songs():
        if path.name == filename:
            return FileResponse(path)
    raise HTTPException(404, "샘플 음원을 찾을 수 없습니다.")


@router.get("/examples/{key}")
def example(key: Literal["midnight", "compressed", "clipped", "library"], request: Request, response: Response):
    songs = sample_songs() if key == "library" else []
    if songs:
        source = songs[0]
        filename, title = "data/sound/" + source.name, source.stem
    else:
        if key == "library":
            key = "clipped"
        filename, title = EXAMPLES[key]
        source = BASE_DIR / "frontend" / filename
    if not source.is_file():
        raise HTTPException(404, "예제 음원을 찾을 수 없습니다.")
    scope = workspace(request, response)
    response.headers["Cache-Control"] = "private, no-store"
    ident = uuid.uuid5(uuid.NAMESPACE_URL, f"aisoundfix/{filename}/{source.stat().st_mtime_ns}").hex
    folder = library.home(scope) / ident
    with library.lock(scope, ident):
        metadata = folder / "track.json"
        if metadata.is_file():
            info = json.loads(metadata.read_text(encoding="utf-8"))
            if "analysis" in info:
                return info
        folder.mkdir(exist_ok=True)
        return prepare_track(folder, source, title, key)


def store_upload(folder, file, stem, extensions=None):
    limits = Config.get_contract()["upload_limits"]
    name = Path(file.filename or "track").name
    ext = Path(name).suffix.lower()
    if extensions and ext not in extensions:
        raise HTTPException(415, "보컬과 반주를 각각 WAV 파일로 선택하세요.")
    if ext not in limits["allowed_extensions"]:
        raise HTTPException(415, "WAV, FLAC, MP3, M4A 파일을 선택하세요.")
    limit = limits["max_file_size_bytes"]
    if file.size is not None and file.size > limit:
        raise HTTPException(413, "100 MB 이하의 음원을 선택하세요.")
    source = folder / (stem + ext)
    total = 0
    with source.open("xb") as target:
        while chunk := file.file.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise HTTPException(413, "100 MB 이하의 음원을 선택하세요.")
            target.write(chunk)
    return source


@router.post("/tracks", status_code=201)
def upload(request: Request, response: Response, file: UploadFile = File(...)):
    def prepare(folder):
        source = store_upload(folder, file, "upload")
        try:
            name = file.filename or "track"
            return prepare_track(folder, source, Path(name).stem)
        finally:
            source.unlink()
    return create_track(request, response, prepare)


def create_track(request, response, prepare):
    scope = workspace(request, response)
    folder = library.home(scope) / uuid.uuid4().hex
    folder.mkdir()
    try:
        with library.lock(scope, folder.name):
            return prepare(folder)
    except Exception as exc:
        shutil.rmtree(folder, ignore_errors=True)
        if isinstance(exc, HTTPException):
            raise
        if isinstance(exc, (subprocess.CalledProcessError, ValueError, sf.LibsndfileError)):
            raise HTTPException(422, "음원을 읽을 수 없습니다. 파일 형식을 확인하세요.") from exc
        raise


def read_stem(path):
    with sf.SoundFile(path) as source:
        if source.format not in {"WAV", "WAVEX", "RF64"} or source.channels not in (1, 2):
            raise HTTPException(422, "모노 또는 스테레오 WAV 스템을 선택하세요.")
        audio = source.read(dtype="float32", always_2d=True)
        if not len(audio) or not np.isfinite(audio).all():
            raise ValueError("유효한 오디오 샘플이 없습니다.")
        return audio, source.samplerate


@router.post("/tracks/stem-pair", status_code=201)
def upload_stem_pair(request: Request, response: Response, vocals: UploadFile = File(...),
                     instrumental: UploadFile = File(...)):
    def prepare(folder):
        vocal_path = store_upload(folder, vocals, "vocal-input", {".wav"})
        backing_path = store_upload(folder, instrumental, "backing-input", {".wav"})
        voice, rate = read_stem(vocal_path)
        backing, backing_rate = read_stem(backing_path)
        if rate != backing_rate:
            decode_file(backing_path, folder / "resampled.wav", backing.shape[1], rate)
            backing, _ = read_stem(folder / "resampled.wav")
            (folder / "resampled.wav").unlink()
        duration = max(len(voice), len(backing))
        voice = np.pad(voice, ((0, duration - len(voice)), (0, 0)))
        backing = np.pad(backing, ((0, duration - len(backing)), (0, 0)))
        sf.write(folder / "vocals.wav", voice, rate, subtype="FLOAT")
        sf.write(folder / "instrumental.wav", backing, rate, subtype="FLOAT")
        # Reserve space for a processed vocal at the master ceiling. Original
        # and processed mixes share the same accompaniment level.
        ceiling = 10 ** (-1 / 20)
        vocal_peak = max(ceiling, 10 ** (peak_db(voice) / 20))
        backing_peak = 10 ** (peak_db(backing) / 20)
        mix_gain = float(min(1., ceiling / (vocal_peak + backing_peak)))
        mixed = (voice + backing) * np.float32(mix_gain)
        sf.write(folder / "source.wav", mixed, rate, subtype="FLOAT")
        analysis = prepare_peak_repair(folder, voice, rate) or {"kind": "none"}
        info = {
            "id": folder.name, "name": Path(vocals.filename or "vocals").stem + " + " +
                Path(instrumental.filename or "instrumental").stem,
            "stemPair": True, "hasStems": True, "mixGain": mix_gain, "example": None,
            "format": "WAV", "bitrate": 0, "channels": mixed.shape[1], "vocalChannels": voice.shape[1], "rate": rate,
            "duration": duration / rate, "analysis": analysis,
            "recommended": {"repair": analysis["kind"] == "peaks", "clarity": 0,
                            "deess": 0, "width": 0, "restore": 0},
            "metrics": measurements(mixed, rate, peak_db(mixed)),
        }
        vocal_path.unlink()
        backing_path.unlink()
        return save_track(folder, info)
    return create_track(request, response, prepare)


@router.get("/tracks/{track_id}/audio")
async def original(track_id: uuid.UUID, request: Request):
    def select(entry):
        source = next((p / "source.wav" for p in entry.tracks if file_ok(p / "source.wav")), None)
        return source, None
    return await send_file(request, track_id.hex, select)


@router.post("/tracks/{track_id}/render")
def render(track_id: uuid.UUID, recipe: Recipe, request: Request, archive_only: bool = False,
           preview: bool = False):
    scope = request_scope(request)
    settings = recipe.model_dump(exclude_none=True)
    if recipe.output == "mix":
        settings.pop("output")  # Keep IDs of existing history versions stable.
    if not recipe.bits or not recipe.dither:
        settings.pop("dither")
    for field in ("fullness", "bits"):
        if not settings[field]:
            settings.pop(field)
    if archive_only and (preview or recipe.output == "vocals"):
        raise HTTPException(422, "합본 출력에 적용한 설정만 히스토리에 저장할 수 있습니다.")
    keep = recipe.output == "mix" and not preview and (archive_only or any(settings.values()))
    with library.lock(scope, track_id.hex):
        entry = entry_for(scope, track_id.hex)
        try:
            folder = library.promote(scope, entry, prepare_track) if keep or not entry.tracks else entry.tracks[0]
            info = read_json(folder / "track.json")
            if recipe.output == "vocals" and not info.get("stemPair"):
                raise HTTPException(422, "보컬 단독 출력에는 보컬과 반주 스템이 필요합니다.")
            if recipe.region:
                stream = sf.info(folder / "source.wav")
                if (recipe.region.end > stream.duration + .49 / stream.samplerate or
                        recipe.region.start >= recipe.region.end or
                        round(recipe.region.start * stream.samplerate) >= round(recipe.region.end * stream.samplerate)):
                    raise HTTPException(422, "음원 안에서 시작보다 뒤에 있는 끝 지점을 선택하세요.")
            saved = saved_version(folder, version_id(settings)) if keep else None
            if saved:
                if archive_only:
                    return Response(status_code=204)
                stats = read_json(saved / "version.json")["stats"]
                body = (saved / "master.wav").read_bytes()
            else:
                with _render_slots:
                    audio, rate, stats = render_audio(folder, **settings)
                    wav = io.BytesIO()
                    write_pcm24(wav, audio, rate)
                    body = wav.getvalue()
                if keep:
                    library.save_version(folder, settings, body, stats)
            if archive_only:
                return Response(status_code=204)
            return Response(body, media_type="audio/wav",
                            headers={"X-Audio-Metrics": json.dumps(stats), "Cache-Control": "private, no-store"})
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Studio render failed for %s", track_id)
            raise HTTPException(500, "보정본을 만들거나 저장하지 못했습니다. 다시 시도하세요.") from exc


@router.post("/tracks/{track_id}/stems")
def stems(track_id: uuid.UUID, request: Request):
    scope = request_scope(request)
    with library.lock(scope, track_id.hex):
        entry = entry_for(scope, track_id.hex)
        try:
            separate_audio(library.promote(scope, entry, prepare_track))
        except Exception as exc:
            logger.exception("Stem separation failed for %s", track_id)
            raise HTTPException(500, "스템 분리에 실패했습니다. 다시 시도하세요.") from exc
    return {"vocals": f"/api/studio/tracks/{track_id}/stems/vocals",
            "instrumental": f"/api/studio/tracks/{track_id}/stems/instrumental"}


@router.get("/tracks/{track_id}/stems/{part}")
async def stem_file(track_id: uuid.UUID, part: Literal["vocals", "instrumental"], request: Request):
    return await send_file(request, track_id.hex, lambda e: (e.previous_files().get(part), part + ".wav"))


@router.get("/history")
def history(request: Request, response: Response):
    scope = workspace(request)
    response.headers["Cache-Control"] = "private, no-store"
    return {"items": library.list(scope) if scope else [], "local": scope == "local"}


@router.post("/history/{track_id}/open")
def open_history(track_id: uuid.UUID, request: Request):
    scope = request_scope(request)
    with library.lock(scope, track_id.hex):
        entry = entry_for(scope, track_id.hex)
        folder = next((p for p in entry.tracks if file_ok(p / "source.wav")), None)
        if folder is None:
            try:
                folder = library.promote(scope, entry, prepare_track)
            except FileNotFoundError as exc:
                raise HTTPException(404, str(exc)) from exc
        info = read_json(folder / "track.json")
        info["hasStems"] = {"vocals", "instrumental"} <= entry.previous_files().keys()
        return info


@router.get("/history/{track_id}/versions/{version}")
async def download_version(track_id: uuid.UUID, version: str, request: Request):
    def select(entry):
        for folder in entry.tracks:
            saved = saved_version(folder, version)
            if saved:
                name = read_json(folder / "track.json").get("name", "track")
                return saved / "master.wav", name + " - AIsoundFix.wav"
        raise HTTPException(404, "보정본을 찾을 수 없습니다.")
    return await send_file(request, track_id.hex, select)


@router.get("/history/{track_id}/files/{part}")
async def download_previous(track_id: uuid.UUID, part: Literal["previous", "vocals", "instrumental"], request: Request):
    def select(entry):
        path = entry.previous_files().get(part)
        return path, path.name if path else None
    return await send_file(request, track_id.hex, select)


class HistorySelection(BaseModel):
    ids: list[uuid.UUID]


def remove_item(request, scope, key, version=None):
    with library.lock(scope, key).acquire(timeout=0):
        entry = library.entries(scope, key).get(key)
        if not entry:
            return
        jobs = getattr(request.app.state, "legacy_jobs", ())
        if any(table.get(folder.name, {}).get("status") in {"queued", "processing"} for table in jobs for folder in entry.jobs):
            raise HTTPException(409, "이 작업은 처리 중입니다. 완료된 뒤 삭제하세요.")
        if version is None:
            library.delete(scope, entry)
            for folder in entry.jobs:
                for table in jobs:
                    table.pop(folder.name, None)
        else:
            for folder in entry.tracks:
                saved = saved_version(folder, version)
                if saved:
                    erase(saved)


@router.post("/history/delete")
def delete_history(selection: HistorySelection, request: Request):
    scope = request_scope(request)
    deleted, failed = [], []
    for track_id in dict.fromkeys(selection.ids):
        key = track_id.hex
        try:
            remove_item(request, scope, key)
        except (Timeout, OSError, HTTPException):
            failed.append(key)
        else:
            deleted.append(key)
    return {"deleted": deleted, "failed": failed}


@router.delete("/history/{track_id}/versions/{version}", status_code=204)
def delete_version(track_id: uuid.UUID, version: str, request: Request):
    try:
        remove_item(request, request_scope(request), track_id.hex, version)
    except (Timeout, OSError) as exc:
        raise HTTPException(409, "파일을 사용 중입니다. 잠시 후 다시 시도하세요.") from exc
    return Response(status_code=204)
