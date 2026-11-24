import sys
import numpy as np
import soundfile as sf
import torch
from huggingface_hub import hf_hub_download
import look2hear.models as models

def load_audio(path):
    data, sr = sf.read(path, dtype="float32", always_2d=True)  # [samples, channels]
    audio = torch.from_numpy(data.T)  # [channels, samples]
    if audio.shape[0] > 1:
        audio = audio.mean(dim=0, keepdim=True)
    return audio.unsqueeze(0), sr

def save_audio(path, audio, sr):
    data = audio.squeeze(0).numpy().T  # [samples, channels]
    sf.write(path, data, sr)

def main(in_wav, out_wav):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("device:", device)

    ckpt_path = hf_hub_download(repo_id="JusperLee/Apollo", filename="pytorch_model.bin")
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    state_dict = ckpt["state_dict"] if isinstance(ckpt, dict) and "state_dict" in ckpt else ckpt

    model = models.Apollo(sr=44100, win=20, feature_dim=256, layer=6)
    model.load_state_dict(state_dict)
    model = model.to(device)
    model.eval()

    audio, sr = load_audio(in_wav)
    audio = audio.to(device)
    print("input shape:", audio.shape, "sr:", sr)

    with torch.no_grad():
        out = model(audio)

    out = out.cpu()
    save_audio(out_wav, out, sr)
    print("wrote", out_wav)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
