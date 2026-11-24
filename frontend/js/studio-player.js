export function hasSignalChange(original,processed,ceilingGain=1) {
  if(!original || !processed) return false;
  const channels=Math.max(original.numberOfChannels,processed.numberOfChannels);
  for(let channel=0;channel<channels;channel++) {
    const dry=original.getChannelData(Math.min(channel,original.numberOfChannels-1));
    const wet=processed.getChannelData(Math.min(channel,processed.numberOfChannels-1));
    const frames=Math.max(dry.length,wet.length);
    for(let i=0;i<frames;i++) {
      // Ignore encoding noise and the common gain applied to meet the output ceiling.
      if(Math.abs((wet[i] ?? 0)-(dry[i] ?? 0)*ceilingGain)>1e-5) return true;
    }
  }
  return false;
}

export class StudioPlayer {
  constructor(onChange) {
    this.onChange=onChange;
    this.mode='original';
    this.levelMatch=true;
    this.loop=false;
    this.volume=.8;
    this.muted=false;
    this.clear();
  }

  context() {
    if (!this.ctx) {
      this.ctx=new AudioContext();
      this.output=this.ctx.createGain();
      this.output.connect(this.ctx.destination);
      this.updateVolume();
    }
    return this.ctx;
  }

  async decode(blob) {
    return this.context().decodeAudioData(await blob.arrayBuffer());
  }

  clear() {
    if (this.group) this.retire();
    this.original=null;
    this.processed=null;
    this.originalLevel=null;
    this.processedLevel=null;
    this.ceilingGain=1;
    this.signalChanged=false;
    this.region=null;
    this.mode='original';
    this.offset=0;
    this.playing=false;
    this.pendingStart=null;
  }

  get duration() {return this.original?.duration || 0}

  get levelsMeasured() {
    return Number.isFinite(this.originalLevel) && Number.isFinite(this.processedLevel);
  }

  get canCompare() {
    const matched=this.levelMatch && this.levelsMeasured;
    return !!this.processed && (this.signalChanged || (!matched && this.ceilingGain<.999));
  }

  position() {
    if (!this.playing || !this.duration) return this.offset;
    const time=this.offset+Math.max(0,this.ctx.currentTime-this.started);
    if(this.region) return this.region.start+(time-this.region.start)%(this.region.end-this.region.start);
    return this.loop ? time%this.duration : Math.min(time,this.duration);
  }

  updateVolume() {
    if (this.output) this.output.gain.setTargetAtTime(this.muted ? 0 : this.volume,this.ctx.currentTime,.012);
  }

  retire() {
    const group=this.group;
    if (!group) return;
    this.group=null;
    const now=this.ctx.currentTime;
    group.bus.gain.cancelScheduledValues(now);
    group.bus.gain.setValueAtTime(group.bus.gain.value,now);
    group.bus.gain.linearRampToValueAtTime(0,now+.012);
    for (const source of group.sources) {
      source.onended=null;
      try {source.stop(now+.016)} catch {}
    }
    setTimeout(()=>group.bus.disconnect(),90);
  }

  startAt(position) {
    this.retire();
    if (!this.original || !this.duration) return;
    const ctx=this.context(), now=ctx.currentTime;
    this.offset=Math.min(position,Math.max(0,this.duration-.0001));
    if(this.region && (this.offset<this.region.start || this.offset>=this.region.end)) this.offset=this.region.start;
    this.started=now;
    const bus=ctx.createGain();
    bus.gain.setValueAtTime(0,now);
    bus.gain.linearRampToValueAtTime(1,now+.012);
    bus.connect(this.output);
    const group={bus,sources:[],gains:[]};
    this.group=group;
    const attach=buffer=>{
      const src=ctx.createBufferSource(), gain=ctx.createGain();
      src.buffer=buffer; src.loop=!!this.region || this.loop;
      if(this.region) {src.loopStart=this.region.start; src.loopEnd=this.region.end}
      src.connect(gain).connect(bus);
      group.gains.push(gain.gain);
      group.sources.push(src);
    };
    attach(this.original);
    if(this.processed) attach(this.processed);
    this.updateMix(true);
    for(const source of group.sources) {
      source.start(now,Math.min(this.offset,Math.max(0,source.buffer.duration-.0001)));
    }
    this.playing=true;
    group.sources[0].onended=()=>{
      if (this.group!==group || this.loop || this.region) return;
      this.playing=false; this.offset=this.duration; this.group=null;
      group.bus.disconnect(); this.onChange();
    };
  }

  async toggle() {
    if(!this.original) return;
    if(this.playing || this.pendingStart){this.pause();return}
    const attempt=Symbol();
    this.pendingStart=attempt;
    this.onChange();
    try {await this.context().resume()} catch(error) {
      if(this.pendingStart!==attempt) return;
      this.pendingStart=null;
      this.onChange();
      throw error;
    }
    if(this.pendingStart!==attempt) return;
    this.pendingStart=null;
    this.startAt(this.offset>=this.duration-.001 ? 0 : this.offset);
    this.onChange();
  }

  pause() {
    this.pendingStart=null;
    this.offset=this.position();
    this.playing=false;
    this.retire();
    this.onChange();
  }

  updateMix(immediate=false) {
    if(!this.group) return;
    const a=this.originalLevel, b=this.processedLevel;
    const matched=this.processed && this.levelMatch && this.levelsMeasured;
    let original=0, processed=0;
    if(this.mode==='processed') {
      processed=matched ? 10**((Math.min(a,b)-b)/20) : 1;
    } else {
      original=matched ? 10**((Math.min(a,b)-a)/20) : 1;
    }
    const now=this.ctx.currentTime;
    this.group.gains.forEach((gain,i)=>{
      const target=i===0 ? original : processed;
      if(immediate) gain.setValueAtTime(target,now);
      else gain.setTargetAtTime(target,now,.003);
    });
  }

  setMode(mode,replaceSources=false) {
    this.mode=mode==='processed' && this.canCompare ? 'processed' : 'original';
    if(replaceSources) this.startAt(this.position());
    else this.updateMix();
    this.onChange();
  }

  setRendered(buffer,level,mode,ceilingGain=1,signalChanged=false) {
    const replaceSources=this.playing && buffer!==this.processed;
    this.processed=buffer;
    this.processedLevel=level;
    this.ceilingGain=ceilingGain;
    this.signalChanged=signalChanged;
    this.setMode(mode,replaceSources);
  }

  seek(time) {
    this.region=null;
    this.offset=Math.min(this.duration,Math.max(0,time));
    if(this.playing) this.startAt(this.offset);
    this.onChange();
  }

  setRegion(range) {
    const pos=this.position();
    const start=Math.max(0,range?.start ?? 0), end=Math.min(this.duration,range?.end ?? 0);
    this.region=end>start ? {start,end} : null;
    this.offset=this.region ? start : pos;
    if(this.playing) this.startAt(this.offset);
    this.onChange();
  }

  changeLoop() {
    if(this.region) {this.loop=false; this.setRegion(null); return}
    const pos=this.position();
    this.loop=!this.loop;
    if(this.playing) this.startAt(pos);
    this.onChange();
  }
}
