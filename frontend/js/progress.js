class ProgressController {
  constructor() {
    this.orbFill = document.getElementById('orbFill');
    this.orbText = document.getElementById('orbText');
    this.checklistContainer = document.getElementById('stageChecklist');
  }

  renderStages(stages) {
    if (!this.checklistContainer) return;
    this.checklistContainer.innerHTML = stages.map((s, idx) => `
      <div id="stg-${idx}" class="stage-item waiting">
        <span>${s}</span>
        <span class="stg-icon"></span>
      </div>
    `).join('');
  }

  updateProgress(data) {
    const { progress, currentStageIndex, stages } = data;
    const percent = Math.round(progress * 100);
    if (this.orbFill) this.orbFill.style.height = `${percent}%`;
    if (this.orbText) this.orbText.textContent = `${percent}%`;

    if (stages) {
      stages.forEach((_, idx) => {
        const item = document.getElementById(`stg-${idx}`);
        if (!item) return;
        if (idx < currentStageIndex) item.className = 'stage-item completed';
        else if (idx === currentStageIndex) item.className = 'stage-item active';
        else item.className = 'stage-item waiting';
      });
    }
  }
}

window.ProgressController = ProgressController;
