class ABPlayerController {
  constructor() {
    this.currentMode = 'result';
    this.isPlaying = false;
    this.offset = 0;
    this.startedAt = 0;
    this.duration = 0;
    this.audioBuffer = null;
    this.extraBuffers = {}; // versionId -> AudioBuffer, for real-processing results
    this.extraButtons = {}; // versionId -> dynamically created <button>
    this.audioCtx = null;
    this.sourceNode = null;
    this.rafId = null;
    // Independently toggleable add-ons for the "정제본(데모)" chain — off by
    // default so the base demo sound is unchanged until the user opts in.
    this.demoOptions = { multiband: false, exciter: false };
    this.initDOMReferences();
    this.bindEvents();
  }

  initDOMReferences() {
    this.btnOriginal = document.getElementById('btnModeOriginal');
    this.btnResult = document.getElementById('btnModeResult');
    this.toggleGroup = document.querySelector('.ab-toggle-group');
    this.btnPlayPause = document.getElementById('btnPlayPause');
    this.timelineSlider = document.getElementById('timelineSlider');
    this.waveformContainer = document.getElementById('waveformBars');
    this.timeCurrentEl = document.getElementById('timeCurrent');
    this.timeDurationEl = document.getElementById('timeDuration');
    this.chkMultiband = document.getElementById('chkDemoMultiband');
    this.chkExciter = document.getElementById('chkDemoExciter');
  }

  bindEvents() {
    if (this.btnOriginal) this.btnOriginal.addEventListener('click', () => this.setMode('original'));
    if (this.btnResult) this.btnResult.addEventListener('click', () => this.setMode('result'));
    if (this.btnPlayPause) this.btnPlayPause.addEventListener('click', () => this.togglePlay());
    if (this.timelineSlider) {
      this.timelineSlider.addEventListener('input', () => {
        const ratio = Number(this.timelineSlider.value) / 1000;
        this.seek(ratio * this.getDuration());
      });
    }
    if (this.chkMultiband) {
      this.chkMultiband.addEventListener('change', () => this.setDemoOption('multiband', this.chkMultiband.checked));
    }
    if (this.chkExciter) {
      this.chkExciter.addEventListener('change', () => this.setDemoOption('exciter', this.chkExciter.checked));
    }
  }

  // Live-toggle a demo add-on. Rebuilds the audio graph from the current
  // playhead so the change is audible immediately without a jarring restart.
  setDemoOption(key, enabled) {
    this.demoOptions[key] = enabled;
    if (this.currentMode === 'result' && this.isPlaying) {
      this.pause();
      this.play();
    }
  }

  // Every new processing variant calls this to get its own comparable tab in
  // the A/B player, instead of overwriting a previous result. Safe to call
  // multiple times with the same versionId (idempotent).
  registerVersion(versionId, label) {
    if (this.extraButtons[versionId]) return this.extraButtons[versionId];
    const btn = document.createElement('button');
    btn.className = 'ab-toggle-btn';
    btn.textContent = label;
    btn.addEventListener('click', () => this.setMode(versionId));
    if (this.toggleGroup) this.toggleGroup.appendChild(btn);
    this.extraButtons[versionId] = btn;
    return btn;
  }

  getDuration() {
    const extra = this.extraBuffers[this.currentMode];
    if (extra) return extra.duration;
    return this.duration;
  }

  async loadFile(file) {
    this.stop();
    this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const arrayBuffer = await file.arrayBuffer();
    this.audioBuffer = await this.audioCtx.decodeAudioData(arrayBuffer);
    this.duration = this.audioBuffer.duration;
    this.offset = 0;
    this.currentMode = 'result';
    this.extraBuffers = {};
    if (this.btnOriginal) this.btnOriginal.classList.remove('active');
    if (this.btnResult) this.btnResult.classList.add('active');
    Object.values(this.extraButtons).forEach(btn => btn.remove());
    this.extraButtons = {};
    this.renderWaveform();
    this.updateTimeDisplay();
  }

  async loadExtraBuffer(versionId, label, arrayBuffer) {
    if (!this.audioCtx) return;
    this.extraBuffers[versionId] = await this.audioCtx.decodeAudioData(arrayBuffer.slice(0));
    this.registerVersion(versionId, label);
  }

  buildChain(mode) {
    const ctx = this.audioCtx;
    const source = ctx.createBufferSource();

    const extra = this.extraBuffers[mode];
    if (extra) {
      source.buffer = extra;
      source.connect(ctx.destination);
      return source;
    }

    source.buffer = this.audioBuffer;

    if (mode === 'original') {
      const lowpass = ctx.createBiquadFilter();
      lowpass.type = 'lowpass';
      lowpass.frequency.value = 6500;
      lowpass.Q.value = 0.7;
      source.connect(lowpass);
      lowpass.connect(ctx.destination);
    } else {
      source.connect(this._buildDemoPolishChain(ctx));
    }
    return source;
  }

  // "정제본(데모)" chain: brightness shelf -> compression -> makeup gain.
  // Multiband compression and the harmonic exciter are independent opt-in
  // add-ons (checkboxes), not baked in, so their individual contribution
  // stays audible on its own. Returns the node the source should connect into.
  _buildDemoPolishChain(ctx) {
    const highshelf = ctx.createBiquadFilter();
    highshelf.type = 'highshelf';
    highshelf.frequency.value = 6500;
    highshelf.gain.value = 5;

    const compressedStage = this.demoOptions.multiband
      ? this._buildMultibandStage(ctx, highshelf)
      : this._buildBroadbandCompressor(ctx, highshelf);

    const preMakeup = this.demoOptions.exciter
      ? this._buildExciterStage(ctx, compressedStage)
      : compressedStage;

    const makeupGain = ctx.createGain();
    makeupGain.gain.value = 1.1;
    preMakeup.connect(makeupGain);
    makeupGain.connect(ctx.destination);

    return highshelf;
  }

  _buildBroadbandCompressor(ctx, input) {
    const compressor = ctx.createDynamicsCompressor();
    compressor.threshold.value = -24;
    compressor.knee.value = 20;
    compressor.ratio.value = 3;
    compressor.attack.value = 0.005;
    compressor.release.value = 0.15;
    input.connect(compressor);
    return compressor;
  }

  // 3-band compression so a loud bass hit can't duck the mids the way
  // single-band compression does — improves perceived separation.
  _buildMultibandStage(ctx, input) {
    const makeBandCompressor = (threshold, ratio, attack, release) => {
      const c = ctx.createDynamicsCompressor();
      c.threshold.value = threshold;
      c.knee.value = 6;
      c.ratio.value = ratio;
      c.attack.value = attack;
      c.release.value = release;
      return c;
    };

    // Subtractive 3-way split: low + mid + high always sums back to the
    // input exactly (mid = input - low - high via inverted-gain summing),
    // so there's no crossover phase/ripple to worry about.
    const lowLP1 = ctx.createBiquadFilter(); lowLP1.type = 'lowpass'; lowLP1.frequency.value = 150;
    const lowLP2 = ctx.createBiquadFilter(); lowLP2.type = 'lowpass'; lowLP2.frequency.value = 150;
    const highHP1 = ctx.createBiquadFilter(); highHP1.type = 'highpass'; highHP1.frequency.value = 4000;
    const highHP2 = ctx.createBiquadFilter(); highHP2.type = 'highpass'; highHP2.frequency.value = 4000;
    input.connect(lowLP1); lowLP1.connect(lowLP2);
    input.connect(highHP1); highHP1.connect(highHP2);

    const invertLow = ctx.createGain(); invertLow.gain.value = -1;
    const invertHigh = ctx.createGain(); invertHigh.gain.value = -1;
    const midBand = ctx.createGain(); midBand.gain.value = 1;
    input.connect(midBand);
    lowLP2.connect(invertLow); invertLow.connect(midBand);
    highHP2.connect(invertHigh); invertHigh.connect(midBand);

    const lowComp = makeBandCompressor(-20, 4, 0.02, 0.2);
    const midComp = makeBandCompressor(-18, 2, 0.01, 0.15);
    const highComp = makeBandCompressor(-22, 3, 0.005, 0.1);
    lowLP2.connect(lowComp);
    midBand.connect(midComp);
    highHP2.connect(highComp);

    const bandSum = ctx.createGain(); bandSum.gain.value = 1;
    lowComp.connect(bandSum);
    midComp.connect(bandSum);
    highComp.connect(bandSum);
    return bandSum;
  }

  // Taps the vocal fundamental range, soft-saturates it, mixes a modest
  // fraction back in for analog-style warmth/presence.
  _buildExciterStage(ctx, input) {
    const exciterHP = ctx.createBiquadFilter(); exciterHP.type = 'highpass'; exciterHP.frequency.value = 200;
    const exciterLP = ctx.createBiquadFilter(); exciterLP.type = 'lowpass'; exciterLP.frequency.value = 800;
    const shaper = ctx.createWaveShaper();
    shaper.curve = this._makeSaturationCurve(3);
    shaper.oversample = '2x';
    const exciterMix = ctx.createGain(); exciterMix.gain.value = 0.15;
    input.connect(exciterHP); exciterHP.connect(exciterLP); exciterLP.connect(shaper);
    shaper.connect(exciterMix);

    const sum = ctx.createGain(); sum.gain.value = 1;
    input.connect(sum);
    exciterMix.connect(sum);
    return sum;
  }

  _makeSaturationCurve(amount = 3, samples = 1024) {
    const curve = new Float32Array(samples);
    const norm = Math.tanh(amount);
    for (let i = 0; i < samples; i++) {
      const x = (i * 2) / samples - 1;
      curve[i] = Math.tanh(amount * x) / norm;
    }
    return curve;
  }

  play() {
    if (this.isPlaying) return;
    if (!this.extraBuffers[this.currentMode] && !this.audioBuffer) return;
    this.sourceNode = this.buildChain(this.currentMode);
    this.sourceNode.start(0, this.offset);
    this.sourceNode.onended = () => {
      if (this.isPlaying && this.offset >= this.getDuration() - 0.05) this.pause(true);
    };
    this.startedAt = this.audioCtx.currentTime - this.offset;
    this.isPlaying = true;
    if (this.btnPlayPause) this.btnPlayPause.textContent = '❚❚';
    this.tick();
  }

  pause(reachedEnd = false) {
    if (!this.isPlaying) return;
    if (this.sourceNode) {
      this.sourceNode.onended = null;
      try { this.sourceNode.stop(); } catch (e) {}
      this.sourceNode = null;
    }
    this.offset = reachedEnd ? 0 : this.audioCtx.currentTime - this.startedAt;
    this.isPlaying = false;
    if (this.btnPlayPause) this.btnPlayPause.textContent = '▶';
    if (this.rafId) cancelAnimationFrame(this.rafId);
    this.updateTimeDisplay();
  }

  togglePlay() {
    if (this.isPlaying) this.pause();
    else this.play();
  }

  seek(seconds) {
    const clamped = Math.max(0, Math.min(this.getDuration(), seconds));
    const wasPlaying = this.isPlaying;
    if (wasPlaying) this.pause();
    this.offset = clamped;
    this.updateTimeDisplay();
    if (wasPlaying) this.play();
  }

  setMode(mode) {
    if (mode === this.currentMode) return;
    if (mode !== 'original' && mode !== 'result' && !this.extraBuffers[mode]) return;
    const wasPlaying = this.isPlaying;
    if (wasPlaying) this.pause();
    this.currentMode = mode;
    this.offset = Math.min(this.offset, this.getDuration());
    if (this.btnOriginal) this.btnOriginal.classList.toggle('active', mode === 'original');
    if (this.btnResult) this.btnResult.classList.toggle('active', mode === 'result');
    Object.entries(this.extraButtons).forEach(([m, btn]) => {
      btn.classList.toggle('active', mode === m);
    });
    this.updateTimeDisplay();
    if (wasPlaying) this.play();
  }

  stop() {
    if (this.isPlaying) this.pause();
    if (this.audioCtx) {
      this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
    }
    this.audioBuffer = null;
    this.extraBuffers = {};
  }

  tick() {
    if (!this.isPlaying) return;
    const elapsed = this.audioCtx.currentTime - this.startedAt;
    if (elapsed >= this.getDuration()) {
      this.pause(true);
      return;
    }
    this.offset = elapsed;
    this.updateTimeDisplay();
    this.rafId = requestAnimationFrame(() => this.tick());
  }

  updateTimeDisplay() {
    const duration = this.getDuration();
    if (this.timelineSlider) {
      this.timelineSlider.value = duration ? Math.round((this.offset / duration) * 1000) : 0;
    }
    if (this.timeCurrentEl) this.timeCurrentEl.textContent = this.formatTime(this.offset);
    if (this.timeDurationEl) this.timeDurationEl.textContent = this.formatTime(duration);
    this.highlightWaveform();
  }

  renderWaveform() {
    if (!this.waveformContainer || !this.audioBuffer) return;
    const channel = this.audioBuffer.getChannelData(0);
    const barCount = 48;
    const step = Math.floor(channel.length / barCount);
    this.waveformContainer.innerHTML = '';
    this.waveformBars = [];
    for (let i = 0; i < barCount; i++) {
      let peak = 0;
      const start = i * step;
      for (let j = start; j < start + step && j < channel.length; j++) {
        const v = Math.abs(channel[j]);
        if (v > peak) peak = v;
      }
      const heightPct = Math.max(12, Math.min(100, Math.round(peak * 130)));
      const bar = document.createElement('div');
      bar.className = 'waveform-bar';
      bar.style.height = `${heightPct}%`;
      this.waveformContainer.appendChild(bar);
      this.waveformBars.push(bar);
    }
  }

  highlightWaveform() {
    const duration = this.getDuration();
    if (!this.waveformBars || !duration) return;
    const activeCount = Math.round((this.offset / duration) * this.waveformBars.length);
    this.waveformBars.forEach((bar, idx) => {
      bar.classList.toggle('active', idx < activeCount);
    });
  }

  formatTime(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${r.toString().padStart(2, '0')}`;
  }
}

window.ABPlayerController = ABPlayerController;
