import assert from 'node:assert/strict';
import test from 'node:test';
import { StudioPlayer, hasSignalChange } from '../frontend/js/studio-player.js';

function audioBuffer(...channels) {
  return { numberOfChannels: channels.length, getChannelData: i => channels[i] };
}

test('only a change of output level is inaudible when A/B is level matched', () => {
  const dry = audioBuffer(Float32Array.of(.4, -.2));
  const wet = audioBuffer(Float32Array.of(.2, -.1 + 1.2e-7));
  const signalChanged = hasSignalChange(dry, wet, .5);
  assert.equal(signalChanged, false);
  const player = new StudioPlayer(() => {});
  player.originalLevel = -12;
  player.setRendered(wet, -18, 'processed', .5, signalChanged);
  assert.equal(player.canCompare, false);
  assert.equal(player.mode, 'original');
  player.levelMatch = false;
  player.setMode('processed');
  assert.equal(player.mode, 'processed');
});

test('a short clip with unmeasurable loudness can compare an output-only level change', () => {
  const player = new StudioPlayer(() => {});
  player.setRendered({ duration: .2 }, null, 'processed', .92, false);
  assert.equal(player.levelsMeasured, false);
  assert.equal(player.canCompare, true);
  assert.equal(player.mode, 'processed');
});

test('live A/B switching changes gains on the same playback clock', () => {
  const player = new StudioPlayer(() => {});
  player.original = { duration: 12 };
  player.originalLevel = -18;
  player.setRendered({ duration: 12 }, -12, 'original', .8, true);
  player.ctx = { currentTime: 5 };
  player.started = 3;
  player.playing = true;
  const targets = [0, 0];
  const group = { gains: targets.map((_, i) => ({
    setTargetAtTime(value, when) {
      assert.equal(when, 5);
      targets[i] = value;
    }
  })) };
  player.group = group;

  player.setMode('processed');
  assert.deepEqual(targets, [0, 10 ** (-6 / 20)]);
  player.setMode('original');
  assert.deepEqual(targets, [1, 0]);
  assert.equal(player.group, group);
  assert.equal(player.position(), 2);
});

test('a short repair between display samples is still detectable', () => {
  const dry = new Float32Array(720 * 300);
  const wet = dry.slice();
  wet[101] = .125;
  assert.equal(hasSignalChange(audioBuffer(dry, dry), audioBuffer(dry, wet)), true);
});

test('a cancelled audio-context resume cannot start a later playback request', async () => {
  const player = new StudioPlayer(() => {});
  player.original = { duration: 5 };
  const resumes = [];
  player.ctx = { resume: () => new Promise(resolve => resumes.push(resolve)) };
  let starts = 0;
  player.startAt = () => { starts++; };
  const first = player.toggle();
  await player.toggle();
  const next = player.toggle();
  resumes[0]();
  await first;
  assert.equal(starts, 0);
  resumes[1]();
  await next;
  assert.equal(starts, 1);
});
