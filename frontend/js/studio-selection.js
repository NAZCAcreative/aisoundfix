// Pointer selection and numeric entry share the same source-time coordinates.
export function setupSelection({duration, select, seek, message}) {
  const byId=id=>document.getElementById(id);
  const wave=byId('seek'), marker=byId('repair-range');
  const startInput=byId('region-start'), endInput=byId('region-end');
  let drag=null;
  function show(range) {
    marker.hidden=!range;
    if(!range || !duration()) return;
    marker.style.left=(100*range.start/duration())+'%';
    marker.style.width=(100*(range.end-range.start)/duration())+'%';
  }
  function at(x) {
    const box=wave.getBoundingClientRect();
    return Math.min(duration(), Math.max(0, (x-box.left)/box.width*duration()));
  }
  function ordered(a,b) {return {start: Math.min(a,b), end: Math.max(a,b)}}
  function reset(available,range) {
    // A new track can arrive while a pointer is held on the previous one.
    drag=null;
    for(const input of [startInput,endInput]) {
      input.max=available?String(duration()):'';
      input.disabled=!available;
    }
    startInput.value=range?.start ?? (available?0:'');
    endInput.value=range?.end ?? (available?duration():'');
    byId('region-select').disabled=!available;
    byId('region-clear').disabled=!available || !range;
  }
  wave.addEventListener('pointerdown',event=>{
    if(wave.disabled || !event.isPrimary || event.button!==0) return;
    event.preventDefault();
    wave.focus();
    drag={id:event.pointerId,x:event.clientX,start:at(event.clientX)};
    wave.setPointerCapture(event.pointerId);
  });
  wave.addEventListener('pointermove',event=>{
    if(drag?.id===event.pointerId && Math.abs(drag.x-event.clientX)>=4) {
      show(ordered(drag.start,at(event.clientX)));
    }
  });
  wave.addEventListener('pointerup',event=>{
    if(drag?.id!==event.pointerId) return;
    const {x,start}=drag, end=at(event.clientX);
    drag=null;
    if(Math.abs(x-event.clientX)<4 || start===end) seek(end);
    else select(ordered(start,end));
  });
  wave.addEventListener('lostpointercapture',()=>{if(drag){drag=null; show(currentMarker)}});
  byId('region-select').onclick=()=>{
    const start=startInput.valueAsNumber, end=endInput.valueAsNumber;
    if(!Number.isFinite(start) || !Number.isFinite(end) || start<0 || end<=start || end>duration()) {
      message('0초부터 곡 끝 사이에서 시작보다 늦은 끝 시간을 입력하세요.');
      return;
    }
    select({start,end});
  };
  byId('region-clear').onclick=()=>select(null);
  let currentMarker=null;
  return {reset, mark(range) {currentMarker=range; if(!drag) show(range)}};
}
