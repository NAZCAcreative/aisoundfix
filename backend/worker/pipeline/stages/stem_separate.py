import shutil
import uuid
from pathlib import Path

VENDOR_MODELS_DIR = Path(__file__).resolve().parents[4] / "vendor" / "audio-separator-models"
# The separator's internal model instance captures output_dir at load time and
# ignores later mutation of `Separator.output_dir`, so a single cached instance
# must always write to this same fixed scratch dir. Results are moved out to
# the caller's requested location after each run.
SCRATCH_DIR = Path(__file__).resolve().parents[4] / "vendor" / "audio-separator-scratch"

_separator = None


def _get_separator():
    global _separator
    if _separator is not None:
        return _separator

    from audio_separator.separator import Separator

    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    separator = Separator(model_file_dir=str(VENDOR_MODELS_DIR), output_dir=str(SCRATCH_DIR))
    separator.load_model()

    _separator = separator
    return _separator


def run_stem_separate(audio_path: str) -> dict:
    print(f"[Stage] Separating stems (vocals/instrumental): {audio_path}")

    dest_dir = Path(audio_path).parent
    separator = _get_separator()

    run_id = uuid.uuid4().hex[:8]
    output_files = separator.separate(
        audio_path,
        custom_output_names={"Vocals": f"vocals_{run_id}", "Instrumental": f"instrumental_{run_id}"},
    )

    result = {}
    for f in output_files:
        src = Path(f) if Path(f).is_absolute() else SCRATCH_DIR / f
        stem_lower = src.stem.lower()
        if "vocal" in stem_lower:
            dest = dest_dir / "vocals.wav"
            shutil.move(str(src), str(dest))
            result["vocals"] = str(dest)
        elif "instrumental" in stem_lower:
            dest = dest_dir / "instrumental.wav"
            shutil.move(str(src), str(dest))
            result["instrumental"] = str(dest)
    return result
