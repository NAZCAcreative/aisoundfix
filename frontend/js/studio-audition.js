// The same low shelf, mid/side width and signed PCM grid used by the WAV renderer.
// This module also runs in the AudioWorklet global scope.
export class AuditionDSP {
  constructor(rate, channels, settings) {
    this.rate = rate;
    this.z1 = new Float64Array(channels);
    this.z2 = new Float64Array(channels);
    this.configure(settings);
  }

  configure({fullness=0, width=0, bits=0, dither=false}) {
    const amplitude = 10 ** ((4 * fullness / 100) / 40);
    const omega = 2 * Math.PI * Math.min(220, this.rate * .42) / this.rate;
    const cosine = Math.cos(omega);
    const root = Math.sqrt(2 * amplitude) * Math.sin(omega); // RBJ low shelf, S=1
    const sum = amplitude + 1, diff = amplitude - 1;
    const a0 = sum + diff * cosine + root;
    this.b0 = amplitude * (sum - diff * cosine + root) / a0;
    this.b1 = 2 * amplitude * (diff - sum * cosine) / a0;
    this.b2 = amplitude * (sum - diff * cosine - root) / a0;
    this.a1 = -2 * (diff + sum * cosine) / a0;
    this.a2 = (sum + diff * cosine - root) / a0;
    this.fullness = fullness;
    if (!fullness) { this.z1.fill(0); this.z2.fill(0); }
    this.width = .004 * width;
    this.scale = bits ? 2 ** (bits - 1) : 0;
    this.dither = dither;
  }

  process(input, output) {
    for (let ch = 0; ch < output.length; ch++) {
      const src = input[ch], dst = output[ch];
      if (!src) { dst.fill(0); continue; }
      if (!this.fullness) { dst.set(src); continue; }
      let z1 = this.z1[ch], z2 = this.z2[ch];
      for (let i = 0; i < dst.length; i++) {
        const x = src[i], y = this.b0 * x + z1;
        z1 = this.b1 * x - this.a1 * y + z2;
        z2 = this.b2 * x - this.a2 * y;
        dst[i] = y;
      }
      this.z1[ch] = z1;
      this.z2[ch] = z2;
    }
    if (this.width && output.length === 2) {
      const [left, right] = output;
      for (let i = 0; i < left.length; i++) {
        const side = this.width * (left[i] - right[i]);
        left[i] += side;
        right[i] -= side;
      }
    }
    if (!this.scale) return;
    for (const dst of output) {
      for (let i = 0; i < dst.length; i++) {
        let x = dst[i] * this.scale;
        if (this.dither) x += Math.random() - Math.random();
        const low = Math.floor(x);
        const code = x - low === .5 ? low + (low & 1) : Math.round(x);
        dst[i] = Math.max(-this.scale, Math.min(this.scale-1, code)) / this.scale;
      }
    }
  }
}

if (typeof AudioWorkletProcessor !== 'undefined') {
  class AuditionProcessor extends AudioWorkletProcessor {
    constructor(options) {
      super();
      this.dsp = new AuditionDSP(sampleRate, options.outputChannelCount[0], options.processorOptions);
      this.port.onmessage = event => {
        if (event.data) this.dsp.configure(event.data);
        else this.dsp = null;
      };
    }
    process(inputs, outputs) {
      if (!this.dsp) return false;
      if (inputs[0].length) this.dsp.process(inputs[0], outputs[0]);
      return true;
    }
  }
  registerProcessor('studio-audition', AuditionProcessor);
}
