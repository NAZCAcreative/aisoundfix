export function toneNames(settings) {
  const names = [];
  if (settings.bits) names.push(settings.bits+'비트 양자화'+(settings.dither?' + 디더':''));
  if (settings.fullness) names.push('풍성함 '+settings.fullness+'%');
  if (settings.width) names.push('입체감 '+settings.width+'%');
  return names;
}

export function setupToneControls({adjust, apply, cancel}) {
  const byId = id => document.getElementById(id);
  const bits = byId('tone-bits'), dither = byId('tone-dither');
  byId('tone-quant').onclick = () => adjust({bits: Number(bits.value) ? 0 : 8, dither:false});
  bits.onchange = () => adjust({bits:Number(bits.value), dither:!!Number(bits.value) && dither.checked});
  dither.onchange = () => adjust({dither:dither.checked});
  for (const key of ['fullness', 'width']) {
    const slider = byId('tone-'+key+'-mix');
    byId('tone-'+key).onclick = () => adjust({[key]:Number(slider.value) ? 0 : 65});
    slider.oninput = () => adjust({[key]:Number(slider.value)});
  }
  byId('tone-apply').onclick = apply;
  byId('tone-cancel').onclick = cancel;

  return function draw(settings, available, stereo, draft, scope) {
    bits.value = settings.bits || 0;
    bits.disabled = byId('tone-quant').disabled = !available;
    byId('tone-quant').setAttribute('aria-pressed',String(!!settings.bits));
    dither.disabled = !available || !settings.bits;
    dither.checked = !!settings.bits && !!settings.dither;
    for (const key of ['fullness', 'width']) {
      const value = settings[key] || 0;
      const toggle = byId('tone-'+key), slider = byId('tone-'+key+'-mix');
      toggle.disabled = slider.disabled = !available || (key==='width' && !stereo);
      if (key==='width') toggle.title = stereo ? '중앙은 유지하고 좌우 폭을 넓힙니다.' : '스테레오 음원에서 사용할 수 있습니다.';
      toggle.setAttribute('aria-pressed',String(value > 0));
      slider.value = value;
      slider.style.setProperty('--fill',value+'%');
      slider.nextElementSibling.textContent = value+'%';
    }
    byId('tone-actions').hidden = !draft;
    byId('tone-apply').disabled = !draft?.result;
    if (draft) {
      byId('tone-status').textContent = scope+' · '+(draft.result ? draft.label : '미리듣기 준비 중…');
      byId('tone-apply').textContent = draft.settings.region ? '이 구간에만 적용' : '전체 곡에 적용';
    }
  };
}
