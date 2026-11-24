const $ = id => document.getElementById(id);
const base = '/api/studio/history';
const date = new Intl.DateTimeFormat('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});

function bytes(value) {
  if(value<1000) return value+' B';
  if(value<1000000) return (value/1000).toFixed(1)+' KB';
  if(value<1000000000) return (value/1000000).toFixed(1)+' MB';
  return (value/1000000000).toFixed(2)+' GB';
}
function element(tag,text,style) {
  const node=document.createElement(tag);
  if(text) node.textContent=text;
  if(style) node.className=style;
  return node;
}

export function setupHistory({request,openTrack,removed,describeRecipe}) {
  const dialog=$('history'), confirm=$('history-confirm'), list=$('history-list');
  const channel=typeof BroadcastChannel==='function' ? new BroadcastChannel('studio-history') : null;
  const choices=new Map();
  let rows=[], serial=0, pending=null, deleting=false;
  function notice(text='') {
    $('history-message').textContent=text;
    $('history-message').hidden=!text;
  }
  function notifyRemoval(ids,recipe=null) {
    removed(ids,recipe);
    channel?.postMessage({ids,recipe});
  }
  function ask(items,version=null) {
    if(deleting || !items.length) return;
    pending={items,version};
    const title=version?'보정본 삭제':items.length===1?'작업 삭제':'작업 전체 삭제';
    const label=items.length===1?'‘'+items[0].name+'’':items.length+'개 작업';
    const size=version?version.bytes:items.reduce((total,row)=>total+row.bytes,0);
    $('confirm-title').textContent=title;
    $('confirm-detail').textContent=version?
      label+'의 선택한 WAV 보정본과 설정('+bytes(size)+')을 삭제합니다.':
      label+'의 원본 사본, 보정본, 스템과 중간 파일('+bytes(size)+')을 스튜디오 저장소에서 삭제합니다. 이미 내려받은 파일은 다운로드 폴더에서 관리하세요.';
    confirm.showModal();
    $('confirm-cancel').focus();
  }
  function rowView(row) {
    const card=element('article',null,'history-row');
    card.dataset.id=row.id;
    card.append(element('h3',row.name));
    const saved=row.versions.length?'보정본 '+row.versions.length+'개':row.files.previous?'이전 결과 파일':'저장된 보정본 없음';
    const meta=[date.format(row.updatedAt*1000),row.format,bytes(row.bytes),saved].filter(Boolean);
    card.append(element('p',meta.join(' · '),'history-meta'));
    const actions=element('div',null,'history-actions');
    const select=element('select');
    const selected=()=>row.versions.find(v=>v.id===select.value);
    if(row.versions.length) {
      select.setAttribute('aria-label',row.name+' 보정 버전');
      for(const v of row.versions) select.add(new Option(date.format(v.createdAt*1000)+' · '+describeRecipe(v.recipe),v.id));
      if(row.versions.some(v=>v.id===choices.get(row.id))) select.value=choices.get(row.id);
      actions.append(select);
    }
    const open=element('button','다시 열기','history-open-track');
    open.disabled=!row.canOpen;
    open.onclick=async()=>{
      open.disabled=true;
      try {
        if(await openTrack(row,selected())) dialog.close();
        else notice('작업을 열지 못했습니다. 기록을 새로 불러오세요.');
      } finally {open.disabled=!row.canOpen}
    };
    actions.append(open);
    const prefix=base+'/'+row.id;
    if(row.versions.length) {
      const save=element('a','WAV 받기');
      const target=()=>{save.href=prefix+'/versions/'+select.value};
      save.download='';target();
      select.onchange=()=>{choices.set(row.id,select.value);target()};
      const remove=element('button','버전 삭제','history-danger');
      remove.onclick=()=>ask([row],selected());
      actions.append(save,remove);
    }
    for(const [part,format] of Object.entries(row.files)) {
      const link=element('a',({previous:'이전 결과',vocals:'보컬',instrumental:'반주'})[part]+' '+format);
      link.href=prefix+'/files/'+part;link.download='';actions.append(link);
    }
    const remove=element('button','작업 삭제','history-danger');
    remove.setAttribute('aria-label',row.name+' 작업 삭제');
    remove.onclick=()=>ask([row]);actions.append(remove);
    card.append(actions);
    return card;
  }
  async function refresh() {
    if(!dialog.open) return;
    const token=++serial;
    list.setAttribute('aria-busy','true');
    $('history-clear').disabled=true;
    try {
      const data=await (await request(base,{cache:'no-store'})).json();
      if(token!==serial || !dialog.open) return;
      rows=data.items;
      const regular=rows.filter(row=>!row.example), examples=rows.filter(row=>row.example);
      const expanded=list.querySelector('details')?.open || false;
      const content=document.createDocumentFragment();
      for(const row of regular) content.append(rowView(row));
      if(!regular.length) content.append(element('p','아직 보관 중인 내 음원이 없습니다.','history-empty'));
      if(examples.length) {
        const group=element('details',null,'history-examples');
        group.open=expanded;
        group.append(element('summary','예제 작업 파일 '+examples.length+'개'));
        for(const row of examples) group.append(rowView(row));
        content.append(group);
      }
      list.replaceChildren(content);
      const size=rows.reduce((total,row)=>total+row.bytes,0);
      $('history-summary').textContent=(data.local?'이 컴퓨터':'이 브라우저')+' · 내 작업 '+regular.length+'개 · 총 '+bytes(size);
      $('history-clear').disabled=!rows.length;
    } catch(err) {
      if(token===serial) {
        rows=[];list.replaceChildren();
        $('history-summary').textContent='기록을 불러오지 못했습니다.';
        notice(err.message);
        const retry=element('button','다시 불러오기','button quiet');
        retry.onclick=()=>{notice();refresh()};list.append(retry);
      }
    } finally {
      if(token===serial) list.setAttribute('aria-busy','false');
    }
  }
  function open() {
    if(!dialog.open) dialog.showModal();
    notice();refresh();
  }
  $('history-open').onclick=e=>{e.preventDefault();open()};
  $('history-clear').onclick=()=>ask([...rows]);
  $('confirm-cancel').onclick=()=>confirm.close();
  confirm.addEventListener('cancel',e=>{if(deleting)e.preventDefault()});
  $('confirm-remove').onclick=async()=>{
    if(!pending || deleting) return;
    const {items,version}=pending, ids=items.map(row=>row.id);
    deleting=true;
    $('confirm-remove').disabled=$('confirm-cancel').disabled=true;
    try {
      if(version) {
        await request(base+'/'+ids[0]+'/versions/'+version.id,{method:'DELETE'});
        choices.delete(ids[0]);notifyRemoval(ids,version.recipe);
        notice('선택한 보정본을 삭제했습니다.');
      } else {
        const result=await (await request(base+'/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})})).json();
        result.deleted.forEach(id=>choices.delete(id));
        if(result.deleted.length) notifyRemoval(result.deleted);
        notice(result.deleted.length+'개 작업을 삭제했습니다.'+(result.failed.length?' '+result.failed.length+'개는 삭제할 수 없습니다. 사용 중인 작업이 끝나면 다시 시도하세요.':''));
      }
    } catch(err) {notice(err.message)}
    finally {
      pending=null;deleting=false;$('confirm-remove').disabled=$('confirm-cancel').disabled=false;
      if(confirm.open) confirm.close();
      await refresh();
    }
  };
  dialog.addEventListener('close',()=>{
    serial++;
    if(location.hash==='#history') history.replaceState(null,'','#studio');
  });
  if(channel) channel.onmessage=e=>{
    if(Array.isArray(e.data?.ids)) removed(e.data.ids,e.data.recipe);
    refresh();
  };
  window.addEventListener('focus',()=>{if(!confirm.open)refresh()});
  return {open,refresh};
}
