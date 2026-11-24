from ..services.job_service import JobService

def handle_create_job(request_form):
    pipeline = request_form.get("pipeline", "lite")
    return JobService.create_job(pipeline=pipeline)

def handle_get_job(job_id: str):
    return JobService.get_job(job_id)
