import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SHARED_CONTRACT_PATH = BASE_DIR / "shared" / "contract.json"

class Config:
    SERVICE_NAME = "REFINERY"
    DEBUG = os.getenv("DEBUG", "true").lower() == "true"
    UPLOAD_DIR = BASE_DIR / "data" / "uploads"
    JOBS_DIR = BASE_DIR / "data" / "jobs"
    OUTPUT_DIR = BASE_DIR / "data" / "outputs"

    @classmethod
    def get_contract(cls):
        with open(SHARED_CONTRACT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
