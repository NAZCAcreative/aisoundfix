import subprocess
from pathlib import Path


def run_encode(audio_path: str, format_ext: str = "mp3") -> str:
    print(f"[Stage Final] Encoding refined result to .{format_ext}")

    out_path = str(Path(audio_path).with_name(Path(audio_path).stem + f"_final.{format_ext}"))
    args = ["ffmpeg", "-y", "-i", audio_path]
    if format_ext == "mp3":
        args += ["-codec:a", "libmp3lame", "-qscale:a", "2"]
    args.append(out_path)
    subprocess.run(args, check=True, capture_output=True)
    return out_path
