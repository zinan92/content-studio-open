'use strict';

/* 设置页「版本与更新」：看现在是哪个版本、有没有新版本，一点就拉下来并安全重启。
 * 只更新工作台自己；deploy.json 里的其他依赖只显示装没装。开发机（不在更新分支、或有没提交的改动）只看不动。
 * 在 app.js 之前加载，所以 $、api 只在函数里用。 */
const UP = { data: null, loading: false, busy: false, packing: false };

function upSupport() {
  return `<p class="up-note">遇到问题，把诊断包发给安装负责人。里面有版本、运行状态、验收单、最近的日志和出错记录，方便远程查到哪一行；登录信息和密钥不带。</p>
    <button class="btn" type="button" id="upDiagnostics" ${UP.packing ? 'disabled' : ''}>${UP.packing ? '正在打包…' : '打包诊断信息'}</button>`;
}

function bindDiagnostics() {
  const button = $('#upDiagnostics');
  if (!button) return;
  button.onclick = async () => {
    UP.packing = true; renderUpdate();
    let url;
    try {
      const response = await fetch('/api/diagnostics', { method: 'POST', headers: { 'X-Content-Studio': '1' } });
      if (!response.ok) throw new Error('诊断包没生成，请稍后重试');
      url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = (response.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/)?.[1] || 'content-studio-diagnostics.zip';
      document.body.appendChild(link); link.click(); link.remove();
      toast('诊断包已下载，请发给安装负责人');
    } catch (err) { toast(err.message); }
    finally {
      if (url) setTimeout(() => URL.revokeObjectURL(url), 1000);
      UP.packing = false; renderUpdate();
    }
  };
}

function upDay(iso) { return iso ? iso.slice(0, 10) : ''; }

async function loadUpdate(fetchRemote) {
  UP.loading = true;
  renderUpdate();
  try { UP.data = await api(`/api/update?fetch=${fetchRemote ? 'true' : 'false'}`); } catch (err) { UP.data = { error: err.message }; }
  UP.loading = false;
  renderUpdate();
}

function renderUpdate() {
  const box = $('#updateBody');
  if (!box) return;
  const d = UP.data;
  if (!d) {
    box.innerHTML = '<p class="up-note">正在读版本…</p>';
    if (!UP.loading) loadUpdate(false); // 只发一次：loadUpdate 自己会再调 renderUpdate
    return;
  }
  if (d.error) { box.innerHTML = `<p class="up-note err">${esc(d.error)}</p>${upSupport()}`; bindDiagnostics(); return; }
  const deps = (d.deps || []).map((x) => `<li class="${x.installed ? 'ok' : x.required ? 'miss' : 'off'}"><b>${esc(x.name)}</b><span>${esc(x.feature)}</span><em>${x.installed ? '已装' : x.required ? '没装' : '可选，没装'}</em></li>`).join('');
  const commits = (d.commits || []).map((c) => `<li><span class="num">${esc(upDay(c.date))}</span>${esc(c.subject)}</li>`).join('');
  const head = d.head || {};
  box.innerHTML = `<div class="up-now">
      <div><span class="up-k">现在的版本</span><b>${esc(upDay(head.date))} · ${esc(head.hash || '')}</b><small>${esc(head.subject || '')}</small></div>
      <div class="up-acts">
        <button class="btn" type="button" id="upCheck" ${UP.loading || UP.busy ? 'disabled' : ''}>${UP.loading ? '正在查…' : '检查更新'}</button>
        ${d.can_update ? `<button class="btn primary" type="button" id="upApply" ${UP.busy ? 'disabled' : ''}>${UP.busy ? '正在更新…' : `更新到最新（${d.behind} 个新改动）`}</button>` : ''}
      </div>
    </div>
    ${d.reason ? `<p class="up-note">${esc(d.reason)}</p>` : d.behind ? '' : '<p class="up-note">已经是最新版。</p>'}
    ${commits ? `<ul class="up-log">${commits}</ul>` : ''}
    ${deps ? `<details class="up-deps"><summary>依赖（${(d.deps || []).filter((x) => x.installed).length}/${(d.deps || []).length} 已装）</summary><ul>${deps}</ul></details>` : ''}
    ${upSupport()}`;
  bindDiagnostics();
  $('#upCheck').onclick = () => loadUpdate(true);
  const apply = $('#upApply');
  if (apply) apply.onclick = async () => {
    UP.busy = true; renderUpdate();
    try {
      const r = await api('/api/update', { method: 'POST' });
      toast(r.message || '更新好了');
      UP.data = null;
      UP.busy = false;
      loadUpdate(false);
      return;
    } catch (err) { toast(err.message); }
    UP.busy = false; renderUpdate();
  };
}
window.renderUpdate = renderUpdate;
