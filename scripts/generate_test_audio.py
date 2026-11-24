import wave
import math
import struct
from pathlib import Path

def generate_sine_wave(output_path: Path, duration_sec: int = 5, freq: float = 440.0):
    sample_rate = 44100
    num_samples = sample_rate * duration_sec
    
    with wave.open(str(output_path), 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        for i in range(num_samples):
            value = int(32767.0 * 0.5 * math.sin(2.0 * math.pi * freq * i / sample_rate))
            data = struct.pack('<h', value)
            wav_file.writeframesraw(data)

if __name__ == "__main__":
    out = Path(__file__).parent.parent / "tests" / "fixtures" / "sample_440hz.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    generate_sine_wave(out)
    print(f"Generated test audio at {out}")
