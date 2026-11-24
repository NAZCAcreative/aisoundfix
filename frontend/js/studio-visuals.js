const icons = {
  history:'M3 11a9 9 0 1 1 2.5 7 M3 5v6h6 M12 7v5l4 2',
  lab:'M9 3h6m-5 0v6l-5.6 9a2 2 0 0 0 1.7 3h11.8a2 2 0 0 0 1.7-3L14 9V3 M7 15h10',
  book:'M3 5c3-1 6-1 9 1 3-2 6-2 9-1v14c-3-1-6-1-9 1-3-2-6-2-9-1z M12 6v14',
  sliders:'M3 6h4m5 0h9M3 12h10m5 0h3M3 18h2m5 0h11 M7 4v4h5V4z M13 10v4h5v-4z M5 16v4h5v-4z',
  layers:'M3 8l9-5 9 5-9 5z M3 12l9 5 9-5 M3 16l9 5 9-5',
  disc:'M21 12a9 9 0 1 1-18 0 9 9 0 1 1 18 0 M14 12a2 2 0 1 1-4 0 2 2 0 1 1 4 0 M6 12c0-3 2-5 5-6',
  cpu:'M6 6h12v12H6z M9 9h6v6H9z M9 3v3m6-3v3m-6 12v3m6-3v3M3 9h3m-3 6h3m12-6h3m-3 6h3',
  grid:'M3 4h7v7H3z M14 4h7v7h-7z M3 15h7v6H3z M14 15h7v6h-7z',
  chevron:'M9 5l7 7-7 7',
  help:'M21 12a9 9 0 1 1-18 0 9 9 0 1 1 18 0 M9 9a3 3 0 0 1 6 0c0 2-3 2-3 5 M12 17h.01',
  upload:'M12 15V3m-4.5 5L12 3l4.5 5 M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4',
  close:'M6 6l12 12 M18 6L6 18',
  wave:'M2 12h3l2-6 3 13 3-16 3 14 2-8 2 3h2',
  check:'M4 12l5 5L20 6', play:'M7 3.8 20 12 7 20.2z',
  pause:'M6 4h4v16H6z M14 4h4v16h-4z',
  loop:'M4 10V8a2 2 0 0 1 2-2h12l-3-3m3 3-3 3 M20 14v2a2 2 0 0 1-2 2H6l3 3m-3-3 3-3',
  volume:'M3 9h4l5-4v14l-5-4H3z M15 9c2 2 2 4 0 6 M18 6c4 3 4 9 0 12',
  muted:'M3 9h4l5-4v14l-5-4H3z M16 9l5 6m0-6-5 6',
  reset:'M4 9a8 8 0 1 1 0 7 M4 4v5h5',
  spark:'M12 3c0 5-2 7-7 8 5 1 7 3 7 8 1-5 3-7 8-8-5-1-7-3-8-8z M4 2v5M2 4.5h5',
  export:'M3 11h3l2-6 3 13 3-15 3 12 2-4h2 M3 21h18',
  download:'M12 3v12m-5-5 5 5 5-5 M4 16v4h16v-4',
  mic:'M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0z M5 11v1a7 7 0 0 0 14 0v-1 M12 19v3m-4 0h8',
  music:'M9 17V6l11-2v11 M9 17c0 4-7 5-7 2 0-3 5-4 7-2 M20 15c0 4-7 5-7 2 0-3 5-4 7-2'
};
const iconImages = new Map();
export function paintIcons(root = document) {
  for (const el of root.querySelectorAll('i[data-icon]')) {
    const name = el.dataset.icon;
    if (!icons[name]) continue;
    if (!iconImages.has(name)) {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 72;
      const ctx = canvas.getContext('2d');
      ctx.scale(3,3);
      ctx.lineWidth = 1.65;
      ctx.lineJoin = ctx.lineCap = 'round';
      const path = new Path2D(icons[name]);
      if (name === 'play' || name === 'pause') ctx.fill(path);
      else ctx.stroke(path);
      iconImages.set(name,'url(' + canvas.toDataURL() + ')');
    }
    el.style.backgroundColor = 'currentColor';
    el.style.mask = iconImages.get(name) + ' center / contain no-repeat';
    el.setAttribute('aria-hidden','true');
  }
}

function surface(canvas) {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return null;
  const scale = Math.min(window.devicePixelRatio || 1, 2);
  if (canvas.width !== Math.round(width*scale) || canvas.height !== Math.round(height*scale)) {
    canvas.width = Math.round(width*scale);
    canvas.height = Math.round(height*scale);
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(scale,0,0,scale,0,0);
  ctx.clearRect(0,0,width,height);
  return {ctx,width,height};
}

export function filterGraph(canvas, key, amount, enabled, color) {
  const bounds = surface(canvas);
  if (!bounds) return;
  const {ctx,width:w,height:h} = bounds;
  const strength = amount / 100;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.globalAlpha = .13;
  ctx.beginPath();
  for (let x=12;x<w;x+=20) { ctx.moveTo(x,0); ctx.lineTo(x,h); }
  for (let y=h/4;y<h;y+=h/4) { ctx.moveTo(0,y); ctx.lineTo(w,y); }
  ctx.stroke();
  ctx.globalAlpha = enabled ? .98 : .65;
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  if (key === 'velvet') {
    const count=Math.max(32,Math.floor(w/2));
    for(let i=0;i<count;i++) {
      const t=i/count, x=w*(.045+.94*t);
      const jitter=Math.sin(i*34.1+1.4)*Math.cos(i*7.72);
      const tail=(1-Math.exp(-28*t))*Math.exp(-3.8*t);
      ctx.moveTo(x,h*.55);ctx.lineTo(x,h*(.55-jitter*tail*(.45+.43*strength)));
    }
    ctx.stroke();
  } else if (key === 'bass') {
    const levels=[.32,.25+.57*strength,.16+.44*strength];
    for(let i=0;i<levels.length;i++) {
      const x=w*(.18+.30*i), y=h*(.88-levels[i]*.79);
      ctx.globalAlpha=i===0?.45:(enabled?.98:.68);
      ctx.beginPath();ctx.moveTo(x-w*.13,h*.88);
      ctx.bezierCurveTo(x-w*.045,h*.88,x-w*.028,y,x,y);
      ctx.bezierCurveTo(x+w*.028,y,x+w*.045,h*.88,x+w*.13,h*.88);
      ctx.stroke();
    }
  } else if (key === 'rhythm') {
    const hits=[.08,.27,.38,.56,.70,.88];
    for(let i=0;i<w;i++) {
      const time=i/w;
      let hit=0;
      for(const at of hits) if(time>=at) hit+=Math.exp(-(time-at)*58);
      const body=(1-strength*.7)*(.11+.045*Math.sin(time*23));
      const y=h*(.82-body-hit*(.25+.37*strength));
      if(i===0)ctx.moveTo(i,y);else ctx.lineTo(i,y);
    }
    ctx.stroke();
  } else if (key === 'width') {
    const spread = .16 + strength * .22;
    for (let i=0;i<=160;i++) {
      const t = 2*Math.PI*i/160;
      const x = w/2 + w*spread*Math.sin(t) + w*.085*Math.sin(3*t);
      const y = h/2 + h*.34*Math.sin(t+1.08);
      if (!i) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }
    ctx.stroke();
    ctx.globalAlpha = .38;
    ctx.beginPath(); ctx.ellipse(w/2,h/2,w*.12,h*.32,-.38,0,Math.PI*2); ctx.stroke();
  } else {
    const bump = (x,at,span) => Math.exp(-Math.pow((x-at)/span,2));
    for (let i=0;i<=w;i++) {
      const x = i/w;
      let y = .55;
      if (key === 'clarity') y += (.08+.18*strength)*bump(x,.29,.14) - (.12+.39*strength)*bump(x,.71,.15);
      if (key === 'deess') {
        const peaks = .46*bump(x,.52,.027) + .32*bump(x,.61,.025) + .24*bump(x,.73,.032);
        y = .7 - .05*Math.sin(x*74) - peaks*(1-strength*.55) - .18*bump(x,.3,.14);
      }
      if (key === 'restore') {
        y = .69 - (.07+.20*x+.11*strength)*Math.abs(Math.sin(x*43)+.45*Math.sin(x*116))*(.5+.5*Math.sin(Math.PI*x));
      }
      if (!i) ctx.moveTo(i,h*y); else ctx.lineTo(i,h*y);
    }
    ctx.stroke();
    ctx.lineTo(w,h); ctx.lineTo(0,h); ctx.closePath();
    ctx.globalAlpha = .08; ctx.fillStyle=color; ctx.fill();
  }
  ctx.globalAlpha = 1;
}

export function envelope(buffer) {
  if (!buffer) return null;
  const bins=720;
  const peaks = new Float32Array(bins*2);
  const channels = Array.from({length:buffer.numberOfChannels},(_,i)=>buffer.getChannelData(i));
  for (let i=0;i<bins;i++) {
    const start=Math.floor(i*buffer.length/bins);
    const end=Math.floor((i+1)*buffer.length/bins);
    const stride=Math.max(1,Math.floor((end-start)/120));
    let high=0, low=0;
    for (const signal of channels) {
      for (let j=start;j<end;j+=stride) {
        const x=signal[j];
        high=Math.max(high,x); low=Math.min(low,x);
      }
    }
    peaks[2*i]=high; peaks[2*i+1]=-low;
  }
  return peaks;
}

export function drawWave(canvas, peaks, position, mode) {
  const bounds=surface(canvas);
  if (!bounds) return;
  const {ctx,width:w,height:h}=bounds;
  ctx.strokeStyle='#ffffff12'; ctx.lineWidth=1; ctx.beginPath();
  for(let i=1;i<12;i++){const x=Math.round(w*i/12)+.5;ctx.moveTo(x,0);ctx.lineTo(x,h)}
  ctx.moveTo(0,h/2+.5);ctx.lineTo(w,h/2+.5);ctx.stroke();
  if (!peaks) return;
  const bars=Math.min(peaks.length/2,Math.floor(w/2.8));
  const spacing=w/bars;
  const cutoff=w*Math.max(0,Math.min(1,position));
  for(let i=0;i<bars;i++) {
    const bin=Math.floor(i*(peaks.length/2)/bars)*2;
    const high=Math.min(1,peaks[bin]);
    const low=Math.min(1,peaks[bin+1]);
    const top=h*.47*Math.sqrt(high), bottom=h*.45*Math.sqrt(low);
    const x=i*spacing;
    ctx.fillStyle = x<cutoff ? '#ffd1b6' : (mode==='processed' ? '#ff9768' : '#c7c9c8');
    ctx.fillRect(x,h/2-top,Math.max(1,spacing*.64),Math.max(1,top+bottom));
  }
  const marker=Math.min(w-1,Math.max(1,cutoff));
  ctx.fillStyle='#fff7ed';ctx.fillRect(marker-1,0,2,h);
}
