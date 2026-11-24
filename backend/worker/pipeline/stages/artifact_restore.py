import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

APOLLO_DIR = Path(__file__).resolve().parents[4] / "vendor" / "Apollo"
if str(APOLLO_DIR) not in sys.path:
    sys.path.insert(0, str(APOLLO_DIR))

_model = None
_device = "cuda" if torch.cuda.is_available() else "cpu"

# Apollo runs full-sequence attention with no chunking of its own, so memory
# scales with input length. A ~2-3 min song can try to allocate 10+ GiB in a
# single forward pass. Process long audio in overlapping windows instead.
CHUNK_SECONDS = 25
OVERLAP_SECONDS = 1


def _get_model():
    global _model
    if _model is not None:
        return _model

    import look2hear.models as models
    from huggingface_hub import hf_hub_download, try_to_load_from_cache

    ckpt_path = try_to_load_from_cache("JusperLee/Apollo", "pytorch_model.bin")
    if not isinstance(ckpt_path, str):
        ckpt_path = hf_hub_download(repo_id="JusperLee/Apollo", filename="pytorch_model.bin")
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    state_dict = ckpt["state_dict"] if isinstance(ckpt, dict) and "state_dict" in ckpt else ckpt

    model = models.Apollo(sr=44100, win=20, feature_dim=256, layer=6)
    model.load_state_dict(state_dict)
    model = model.to(_device).eval()

    _model = model
    return _model


def _run_model_on_chunk(model, chunk: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        x = torch.from_numpy(chunk).unsqueeze(0).unsqueeze(0).to(_device)
        out = model(x).squeeze(0).squeeze(0).cpu().numpy()
    if _device == "cuda":
        torch.cuda.empty_cache()
    return out


def _restore_channel(model, signal: np.ndarray, sr: int) -> np.ndarray:
    chunk_len = int(CHUNK_SECONDS * sr)
    n = len(signal)

    if n <= chunk_len:
        return _run_model_on_chunk(model, signal)

    overlap = int(OVERLAP_SECONDS * sr)
    step = chunk_len - overlap
    fade = np.linspace(0.0, 1.0, overlap, dtype=np.float32) if overlap > 0 else None

    output = np.zeros(n, dtype=np.float32)
    weight = np.zeros(n, dtype=np.float32)

    start = 0
    while start < n:
        end = min(start + chunk_len, n)
        chunk = signal[start:end]
        out_chunk = _run_model_on_chunk(model, chunk)

        w = np.ones(end - start, dtype=np.float32)
        if fade is not None and start > 0:
            head = min(overlap, len(w))
            w[:head] = fade[:head]
        if fade is not None and end < n:
            tail = min(overlap, len(w))
            w[-tail:] = np.minimum(w[-tail:], fade[::-1][:tail])

        output[start:end] += out_chunk * w
        weight[start:end] += w

        if end == n:
            break
        start += step

    weight[weight == 0] = 1.0
    return output / weight


def run_artifact_restore(audio_path: str, *, subtype: str = "PCM_16") -> str:
    print(f"[Stage] Restoring AI high-frequency compression artifacts: {audio_path}")

    model = _get_model()

    data, sr = sf.read(audio_path, dtype="float32", always_2d=True)  # [samples, channels]
    channels = data.shape[1]

    restored_channels = [_restore_channel(model, data[:, ch], sr) for ch in range(channels)]
    restored = np.stack(restored_channels, axis=1)  # [samples, channels]

    out_path = str(Path(audio_path).with_name(Path(audio_path).stem + "_restored.wav"))
    sf.write(out_path, restored, sr, subtype=subtype)
    return out_path
