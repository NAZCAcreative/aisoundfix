import uuid
from typing import Dict, Any

class JobService:
    _jobs: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def create_job(cls, pipeline: str = "lite") -> Dict[str, Any]:
        job_id = f"job_{uuid.uuid4().hex[:8]}"
        job_data = {
            "id": job_id,
            "status": "queued",
            "pipeline": pipeline,
            "stage": "디코딩",
            "progress": 0.0
        }
        cls._jobs[job_id] = job_data
        return job_data

    @classmethod
    def get_job(cls, job_id: str) -> Dict[str, Any]:
        return cls._jobs.get(job_id, {"status": "error", "error": "Job not found"})
