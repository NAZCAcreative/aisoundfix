import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from worker.pipeline.stages.decode import run_decode
from worker.pipeline.stages.artifact_restore import run_artifact_restore
from worker.pipeline.stages.mastering import run_mastering
from worker.pipeline.stages.encode import run_encode


def run_lite_pipeline(input_path: str, target_lufs: float = -14.0, format_ext: str = "mp3") -> str:
    decoded = run_decode(input_path)
    restored = run_artifact_restore(decoded)
    mastered = run_mastering(restored, target_lufs=target_lufs)
    final = run_encode(mastered, format_ext=format_ext)
    return final


if __name__ == "__main__":
    result = run_lite_pipeline(sys.argv[1])
    print("FINAL:", result)
