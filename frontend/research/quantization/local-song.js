// OfflineAudioContext lets WAV, FLAC and MP3 keep the source clock during decoding.
// Other containers decode at the playback context's sample rate.
function nativeRate(bytes, file) {
  const view = new DataView(bytes);
  if (view.byteLength < 42) return;
  const tag = offset => view.getUint32(offset);
  if (tag(0) === 0x664c6143 && (view.getUint8(4) & 127) === 0) {
    return view.getUint32(18) >>> 12;
  }
  if (/\.mp3$/i.test(file.name) || file.type === "audio/mpeg") {
    // Skip ID3v2 including optional footer, then find a Layer III frame.
    let start = 0;
    if ((tag(0) >>> 8) === 0x494433) {
      for (let i = 6; i < 10; i++) start = 128 * start + (view.getUint8(i) & 127);
      start += 10 + (view.getUint8(3) === 4 && (view.getUint8(5) & 16) ? 10 : 0);
    }
    const limit = Math.min(start + 16384, view.byteLength - 3);
    for (let i = start; i < limit; i++) {
      const header = tag(i), version = (header >>> 19) & 3;
      const bitrate = (header >>> 12) & 15, clock = (header >>> 10) & 3;
      if ((header >>> 21) === 0x7ff && version !== 1 && ((header >>> 17) & 3) === 1 &&
          bitrate !== 15 && clock < 3) {
        return [44100, 48000, 32000][clock] / (version === 3 ? 1 : version === 2 ? 2 : 4);
      }
    }
  }
  if (tag(0) !== 0x52494646 || tag(8) !== 0x57415645) return;
  for (let offset = 12; offset + 16 <= view.byteLength;) {
    const size = view.getUint32(offset + 4, true);
    if (tag(offset) === 0x666d7420 && size >= 16) return view.getUint32(offset + 12, true);
    offset += 8 + size + (size % 2);
  }
}

export async function decodeSong(file, context) {
  const bytes = await file.arrayBuffer();
  const rate = nativeRate(bytes, file);
  let decoder = context;
  if (rate && rate !== context.sampleRate) {
    try { decoder = new OfflineAudioContext(1, 1, rate); } catch { /* Unsupported source rate. */ }
  }
  return decoder.decodeAudioData(bytes);
}

function nearestCode(value, scale) {
  const lower = Math.floor(value);
  const rounded = value - lower === .5 ? lower + Math.abs(lower % 2) : Math.round(value);
  return Math.max(-scale, Math.min(scale - 1, rounded));
}

export function prepareExcerpt(song, from, bits, context) {
  const {sampleRate: rate, numberOfChannels: channels} = song;
  const first = Math.min(song.length - 1, Math.max(0, Math.round(from * rate)));
  const length = Math.min(8 * rate, song.length - first);
  const buffers = {};
  let peak = 1;
  for (let channel = 0; channel < channels; channel++) {
    const samples = song.getChannelData(channel).subarray(first, first + length);
    for (let i = 0; i < length; i++) peak = Math.max(peak, Math.abs(samples[i]));
  }
  if (!Number.isFinite(peak)) throw new Error("invalid PCM samples");
  for (const key of ["reference", "round", "tpdf"]) buffers[key] = context.createBuffer(channels, length, rate);
  const scale = 2 ** (bits - 1);
  for (let channel = 0; channel < channels; channel++) {
    const original = song.getChannelData(channel);
    const reference = buffers.reference.getChannelData(channel);
    const round = buffers.round.getChannelData(channel);
    const tpdf = buffers.tpdf.getChannelData(channel);
    for (let i = 0; i < length; i++) {
      reference[i] = original[first + i] / peak;
      const value = reference[i] * scale;
      round[i] = nearestCode(value, scale) / scale;
      tpdf[i] = nearestCode(value + Math.random() - Math.random(), scale) / scale;
    }
  }
  return {buffers, gain: 1 / peak, start: first / rate, end: (first + length) / rate};
}
