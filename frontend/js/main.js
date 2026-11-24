document.addEventListener('DOMContentLoaded', () => {
  const landingView = document.getElementById('landingView');
  const toolView = document.getElementById('toolView');
  const steps = [1, 2, 3, 4].map(n => document.getElementById(`wizardStep${n}`));
  const stepNodes = [1, 2, 3, 4].map(n => document.getElementById(`stepNode${n}`));
  const wizardError = document.getElementById('wizardError');
  const btnGoToStep2 = document.getElementById('btnGoToStep2');
  const btnRemoveFile = document.getElementById('btnRemoveFile');
  const btnStartRefine = document.getElementById('btnStartRefine');
  const btnRunApollo = document.getElementById('btnRunApollo');
  const apolloStatus = document.getElementById('apolloStatus');
  const btnRunStemSeparate = document.getElementById('btnRunStemSeparate');
  const stemStatus = document.getElementById('stemStatus');
  const stemPlayersWrap = document.getElementById('stemPlayersWrap');
  const audioVocals = document.getElementById('audioVocals');
  const audioInstrumental = document.getElementById('audioInstrumental');
  const btnRunUpgradeV1 = document.getElementById('btnRunUpgradeV1');
  const upgradeV1Status = document.getElementById('upgradeV1Status');
  const btnRunUpgradeV2 = document.getElementById('btnRunUpgradeV2');
  const upgradeV2Status = document.getElementById('upgradeV2Status');
  const btnRunUpgradeV3 = document.getElementById('btnRunUpgradeV3');
  const upgradeV3Status = document.getElementById('upgradeV3Status');
  const btnRunUpgradeV4 = document.getElementById('btnRunUpgradeV4');
  const upgradeV4Status = document.getElementById('upgradeV4Status');
  const presetCards = document.querySelectorAll('#presetRadioGroup .tier-radio-card');

  // Swaps only the leading icon to a checkmark so the technique description
  // stays visible after completion instead of being replaced by generic text.
  function markDone(btn, initialText) {
    btn.textContent = initialText.replace(/^\S+/, '✅');
  }

  // Every future mastering/processing improvement should add its own entry
  // here (+ a matching button/status pair in index.html) rather than
  // replacing an existing version, so old and new can always be A/B'd.
  const UPGRADE_VERSIONS = {
    v1: {
      btn: btnRunUpgradeV1,
      status: upgradeV1Status,
      versionId: 'upgrade-v1',
      label: '업그레이드 v1',
      initialText: '🚀 업그레이드 v1 (Apollo 복원 + 블렌딩 + 마스터링)',
    },
    v2: {
      btn: btnRunUpgradeV2,
      status: upgradeV2Status,
      versionId: 'upgrade-v2',
      label: '업그레이드 v2',
      initialText: '🚀 업그레이드 v2 (+ 디에서 + Mid-Side 선명도/입체감)',
    },
    v3: {
      btn: btnRunUpgradeV3,
      status: upgradeV3Status,
      versionId: 'upgrade-v3',
      label: '업그레이드 v3',
      initialText: '🚀 업그레이드 v3 (v2 + 정제본 필터 오버레이)',
    },
    v4: {
      btn: btnRunUpgradeV4,
      status: upgradeV4Status,
      versionId: 'upgrade-v4',
      label: '업그레이드 v4',
      initialText: '🚀 업그레이드 v4 (v2 + 멀티밴드 컴프레션 + 하모닉 익사이터)',
    },
  };

  let selectedPreset = 'clear';
  let pollTimer = null;
  let apolloPollTimer = null;
  let stemPollTimer = null;
  let stemObjectUrls = [];
  const upgradePollTimers = {};

  const progressController = new ProgressController();
  const abPlayer = new ABPlayerController();
  const uploadController = new UploadController({
    onFileSelect: (file) => {
      btnGoToStep2.disabled = !file;
      hideError();
    },
    onError: (msg) => showError(msg),
  });

  function showError(msg) {
    wizardError.textContent = msg;
    wizardError.style.display = 'block';
  }

  function hideError() {
    wizardError.style.display = 'none';
  }

  function showView(view) {
    landingView.style.display = view === 'landing' ? '' : 'none';
    toolView.style.display = view === 'tool' ? '' : 'none';
    window.scrollTo(0, 0);
  }

  function showStep(n) {
    steps.forEach((el, idx) => { el.style.display = (idx + 1 === n) ? '' : 'none'; });
    stepNodes.forEach((el, idx) => {
      el.classList.remove('active', 'completed');
      if (idx + 1 < n) el.classList.add('completed');
      else if (idx + 1 === n) el.classList.add('active');
    });
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  function stopApolloPolling() {
    if (apolloPollTimer) clearInterval(apolloPollTimer);
    apolloPollTimer = null;
  }

  function stopStemPolling() {
    if (stemPollTimer) clearInterval(stemPollTimer);
    stemPollTimer = null;
  }

  function stopUpgradePolling(version) {
    if (upgradePollTimers[version]) clearInterval(upgradePollTimers[version]);
    upgradePollTimers[version] = null;
  }

  function resetWizard() {
    stopPolling();
    stopApolloPolling();
    stopStemPolling();
    Object.keys(UPGRADE_VERSIONS).forEach(v => {
      stopUpgradePolling(v);
      const cfg = UPGRADE_VERSIONS[v];
      cfg.btn.disabled = false;
      cfg.btn.textContent = cfg.initialText;
      cfg.status.style.display = 'none';
    });
    uploadController.clearSelectedFile();
    btnGoToStep2.disabled = true;
    abPlayer.stop();
    btnRunApollo.disabled = false;
    btnRunApollo.textContent = '🧬 실제 Apollo AI로 처리해서 비교하기';
    apolloStatus.style.display = 'none';
    btnRunStemSeparate.disabled = false;
    btnRunStemSeparate.textContent = '🎛️ 보컬 · 반주 분리해서 따로 듣기';
    stemStatus.style.display = 'none';
    stemPlayersWrap.style.display = 'none';
    audioVocals.pause();
    audioInstrumental.pause();
    audioVocals.removeAttribute('src');
    audioInstrumental.removeAttribute('src');
    stemObjectUrls.forEach(url => URL.revokeObjectURL(url));
    stemObjectUrls = [];
    hideError();
    showStep(1);
  }

  document.getElementById('btnHeroCta').addEventListener('click', () => { showView('tool'); showStep(1); });
  document.getElementById('btnHeaderCta').addEventListener('click', () => { showView('tool'); showStep(1); });
  document.getElementById('brandLogo').addEventListener('click', () => { resetWizard(); showView('landing'); });
  document.getElementById('btnReturnToLanding').addEventListener('click', () => { resetWizard(); showView('landing'); });

  btnGoToStep2.addEventListener('click', () => showStep(2));
  document.getElementById('btnBackToStep1').addEventListener('click', () => showStep(1));
  document.getElementById('btnRestartWizard').addEventListener('click', () => resetWizard());

  btnRemoveFile.addEventListener('click', () => {
    uploadController.clearSelectedFile();
    btnGoToStep2.disabled = true;
  });

  presetCards.forEach(card => {
    card.addEventListener('click', () => {
      presetCards.forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      selectedPreset = card.querySelector('input').value;
    });
  });

  btnStartRefine.addEventListener('click', async () => {
    const formData = uploadController.getFormData();
    if (!formData) { showError('먼저 음원 파일을 선택해주세요.'); showStep(1); return; }
    formData.append('preset', selectedPreset);

    hideError();
    btnStartRefine.disabled = true;
    try {
      const job = await window.RefineryAPI.createJob(formData);
      if (job.status === 'error') throw new Error(job.error || '작업 생성에 실패했습니다.');
      showStep(3);
      progressController.updateProgress({ progress: 0, currentStageIndex: 0, stages: [] });
      pollJob(job.id);
    } catch (err) {
      showError(err.message || '작업 생성 중 오류가 발생했습니다.');
    } finally {
      btnStartRefine.disabled = false;
    }
  });

  function pollJob(jobId) {
    let stagesRendered = false;
    stopPolling();
    pollTimer = setInterval(async () => {
      try {
        const data = await window.RefineryAPI.getJobStatus(jobId);
        if (data.status === 'error') {
          stopPolling();
          showError(data.error || '처리 중 오류가 발생했습니다.');
          showStep(2);
          return;
        }
        if (!stagesRendered && data.stages) {
          progressController.renderStages(data.stages);
          stagesRendered = true;
        }
        progressController.updateProgress(data);
        if (data.status === 'done') {
          stopPolling();
          await abPlayer.loadFile(uploadController.selectedFile);
          showStep(4);
        }
      } catch (err) {
        stopPolling();
        showError('상태 확인 중 오류가 발생했습니다.');
      }
    }, 1500);
  }

  btnRunApollo.addEventListener('click', async () => {
    const file = uploadController.selectedFile;
    if (!file) return;

    btnRunApollo.disabled = true;
    apolloStatus.style.display = 'block';
    apolloStatus.textContent = '실제 Apollo AI로 업로드 중...';

    const formData = new FormData();
    formData.append('file', file);
    formData.append('pipeline', 'lite');
    formData.append('preset', selectedPreset);

    try {
      const job = await window.RefineryAPI.createRealJob(formData);
      if (job.status === 'error') throw new Error(job.error || '실제 처리 작업 생성에 실패했습니다.');
      pollApolloJob(job.id);
    } catch (err) {
      apolloStatus.textContent = err.message || '실제 처리 중 오류가 발생했습니다.';
      btnRunApollo.disabled = false;
    }
  });

  function pollApolloJob(jobId) {
    stopApolloPolling();
    apolloPollTimer = setInterval(async () => {
      try {
        const data = await window.RefineryAPI.getRealJobStatus(jobId);
        if (data.status === 'error') {
          stopApolloPolling();
          apolloStatus.textContent = data.error || '실제 처리 중 오류가 발생했습니다.';
          btnRunApollo.disabled = false;
          return;
        }
        apolloStatus.textContent = `실제 Apollo AI 처리 중... ${data.stage} (${Math.round((data.progress || 0) * 100)}%)`;
        if (data.status === 'done') {
          stopApolloPolling();
          const res = await fetch(window.RefineryAPI.getRealResultUrl(jobId));
          const arrayBuffer = await res.arrayBuffer();
          await abPlayer.loadExtraBuffer('apollo', 'Apollo(실제)', arrayBuffer);
          abPlayer.setMode('apollo');
          apolloStatus.textContent = '완료! "Apollo(실제)" 탭에서 비교해보세요.';
          markDone(btnRunApollo, '🧬 실제 Apollo AI로 처리해서 비교하기');
        }
      } catch (err) {
        stopApolloPolling();
        apolloStatus.textContent = '상태 확인 중 오류가 발생했습니다. (백엔드 서버가 켜져 있는지 확인하세요)';
        btnRunApollo.disabled = false;
      }
    }, 1500);
  }

  btnRunStemSeparate.addEventListener('click', async () => {
    const file = uploadController.selectedFile;
    if (!file) return;

    btnRunStemSeparate.disabled = true;
    stemStatus.style.display = 'block';
    stemStatus.textContent = '보컬·반주 분리를 위해 업로드 중...';

    const formData = new FormData();
    formData.append('file', file);

    try {
      const job = await window.RefineryAPI.createStemJob(formData);
      if (job.status === 'error') throw new Error(job.error || '분리 작업 생성에 실패했습니다.');
      pollStemJob(job.id);
    } catch (err) {
      stemStatus.textContent = err.message || '분리 작업 중 오류가 발생했습니다.';
      btnRunStemSeparate.disabled = false;
    }
  });

  function pollStemJob(jobId) {
    stopStemPolling();
    stemPollTimer = setInterval(async () => {
      try {
        const data = await window.RefineryAPI.getStemJobStatus(jobId);
        if (data.status === 'error') {
          stopStemPolling();
          stemStatus.textContent = data.error || '분리 중 오류가 발생했습니다.';
          btnRunStemSeparate.disabled = false;
          return;
        }
        stemStatus.textContent = `분리 중... ${data.stage} (${Math.round((data.progress || 0) * 100)}%)`;
        if (data.status === 'done') {
          stopStemPolling();
          const [vocalsRes, instrumentalRes] = await Promise.all([
            fetch(window.RefineryAPI.getStemResultUrl(jobId, 'vocals')),
            fetch(window.RefineryAPI.getStemResultUrl(jobId, 'instrumental')),
          ]);
          const [vocalsBlob, instrumentalBlob] = await Promise.all([vocalsRes.blob(), instrumentalRes.blob()]);
          const vocalsUrl = URL.createObjectURL(vocalsBlob);
          const instrumentalUrl = URL.createObjectURL(instrumentalBlob);
          stemObjectUrls.push(vocalsUrl, instrumentalUrl);
          audioVocals.src = vocalsUrl;
          audioInstrumental.src = instrumentalUrl;
          stemPlayersWrap.style.display = 'block';
          stemStatus.textContent = '완료! 아래에서 각각 재생해보세요.';
          markDone(btnRunStemSeparate, '🎛️ 보컬 · 반주 분리해서 따로 듣기');
        }
      } catch (err) {
        stopStemPolling();
        stemStatus.textContent = '상태 확인 중 오류가 발생했습니다. (백엔드 서버가 켜져 있는지 확인하세요)';
        btnRunStemSeparate.disabled = false;
      }
    }, 1500);
  }

  function setupUpgradeVersion(version) {
    const cfg = UPGRADE_VERSIONS[version];
    cfg.btn.addEventListener('click', async () => {
      const file = uploadController.selectedFile;
      if (!file) return;

      cfg.btn.disabled = true;
      cfg.status.style.display = 'block';
      cfg.status.textContent = `${cfg.label}을(를) 위해 업로드 중...`;

      const formData = new FormData();
      formData.append('file', file);
      formData.append('preset', selectedPreset);

      try {
        const job = await window.RefineryAPI.createUpgradeJob(formData, version);
        if (job.status === 'error') throw new Error(job.error || '작업 생성에 실패했습니다.');
        pollUpgradeVersionJob(version, job.id);
      } catch (err) {
        cfg.status.textContent = err.message || '작업 중 오류가 발생했습니다.';
        cfg.btn.disabled = false;
      }
    });
  }

  function pollUpgradeVersionJob(version, jobId) {
    const cfg = UPGRADE_VERSIONS[version];
    stopUpgradePolling(version);
    upgradePollTimers[version] = setInterval(async () => {
      try {
        const data = await window.RefineryAPI.getUpgradeJobStatus(jobId, version);
        if (data.status === 'error') {
          stopUpgradePolling(version);
          cfg.status.textContent = data.error || '처리 중 오류가 발생했습니다.';
          cfg.btn.disabled = false;
          return;
        }
        cfg.status.textContent = `${cfg.label} 처리 중... ${data.stage} (${Math.round((data.progress || 0) * 100)}%)`;
        if (data.status === 'done') {
          stopUpgradePolling(version);
          const res = await fetch(window.RefineryAPI.getUpgradeResultUrl(jobId, version));
          const arrayBuffer = await res.arrayBuffer();
          await abPlayer.loadExtraBuffer(cfg.versionId, cfg.label, arrayBuffer);
          abPlayer.setMode(cfg.versionId);
          cfg.status.textContent = `완료! "${cfg.label}" 탭에서 비교해보세요.`;
          markDone(cfg.btn, cfg.initialText);
        }
      } catch (err) {
        stopUpgradePolling(version);
        cfg.status.textContent = '상태 확인 중 오류가 발생했습니다. (백엔드 서버가 켜져 있는지 확인하세요)';
        cfg.btn.disabled = false;
      }
    }, 1500);
  }

  Object.keys(UPGRADE_VERSIONS).forEach(setupUpgradeVersion);

  showStep(1);
  console.log("REFINERY frontend app initialized.");
});
