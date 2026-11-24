const DEMO = true;
const REAL_API_BASE = 'http://127.0.0.1:8000';
const STAGES_LITE = ["디코딩", "압축 아티팩트 복원", "마스터링", "인코딩"];
const STAGES_STANDARD = ["디코딩", "스템 분리·보컬 개선", "압축 아티팩트 복원", "마스터링", "인코딩"];

class RefineryAPI {
  static demoJobs = new Map();

  static async createRealJob(formData) {
    const res = await fetch(`${REAL_API_BASE}/api/jobs`, { method: 'POST', body: formData });
    return await res.json();
  }

  static async getRealJobStatus(jobId) {
    const res = await fetch(`${REAL_API_BASE}/api/jobs/${jobId}`);
    return await res.json();
  }

  static getRealResultUrl(jobId) {
    return `${REAL_API_BASE}/api/jobs/${jobId}/result`;
  }

  static async createStemJob(formData) {
    const res = await fetch(`${REAL_API_BASE}/api/stems`, { method: 'POST', body: formData });
    return await res.json();
  }

  static async getStemJobStatus(jobId) {
    const res = await fetch(`${REAL_API_BASE}/api/stems/${jobId}`);
    return await res.json();
  }

  static getStemResultUrl(jobId, stemType) {
    return `${REAL_API_BASE}/api/stems/${jobId}/${stemType}`;
  }

  // version: 'v1' -> /api/upgrade, 'v2' -> /api/upgrade-v2, etc. Each new
  // processing version gets its own endpoint suffix and its own path here.
  static _upgradeBase(version) {
    return version === 'v1' ? `${REAL_API_BASE}/api/upgrade` : `${REAL_API_BASE}/api/upgrade-${version}`;
  }

  static async createUpgradeJob(formData, version = 'v1') {
    const res = await fetch(this._upgradeBase(version), { method: 'POST', body: formData });
    return await res.json();
  }

  static async getUpgradeJobStatus(jobId, version = 'v1') {
    const res = await fetch(`${this._upgradeBase(version)}/${jobId}`);
    return await res.json();
  }

  static getUpgradeResultUrl(jobId, version = 'v1') {
    return `${this._upgradeBase(version)}/${jobId}/result`;
  }

  static async createJob(formData) {
    if (DEMO) return this._createDemoJob(formData);
    const res = await fetch('/api/jobs', { method: 'POST', body: formData });
    return await res.json();
  }

  static async getJobStatus(jobId) {
    if (DEMO) return this._getDemoJobStatus(jobId);
    const res = await fetch(`/api/jobs/${jobId}`);
    return await res.json();
  }

  static _createDemoJob(formData) {
    const pipeline = formData.get('pipeline') || 'lite';
    const jobId = 'job_' + Math.random().toString(36).substring(2, 9);
    const stages = pipeline === 'standard' ? STAGES_STANDARD : STAGES_LITE;

    this.demoJobs.set(jobId, {
      id: jobId,
      status: 'processing',
      pipeline,
      stages,
      currentStageIndex: 0,
      stage: stages[0],
      progress: 0.05,
      createdAt: Date.now(),
      totalDurationMs: pipeline === 'standard' ? 8000 : 4500
    });

    return Promise.resolve({ id: jobId, status: 'queued', stage: stages[0], progress: 0.0, pipeline });
  }

  static _getDemoJobStatus(jobId) {
    const job = this.demoJobs.get(jobId);
    if (!job) return Promise.resolve({ status: 'error', error: 'Job not found' });

    const elapsed = Date.now() - job.createdAt;
    const progressRatio = Math.min(1.0, elapsed / job.totalDurationMs);
    const stageIdx = Math.min(job.stages.length - 1, Math.floor(progressRatio * job.stages.length));

    job.progress = parseFloat(progressRatio.toFixed(2));
    job.currentStageIndex = stageIdx;
    job.stage = job.stages[stageIdx];
    if (progressRatio >= 1.0) job.status = 'done';

    return Promise.resolve({ ...job });
  }
}

window.RefineryAPI = RefineryAPI;
window.DEMO = DEMO;
