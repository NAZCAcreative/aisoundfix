import shutil
from pathlib import Path
from .config import Config

class Storage:
    @staticmethod
    def save_upload(job_id: str, file_name: str, content: bytes) -> Path:
        job_dir = Config.UPLOAD_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        file_path = job_dir / file_name
        with open(file_path, "wb") as f:
            f.write(content)
        return file_path
