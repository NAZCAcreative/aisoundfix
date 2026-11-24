import sys
import time
from pathlib import Path

from audio_separator.separator import Separator

def main(input_path, output_dir):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    model_dir = str(Path(__file__).resolve().parents[2] / "vendor" / "audio-separator-models")

    separator = Separator(model_file_dir=model_dir, output_dir=output_dir)
    print("loading model...")
    t0 = time.time()
    separator.load_model()
    print(f"model loaded in {time.time()-t0:.1f}s")

    t1 = time.time()
    output_files = separator.separate(input_path)
    print(f"separated in {time.time()-t1:.1f}s")
    print("outputs:", output_files)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
