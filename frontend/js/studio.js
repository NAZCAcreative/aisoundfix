import { StudioPlayer, hasSignalChange } from './studio-player.js?v=20261122-master';
import { paintIcons, filterGraph, envelope, drawWave } from './studio-visuals.js?v=20261122-history';
import { setupHistory } from './studio-history.js?v=20261122-history2';

const $ = id => document.getElementById(id);
const all = selector => [...document.querySelectorAll(selector)];
const restorationFilters = [
  { key:'clarity', name:'선명도 EQ', type:'PRESENCE EQ', description:'뭉친 저중역을 정리하고 멜로디의 윤곽을 살립니다.', value:36 },
  { key:'deess', name:'치찰음 완화', type:'DE-ESSER', description:'튀는 ㅅ 발음과 거친 심벌의 고역을 눌러줍니다.', value:35 },
  { key:'width', name:'공간 확장', type:'MID / SIDE', description:'중앙의 소리를 유지하며 좌우 공간을 넓힙니다.', value:45 },
  { key:'restore', name:'AI 압축 복원', type:'APOLLO AI', description:'AI가 압축으로 손상된 소리의 디테일을 추정해 보완합니다.', value:55 }
];
const labFilters = [
  { key:'velvet', name:'벨벳 룸', type:'DARK VELVET NOISE', description:'스네어와 보컬 뒤로 부풀었다가 어두워지는 잔향을 펼칩니다.', value:68 },
  { key:'bass', name:'고스트 베이스', type:'VIRTUAL BASS', description:'저음에 배음을 더해 작은 스피커에서도 베이스 라인을 따라가기 쉽게 합니다.', value:72 },
  { key:'rhythm', name:'리듬 포커스', type:'MEDIAN HPSS', description:'길게 울리는 음을 뒤로 보내고 킥과 스네어의 타격을 앞으로 꺼냅니다.', value:78 }
];
const filters = [...restorationFilters, ...labFilters];
const repairKinds = ['peaks','band'];
const repairNames = {peaks:'잘린 피크 복원',band:'고역 복원'};
const comparisonClarity = 70;
const player = new StudioPlayer(refreshTransport);
const state = Object.fromEntries(filters.map(f=>[f.key,{enabled:false,value:f.value}]));
const nodes = {};
let track=null, loading=false, loadSerial=0, loadRequest=null;
let requestedTrackName='';
let requestedTrackId=null;
let requestedVersion=null;
let renderedKey='', master=null, renderTimer=0, activeRender=null, preferred='processed';
let renderFailed=false;
let stemRequest=null, stemLinks=null;
let auditionFor=null;
let repairEnabled=false;
let frame=0;
let wavePeaks={};
const cache=new Map();
const base = id => '/api/studio/tracks/'+id;
const timestamp = t => Math.floor(t/60)+':'+String(Math.floor(t%60)).padStart(2,'0');
function cueTime(seconds) {
  const ticks=Math.round(seconds*100), fraction=ticks%100;
  return timestamp(ticks/100)+(fraction?'.'+String(fraction).padStart(2,'0').replace(/0$/,''):'');
}
const keyOf = recipe => JSON.stringify(recipe);
function recipe() {
  const manual=Object.fromEntries(filters.map(({key})=>[key,state[key].enabled ? state[key].value : 0]));
  return {repair:repairEnabled,...manual};
}
function hasProcessing(settings=recipe()) {return Object.values(settings).some(Boolean)}
function effectNames() {
  const names=filters.filter(f=>state[f.key].enabled).map(f=>f.name+' '+state[f.key].value+'%');
  if(repairEnabled) names.unshift(repairNames[track.analysis.kind]);
  return names;
}
function ready() {return !!track && !!master && renderedKey===keyOf(recipe()) && !loading}
function message(text) {
  const box=$('notice');
  box.querySelector('span').textContent=text || '';
  box.hidden=!text;
}
async function request(url,options={}) {
  const res=await fetch(url,options);
  if(!res.ok) {
    let detail;
    try {detail=(await res.json()).detail} catch {}
    throw new Error(typeof detail==='string' ? detail : '요청을 완료하지 못했습니다. 잠시 후 다시 시도하세요.');
  }
  return res;
}
function engine(online) {
  document.querySelector('.engine').classList.toggle('online',online);
  $('engine-state').lastElementChild.textContent=online?'연결됨':'연결 안 됨';
}
function iconIn(button,icon) {
  const node=button.querySelector('i');
  if(node.dataset.icon!==icon) {node.dataset.icon=icon; paintIcons(button)}
}
function meter(id,value,unit) {
  const target=$(id);
  target.replaceChildren();
  target.append(Number.isFinite(value)?value.toFixed(1):'—');
  const small=document.createElement('small');
  small.textContent=' '+unit;
  target.append(small);
}
function renderStatus(text,activity='',stats=null) {
  $('render-status').textContent=text;
  meter('lufs',stats?.lufs,'LUFS');meter('peak',stats?.truePeak,'dBTP');
  $('monitor-state').textContent=activity;
  $('monitor-state').hidden=!activity;
  document.querySelector('.output').classList.toggle('is-busy',Boolean(activity));
}
function showMaster() {
  const names=effectNames();
  const settings=names.length ? '저장 설정 · '+names.join(' + ') :
    '필터 미적용'+(master.stats.ceilingGain<1?' · 출력 피크 조정':'');
  renderStatus(settings,'',master.stats);
}
function diagnosisSummary(kind,manual) {
  if(loading) return '‘'+requestedTrackName+'’의 복원 가능 여부를 확인하고 있습니다.';
  if(!track) return requestedTrackName?'음원을 열지 못했습니다. 음원 불러오기로 파일을 다시 선택하세요.':'음원을 불러오면 사용할 수 있는 복원을 표시합니다.';
  if(!kind) return '이 음원의 자동 복원 결과를 확인할 수 없습니다. 수동 필터로 음색을 조절할 수 있습니다.';
  let detail;
  if(kind==='peaks') {
    const {peakCount,preview}=track.analysis;
    detail='잘린 피크 '+peakCount.toLocaleString('ko-KR')+'곳을 찾았습니다(채널 합계). '+cueTime(preview.start)+'–'+cueTime(preview.end)+' 구간에서 원본(A)과 보정본(B)을 비교하세요.';
  } else if(kind==='band') {
    detail=track.bitrate+' kbps MP3에서 '+(track.analysis.edgeHz/1000).toLocaleString('ko-KR')+' kHz 위의 에너지가 급격히 줄었습니다.';
  } else {
    const source=track.format==='MP3' && track.bitrate>0 ? track.bitrate+' kbps MP3' : '이 음원';
    return source+'에는 자동 복원 대상이 없습니다. '+(manual?'켜 둔 필터의 결과를 원본과 비교할 수 있습니다.':'B로 선명도 EQ를 들어보거나 수동 필터를 직접 선택하세요.');
  }
  if(!repairEnabled) detail+=' 비교 듣기를 누르면 복원이 켜집니다.';
  if(manual) detail+=' 켜 둔 필터도 보정본에 함께 적용됩니다.';
  return detail;
}
function drawDiagnosis() {
  const kind=loading ? null : track?.analysis?.kind;
  const eligible=repairKinds.includes(kind);
  const manual=filters.some(f=>state[f.key].enabled);
  let inactive='대상 없음';
  if(loading) inactive='분석 중';
  else if(!track) inactive=requestedTrackName?'확인 불가':'대기';
  else if(!kind) inactive='정보 없음';
  let selection='사용 가능';
  if(repairEnabled) selection=ready()?'적용됨':'선택됨';
  for(const method of repairKinds) {
    const status=$(method+'-status');
    status.textContent=method===kind ? selection : inactive;
    status.dataset.state=method===kind ? (repairEnabled?'on':'available') : 'idle';
  }
  const summary=diagnosisSummary(kind,manual);
  if($('diagnosis-detail').textContent!==summary) $('diagnosis-detail').textContent=summary;
  $('repair-toggle').checked=eligible && repairEnabled;
  $('repair-toggle').disabled=!eligible;
  $('recommend').disabled=loading || !track || (!eligible && !manual);
  const comparing=!!player.region && !loading, waiting=auditionFor?.source==='repair';
  $('recommend').lastElementChild.textContent=waiting?'미리듣기 취소':comparing?'전체 곡 듣기':'복원 비교 듣기';
  iconIn($('recommend'),waiting?'close':comparing?'music':'play');
}
function buildFilters() {
  for(const f of filters) {
    const isLab=labFilters.includes(f);
    const card=document.createElement('article');
    card.className='filter';
    card.dataset.key=f.key;
    card.innerHTML='<div class="filter-top"><span class="filter-type">'+f.type+'</span><button class="switch" role="switch" aria-label="'+f.name+'" aria-checked="false"></button></div>'+
      '<h3>'+f.name+'</h3><p>'+f.description+'</p><div class="graph"><canvas aria-hidden="true"></canvas></div>'+
      '<div class="filter-control"><label for="mix-'+f.key+'">강도</label><input id="mix-'+f.key+'" type="range" min="0" max="100" value="0" aria-label="'+f.name+' 강도"><output for="mix-'+f.key+'">0%</output></div>';
    $(isLab?'lab-filters':'filters').append(card);
    const toggle=card.querySelector('.switch'), slider=card.querySelector('input');
    let listen;
    if(isLab) {
      listen=document.createElement('button');
      listen.className='lab-listen';
      listen.innerHTML='<i data-icon="play"></i><span>이 효과 듣기</span>';
      listen.setAttribute('aria-label',f.name+' 듣기');
      card.append(listen);
      listen.onclick=()=>{
        if(auditionFor?.source===f.key) cancelAudition();
        else if(listen.getAttribute('aria-pressed')==='true') togglePlay();
        else audition(f.key);
      };
    }
    nodes[f.key]={card,toggle,slider,listen,canvas:card.querySelector('canvas'),output:card.querySelector('output')};
    toggle.addEventListener('click',()=>{
      state[f.key].enabled=!state[f.key].enabled;
      if(f.key==='restore' && state.restore.enabled && track.analysis?.kind==='band') repairEnabled=false;
      changed();
    });
    slider.addEventListener('input',()=>{
      const amount=Number(slider.value);
      state[f.key].enabled=amount>0;
      if(amount>0) state[f.key].value=amount;
      if(f.key==='restore' && amount>0 && track.analysis?.kind==='band') repairEnabled=false;
      changed();
    });
  }
}
function drawFilters() {
  for(const f of filters) {
    const s=state[f.key], n=nodes[f.key], locked=loading || !track || (f.key==='width' && track.channels===1);
    const value=s.enabled?s.value:0;
    n.card.dataset.enabled=String(s.enabled);
    n.toggle.disabled=n.slider.disabled=locked;
    n.toggle.setAttribute('aria-checked',String(s.enabled));
    n.slider.value=value;
    n.slider.style.setProperty('--fill',value+'%');
    n.slider.setAttribute('aria-valuetext',value?value+'퍼센트':'꺼짐');
    n.output.textContent=value+'%';
    n.card.querySelector('p').textContent=(f.key==='width' && track?.channels===1)?'스테레오 음원에서 사용할 수 있습니다.':f.description;
    filterGraph(n.canvas,f.key,s.value,s.enabled,getComputedStyle(n.card).getPropertyValue('--accent').trim());
  }
  const active=filters.filter(f=>state[f.key].enabled);
  const labCount=labFilters.filter(f=>state[f.key].enabled).length;
  $('filter-count').textContent=(active.length-labCount)+' / '+restorationFilters.length+' 활성';
  $('lab-count').textContent=labCount+' / '+labFilters.length+' 활성';
  $('mix-summary').hidden=!labCount;
  $('mix-summary').textContent='현재 조합 · '+effectNames().join(' + ');
  $('lab-reset').disabled=loading || !track || !labCount;
  $('reset').disabled=loading || !track;
}
function setRecipe(values,group=filters) {
  for(const {key,value} of group) {
    const next=values[key] || 0;
    state[key].enabled=next>0 && !(key==='width' && track?.channels===1);
    state[key].value=next || value;
  }
}
function drawTimeline() {
  const time=player.position(), duration=player.duration;
  $('elapsed').textContent=timestamp(time);
  $('seek').value=duration?Math.round(time/duration*1000):0;
  $('seek').setAttribute('aria-valuetext',timestamp(time)+' / '+timestamp(duration));
  drawWave($('waveform'),wavePeaks[player.mode],duration?time/duration:0,player.mode);
}
function animate() {
  frame=0;
  drawTimeline();
  if(player.playing) frame=requestAnimationFrame(animate);
}
function playingStem() {
  return [$('vocals-audio'),$('instrumental-audio')].find(audio=>!audio.paused && !audio.ended);
}
function refreshComparison() {
  const available=!!player.original && !loading;
  const effects=effectNames(), rendered=ready();
  const noDifference=rendered && effects.length>0 && !player.canCompare;
  for(const button of all('[data-mode]')) {
    const mode=button.dataset.mode;
    button.setAttribute('aria-pressed',String(player.mode===mode));
    button.disabled=!available || (mode==='processed' && noDifference);
  }
  let note;
  if(!available) note=loading?'음원을 준비하고 있습니다.':'음원을 불러오면 원본과 보정을 비교할 수 있습니다.';
  else if(!effects.length) {
    const firstEffect=repairNames[track.analysis?.kind] || '선명도 EQ '+comparisonClarity+'%';
    note='B를 누르면 '+firstEffect+' 효과를 켭니다. A로 원본을 다시 들을 수 있습니다.';
  } else if(renderFailed) note='보정본을 만들지 못했습니다. B를 눌러 다시 시도하세요.';
  else if(!rendered) note=preferred==='processed'?'지금은 A 원본입니다. 보정이 끝나면 B로 전환합니다.':'보정본을 준비하고 있습니다. 현재 선택은 A 원본입니다.';
  else if(noDifference) note='현재 설정과 원본의 차이가 거의 없습니다. 필터나 강도를 바꿔 비교하세요.';
  else if(!player.signalChanged) note='출력 피크를 맞추면서 음량만 달라졌습니다. '+(player.levelsMeasured?'음량 맞춤을 켜서 확인할 수 있습니다.':'이 음원은 파일의 재생 음량으로 비교합니다.');
  else note=(player.mode==='processed'?'B 보정 · ':'A 원본 · B 설정 · ')+effects.join(' + ');
  if(available && playingStem()) note='스템 재생 중 · A/B를 누르면 같은 위치에서 전체 믹스를 듣습니다.'+(effects.length?'':' '+note);
  if($('compare-note').textContent!==note) $('compare-note').textContent=note;
}
function refreshTransport() {
  drawDiagnosis();
  const waiting=!!auditionFor && !player.playing;
  const playLabel=waiting?'미리듣기 취소':player.playing?'일시정지':player.pendingStart?'재생 취소':'재생';
  $('play').disabled=loading || !player.original;
  $('play').setAttribute('aria-label',playLabel);
  $('play').title=playLabel+' · Space';
  iconIn($('play'),waiting || player.pendingStart?'close':player.playing?'pause':'play');
  $('loop').setAttribute('aria-pressed',String(!!player.region || player.loop));
  $('loop').setAttribute('aria-label',player.region?'복원 구간 반복 해제':'전체 반복 재생');
  const marker=$('repair-range');
  marker.hidden=!player.region;
  if(player.region) {
    marker.style.left=(100*player.region.start/player.duration)+'%';
    marker.style.width=(100*(player.region.end-player.region.start)/player.duration)+'%';
  }
  const match=$('match');
  const unmeasurable=!!track && !loading && (!Number.isFinite(player.originalLevel) || (ready() && !!player.processed && !player.levelsMeasured));
  match.disabled=loading || !track || unmeasurable;
  match.setAttribute('aria-pressed',String(!match.disabled && player.levelMatch));
  match.lastElementChild.textContent=unmeasurable?'음량 측정 불가':'음량 맞춤';
  match.title=unmeasurable?'통합 음량을 측정할 수 없어 파일의 재생 음량으로 비교합니다.':'A/B 재생 음량 맞추기';
  $('mute').setAttribute('aria-pressed',String(player.muted));
  $('mute').setAttribute('aria-label',player.muted?'음소거 해제':'음소거');
  iconIn($('mute'),player.muted || !player.volume?'muted':'volume');
  $('volume').style.setProperty('--fill',Math.round(player.volume*100)+'%');
  $('seek').disabled=loading || !player.original;
  $('total').textContent=timestamp(track?.duration || 0);
  refreshComparison();
  $('export').disabled=!ready();
  $('export').lastElementChild.textContent=!loading && track && hasProcessing()?'보정본 WAV 저장':'WAV 저장';
  const enabledLab=labFilters.filter(f=>state[f.key].enabled);
  for(const f of labFilters) {
    const button=nodes[f.key].listen;
    const selected=enabledLab.length===1 && enabledLab[0]===f;
    const playing=selected && ready() && player.playing && player.mode==='processed';
    const pending=auditionFor?.source===f.key;
    button.disabled=loading || !track;
    button.setAttribute('aria-pressed',String(playing));
    button.setAttribute('aria-label',f.name+(pending?' 미리듣기 취소':playing?' 일시정지':' 듣기'));
    button.lastElementChild.textContent=pending?'미리듣기 취소':playing?'일시정지':'이 효과 듣기';
    iconIn(button,pending?'close':playing?'pause':'play');
  }
  $('split').disabled=loading || !track || !!stemRequest || !!stemLinks;
  if(frame) cancelAnimationFrame(frame);
  animate();
}
function releaseTrack() {
  if(activeRender) activeRender.controller.abort();
  activeRender=null;
  if(stemRequest) stemRequest.abort();
  stemRequest=null; stemLinks=null;
  clearTimeout(renderTimer);
  player.clear();
  track=null; master=null; renderedKey=''; renderFailed=false;
  repairEnabled=false;auditionFor=null;preferred='original';
  setRecipe({});wavePeaks={};
  cache.clear();
  for(const part of ['vocals','instrumental']) {
    const audio=$(part+'-audio'); audio.pause(); audio.removeAttribute('src'); audio.load();
    $(part+'-save').hidden=true; $(part+'-save').removeAttribute('href');
  }
  $('stem-status').textContent='현재 트랙의 원본에서 보컬과 반주 WAV를 추출합니다.';
  $('split').lastChild.textContent='스템 분리 시작';
}
function showEmptyTrack() {
  $('track-title').textContent='음원을 불러오세요';
  $('track-title').title='';$('source-tag').textContent='내 음원';$('track-spec').textContent='';
  $('ruler').replaceChildren();
  renderStatus('음원을 불러오세요');
  drawFilters();refreshTransport();
}
function showStems(links) {
  stemLinks=links;
  for(const part of ['vocals','instrumental']) {
    $(part+'-audio').src=links[part];
    const a=$(part+'-save'); a.href=links[part]; a.download=track.name+'-'+part+'.wav'; a.hidden=false;
  }
  $('split').lastChild.textContent='분리 완료';
  $('stem-status').textContent='보컬과 반주를 각각 들어보거나 WAV로 저장하세요.';
}
function replaceTrack(info,buffer,settings) {
  releaseTrack();
  track=info;
  wavePeaks={original:envelope(buffer)};
  player.original=buffer; player.originalLevel=info.metrics.lufs;
  $('track-title').textContent=info.name;
  $('track-title').title=info.name;
  $('source-tag').textContent=info.example?'예제 트랙':'내 음원';
  const rate=Number((info.rate/1000).toFixed(2))+' kHz';
  $('track-spec').textContent=[info.format,rate,info.channels===2?'STEREO':'MONO'].join('  /  ');
  $('ruler').replaceChildren(...Array.from({length:5},(_,i)=>{
    const el=document.createElement('span');el.textContent=timestamp(info.duration*i/4);return el;
  }));
  if(info.hasStems) showStems({vocals:base(info.id)+'/stems/vocals',instrumental:base(info.id)+'/stems/instrumental'});
  setRecipe(settings || {});
  repairEnabled=!!(settings || info.recommended)?.repair && repairKinds.includes(info.analysis?.kind);
  preferred=hasProcessing()?'processed':'original';
}
function startAudition(key) {
  if(auditionFor?.id!==track?.id || auditionFor?.key!==key) return;
  const region=auditionFor.region;
  auditionFor=null;
  if(region) player.setRegion(region);
  if(!player.playing && !player.pendingStart) togglePlay();
  else if(!region) refreshTransport();
}
function cancelAudition() {
  auditionFor=null;
  preferred=player.mode;
  refreshTransport();
}
async function loadTrack(url,options={},name='예제 음원',version=null,historyId=null) {
  const serial=++loadSerial;
  loadRequest?.abort();
  loadRequest=new AbortController();
  const signal=loadRequest.signal;
  requestedTrackName=name;
  requestedTrackId=historyId;
  requestedVersion=version;
  loading=true;
  auditionFor=null;
  if(player.playing || player.pendingStart) player.pause();
  drawFilters(); refreshTransport();
  renderStatus('음원을 준비하는 중…','음원 준비 중'); message('');
  try {
    const info=await (await request(url,{...options,signal})).json();
    if(serial!==loadSerial) return false;
    requestedTrackId=info.id;
    const audio=async path=>(await request(path,{signal})).blob();
    const [decoded,saved]=await Promise.all([
      audio(base(info.id)+'/audio').then(blob=>player.decode(blob)),
      version?audio('/api/studio/history/'+info.id+'/versions/'+version.id):null
    ]);
    const processed=saved?await player.decode(saved):null;
    if(serial!==loadSerial) return false;
    replaceTrack(info,decoded,version?.recipe);
    requestedTrackId=null;requestedVersion=null;
    engine(true);
    loading=false;
    drawFilters(); refreshTransport();
    if(saved) {
      const key=keyOf(recipe());
      publish(key,remember(key,saved,processed,version.stats));
    } else queueRender(true);
    return true;
  } catch(err) {
    if(serial!==loadSerial || err.name==='AbortError') return false;
    requestedTrackId=null;requestedVersion=null;
    loading=false;
    const reason=err.message || '음원을 불러오지 못했습니다.';
    message(reason+(track?' 현재 음원은 ‘'+track.name+'’입니다.':''));
    if(ready()) showMaster();
    else renderStatus('음원을 다시 불러오세요');
    drawFilters(); refreshTransport();
    if(track && !ready()) queueRender(true);
    return false;
  }
}
function publish(key,result) {
  renderFailed=false;
  renderedKey=key; master=result;
  wavePeaks.processed=result.wave;
  showMaster();
  player.setRendered(result.buffer,result.stats.lufs,preferred,result.stats.ceilingGain,result.signalChanged);
  startAudition(key);
  libraryUI.refresh();
}
function remember(key,blob,buffer,stats) {
  const result={blob,buffer,stats,wave:envelope(buffer),signalChanged:hasSignalChange(player.original,buffer,stats.ceilingGain)};
  if(blob.size<16000000) {
    if(cache.size>=2) cache.delete(cache.keys().next().value);
    cache.set(key,result);
  }
  return result;
}
function queueRender(immediate=false) {
  clearTimeout(renderTimer);
  if(!track || loading) return;
  if(renderFailed) message('');
  renderFailed=false;
  const key=keyOf(recipe());
  if(cache.has(key)) {publish(key,cache.get(key));return}
  if(key===renderedKey && master) {publish(key,master);return}
  const usesModel=state.restore.enabled || (repairEnabled && track.analysis?.kind==='band');
  if(usesModel) renderStatus('Apollo 복원을 적용하는 중…','AI 복원 중');
  else renderStatus('필터를 적용하는 중…','필터 적용 중');
  if(player.mode!=='original') player.setMode('original');
  else refreshTransport();
  if(activeRender && (activeRender.recipe.restore || (activeRender.recipe.repair && track.analysis?.kind==='band')) && !usesModel) {
    activeRender.controller.abort(); activeRender=null;
  }
  renderTimer=setTimeout(renderLatest,immediate?0:160);
}
function changed({source=null,region=null,immediate=false}={}) {
  auditionFor=source?{id:track.id,key:keyOf(recipe()),source,region}:null;
  preferred=hasProcessing()?'processed':'original';
  drawFilters();
  queueRender(immediate || !!source);
}
async function renderLatest() {
  if(!track || loading || activeRender) return;
  const selected=recipe(), key=keyOf(selected), id=track.id;
  if(key===renderedKey && master) return;
  if(cache.has(key)) {publish(key,cache.get(key));return}
  const controller=new AbortController();
  const run={recipe:selected,controller};
  activeRender=run;
  try {
    const res=await request(base(id)+'/render',{method:'POST',headers:{'Content-Type':'application/json'},body:key,signal:controller.signal});
    const stats=JSON.parse(res.headers.get('X-Audio-Metrics'));
    const blob=await res.blob();
    if(controller.signal.aborted || track?.id!==id) return;
    // Keep a bypass export, but never monitor an unprocessed encode as B.
    const buffer=hasProcessing(selected) ? await player.decode(blob) : null;
    if(controller.signal.aborted || track?.id!==id) return;
    const result=remember(key,blob,buffer,stats);
    if(!loading && key===keyOf(recipe())) publish(key,result);
  } catch(err) {
    if(err.name!=='AbortError' && !loading && track?.id===id && key===keyOf(recipe())) {
      renderFailed=true;
      auditionFor=null;
      renderStatus(hasProcessing(selected)?'적용 실패 · B로 다시 시도하세요.':'WAV 준비 실패 · 음원을 다시 불러오세요.');
      message(err.message); refreshTransport();
    }
  } finally {
    if(activeRender===run) {
      activeRender=null;
      if(track?.id===id && key!==keyOf(recipe())) queueRender(true);
    }
  }
}
function selectFile(file) {
  if(!file) return;
  if(!/\.(mp3|wav|flac|m4a)$/i.test(file.name)) {message('WAV, FLAC, MP3, M4A 파일을 선택하세요.');return}
  if(file.size>100*1024*1024) {message('100 MB 이하의 음원을 선택하세요.');return}
  const data=new FormData(); data.append('file',file);
  loadTrack('/api/studio/tracks',{method:'POST',body:data},file.name);
}
async function saveMaster() {
  if(!ready()) return;
  const id=track.id, settings=recipe();
  const url=URL.createObjectURL(master.blob);
  const a=document.createElement('a');
  a.href=url; a.download=track.name.replace(/[\\/:*?"<>|]/g,'-')+' - AIsoundFix.wav';
  document.body.append(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),60000);
  if(!hasProcessing(settings)) {
    try {
      await request(base(id)+'/render?archive_only=true',{method:'POST',headers:{'Content-Type':'application/json'},body:keyOf(settings)});
      libraryUI.refresh();
    } catch(err) {
      if(track?.id===id) message('WAV 다운로드를 시작했지만 히스토리에 저장하지 못했습니다. '+err.message);
    }
  }
}
async function splitTrack() {
  if(!track || stemRequest || stemLinks) return;
  const id=track.id, controller=new AbortController();
  stemRequest=controller;
  $('stem-status').textContent='BS-RoFormer가 보컬과 반주를 분리하고 있습니다…';
  $('split').lastChild.textContent='분리 중…'; refreshTransport(); message('');
  try {
    const links=await (await request(base(id)+'/stems',{method:'POST',signal:controller.signal})).json();
    if(track?.id!==id || controller.signal.aborted) return;
    showStems(links);libraryUI.refresh();
  } catch(err) {
    if(controller.signal.aborted || track?.id!==id) return;
    message(err.message); $('stem-status').textContent='분리를 다시 시도할 수 있습니다.';
    $('split').lastChild.textContent='스템 분리 시작';
  } finally {
    if(stemRequest===controller) stemRequest=null;
    refreshTransport();
  }
}
function page() {
  if(location.hash==='#history') libraryUI.open();
  const view=location.hash==='#stems'?'stems':location.hash==='#lab'?'lab':'studio';
  const stems=view==='stems', lab=view==='lab';
  if((stems || lab) && player.region) player.setRegion(null);
  if(stems || lab) auditionFor=null;
  $('studio-view').hidden=stems; $('stems-view').hidden=!stems;
  $('restoration-rack').hidden=lab; $('lab-view').hidden=!lab;
  const title=stems?'스템 분리':lab?'사운드 랩':'복원 스튜디오';
  $('page-title').textContent=$('crumb-current').textContent=title;
  document.title=title+' · AIsoundFix';
  $('page-intro').textContent=stems?'한 트랙에서 보컬과 반주를 각각 꺼내 들어보세요.':lab?'효과를 하나씩 들어보세요. 스위치를 켜면 여러 효과를 섞을 수 있습니다.':'음원을 불러와 복원할 부분을 확인하고 원본과 비교하세요.';
  for(const a of all('[data-view]')) {
    const active=a.dataset.view===view;
    a.classList.toggle('active',active);
    if(active) a.setAttribute('aria-current','page'); else a.removeAttribute('aria-current');
    a.setAttribute('aria-label',a.textContent.trim());
  }
  if(stems && player.original){auditionFor=null;preferred='original';player.setMode('original')}
  if(!stems) for(const part of ['vocals','instrumental']) $(part+'-audio').pause();
  drawFilters(); refreshTransport();
  if(location.hash==='#rack-title') $('rack-title').focus();
}
async function togglePlay() {
  if(auditionFor) {
    cancelAudition();
    if(!player.playing && !player.pendingStart) return;
  }
  for(const part of ['vocals','instrumental']) $(part+'-audio').pause();
  try {await player.toggle()} catch {message('브라우저가 음원을 재생하지 못했습니다. 재생 버튼을 다시 눌러주세요.')}
}
function chooseMode(mode) {
  if(loading || !player.original || document.querySelector('[data-mode="'+mode+'"]').disabled) return;
  auditionFor=null;
  const stem=playingStem();
  if(stem) {
    const position=stem.currentTime;
    stem.pause();
    player.seek(position);
    togglePlay();
  }
  preferred=mode;
  if(mode==='processed' && !hasProcessing()) {
    if(repairKinds.includes(track.analysis?.kind)) enableRepair(true);
    else {
      state.clarity.enabled=true;
      state.clarity.value=comparisonClarity;
    }
    changed({immediate:true});
    return;
  }
  if(mode==='processed' && !ready()) {
    if(renderFailed) queueRender(true);
    else refreshTransport();
    return;
  }
  player.setMode(mode);
}
function audition(key) {
  if(!track || loading) return;
  player.context().resume().catch(()=>{});
  setRecipe({[key]:state[key].value},labFilters);
  changed({source:key});
}
function enableRepair(enabled) {
  repairEnabled=enabled;
  if(enabled && track.analysis?.kind==='band') state.restore.enabled=false;
  if(!enabled && player.region) player.setRegion(null);
}
function listenToRepair() {
  if(!track || loading) return;
  if(auditionFor?.source==='repair') {cancelAudition();return}
  if(player.region) {player.setRegion(null); if(!player.playing) togglePlay(); return}
  const eligible=repairKinds.includes(track.analysis?.kind);
  if(!eligible && !filters.some(f=>state[f.key].enabled)) return;
  player.context().resume().catch(()=>{});
  if(eligible) enableRepair(true);
  changed({source:'repair',region:track.analysis?.preview});
}

function historyRemoved(ids,settings) {
  const matches=other=>!!other && Object.keys(settings).every(key=>settings[key]===other[key]);
  const pending=loading && ids.includes(requestedTrackId) && (!settings || matches(requestedVersion?.recipe));
  if(pending) {
    loadSerial++;loadRequest?.abort();loading=false;requestedTrackId=null;requestedVersion=null;requestedTrackName='';
  }
  if(!track || !ids.includes(track.id)) {
    if(pending) {
      if(track) {drawFilters();queueRender(true)} else showEmptyTrack();
    }
    return;
  }
  cache.clear();
  if(settings) {
    if(renderedKey && matches(JSON.parse(renderedKey))) {master=null;renderedKey=''}
    if(!matches(recipe())) return;
    clearTimeout(renderTimer);activeRender?.controller.abort();activeRender=null;
    auditionFor=null;player.pause();player.setRegion(null);
    setRecipe({});repairEnabled=false;preferred='original';master=null;renderedKey='';
    player.setRendered(null,null,'original');drawFilters();queueRender(true);
  } else {
    releaseTrack();
    if(!loading) requestedTrackName='';
    showEmptyTrack();
  }
}
const libraryUI=setupHistory({
  request,removed:historyRemoved,
  describeRecipe(settings) {
    const names=filters.filter(f=>settings[f.key]>0).map(f=>f.name+' '+settings[f.key]+'%');
    if(settings.repair) names.unshift('진단 복원');
    return names.join(' + ') || '필터 미적용';
  },
  async openTrack(row,version) {
    const opened=await loadTrack('/api/studio/history/'+row.id+'/open',{method:'POST'},row.name,version,row.id);
    if(opened && location.hash!=='#studio') location.hash='#studio';
    return opened;
  }
});
buildFilters(); paintIcons(); page();
document.querySelector('.skip').onclick=e=>{e.preventDefault();$('main').focus()};
$('upload').onclick=()=>$('file-input').click();
$('file-input').onchange=e=>{selectFile(e.target.files[0]);e.target.value=''};
$('play').onclick=togglePlay;
$('loop').onclick=()=>player.changeLoop();
$('seek').oninput=e=>{auditionFor=null; player.seek(player.duration*Number(e.target.value)/1000)};
$('match').onclick=()=>{player.levelMatch=!player.levelMatch;player.setMode(player.mode)};
$('mute').onclick=()=>{player.muted=!player.muted;player.updateVolume();refreshTransport()};
$('volume').oninput=e=>{player.volume=Number(e.target.value)/100;player.muted=false;player.updateVolume();refreshTransport()};
for(const b of all('[data-mode]')) b.onclick=()=>chooseMode(b.dataset.mode);
$('recommend').onclick=listenToRepair;
$('repair-toggle').onchange=e=>{enableRepair(e.target.checked);changed()};
$('reset').onclick=()=>{enableRepair(false);setRecipe({},restorationFilters);changed()};
$('lab-reset').onclick=()=>{setRecipe({},labFilters);changed()};
$('export').onclick=saveMaster;
$('split').onclick=splitTrack;
$('notice').querySelector('button').onclick=()=>message('');
for(const part of ['vocals','instrumental']) {
  $(part+'-audio').onplay=()=>{
    if(auditionFor) {auditionFor=null;preferred=player.mode}
    if(player.playing || player.pendingStart) player.pause();
    $(part==='vocals'?'instrumental-audio':'vocals-audio').pause();
    refreshTransport();
  };
  $(part+'-audio').onpause=refreshComparison;
}
for(const el of all('[data-open]')) {
  el.setAttribute('aria-label',el.textContent.trim());
  el.onclick=()=>$(el.dataset.open).showModal();
}
for(const el of all('[data-close]')) el.onclick=()=>el.closest('dialog').close();
for(const dialog of all('dialog')) dialog.onclick=e=>{if(e.target===dialog) dialog.close()};
for(const el of all('[data-example]')) el.onclick=()=>{$('examples').close();loadTrack('/api/studio/examples/'+el.dataset.example,{},el.querySelector('b').textContent)};
window.addEventListener('hashchange',page);
document.addEventListener('keydown',e=>{
  if(e.repeat || e.altKey || e.ctrlKey || e.metaKey || document.querySelector('dialog[open]') || e.target.closest('input,textarea,select,[contenteditable="true"]')) return;
  if(e.code==='Space' && !e.target.closest('button,a') && player.original){e.preventDefault();togglePlay()}
  if(e.code==='KeyA') chooseMode('original');
  if(e.code==='KeyB') chooseMode('processed');
});
let dragDepth=0;
window.addEventListener('dragenter',e=>{if(Array.from(e.dataTransfer.types).includes('Files')){dragDepth++;$('drop-overlay').hidden=false;e.preventDefault()}});
window.addEventListener('dragover',e=>{if(Array.from(e.dataTransfer.types).includes('Files'))e.preventDefault()});
window.addEventListener('dragleave',()=>{dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)$('drop-overlay').hidden=true});
window.addEventListener('drop',e=>{e.preventDefault();dragDepth=0;$('drop-overlay').hidden=true;selectFile(e.dataTransfer.files[0])});
const resize=new ResizeObserver(()=>{drawTimeline();drawFilters()});
resize.observe($('waveform')); resize.observe($('filters')); resize.observe($('lab-filters'));
request('/api/studio/health').then(()=>engine(true)).catch(()=>engine(false));
const requestedExample=new URLSearchParams(location.search).get('example');
const exampleKey=['midnight','compressed'].includes(requestedExample)?requestedExample:'clipped';
if(location.hash==='#history') showEmptyTrack();
else loadTrack('/api/studio/examples/'+exampleKey);
