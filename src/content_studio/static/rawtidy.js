/* 独立面板；不重绘 X 页。 */
(() => {
  let dialog, timer;
  const percent = (n) => (100 * n).toFixed(1);
  function render(data) {
    if (!dialog?.open) return;
    dialog.querySelector('[data-rt-run]').disabled = data.busy;
    dialog.querySelector('[data-rt-status]').innerHTML = data.busy
      ? '<span class="rawtidy-spinner" aria-hidden="true"></span>正在整理…'
      : esc(data.error || '');
    dialog.querySelector('[data-rt-records]').innerHTML = (data.results || []).filter(g => g.status === 'discarded')
      .map(g => `<p class="err">第 ${esc(g.group)} 组已跳过：${esc(g.reason)}</p>`).join('') +
      (data.records || []).map(r => `<article class="rawtidy-record">
        <b>${r.type === 'merge' ? '合并' : '拆分'} · ${r.outputs.map(o => esc(o.title)).join(' / ')}</b>
        <p>来源：${r.source_titles.map(esc).join('、')}</p>
        <p>改了 ${percent(r.change_ratio)}%，覆盖 ${percent(r.coverage)}%</p>
        ${r.outputs.map(o => `<details><summary>${esc(o.title)} · 展开前 200 字</summary><p class="rawtidy-preview">${esc(o.preview)}</p></details>`).join('')}
        <button class="btn small ghost" type="button" data-rt-undo="${esc(r.id)}" ${r.undone || data.busy ? 'disabled' : ''}>${r.undone ? '已撤回' : '撤回'}</button>
      </article>`).join('');
    clearTimeout(timer);
    if (data.busy) timer = setTimeout(refresh, 1500);
  }
  async function refresh() {
    try { render(await api('/api/rawtidy')); }
    catch (err) { if (dialog?.open) dialog.querySelector('[data-rt-status]').textContent = err.message; }
  }
  function open() {
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'rawtidy-dialog';
      dialog.setAttribute('aria-labelledby', 'rawtidy-title');
      dialog.innerHTML = `<header><h2 id="rawtidy-title">整理素材</h2><button type="button" class="btn small ghost" data-rt-close>关闭</button></header>
        <p>按原话合并或拆分，改动最多 5%。来源会保存在「整理前」，可撤回。</p>
        <button type="button" class="btn primary" data-rt-run>整理一批（最多 5 组）</button>
        <p role="status" data-rt-status></p><div data-rt-records></div>`;
      document.body.append(dialog);
      dialog.addEventListener('close', () => clearTimeout(timer));
      dialog.addEventListener('click', async (e) => {
        const b = e.target.closest('button');
        if (!b) return;
        if (b.hasAttribute('data-rt-close')) { dialog.close(); return; }
        b.disabled = true;
        try {
          if (b.hasAttribute('data-rt-run')) await api('/api/rawtidy/run', {method: 'POST', body: {limit: 5}});
          if (b.hasAttribute('data-rt-undo')) await api(`/api/rawtidy/${encodeURIComponent(b.dataset.rtUndo)}/undo`, {method: 'POST'});
          await refresh();
        } catch (err) { toast(err.message); b.disabled = false; }
        finally { if (!b.hasAttribute('data-rt-run')) b.disabled = false; }
      });
    }
    if (!dialog.open) dialog.showModal();
    refresh();
  }
  document.addEventListener('click', (e) => {
    if (!e.target.closest('[data-rawtidy-open]')) return;
    e.preventDefault();
    open();
  });
})();
