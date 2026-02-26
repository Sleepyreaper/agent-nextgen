/**
 * video-upload.js – Chunked MP4 upload to Azure Blob Storage
 *
 * When a user selects (or drags) an .mp4 file the uploader:
 *   1. Slices the file into ≤4 MB chunks
 *   2. POSTs each chunk to /api/video/upload-chunk
 *   3. After the last chunk the server commits the block list
 *   4. The blob path is stored in a hidden <input> so the regular
 *      form POST can tell the server where to find the video.
 *
 * Usage (in the template):
 *   <script src="{{ url_for('static', filename='js/video-upload.js') }}"></script>
 *   <script>
 *     VideoUpload.init({
 *       fileInputId:  'fileInput',
 *       formId:       'uploadForm',
 *       progressId:   'videoProgress',
 *       progressBarId:'videoProgressBar',
 *       progressTextId:'videoProgressText',
 *       hiddenFieldId:'videoBlobInfo',
 *       appTypeGetter: () => document.querySelector('input[name="app_type"]:checked')?.value || '2026'
 *     });
 *   </script>
 */
const VideoUpload = (() => {
  const CHUNK_SIZE = 4 * 1024 * 1024; // 4 MB per chunk

  let _cfg = {};
  let _pendingVideos = []; // [{file, uploadId, blobPath, container, status}]

  function _uuid() {
    return 'xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = (Math.random() * 16) | 0;
      return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  /* ── Upload a single video file in chunks ────────────────────── */
  async function _uploadVideo(entry, onProgress) {
    const file = entry.file;
    const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
    const appType = _cfg.appTypeGetter ? _cfg.appTypeGetter() : '2026';

    for (let i = 0; i < totalChunks; i++) {
      const start = i * CHUNK_SIZE;
      const end = Math.min(start + CHUNK_SIZE, file.size);
      const chunk = file.slice(start, end);

      const fd = new FormData();
      fd.append('chunk', chunk, file.name);
      fd.append('upload_id', entry.uploadId);
      fd.append('chunk_index', i);
      fd.append('total_chunks', totalChunks);
      fd.append('filename', file.name);
      fd.append('app_type', appType);

      let retries = 3;
      let resp;
      while (retries > 0) {
        try {
          resp = await fetch('/api/video/upload-chunk', {
            method: 'POST',
            body: fd,
          });
          if (resp.ok) break;
        } catch (_) { /* retry */ }
        retries--;
        if (retries > 0) await new Promise(r => setTimeout(r, 1000));
      }

      if (!resp || !resp.ok) {
        const errText = resp ? await resp.text() : 'Network error';
        throw new Error(`Chunk ${i}/${totalChunks} failed: ${errText}`);
      }

      const data = await resp.json();
      onProgress(data.progress || 0);

      if (data.complete) {
        entry.blobPath = data.blob_path;
        entry.container = data.container;
        entry.status = 'done';
      }
    }
  }

  /* ── Upload ALL pending videos sequentially ──────────────────── */
  async function _uploadAllVideos() {
    if (_pendingVideos.length === 0) return true;

    const progressEl = document.getElementById(_cfg.progressId);
    const barEl = document.getElementById(_cfg.progressBarId);
    const textEl = document.getElementById(_cfg.progressTextId);
    if (progressEl) progressEl.style.display = 'block';

    for (let idx = 0; idx < _pendingVideos.length; idx++) {
      const entry = _pendingVideos[idx];
      const label = _pendingVideos.length > 1
        ? `Video ${idx + 1}/${_pendingVideos.length}: ${entry.file.name}`
        : entry.file.name;

      if (textEl) textEl.textContent = `Uploading ${label}…`;

      try {
        await _uploadVideo(entry, pct => {
          if (barEl) {
            barEl.style.width = `${pct}%`;
            barEl.textContent = `${Math.round(pct)}%`;
          }
        });
      } catch (err) {
        if (textEl) textEl.textContent = `❌ Upload failed: ${err.message}`;
        return false;
      }
    }

    if (textEl) textEl.textContent = '✅ Video uploaded – submitting form…';
    return true;
  }

  /* ── Intercept form submit ───────────────────────────────────── */
  function _onSubmit(e) {
    if (_pendingVideos.length === 0) return; // no videos → normal submit

    // If any video is not yet uploaded, block and upload first
    const allDone = _pendingVideos.every(v => v.status === 'done');
    if (allDone) {
      _injectHiddenField();
      return; // let the form submit normally
    }

    e.preventDefault();
    const form = e.target;
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '⏳ Uploading video…';
    }

    _uploadAllVideos().then(ok => {
      if (ok) {
        _injectHiddenField();
        _stripVideoFiles();
        form.submit();
      } else {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = '📥 Upload File';
        }
      }
    });
  }

  /* ── Inject blob info into a hidden field ────────────────────── */
  function _injectHiddenField() {
    let hidden = document.getElementById(_cfg.hiddenFieldId);
    if (!hidden) {
      hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = 'video_blob_info';
      hidden.id = _cfg.hiddenFieldId;
      const form = document.getElementById(_cfg.formId);
      if (form) form.appendChild(hidden);
    }
    const info = _pendingVideos
      .filter(v => v.status === 'done')
      .map(v => ({
        upload_id: v.uploadId,
        filename: v.file.name,
        blob_path: v.blobPath,
        container: v.container,
      }));
    hidden.value = JSON.stringify(info);
  }

  /* ── Remove video files from the <input type=file> ───────────── */
  function _stripVideoFiles() {
    const input = document.getElementById(_cfg.fileInputId);
    if (!input || !input.files) return;
    const dt = new DataTransfer();
    for (const f of input.files) {
      if (!f.name.toLowerCase().endsWith('.mp4')) {
        dt.items.add(f);
      }
    }
    input.files = dt.files;
  }

  /* ── Detect video files on input change ──────────────────────── */
  function _onFileChange() {
    const input = document.getElementById(_cfg.fileInputId);
    if (!input || !input.files) return;

    _pendingVideos = [];
    const progressEl = document.getElementById(_cfg.progressId);
    if (progressEl) progressEl.style.display = 'none';

    for (const f of input.files) {
      if (f.name.toLowerCase().endsWith('.mp4')) {
        _pendingVideos.push({
          file: f,
          uploadId: _uuid(),
          blobPath: null,
          container: null,
          status: 'pending',
        });
      }
    }

    // Update the size hint when videos are present
    if (_pendingVideos.length > 0) {
      const totalMB = _pendingVideos.reduce((s, v) => s + v.file.size, 0) / (1024 * 1024);
      const hint = document.getElementById('videoSizeHint');
      if (hint) {
        hint.textContent = `🎬 ${_pendingVideos.length} video${_pendingVideos.length > 1 ? 's' : ''} (${totalMB.toFixed(1)} MB) – will upload to cloud storage`;
        hint.style.display = 'block';
      }
    }
  }

  /* ── Public init ─────────────────────────────────────────────── */
  function init(cfg) {
    _cfg = cfg;
    const input = document.getElementById(cfg.fileInputId);
    if (input) input.addEventListener('change', _onFileChange);

    const form = document.getElementById(cfg.formId);
    if (form) form.addEventListener('submit', _onSubmit);
  }

  return { init };
})();
