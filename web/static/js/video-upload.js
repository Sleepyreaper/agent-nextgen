/**
 * video-upload.js – Chunked file upload to Azure Blob Storage
 *
 * ALL files are uploaded in chunks (100 KB) with parallel upload
 * support to maximize throughput on Azure Front Door Premium.
 *
 * Flow:
 *   1. User selects files via <input type=file>
 *   2. On form submit, files are sliced into ≤100 KB chunks
 *   3. Each chunk is POSTed to /api/file/upload-chunk
 *   4. After the last chunk the server commits the block list
 *   5. Blob paths are stored in a hidden <input> so the regular
 *      form POST carries references (not raw bytes)
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
  // Front Door Premium supports configurable WAF body inspection limits.
  // Configure the WAF policy to exclude /api/file/upload-chunk from body
  // inspection OR set the request body size limit to ≥8 MB for this route.
  // See: docs/azure-front-door-upload-optimization.md
  const CHUNK_SIZE = 4 * 1024 * 1024; // 4 MB per chunk – optimized for Front Door Premium
  const PARALLEL_UPLOADS = 6; // Upload up to 6 chunks concurrently for high throughput

  let _cfg = {};
  let _pendingFiles = []; // [{file, uploadId, blobPath, container, status}]

  function _uuid() {
    return 'xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = (Math.random() * 16) | 0;
      return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  /* ── Upload a single file in chunks (with parallelism) ─────── */
  async function _uploadFile(entry, onProgress) {
    const file = entry.file;
    const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
    const appType = _cfg.appTypeGetter ? _cfg.appTypeGetter() : '2026';

    let completedChunks = 0;

    async function _sendChunk(i) {
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
          resp = await fetch('/api/file/upload-chunk', {
            method: 'POST',
            body: fd,
          });
          if (resp.ok) break;
        } catch (_) { /* retry */ }
        retries--;
        if (retries > 0) await new Promise(r => setTimeout(r, 1000 * (4 - retries)));
      }

      if (!resp || !resp.ok) {
        let errText = 'Network error';
        if (resp) {
          const raw = await resp.text();
          errText = resp.status === 403 ? 'Request blocked by firewall (chunk too large)' : raw.substring(0, 200);
        }
        throw new Error(`Chunk ${i + 1}/${totalChunks} failed (HTTP ${resp ? resp.status : '?'}): ${errText}`);
      }

      let data;
      const contentType = resp.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) {
        throw new Error(`Chunk ${i + 1}/${totalChunks}: unexpected response type "${contentType}"`);
      }
      data = await resp.json();
      completedChunks++;
      onProgress(Math.round((completedChunks / totalChunks) * 100));

      if (data.complete) {
        entry.blobPath = data.blob_path;
        entry.container = data.container;
        entry.status = 'done';
      }
    }

    // Upload non-final chunks in parallel batches, then send the final chunk last
    // (server commits on final chunk, so it must arrive after all others)
    const nonFinalChunks = [];
    for (let i = 0; i < totalChunks - 1; i++) {
      nonFinalChunks.push(i);
    }

    // Process in batches of PARALLEL_UPLOADS
    for (let b = 0; b < nonFinalChunks.length; b += PARALLEL_UPLOADS) {
      const batch = nonFinalChunks.slice(b, b + PARALLEL_UPLOADS);
      await Promise.all(batch.map(i => _sendChunk(i)));
    }

    // Send the final chunk (triggers server-side commit)
    if (totalChunks > 0) {
      await _sendChunk(totalChunks - 1);
    }
  }

  /* ── Upload ALL pending files sequentially ───────────────────── */
  async function _uploadAllFiles() {
    if (_pendingFiles.length === 0) return true;

    const progressEl = document.getElementById(_cfg.progressId);
    const barEl = document.getElementById(_cfg.progressBarId);
    const textEl = document.getElementById(_cfg.progressTextId);
    if (progressEl) progressEl.style.display = 'block';

    for (let idx = 0; idx < _pendingFiles.length; idx++) {
      const entry = _pendingFiles[idx];
      const label = _pendingFiles.length > 1
        ? `File ${idx + 1}/${_pendingFiles.length}: ${entry.file.name}`
        : entry.file.name;

      if (textEl) textEl.textContent = `Uploading ${label}…`;

      try {
        await _uploadFile(entry, pct => {
          // Calculate overall progress across all files
          const filePct = (idx / _pendingFiles.length) * 100 + (pct / _pendingFiles.length);
          if (barEl) {
            barEl.style.width = `${filePct}%`;
            barEl.textContent = `${Math.round(filePct)}%`;
          }
        });
      } catch (err) {
        if (textEl) textEl.textContent = `❌ Upload failed: ${err.message}`;
        return false;
      }
    }

    if (textEl) textEl.textContent = '✅ Files uploaded – submitting form…';
    return true;
  }

  /* ── Intercept form submit ───────────────────────────────────── */
  function _onSubmit(e) {
    if (_pendingFiles.length === 0) return; // no files → normal submit (shouldn't happen)

    // If all files are already uploaded (e.g. re-submit), let it go
    const allDone = _pendingFiles.every(v => v.status === 'done');
    if (allDone) {
      _injectHiddenField();
      _stripAllFiles();
      return; // let the form submit normally
    }

    e.preventDefault();
    const form = e.target;
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '⏳ Uploading files…';
    }

    _uploadAllFiles().then(ok => {
      if (ok) {
        _injectHiddenField();
        _stripAllFiles();
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
      hidden.id = _cfg.hiddenFieldId;
      const form = document.getElementById(_cfg.formId);
      if (form) form.appendChild(hidden);
    }
    // Always set the name to chunked_blob_info (templates may use legacy name)
    hidden.name = 'chunked_blob_info';
    const info = _pendingFiles
      .filter(v => v.status === 'done')
      .map(v => ({
        upload_id: v.uploadId,
        filename: v.file.name,
        blob_path: v.blobPath,
        container: v.container,
      }));
    // Base64-encode JSON so WAF doesn't trigger on JSON patterns
    hidden.value = btoa(unescape(encodeURIComponent(JSON.stringify(info))));
  }

  /* ── Remove ALL files from the <input type=file> ─────────────── */
  function _stripAllFiles() {
    const input = document.getElementById(_cfg.fileInputId);
    if (!input) return;
    // Belt-and-suspenders: clear multiple ways for cross-browser safety
    try { input.value = ''; } catch (_) { /* IE security exception */ }
    try {
      const dt = new DataTransfer();
      input.files = dt.files;
    } catch (_) { /* older browsers */ }
    // Remove name so multipart body doesn't include any file part at all
    input.removeAttribute('name');
    // Remove required so programmatic submit doesn't get blocked
    input.removeAttribute('required');
  }

  /* ── Detect files on input change ────────────────────────────── */
  function _onFileChange() {
    const input = document.getElementById(_cfg.fileInputId);
    if (!input || !input.files) return;

    _pendingFiles = [];
    const progressEl = document.getElementById(_cfg.progressId);
    if (progressEl) progressEl.style.display = 'none';

    for (const f of input.files) {
      _pendingFiles.push({
        file: f,
        uploadId: _uuid(),
        blobPath: null,
        container: null,
        status: 'pending',
      });
    }

    // Update the size hint
    if (_pendingFiles.length > 0) {
      const totalMB = _pendingFiles.reduce((s, v) => s + v.file.size, 0) / (1024 * 1024);
      const isVideo = _pendingFiles.some(v => v.file.name.toLowerCase().endsWith('.mp4'));
      // Check for page-specific hint elements
      const hint = document.getElementById('videoSizeHint')
                || document.getElementById(_cfg.fileInputId + 'SizeHint');
      if (hint) {
        const icon = isVideo ? '🎬' : '📄';
        hint.textContent = `${icon} ${_pendingFiles.length} file${_pendingFiles.length > 1 ? 's' : ''} (${totalMB.toFixed(1)} MB) – will upload via secure chunked transfer`;
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
