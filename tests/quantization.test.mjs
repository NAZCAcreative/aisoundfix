import assert from 'node:assert/strict';
import test from 'node:test';
import {prepareExcerpt} from '../frontend/research/quantization/local-song.js';

// Mirror AudioBuffer's channel layout without depending on an audio device.
function createBuffer(numberOfChannels, length, sampleRate) {
  const channels = Array.from({length: numberOfChannels}, () => new Float32Array(length));
  return {numberOfChannels, length, sampleRate, getChannelData: i => channels[i]};
}
const context = {createBuffer};

test('rounding uses the signed grid, including negative half steps and the positive rail', () => {
  const song = createBuffer(1, 6, 44100);
  song.getChannelData(0).set([-.5/128, -1.5/128, .5/128, 1.5/128, 1, -1]);
  const {buffers} = prepareExcerpt(song, 0, 8, context);
  assert.deepEqual(Array.from(buffers.round.getChannelData(0)), [0, -2/128, 0, 2/128, 127/128, -1]);
});

test('a late stereo excerpt retains alignment and uses one common gain', () => {
  const song = createBuffer(2, 120, 10);
  song.getChannelData(0)[110] = 2;
  song.getChannelData(1)[111] = -.5;
  const {buffers, start, end, gain} = prepareExcerpt(song, 11, 16, context);
  assert.deepEqual([start, end, gain], [11, 12, .5]);
  assert.equal(song.getChannelData(0)[110], 2);
  assert.equal(buffers.reference.length, 10);
  assert.equal(buffers.reference.getChannelData(0)[0], 1);
  assert.equal(buffers.reference.getChannelData(1)[1], -.25);
  assert.equal(buffers.round.getChannelData(1)[1], -.25);
  assert.equal(prepareExcerpt(song, 0, 24, context).buffers.reference.length, 80);
});

test('TPDF can move silence by one target-depth code in either direction', t => {
  const numbers = [.99, .01, .01, .99];
  let index = 0;
  t.mock.method(Math, 'random', () => numbers[index++]);
  const {buffers} = prepareExcerpt(createBuffer(1, 2, 48000), 0, 12, context);
  assert.deepEqual(Array.from(buffers.tpdf.getChannelData(0)), [1/2048, -1/2048]);
  assert.deepEqual(Array.from(buffers.round.getChannelData(0)), [0, 0]);
});
