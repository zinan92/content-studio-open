'use strict';

(() => {
  let loaded = false, loading = false, saving = false, request = 0, current = null;

  async function openFrame(doc) {
    if (saving) return;
    const ticket = ++request;
    $('#framesMsg').textContent = '';
    try {
      const result = await api(`/api/frames/doc?${new URLSearchParams(doc)}`);
      if (ticket !== request) return;
      current = doc;
      $('#frameName').textContent = result.name;
      $('#framePath').textContent = result.path;
      $('#frameText').value = result.body;
      $('#frameMsg').textContent = '';
      $('#frameEditor').hidden = false;
    } catch (err) {
      if (ticket === request) $('#framesMsg').textContent = err.message;
    }
  }

  function renderFrames(data) {
    $('#frameOne').innerHTML = data.layer_one.map((f) => `<button type="button" class="soul-row" data-frame-key="${esc(f.key)}"><b>${esc(f.label)}</b><small>${esc(f.path || f.file)}</small></button>`).join('');
    $('#frameSeries').innerHTML = data.series.map((s) => `<button type="button" class="soul-row" data-frame-folder="${esc(s.folder)}"><span class="frame-row-head"><b>${esc(s.folder)}</b><small>${s.has_frame ? '有第二层' : '默认：只有第一层'}</small></span><small>${esc(s.path)}</small></button>`).join('') || '<p class="sync-note">还没有系列</p>';
    $$('[data-frame-key]').forEach((b) => { b.onclick = () => openFrame({ kind: 'one', key: b.dataset.frameKey }); });
    $$('[data-frame-folder]').forEach((b) => { b.onclick = () => openFrame({ kind: 'series', folder: b.dataset.frameFolder }); });
  }

  window.loadFrames = async function () {
    if (loaded || loading) return;
    loading = true;
    try {
      renderFrames(await api('/api/frames'));
      loaded = true;
      $('#framesMsg').textContent = '';
      $('#frameCancel').onclick = () => {
        if (saving) return;
        request++;
        current = null;
        $('#frameEditor').hidden = true;
      };
      $('#frameText').oninput = () => { $('#frameMsg').textContent = ''; };
      $('#frameSave').onclick = async () => {
        if (!current || saving) return;
        const text = $('#frameText').value;
        if (!text.trim()) { $('#frameMsg').textContent = '内容是空的'; return; }
        saving = true;
        request++;
        $('#frameSave').disabled = true;
        $('#frameCancel').disabled = true;
        $('#frameText').readOnly = true;
        $('#frameMsg').textContent = '保存中…';
        try {
          await api('/api/frames/doc', { method: 'PUT', body: JSON.stringify({ ...current, text }) });
          $('#frameMsg').textContent = '已保存';
          try { renderFrames(await api('/api/frames')); }
          catch (err) { $('#framesMsg').textContent = `已保存，列表刷新失败：${err.message}`; }
        } catch (err) {
          $('#frameMsg').textContent = err.message;
        } finally {
          saving = false;
          $('#frameSave').disabled = false;
          $('#frameCancel').disabled = false;
          $('#frameText').readOnly = false;
        }
      };
    } catch (err) {
      $('#framesMsg').textContent = err.message;
    } finally {
      loading = false;
    }
  };
})();
