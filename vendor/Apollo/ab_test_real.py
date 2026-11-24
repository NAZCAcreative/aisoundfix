import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from worker.pipeline.stages.decode import run_decode
from worker.pipeline.stages.artifact_restore import run_artifact_restore

def main(input_path):
    t0 = time.time()
    decoded = run_decode(input_path)
    print(f"decoded -> {decoded} ({time.time()-t0:.1f}s)")

    t1 = time.time()
    restored = run_artifact_restore(decoded)
    print(f"restored -> {restored} ({time.time()-t1:.1f}s)")

if __name__ == "__main__":
    main(sys.argv[1])
