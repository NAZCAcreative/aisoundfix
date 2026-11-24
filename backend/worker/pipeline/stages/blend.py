from pathlib import Path

import numpy as np
import soundfile as sf


def run_blend(processed_path: str, original_path: str, wet: float = 0.8) -> str:
    print(f"[Stage] Blending processed ({wet:.0%} wet) with original: {processed_path} + {original_path}")

    processed, sr1 = sf.read(processed_path, dtype="float32", always_2d=True)
    original, sr2 = sf.read(original_path, dtype="float32", always_2d=True)
    assert sr1 == sr2, f"sample rate mismatch: {sr1} vs {sr2}"
    assert processed.shape[1] == original.shape[1], (
        f"channel count mismatch: processed={processed.shape[1]}, original={original.shape[1]}"
    )

    n = min(len(processed), len(original))
    blended = wet * processed[:n] + (1 - wet) * original[:n]

    peak = np.max(np.abs(blended))
    if peak > 0.99:
        blended = blended * (0.99 / peak)

    out_path = str(Path(processed_path).with_name("blended.wav"))
    sf.write(out_path, blended, sr1)
    return out_path
