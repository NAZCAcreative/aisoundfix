class UploadController {
  constructor(options = {}) {
    this.maxSizeBytes = 100 * 1024 * 1024;
    this.allowedExtensions = ['.mp3', '.wav', '.flac', '.m4a'];
    this.selectedFile = null;
    this.selectedPipeline = 'lite';
    this.onFileSelect = options.onFileSelect || (() => {});
    this.onError = options.onError || (() => {});
    this.initDOMReferences();
    this.bindEvents();
  }

  initDOMReferences() {
    this.dropZone = document.getElementById('dropZone');
    this.fileInput = document.getElementById('fileInput');
    this.selectedCard = document.getElementById('selectedFileCard');
    this.fileNameEl = document.getElementById('selectedFileName');
    this.fileSizeEl = document.getElementById('selectedFileSize');
    this.tierCards = document.querySelectorAll('#tierRadioGroup .tier-radio-card');
  }

  bindEvents() {
    if (!this.dropZone) return;
    this.dropZone.addEventListener('click', () => this.fileInput.click());
    this.fileInput.addEventListener('change', (e) => {
      if (e.target.files.length) this.handleFileSelected(e.target.files[0]);
    });

    this.tierCards.forEach(card => {
      card.addEventListener('click', () => {
        this.tierCards.forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
        this.selectedPipeline = card.querySelector('input').value;
      });
    });
  }

  handleFileSelected(file) {
    if (file.size > this.maxSizeBytes) {
      this.onError('파일 용량이 100MB 제한을 초과했습니다.');
      return;
    }
    this.selectedFile = file;
    this.dropZone.style.display = 'none';
    this.selectedCard.style.display = 'flex';
    if (this.fileNameEl) this.fileNameEl.textContent = file.name;
    if (this.fileSizeEl) this.fileSizeEl.textContent = (file.size / 1024 / 1024).toFixed(1) + ' MB';
    this.onFileSelect(file);
  }

  clearSelectedFile() {
    this.selectedFile = null;
    this.fileInput.value = '';
    this.dropZone.style.display = 'flex';
    this.selectedCard.style.display = 'none';
    this.onFileSelect(null);
  }

  getFormData() {
    if (!this.selectedFile) return null;
    const fd = new FormData();
    fd.append('file', this.selectedFile);
    fd.append('pipeline', this.selectedPipeline);
    return fd;
  }
}

window.UploadController = UploadController;
