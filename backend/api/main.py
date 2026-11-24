import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Dict

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
for p in (str(PROJECT_ROOT), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI, UploadFile, Form, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes.studio import router as studio_router

from common.config import Config
from common.storage import Storage
from worker.pipeline.stages.decode import run_decode
from worker.pipeline.stages.artifact_restore import run_artifact_restore
from worker.pipeline.stages.mastering import run_mastering
from worker.pipeline.stages.encode import run_encode
from worker.pipeline.stages.stem_separate import run_stem_separate
from worker.pipeline.stages.blend import run_blend
from worker.pipeline.stages.polish import run_polish
from worker.pipeline.stages.demo_filter import run_demo_filter
from worker.pipeline.stages.multiband import run_multiband_compress, run_harmonic_exciter

app = FastAPI(title="REFINERY Real Pipeline API")
app.include_router(studio_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STAGES = ["디코딩", "압축 아티팩트 복원", "마스터링", "인코딩"]

JOBS: Dict[str, Dict[str, Any]] = {}


def _set_stage(job_id: str, stage_idx: int, progress: float):
    JOBS[job_id].update(
        status="processing",
        stage=STAGES[stage_idx],
        currentStageIndex=stage_idx,
        progress=progress,
    )


def _process_job(job_id: str, input_path: str, target_lufs: float):
    try:
        _set_stage(job_id, 0, 0.05)
        decoded = run_decode(input_path)

        _set_stage(job_id, 1, 0.30)
        restored = run_artifact_restore(decoded)

        _set_stage(job_id, 2, 0.70)
        mastered = run_mastering(restored, target_lufs=target_lufs)

        _set_stage(job_id, 3, 0.90)
        final = run_encode(mastered, format_ext="mp3")

        JOBS[job_id].update(
            status="done",
            stage=STAGES[-1],
            currentStageIndex=len(STAGES) - 1,
            progress=1.0,
            result_path=final,
        )
    except Exception as e:  # noqa: BLE001
        JOBS[job_id].update(status="error", error=str(e))


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    pipeline: str = Form("lite"),
    preset: str = Form("clear"),
):
    contract = Config.get_contract()
    ext = Path(file.filename).suffix.lower()
    if ext not in contract["upload_limits"]["allowed_extensions"]:
        return JSONResponse(status_code=400, content={"status": "error", "error": "지원하지 않는 파일 형식입니다."})

    content = await file.read()
    if len(content) > contract["upload_limits"]["max_file_size_bytes"]:
        return JSONResponse(status_code=400, content={"status": "error", "error": "파일 용량이 100MB 제한을 초과했습니다."})

    job_id = f"real_{uuid.uuid4().hex[:8]}"
    saved_path = Storage.save_upload(job_id, f"input{ext}", content)

    preset_path = PROJECT_ROOT / "config" / "presets" / f"{preset}.json"
    target_lufs = -14.0
    if preset_path.exists():
        import json
        target_lufs = json.loads(preset_path.read_text(encoding="utf-8")).get("target_lufs", -14.0)

    JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "pipeline": pipeline,
        "stage": STAGES[0],
        "currentStageIndex": 0,
        "progress": 0.0,
        "stages": STAGES,
    }

    thread = threading.Thread(target=_process_job, args=(job_id, str(saved_path), target_lufs), daemon=True)
    thread.start()

    return JOBS[job_id]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"status": "error", "error": "Job not found"})
    return job


@app.get("/api/jobs/{job_id}/result")
async def get_result(job_id: str):
    job = JOBS.get(job_id)
    if job is None or job.get("status") != "done":
        return JSONResponse(status_code=404, content={"status": "error", "error": "Result not ready"})
    return FileResponse(job["result_path"], media_type="audio/mpeg", filename=f"{job_id}.mp3")


STEM_JOBS: Dict[str, Dict[str, Any]] = {}


def _process_stem_job(job_id: str, input_path: str):
    try:
        STEM_JOBS[job_id].update(status="processing", stage="디코딩", progress=0.1)
        decoded = run_decode(input_path)

        STEM_JOBS[job_id].update(stage="보컬·반주 분리", progress=0.3)
        stems = run_stem_separate(decoded)

        if "vocals" not in stems or "instrumental" not in stems:
            raise RuntimeError("스템 분리 결과를 찾을 수 없습니다.")

        STEM_JOBS[job_id].update(
            status="done",
            stage="완료",
            progress=1.0,
            vocals_path=stems["vocals"],
            instrumental_path=stems["instrumental"],
        )
    except Exception as e:  # noqa: BLE001
        STEM_JOBS[job_id].update(status="error", error=str(e))


@app.post("/api/stems")
async def create_stem_job(file: UploadFile = File(...)):
    contract = Config.get_contract()
    ext = Path(file.filename).suffix.lower()
    if ext not in contract["upload_limits"]["allowed_extensions"]:
        return JSONResponse(status_code=400, content={"status": "error", "error": "지원하지 않는 파일 형식입니다."})

    content = await file.read()
    if len(content) > contract["upload_limits"]["max_file_size_bytes"]:
        return JSONResponse(status_code=400, content={"status": "error", "error": "파일 용량이 100MB 제한을 초과했습니다."})

    job_id = f"stem_{uuid.uuid4().hex[:8]}"
    saved_path = Storage.save_upload(job_id, f"input{ext}", content)

    STEM_JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "stage": "대기 중",
        "progress": 0.0,
    }

    thread = threading.Thread(target=_process_stem_job, args=(job_id, str(saved_path)), daemon=True)
    thread.start()

    return STEM_JOBS[job_id]


@app.get("/api/stems/{job_id}")
async def get_stem_job(job_id: str):
    job = STEM_JOBS.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"status": "error", "error": "Job not found"})
    return job


@app.get("/api/stems/{job_id}/vocals")
async def get_stem_vocals(job_id: str):
    job = STEM_JOBS.get(job_id)
    if job is None or job.get("status") != "done":
        return JSONResponse(status_code=404, content={"status": "error", "error": "Result not ready"})
    return FileResponse(job["vocals_path"], media_type="audio/wav", filename=f"{job_id}_vocals.wav")


@app.get("/api/stems/{job_id}/instrumental")
async def get_stem_instrumental(job_id: str):
    job = STEM_JOBS.get(job_id)
    if job is None or job.get("status") != "done":
        return JSONResponse(status_code=404, content={"status": "error", "error": "Result not ready"})
    return FileResponse(job["instrumental_path"], media_type="audio/wav", filename=f"{job_id}_instrumental.wav")


UPGRADE_STAGES = ["디코딩", "Apollo 전체 믹스 복원", "원본과 블렌딩", "마스터링", "인코딩"]
UPGRADE_JOBS: Dict[str, Dict[str, Any]] = {}
UPGRADE_WET = 0.8  # 80% processed / 20% original, avoids full-strength artifacts while keeping most of the improvement


def _set_upgrade_stage(job_id: str, stage_idx: int, progress: float):
    UPGRADE_JOBS[job_id].update(
        status="processing",
        stage=UPGRADE_STAGES[stage_idx],
        currentStageIndex=stage_idx,
        progress=progress,
    )


def _process_upgrade_job(job_id: str, input_path: str, target_lufs: float):
    try:
        _set_upgrade_stage(job_id, 0, 0.10)
        decoded = run_decode(input_path)

        _set_upgrade_stage(job_id, 1, 0.35)
        restored = run_artifact_restore(decoded)

        _set_upgrade_stage(job_id, 2, 0.70)
        blended = run_blend(restored, decoded, wet=UPGRADE_WET)

        _set_upgrade_stage(job_id, 3, 0.85)
        mastered = run_mastering(blended, target_lufs=target_lufs)

        _set_upgrade_stage(job_id, 4, 0.95)
        final = run_encode(mastered, format_ext="mp3")

        UPGRADE_JOBS[job_id].update(
            status="done",
            stage=UPGRADE_STAGES[-1],
            currentStageIndex=len(UPGRADE_STAGES) - 1,
            progress=1.0,
            result_path=final,
        )
    except Exception as e:  # noqa: BLE001
        UPGRADE_JOBS[job_id].update(status="error", error=str(e))


@app.post("/api/upgrade")
async def create_upgrade_job(file: UploadFile = File(...), preset: str = Form("clear")):
    contract = Config.get_contract()
    ext = Path(file.filename).suffix.lower()
    if ext not in contract["upload_limits"]["allowed_extensions"]:
        return JSONResponse(status_code=400, content={"status": "error", "error": "지원하지 않는 파일 형식입니다."})

    content = await file.read()
    if len(content) > contract["upload_limits"]["max_file_size_bytes"]:
        return JSONResponse(status_code=400, content={"status": "error", "error": "파일 용량이 100MB 제한을 초과했습니다."})

    job_id = f"upgrade_{uuid.uuid4().hex[:8]}"
    saved_path = Storage.save_upload(job_id, f"input{ext}", content)

    preset_path = PROJECT_ROOT / "config" / "presets" / f"{preset}.json"
    target_lufs = -14.0
    if preset_path.exists():
        import json
        target_lufs = json.loads(preset_path.read_text(encoding="utf-8")).get("target_lufs", -14.0)

    UPGRADE_JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "stage": UPGRADE_STAGES[0],
        "currentStageIndex": 0,
        "progress": 0.0,
        "stages": UPGRADE_STAGES,
    }

    thread = threading.Thread(target=_process_upgrade_job, args=(job_id, str(saved_path), target_lufs), daemon=True)
    thread.start()

    return UPGRADE_JOBS[job_id]


@app.get("/api/upgrade/{job_id}")
async def get_upgrade_job(job_id: str):
    job = UPGRADE_JOBS.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"status": "error", "error": "Job not found"})
    return job


@app.get("/api/upgrade/{job_id}/result")
async def get_upgrade_result(job_id: str):
    job = UPGRADE_JOBS.get(job_id)
    if job is None or job.get("status") != "done":
        return JSONResponse(status_code=404, content={"status": "error", "error": "Result not ready"})
    return FileResponse(job["result_path"], media_type="audio/mpeg", filename=f"{job_id}.mp3")


# --- v2: v1 + de-esser + mid-side presence/clarity/width EQ -----------------
UPGRADE_V2_STAGES = ["디코딩", "Apollo 전체 믹스 복원", "원본과 블렌딩", "디에서·Mid-Side 폴리싱", "마스터링", "인코딩"]
UPGRADE_V2_JOBS: Dict[str, Dict[str, Any]] = {}


def _set_upgrade_v2_stage(job_id: str, stage_idx: int, progress: float):
    UPGRADE_V2_JOBS[job_id].update(
        status="processing",
        stage=UPGRADE_V2_STAGES[stage_idx],
        currentStageIndex=stage_idx,
        progress=progress,
    )


def _process_upgrade_v2_job(job_id: str, input_path: str, target_lufs: float):
    try:
        _set_upgrade_v2_stage(job_id, 0, 0.10)
        decoded = run_decode(input_path)

        _set_upgrade_v2_stage(job_id, 1, 0.30)
        restored = run_artifact_restore(decoded)

        _set_upgrade_v2_stage(job_id, 2, 0.55)
        blended = run_blend(restored, decoded, wet=UPGRADE_WET)

        _set_upgrade_v2_stage(job_id, 3, 0.75)
        polished = run_polish(blended)

        _set_upgrade_v2_stage(job_id, 4, 0.90)
        mastered = run_mastering(polished, target_lufs=target_lufs)

        _set_upgrade_v2_stage(job_id, 5, 0.97)
        final = run_encode(mastered, format_ext="mp3")

        UPGRADE_V2_JOBS[job_id].update(
            status="done",
            stage=UPGRADE_V2_STAGES[-1],
            currentStageIndex=len(UPGRADE_V2_STAGES) - 1,
            progress=1.0,
            result_path=final,
        )
    except Exception as e:  # noqa: BLE001
        UPGRADE_V2_JOBS[job_id].update(status="error", error=str(e))


@app.post("/api/upgrade-v2")
async def create_upgrade_v2_job(file: UploadFile = File(...), preset: str = Form("clear")):
    contract = Config.get_contract()
    ext = Path(file.filename).suffix.lower()
    if ext not in contract["upload_limits"]["allowed_extensions"]:
        return JSONResponse(status_code=400, content={"status": "error", "error": "지원하지 않는 파일 형식입니다."})

    content = await file.read()
    if len(content) > contract["upload_limits"]["max_file_size_bytes"]:
        return JSONResponse(status_code=400, content={"status": "error", "error": "파일 용량이 100MB 제한을 초과했습니다."})

    job_id = f"upgradev2_{uuid.uuid4().hex[:8]}"
    saved_path = Storage.save_upload(job_id, f"input{ext}", content)

    preset_path = PROJECT_ROOT / "config" / "presets" / f"{preset}.json"
    target_lufs = -14.0
    if preset_path.exists():
        import json
        target_lufs = json.loads(preset_path.read_text(encoding="utf-8")).get("target_lufs", -14.0)

    UPGRADE_V2_JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "stage": UPGRADE_V2_STAGES[0],
        "currentStageIndex": 0,
        "progress": 0.0,
        "stages": UPGRADE_V2_STAGES,
    }

    thread = threading.Thread(target=_process_upgrade_v2_job, args=(job_id, str(saved_path), target_lufs), daemon=True)
    thread.start()

    return UPGRADE_V2_JOBS[job_id]


@app.get("/api/upgrade-v2/{job_id}")
async def get_upgrade_v2_job(job_id: str):
    job = UPGRADE_V2_JOBS.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"status": "error", "error": "Job not found"})
    return job


@app.get("/api/upgrade-v2/{job_id}/result")
async def get_upgrade_v2_result(job_id: str):
    job = UPGRADE_V2_JOBS.get(job_id)
    if job is None or job.get("status") != "done":
        return JSONResponse(status_code=404, content={"status": "error", "error": "Result not ready"})
    return FileResponse(job["result_path"], media_type="audio/mpeg", filename=f"{job_id}.mp3")


# --- v3: v2 + demo-style perceptual filter overlay (brightness + loudness) --
UPGRADE_V3_STAGES = [
    "디코딩", "Apollo 전체 믹스 복원", "원본과 블렌딩", "디에서·Mid-Side 폴리싱",
    "마스터링", "정제본 필터 오버레이", "인코딩",
]
UPGRADE_V3_JOBS: Dict[str, Dict[str, Any]] = {}


def _set_upgrade_v3_stage(job_id: str, stage_idx: int, progress: float):
    UPGRADE_V3_JOBS[job_id].update(
        status="processing",
        stage=UPGRADE_V3_STAGES[stage_idx],
        currentStageIndex=stage_idx,
        progress=progress,
    )


def _process_upgrade_v3_job(job_id: str, input_path: str, target_lufs: float):
    try:
        _set_upgrade_v3_stage(job_id, 0, 0.08)
        decoded = run_decode(input_path)

        _set_upgrade_v3_stage(job_id, 1, 0.25)
        restored = run_artifact_restore(decoded)

        _set_upgrade_v3_stage(job_id, 2, 0.45)
        blended = run_blend(restored, decoded, wet=UPGRADE_WET)

        _set_upgrade_v3_stage(job_id, 3, 0.62)
        polished = run_polish(blended)

        _set_upgrade_v3_stage(job_id, 4, 0.78)
        mastered = run_mastering(polished, target_lufs=target_lufs)

        _set_upgrade_v3_stage(job_id, 5, 0.90)
        filtered = run_demo_filter(mastered)

        _set_upgrade_v3_stage(job_id, 6, 0.97)
        final = run_encode(filtered, format_ext="mp3")

        UPGRADE_V3_JOBS[job_id].update(
            status="done",
            stage=UPGRADE_V3_STAGES[-1],
            currentStageIndex=len(UPGRADE_V3_STAGES) - 1,
            progress=1.0,
            result_path=final,
        )
    except Exception as e:  # noqa: BLE001
        UPGRADE_V3_JOBS[job_id].update(status="error", error=str(e))


@app.post("/api/upgrade-v3")
async def create_upgrade_v3_job(file: UploadFile = File(...), preset: str = Form("clear")):
    contract = Config.get_contract()
    ext = Path(file.filename).suffix.lower()
    if ext not in contract["upload_limits"]["allowed_extensions"]:
        return JSONResponse(status_code=400, content={"status": "error", "error": "지원하지 않는 파일 형식입니다."})

    content = await file.read()
    if len(content) > contract["upload_limits"]["max_file_size_bytes"]:
        return JSONResponse(status_code=400, content={"status": "error", "error": "파일 용량이 100MB 제한을 초과했습니다."})

    job_id = f"upgradev3_{uuid.uuid4().hex[:8]}"
    saved_path = Storage.save_upload(job_id, f"input{ext}", content)

    preset_path = PROJECT_ROOT / "config" / "presets" / f"{preset}.json"
    target_lufs = -14.0
    if preset_path.exists():
        import json
        target_lufs = json.loads(preset_path.read_text(encoding="utf-8")).get("target_lufs", -14.0)

    UPGRADE_V3_JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "stage": UPGRADE_V3_STAGES[0],
        "currentStageIndex": 0,
        "progress": 0.0,
        "stages": UPGRADE_V3_STAGES,
    }

    thread = threading.Thread(target=_process_upgrade_v3_job, args=(job_id, str(saved_path), target_lufs), daemon=True)
    thread.start()

    return UPGRADE_V3_JOBS[job_id]


@app.get("/api/upgrade-v3/{job_id}")
async def get_upgrade_v3_job(job_id: str):
    job = UPGRADE_V3_JOBS.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"status": "error", "error": "Job not found"})
    return job


@app.get("/api/upgrade-v3/{job_id}/result")
async def get_upgrade_v3_result(job_id: str):
    job = UPGRADE_V3_JOBS.get(job_id)
    if job is None or job.get("status") != "done":
        return JSONResponse(status_code=404, content={"status": "error", "error": "Result not ready"})
    return FileResponse(job["result_path"], media_type="audio/mpeg", filename=f"{job_id}.mp3")


# --- v4: v2 recipe + multiband compression + harmonic exciter ---------------
UPGRADE_V4_STAGES = [
    "디코딩", "Apollo 전체 믹스 복원", "원본과 블렌딩", "디에서·Mid-Side 폴리싱",
    "멀티밴드 컴프레션", "하모닉 익사이터", "마스터링", "인코딩",
]
UPGRADE_V4_JOBS: Dict[str, Dict[str, Any]] = {}


def _set_upgrade_v4_stage(job_id: str, stage_idx: int, progress: float):
    UPGRADE_V4_JOBS[job_id].update(
        status="processing",
        stage=UPGRADE_V4_STAGES[stage_idx],
        currentStageIndex=stage_idx,
        progress=progress,
    )


def _process_upgrade_v4_job(job_id: str, input_path: str, target_lufs: float):
    try:
        _set_upgrade_v4_stage(job_id, 0, 0.06)
        decoded = run_decode(input_path)

        _set_upgrade_v4_stage(job_id, 1, 0.20)
        restored = run_artifact_restore(decoded)

        _set_upgrade_v4_stage(job_id, 2, 0.38)
        blended = run_blend(restored, decoded, wet=UPGRADE_WET)

        _set_upgrade_v4_stage(job_id, 3, 0.52)
        polished = run_polish(blended)

        _set_upgrade_v4_stage(job_id, 4, 0.68)
        multiband = run_multiband_compress(polished)

        _set_upgrade_v4_stage(job_id, 5, 0.80)
        excited = run_harmonic_exciter(multiband)

        _set_upgrade_v4_stage(job_id, 6, 0.90)
        mastered = run_mastering(excited, target_lufs=target_lufs)

        _set_upgrade_v4_stage(job_id, 7, 0.97)
        final = run_encode(mastered, format_ext="mp3")

        UPGRADE_V4_JOBS[job_id].update(
            status="done",
            stage=UPGRADE_V4_STAGES[-1],
            currentStageIndex=len(UPGRADE_V4_STAGES) - 1,
            progress=1.0,
            result_path=final,
        )
    except Exception as e:  # noqa: BLE001
        UPGRADE_V4_JOBS[job_id].update(status="error", error=str(e))


@app.post("/api/upgrade-v4")
async def create_upgrade_v4_job(file: UploadFile = File(...), preset: str = Form("clear")):
    contract = Config.get_contract()
    ext = Path(file.filename).suffix.lower()
    if ext not in contract["upload_limits"]["allowed_extensions"]:
        return JSONResponse(status_code=400, content={"status": "error", "error": "지원하지 않는 파일 형식입니다."})

    content = await file.read()
    if len(content) > contract["upload_limits"]["max_file_size_bytes"]:
        return JSONResponse(status_code=400, content={"status": "error", "error": "파일 용량이 100MB 제한을 초과했습니다."})

    job_id = f"upgradev4_{uuid.uuid4().hex[:8]}"
    saved_path = Storage.save_upload(job_id, f"input{ext}", content)

    preset_path = PROJECT_ROOT / "config" / "presets" / f"{preset}.json"
    target_lufs = -14.0
    if preset_path.exists():
        import json
        target_lufs = json.loads(preset_path.read_text(encoding="utf-8")).get("target_lufs", -14.0)

    UPGRADE_V4_JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "stage": UPGRADE_V4_STAGES[0],
        "currentStageIndex": 0,
        "progress": 0.0,
        "stages": UPGRADE_V4_STAGES,
    }

    thread = threading.Thread(target=_process_upgrade_v4_job, args=(job_id, str(saved_path), target_lufs), daemon=True)
    thread.start()

    return UPGRADE_V4_JOBS[job_id]


@app.get("/api/upgrade-v4/{job_id}")
async def get_upgrade_v4_job(job_id: str):
    job = UPGRADE_V4_JOBS.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"status": "error", "error": "Job not found"})
    return job


@app.get("/api/upgrade-v4/{job_id}/result")
async def get_upgrade_v4_result(job_id: str):
    job = UPGRADE_V4_JOBS.get(job_id)
    if job is None or job.get("status") != "done":
        return JSONResponse(status_code=404, content={"status": "error", "error": "Result not ready"})
    return FileResponse(job["result_path"], media_type="audio/mpeg", filename=f"{job_id}.mp3")


app.state.legacy_jobs = (JOBS, STEM_JOBS, UPGRADE_JOBS, UPGRADE_V2_JOBS, UPGRADE_V3_JOBS, UPGRADE_V4_JOBS)
app.mount("/", StaticFiles(directory=PROJECT_ROOT / "frontend", html=True), name="studio-ui")
