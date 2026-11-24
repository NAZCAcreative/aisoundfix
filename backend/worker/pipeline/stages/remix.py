from pathlib import Path

import numpy as np
import soundfile as sf


def run_remix(vocals_path: str, instrumental_path: str) -> str:
    print(f"[Stage] Remixing enhanced vocals with instrumental: {vocals_path} + {instrumental_path}")

    vocals, sr1 = sf.read(vocals_path, dtype="float32", always_2d=True)
    instrumental, sr2 = sf.read(instrumental_path, dtype="float32", always_2d=True)
    assert sr1 == sr2, f"sample rate mismatch: {sr1} vs {sr2}"
    assert vocals.shape[1] == instrumental.shape[1], (
        f"channel count mismatch: vocals={vocals.shape[1]}, instrumental={instrumental.shape[1]}"
    )

    n = min(len(vocals), len(instrumental))
    mixed = vocals[:n] + instrumental[:n]

    peak = np.max(np.abs(mixed))
    if peak > 0.99:
        mixed = mixed * (0.99 / peak)

    out_path = str(Path(vocals_path).with_name("remixed.wav"))
    sf.write(out_path, mixed, sr1)
    return out_path
