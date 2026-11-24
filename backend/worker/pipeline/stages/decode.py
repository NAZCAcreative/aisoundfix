import subprocess
from pathlib import Path


def run_decode(input_path: str, target_sr: int = 44100) -> str:
    print(f"[Stage 1] Decoding audio file: {input_path}")

    out_path = str(Path(input_path).with_name(Path(input_path).stem + "_decoded.wav"))
    subprocess.run(
        ["ffmpeg", "-y", "-i", input_path, "-ar", str(target_sr), "-sample_fmt", "s16", out_path],
        check=True,
        capture_output=True,
    )
    return out_path
