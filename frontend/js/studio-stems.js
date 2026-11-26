export function setupStemPair({loadTrack, request, message, getTrack, recipe}) {
  const form = document.getElementById('stem-pair-form');
  const open = document.getElementById('stem-pair-open');
  const status = document.getElementById('stem-pair-status');
  const save = document.getElementById('stem-vocal-export');
  const mixSave = document.getElementById('export');
  const inputs = [form.elements.vocals, form.elements.instrumental];
  let importing = false;
  let download = null;

  function fileError(file) {
    if (!file) return '';
    if (!/\.wav$/i.test(file.name)) return '보컬과 반주 모두 WAV 파일을 선택하세요.';
    if (!file.size) return '비어 있는 파일입니다. 다른 WAV를 선택하세요.';
    if (file.size > 100 * 1024 * 1024) return '파일당 최대 100 MB까지 불러올 수 있습니다.';
    return '';
  }
  function checkFiles() {
    const files = inputs.map(input => input.files[0]);
    const error = files.map(fileError).find(Boolean);
    open.disabled = importing || !!error || files.some(file => !file);
    status.textContent = importing ? '보컬과 반주를 불러오는 중…' : error || 'WAV 파일당 최대 100 MB';
    for (const input of inputs) input.disabled = importing;
  }
  form.onchange = checkFiles;
  function acceptDrop(target, files) {
    if (!form.contains(target)) return false;
    const input = target.closest('label')?.querySelector('input[type="file"]');
    if (!importing && input && files.length === 1) {
      input.files = files;
      checkFiles();
    } else if (!importing) {
      status.textContent = '보컬 WAV와 반주 WAV를 각각 해당 칸에 놓으세요.';
    }
    return true;
  }
  form.onsubmit = async event => {
    event.preventDefault();
    checkFiles();
    if (open.disabled) return;
    const name = inputs[0].files[0].name;
    const data = new FormData(form);
    importing = true;
    checkFiles();
    try {
      if (await loadTrack('/api/studio/tracks/stem-pair', {method:'POST', body:data}, name)) {
        form.reset();
        location.hash = '#studio';
        document.getElementById('main').focus();
      }
    } finally {
      importing = false;
      checkFiles();
    }
  };

  function refresh() {
    const track = getTrack();
    if (download && (mixSave.disabled || track?.id !== download.id || JSON.stringify(recipe()) !== download.settings)) {
      download.controller.abort();
    }
    save.hidden = !track?.stemPair;
    save.disabled = save.hidden || mixSave.disabled || !!download;
    save.textContent = download ? '보컬 WAV 준비 중…' : '보컬 WAV 저장';
  }
  save.onclick = async () => {
    if (save.disabled) return;
    const track = getTrack(), settings = recipe();
    const controller = new AbortController();
    download = {controller, id:track.id, settings:JSON.stringify(settings)};
    refresh();
    try {
      const response = await request('/api/studio/tracks/'+track.id+'/render?preview=true', {
        method:'POST', headers:{'Content-Type':'application/json'}, signal:controller.signal,
        body:JSON.stringify({...settings, output:'vocals'})
      });
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = track.name.replace(/[\\/:*?"<>|]/g,'-')+' - 보컬.wav';
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    } catch (error) {
      if (!controller.signal.aborted) message(error.message);
    } finally {
      download = null;
      refresh();
    }
  };
  checkFiles();
  return {refresh, acceptDrop};
}
