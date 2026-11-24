import shutil
from pathlib import Path

def cleanup_temp_jobs():
    data_dir = Path(__file__).parent.parent / "data"
    for folder in ["uploads", "jobs", "outputs"]:
        target = data_dir / folder
        if target.exists():
            for item in target.glob("*"):
                if item.name != ".gitkeep":
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
    print("Cleanup completed.")

if __name__ == "__main__":
    cleanup_temp_jobs()
