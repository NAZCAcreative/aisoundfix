"""Original eight-second stereo performance and level-matched public listening clips."""

from pathlib import Path

import numpy as np
import pyloudnorm as pyln
from scipy import signal
import soundfile as sf

RATE = 44100
ROOT = Path(__file__).resolve().parents[2]
LISTEN = ROOT / "frontend" / "research" / "restoration"


def original_mix():
    rate = RATE
    rng = np.random.default_rng(7283)
    mix = np.zeros((8 * rate, 2))
    harmonics = np.arange(1, 13)

    def put(when, mono, pan):
        start = round(when * rate)
        length = min(len(mono), len(mix) - start)
        if length > 0:
            angle = (pan + 1) * np.pi / 4
            mix[start:start+length] += mono[:length, None] * [np.cos(angle), np.sin(angle)]

    def pluck(when, note, strength, pan):
        t = np.arange(round(.89*rate)) / rate
        frequency = 440 * 2**((note - 69)/12)
        k = harmonics[:, None]
        string = np.sum(np.sin(2*np.pi*frequency*k*(1+.00013*k*k)*t)
                        * np.exp(-t*(5 + .95*k)) / k**1.35, axis=0)
        put(when, strength * (1-np.exp(-900*t)) * string, pan)

    for bar, chord in enumerate(([57, 60, 64, 67], [53, 57, 60, 64],
                                  [55, 59, 62, 67], [52, 56, 59, 62])):
        base = bar * 2.
        for beat, pos in enumerate((0, 2, 1, 3, 2, 1, 3, 2)):
            pluck(base + beat*.25, chord[pos]+12, .16 if beat % 2 else .21, .38*(-1)**beat)
        for tick in (0, .75, 1.5):
            t = np.arange(round(.45*rate)) / rate
            f = 440 * 2**((chord[0]-24-69)/12)
            bass = .48*(np.sin(2*np.pi*f*t) + .32*np.sin(4*np.pi*f*t))*np.exp(-7*t)
            put(base+tick, bass*(1-np.exp(-260*t)), -.08)
        for tick in (0, 1., 1.75):
            t = np.arange(round(.33*rate)) / rate
            kick = .84*np.sin(2*np.pi*(53*t + 2.6*(1-np.exp(-45*t))))*np.exp(-14*t)
            put(base+tick, kick, 0)
        for tick in (.5, 1.5):
            t = np.arange(round(.23*rate)) / rate
            noise = signal.sosfilt(signal.butter(2, (1200, 10500), fs=rate,
                                                  btype="bandpass", output="sos"), rng.normal(size=len(t)))
            snare = .30*noise*np.exp(-26*t) + .34*np.sin(2*np.pi*185*t)*np.exp(-33*t)
            put(base+tick, snare, -.13)
        for beat in range(8):
            t = np.arange(round(.13*rate)) / rate
            hiss = signal.sosfilt(signal.butter(3, 7800, fs=rate, btype="highpass", output="sos"),
                                  rng.normal(size=len(t)))
            put(base + .25*beat, (.16 if beat % 2 else .09)*hiss*np.exp(-42*t), .53)
    fade = round(.035*rate)
    mix[:fade] *= np.linspace(0, 1, fade)[:, None]
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return (.8 * mix / np.abs(mix).max()).astype(np.float32)


def listening_clips(name, variants):
    from worker.pipeline.studio import peak_db

    LISTEN.mkdir(parents=True, exist_ok=True)
    meter = pyln.Meter(RATE)
    levels = {k: meter.integrated_loudness(x) for k, x in variants.items()}
    # One shared target. Every version fits under -1.2 dBTP without limiting.
    target = min(-18., *(levels[k] - peak_db(x) - 1.2 for k, x in variants.items()))
    for k, x in variants.items():
        path = LISTEN / f"{name}-{k}.flac"
        sf.write(path, x * 10**((target - levels[k])/20), RATE, subtype="PCM_24")
    print(f"{name} listening target {target:.3f} LUFS", flush=True)
