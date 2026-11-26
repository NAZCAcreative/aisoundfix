import test from 'node:test';
import assert from 'node:assert/strict';
import {AuditionDSP} from '../frontend/js/studio-audition.js';
import {StudioPlayer} from '../frontend/js/studio-player.js';

function process(dsp, ...input) {
  const output = input.map(channel => new Float32Array(channel.length));
  dsp.process(input, output);
  return output;
}

test('PCM preview rounds half to even and clamps signed rails', () => {
  const dsp = new AuditionDSP(48000, 1, {bits:8});
  const samples = Float32Array.from([-129, -3.5, -2.5, 2.5, 3.5, 128], x => x / 128);
  const [out] = process(dsp, samples);
  assert.deepEqual(Array.from(out, x => x*128), [-128, -4, -2, 2, 4, 127]);
  dsp.configure({});
  assert.deepEqual(process(dsp, samples)[0], samples);
});

test('shelf retains state between blocks and converges to the requested DC gain', () => {
  const dsp = new AuditionDSP(48000, 1, {fullness:100});
  const input = new Float32Array(128).fill(.25);
  let last;
  for (let i=0; i<12; i++) [last] = process(dsp, input);
  assert.ok(Math.abs(last.at(-1) - .25 * 10**(4/20)) < 1e-5);
  dsp.configure({fullness:0});
  assert.deepEqual(process(dsp, input)[0], input);
});

test('stereo width preserves the center and has no effect on mono', () => {
  const dsp = new AuditionDSP(48000, 2, {width:100});
  const [left, right] = process(dsp, Float32Array.of(.5, .25), Float32Array.of(-.5, .25));
  assert.ok(Math.abs(left[0] - .9) < 1e-6 && Math.abs(right[0] + .9) < 1e-6);
  assert.equal(left[1], .25);
  assert.equal(right[1], .25);
  assert.deepEqual(process(dsp, Float32Array.of(-.6))[0], Float32Array.of(-.6));
});

test('restoring a render while the processor loads cancels the old audition', async () => {
  const player = new StudioPlayer(() => {});
  let complete;
  player.original = {duration:8};
  player.ctx = {audioWorklet: {addModule: () => new Promise(resolve => {complete = resolve;})}};
  const pending = player.setAudition({bits:8});
  player.setRendered({duration:8}, -18, 'processed', 1, true);
  complete();
  await pending;
  assert.equal(player.audition, null);
  assert.equal(player.canCompare, true);
});
