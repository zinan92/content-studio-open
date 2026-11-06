'use strict';

/* 咨询客户页：一个客户一行（= vault 010_咨询/<客户>/ 一个文件夹）。
 * 作者 填的来源、首次收费、微信名、后续方案和报价存进那个文件夹的「客户档案.md」；
 * 画像由录音分析自动填一次，之后随便改。最右边是每一场咨询的两份 summary。
 * 上传录音还是那个窗口；上传后在这张表里看进度。
 * 这个文件在 app.js 之前加载（要先登记 VIEWS），所以 $、api 只在函数里用。 */
window.VIEWS = window.VIEWS || {};

const CS = { rows: null, timer: null, drafts: Object.create(null), generation: 0, loading: null, loadedAt: 0, error: '' };
const CS_STAGE = { queued: '排队中', transcribing: '转文字中', analyzing: '分析中', client: '写客户版', done: '已完成', failed: '失败', interrupted: '中断了' };
const CS_PLAN = ['', '待定', '要出方案', '暂不需要'];
const CS_COLS = [
  ['来源', '怎么进来的', '例如：抖音私信、博主介绍'],
  ['首次咨询收费', '初始咨询收费', '例如：1000 元 / 1 小时'],
  ['画像', '一句话定位 · 体量', '做什么、多大体量'],
  ['微信名', '微信名', ''],
  ['后续方案', '后续方案', ''],
  ['报价', '怎么报价', '例如：方案 3 万，分两期'],
];

function consultToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function clientDraft(name) {
  if (!CS.drafts[name]) {
    const row = (CS.rows || []).find((item) => item.name === name);
    CS.drafts[name] = { base: { ...(row?.profile || {}) }, values: {}, revisions: {}, version: 0, saving: false, deleting: false, uploading: false, retrying: 0, deleteError: '', error: '', saved: false };
  }
  return CS.drafts[name];
}
const clientValue = (draft, key) => key in draft.values ? draft.values[key] : draft.base[key] || '';
function editClient(name, key, value) {
  const draft = clientDraft(name);
  if (draft.deleting) return;
  draft.revisions[key] = (draft.revisions[key] || 0) + 1;
  if (value === (draft.base[key] || '')) delete draft.values[key]; else draft.values[key] = value;
  draft.error = ''; draft.deleteError = ''; draft.saved = false;
}
function clientSaveStatus(draft) {
  return draft.deleting ? '正在删除…' : draft.deleteError ? `删除失败：${draft.deleteError}。资料和草稿仍保留。` : draft.error ? `保存失败：${draft.error}。草稿已保留，可重试。` : draft.saving ? '保存中…' : Object.keys(draft.values).length ? `${Object.keys(draft.values).length} 项未保存` : '已保存';
}
async function loadClients(force = false) {
  if (CS.loading) {
    if (force) { await CS.loading; return loadClients(); }
    return CS.loading;
  }
  clearTimeout(CS.timer);
  const generation = CS.generation;
  const versions = Object.fromEntries(Object.entries(CS.drafts).map(([name, draft]) => [name, draft.version]));
  CS.loading = (async () => {
    try {
      const rows = (await api('/api/clients')).clients;
      if (generation !== CS.generation) return;
      rows.forEach((row) => {
        const draft = CS.drafts[row.name];
        if (!draft) return;
        if (draft.saving || draft.version !== (versions[row.name] || 0)) row.profile = { ...row.profile, ...draft.base };
        else draft.base = { ...row.profile };
      });
      CS.rows = rows; CS.error = ''; CS.loadedAt = Date.now();
    } catch (err) { CS.error = err.message; }
    finally { CS.loading = null; }
    if (S.view === 'consults') renderClients();
    updateClientLive();
    const running = (CS.rows || []).some((row) => row.consults.some((job) => job.running));
    if (running && S.view === 'consults') CS.timer = setTimeout(loadClients, 5000);
  })();
  return CS.loading;
}
async function saveClientProfile(name) {
  const draft = clientDraft(name);
  if (draft.deleting || draft.saving || !Object.keys(draft.values).length) return false;
  const values = { ...draft.values }, revisions = { ...draft.revisions };
  draft.saving = true; draft.error = ''; draft.deleteError = ''; draft.version++;
  updateClientSaveStatus(name);
  try {
    const result = await api(`/api/clients/${encodeURIComponent(name)}`, { method: 'PUT', body: values });
    const current = Object.fromEntries(CS_COLS.map(([key]) => [key, clientValue(draft, key)]));
    draft.base = { ...draft.base, ...result.profile };
    for (const key of Object.keys(values)) {
      if (draft.revisions[key] === revisions[key]) delete draft.values[key];
      else if (current[key] === (draft.base[key] || '')) delete draft.values[key];
      else draft.values[key] = current[key];
    }
    draft.saved = true;
    const row = (CS.rows || []).find((item) => item.name === name);
    if (row) row.profile = { ...draft.base };
    const currentRow = clientRowNode(name);
    if (currentRow) $$('[data-field]', currentRow).forEach((input) => {
      if (draft.revisions[input.dataset.field] === revisions[input.dataset.field]) input.value = clientValue(draft, input.dataset.field);
    });
    if (S.view === 'consults') renderClients();
    return true;
  } catch (err) { draft.error = err.message; return false; }
  finally { draft.saving = false; draft.version++; updateClientSaveStatus(name); }
}
function clientField(name, [key, label, hint]) {
  const value = clientValue(clientDraft(name), key), data = `data-client="${esc(name)}" data-field="${esc(key)}"`;
  const long = ['画像', '报价'].includes(key);
  const placeholder = ({ 来源: '抖音 / 转介绍', 首次咨询收费: '如 1000 元' })[key] || hint;
  let input;
  if (key === '后续方案') input = `<select ${data}>${[...new Set([...CS_PLAN, value])].map((option) => `<option value="${esc(option)}"${option === value ? ' selected' : ''}>${option || '还没定'}</option>`).join('')}</select>`;
  else input = `<textarea rows="${long ? 3 : 1}" ${data} placeholder="${esc(placeholder)}">${esc(value)}</textarea>`;
  return `<label class="cd-field ${long ? 'cd-field-long' : 'cd-field-short'}"><span>${esc(label)}</span>${input}</label>`;  // 只在「改资料」里
}

function jobLine(c, name = '') {
  const day = (c.day || '').slice(5).replace('-', '/');
  const retry = c.stage === 'failed' || c.stage === 'interrupted'
    ? `<button class="btn small" type="button" data-cs-retry="${esc(c.slug)}" data-client-owner="${esc(name)}">重试</button>` : '';
  return `<div class="cl-job"><span class="cl-day">${esc(day)}</span><span class="cs-stage cs-${esc(c.stage)}">${esc(CS_STAGE[c.stage] || c.stage)}</span>${retry}${c.error ? `<small class="cs-err">${esc(c.error)}</small>` : ''}</div>`;
}

function docChip(name, d) {
  const main = d.pdf_url || d.html_url;
  const alt = d.pdf_url && d.html_url ? `<a class="cl-alt" href="${esc(d.html_url)}" target="_blank" rel="noopener" title="网页版">HTML</a>` : '';
  return `<span class="cl-doc"><a href="${esc(main)}" target="_blank" rel="noopener" title="打开"><i>${d.pdf_url ? 'PDF' : 'HTML'}</i>${esc(d.label)}</a>${alt}`
    + `<button class="cl-find" type="button" data-cl-reveal="${esc(name)}" data-file="${esc(d.pdf || d.html)}" title="在 Finder 里选中，拖进微信发给客户" aria-label="在 Finder 中显示${esc(d.label)}">⌕</button></span>`;
}

/* 10/11 晚 作者：「明明一两行能搞定，现在一个客户要占半页」——每场咨询一行：日期 + 发给他的 + 自己看的，排成一串小签 */
function summaryCell(r) {
  const jobs = r.consults.filter((c) => c.stage !== 'done').map((job) => jobLine(job, r.name)).join('');
  const days = (r.files || []).map((f) => `<div class="cl-day-block"><span class="cl-day">${esc(f.day.slice(0, 2))}/${esc(f.day.slice(2))}</span>
      ${f.sent.map((d) => docChip(r.name, d)).join('')}${f.mine.map((d) => `<span class="cl-doc mine"><a href="${esc(d.obsidian)}" title="自己看的，在 Obsidian 打开"><i>MD</i>${esc(d.label)}</a></span>`).join('')}</div>`).join('');
  return jobs + days || `<span class="cl-none">${r.consults.length ? '暂时没有交付文件' : '还没有录音'}</span>`;
}

function clientBrief(name) {
  const d = clientDraft(name), v = (k) => clientValue(d, k);
  const meta = [v('来源'), v('首次咨询收费') && `首次 ${v('首次咨询收费')}`, v('微信名') && `微信 ${v('微信名')}`].filter(Boolean).map(esc).join(' · ');
  const plan = v('后续方案');
  return `<div class="cl-who">${meta || '<span class="cl-none">来源没填</span>'}</div>
    <div class="cl-what" title="${esc(v('画像'))}">${esc(v('画像')) || '<span class="cl-none">画像没填</span>'}</div>
    <div class="cl-plan">${plan ? `<span class="cl-pill${plan === '要出方案' ? ' go' : ''}">${esc(plan)}</span>` : '<span class="cl-none">后续还没定</span>'}${v('报价') ? `<span>${esc(v('报价'))}</span>` : ''}</div>`;
}

function clientProgress(row) {
  const jobs = row.consults || [], active = jobs.find((job) => job.running), failed = jobs.find((job) => ['failed', 'interrupted'].includes(job.stage));
  if (active) return CS_STAGE[active.stage] || active.stage;
  if (failed) return '有咨询待恢复';
  return (row.files || []).length ? '交付文件已生成' : jobs.length ? CS_STAGE[jobs[0].stage] || jobs[0].stage : '等待咨询录音';
}
function clientNext(row) {
  if ((row.consults || []).some((job) => job.running)) return '等待处理完成';
  if ((row.consults || []).some((job) => ['failed', 'interrupted'].includes(job.stage))) return '重试右侧未完成的咨询';
  const plan = row.profile['后续方案'];
  return plan === '要出方案' ? '准备后续方案' : plan === '暂不需要' ? '暂不安排后续方案' : '确认后续是否需要方案';
}
function clientRowNode(name) {
  return $$('[data-client-row]', $('#clientsBody')).find((node) => node.dataset.clientRow === name) || null;
}
function fitClientField(input) {
  if (input.tagName !== 'TEXTAREA' || !input.getClientRects?.().length) return;
  if (typeof CSS !== 'undefined' && CSS.supports('field-sizing', 'content')) return;
  input.style.height = 'auto'; input.style.height = `${input.scrollHeight + 2}px`;
}
function clientInput(event) {
  const input = event.target;
  if (!input.dataset.field || (event.type === 'input') === (input.tagName === 'SELECT')) return;
  editClient(input.dataset.client, input.dataset.field, input.value);
  fitClientField(input); updateClientSaveStatus(input.dataset.client);
}
function renderClients() {
  const body = $('#clientsBody');
  if (!body) return;
  if (!CS.rows) { body.innerHTML = `<div class="panel empty" role="${CS.error ? 'alert' : 'status'}">${CS.error ? `客户读取失败：${esc(CS.error)} <button class="btn" type="button" data-cl-refresh>重试</button>` : '正在读客户…'}</div>`; return; }
  if (!CS.rows.length) { body.innerHTML = CS.error ? `<div class="panel empty" role="alert">客户刷新失败：${esc(CS.error)} <button class="btn" type="button" data-cl-refresh>重试</button></div>` : '<div class="panel empty">还没有客户。做完一场咨询，点右上角「上传咨询录音」。</div>'; return; }
  const signature = JSON.stringify(CS.rows.map((row) => row.name));
  // Keep the native fields, selection and focus during polling and save acknowledgements.
  if (body.dataset.clients !== signature || !$('#clientTable', body)) {
    const active = document.activeElement;
    const focus = active?.dataset?.client ? { name: active.dataset.client, key: active.dataset.field, start: active.selectionStart, end: active.selectionEnd } : null;
    body.innerHTML = `<div class="cd-overview" data-client-counts></div><div data-client-error></div>
      <div class="panel cl-list" id="clientTable">${CS.rows.map((row) => `<article class="cl-item" data-client-row="${esc(row.name)}">
        <div class="cl-line">
          <div class="cl-name"><b class="cd-name">${esc(row.name)}</b><small data-client-summary></small></div>
          <div class="cl-brief" data-client-brief></div>
          <div class="cl-files"><div data-client-live></div><small class="cd-progress" data-client-progress></small></div>
          <div class="cl-acts"><button class="btn small" type="button" data-client-upload="${esc(row.name)}">上传录音</button></div>
        </div>
        <details class="cl-edit"><summary>改资料</summary>
          <div class="cl-form">${CS_COLS.map((col) => clientField(row.name, col)).join('')}</div>
          <div class="cl-form-acts"><button class="btn primary small" type="button" data-client-save="${esc(row.name)}">保存</button><span class="cd-save-status" data-client-save-status role="status" aria-live="polite"></span>
            <button class="btn ghost small cl-del" type="button" data-cl-del="${esc(row.name)}">删除客户及相关文件</button></div>
        </details></article>`).join('')}</div>`;
    body.dataset.clients = signature;
    if (focus) {
      const focusRow = clientRowNode(focus.name);
      const input = focusRow ? $$('[data-field]', focusRow).find((node) => node.dataset.field === focus.key) : null;
      input?.focus({ preventScroll: true });
      if (input?.setSelectionRange && focus.start !== null) input.setSelectionRange(focus.start, focus.end);
    }
  }
  const sessions = CS.rows.reduce((count, row) => count + Math.max(row.consults.length, (row.files || []).length), 0);
  const follow = CS.rows.filter((row) => row.profile['后续方案'] === '要出方案').length;
  $('[data-client-counts]', body).innerHTML = `<span><b>${CS.rows.length}</b> 位客户</span><span><b>${sessions}</b> 场咨询</span><span><b>${follow}</b> 位要出方案</span>`;
  $('[data-client-error]', body).innerHTML = CS.error ? `<p class="cd-error" role="alert">刷新失败：${esc(CS.error)}。保留上次读取的内容。 <button class="btn small" type="button" data-cl-refresh>重试</button></p>` : '';
  updateClientLive();
}
function updateClientSaveStatus(name) {
  const row = clientRowNode(name); if (!row) return;
  const draft = clientDraft(name), status = $('[data-client-save-status]', row), button = $('[data-client-save]', row);
  if (status) { status.textContent = clientSaveStatus(draft); status.className = draft.error || draft.deleteError ? 'cd-save-status cd-error' : 'cd-save-status'; }
  if (button) button.disabled = draft.deleting || draft.saving || !Object.keys(draft.values).length;
  const upload = $('[data-client-upload]', row);
  if (upload) upload.disabled = draft.deleting || draft.uploading;
  $$('[data-cs-retry], [data-field]', row).forEach((input) => { input.disabled = draft.deleting; });
  const remove = $('[data-cl-del]', row);
  if (remove) remove.disabled = draft.deleting || draft.saving || draft.uploading || draft.retrying > 0;
}
function updateClientLive() {
  for (const data of CS.rows || []) {
    const row = clientRowNode(data.name); if (!row) continue;
    const live = $('[data-client-live]', row), markup = summaryCell(data);
    if (live && live.innerHTML !== markup) live.innerHTML = markup;
    const summary = $('[data-client-summary]', row), progress = $('[data-client-progress]', row);
    if (summary) summary.textContent = `${Math.max(data.consults.length, (data.files || []).length)} 场咨询`;
    if (progress) progress.textContent = `${clientProgress(data)} · ${clientNext(data)}`;
    const brief = $('[data-client-brief]', row), briefMarkup = clientBrief(data.name);
    if (brief && brief.innerHTML !== briefMarkup) brief.innerHTML = briefMarkup;
    const draft = clientDraft(data.name);
    $$('[data-field]', row).forEach((input) => {
      if (input !== document.activeElement) input.value = clientValue(draft, input.dataset.field);
      fitClientField(input);
    });
    updateClientSaveStatus(data.name);
  }
}
async function clientAction(event) {
  const target = event.target.closest('button'); if (!target) return;
  const data = target.dataset;
  if (data.clientSave) await saveClientProfile(data.clientSave);
  else if (data.clientUpload) openConsult(data.clientUpload);
  else if ('clRefresh' in data) await loadClients(true);
  else if (data.clDel) {
    const draft = clientDraft(data.clDel);
    if (draft.deleting || draft.saving || draft.uploading || draft.retrying) return;
    if (!confirm(`删除客户「${data.clDel}」？\n\n客户档案、会议纪要、PDF，还有录音原件和转写，会一起挪进废纸篓。删错了可以从废纸篓拿回来。`)) return;
    draft.deleting = true; draft.deleteError = '';
    target.disabled = true; updateClientSaveStatus(data.clDel);
    try {
      await api(`/api/clients/${encodeURIComponent(data.clDel)}`, { method: 'DELETE' });
      CS.generation++; delete CS.drafts[data.clDel];
      CS.rows = (CS.rows || []).filter((row) => row.name !== data.clDel); renderClients();
      toast(`已删除「${data.clDel}」，在废纸篓里`); await loadClients(true);
    } catch (err) { draft.deleteError = err.message; toast(err.message); }
    finally { draft.deleting = false; target.disabled = false; updateClientSaveStatus(data.clDel); }
  } else if (data.clReveal) {
    try { await api(`/api/clients/${encodeURIComponent(data.clReveal)}/reveal?file=${encodeURIComponent(data.file)}`, { method: 'POST' }); toast('已在 Finder 里选中，拖进微信就能发'); } catch (err) { toast(err.message); }
  } else if (data.csReveal) {
    try { await api(`/api/consults/${encodeURIComponent(data.csReveal)}/reveal?what=${data.what}`, { method: 'POST' }); toast(data.what === 'client' ? '已在 Finder 里选中客户版，拖进微信就能发' : '已在 Finder 里打开'); } catch (err) { toast(err.message); }
  } else if (data.csRetry) {
    const name = data.clientOwner || (CS.rows || []).find((row) => row.consults.some((job) => job.slug === data.csRetry))?.name;
    const draft = name ? clientDraft(name) : null;
    if (draft?.deleting) return;
    if (draft) { draft.retrying++; updateClientSaveStatus(name); }
    target.disabled = true;
    try { await api(`/api/consults/${encodeURIComponent(data.csRetry)}/retry`, { method: 'POST' }); } catch (err) { toast(err.message); target.disabled = false; }
    finally { if (draft) { draft.retrying--; updateClientSaveStatus(name); } }
    await loadClients(true);
  }
}

function openConsult(name = '') {
  if (typeof name === 'string' && name && CS.drafts[name]?.deleting) return;
  $('#csFile').value = '';
  $('#csName').value = typeof name === 'string' ? name : '';
  $('#csDay').value = consultToday();
  $('#csMsg').classList.remove('err');
  $('#csMsg').textContent = '录音、录像都行（m4a、mp3、mp4、mov…）。45 分钟大约 10–15 分钟出两份：给你的、给客户的。同一个客户写同一个名字，会放进同一个文件夹。';
  $('#consultDlg').showModal();
}

/* 诊断流程：做咨询时照着过的那一页（vault 010_咨询/诊断流程.md）。每次打开重新读，Obsidian 里改了这里就变。 */
async function openPlaybook() {
  const body = $('#playbookBody');
  body.innerHTML = '<p class="cl-none">正在读…</p>';
  $('#playbookDlg').showModal();
  try {
    const d = await api('/api/consults/playbook');
    $('#playbookEdit').href = d.obsidian;
    body.innerHTML = d.markdown ? `<p class="cl-source-note">这是知识库中的流程文档；咨询时长与服务范围以「定位 → 服务与定价」中的当前版本为准。</p>${renderMarkdown(d.markdown)}` : `<p class="cl-none">还没有这一页。在 Obsidian 里建 ${esc(d.path)}，写好再回来点开。</p>`;
    body.scrollTop = 0;
  } catch (err) { body.innerHTML = `<p class="cl-none">${esc(err.message)}</p>`; }
}

/* 统一话术：回微信用的几段固定说法（vault 010_咨询/统一话术.md）。一个「## 标题」是一条，每条一个复制按钮，
 * 复制出来的是去掉 Markdown 记号的纯文字，直接粘进微信。 */
function scriptSections(md) {
  const out = [];
  let cur = null;
  for (const line of md.split('\n')) {
    if (line.startsWith('## ')) { cur = { title: line.slice(3).trim(), lines: [] }; out.push(cur); }
    else if (cur) cur.lines.push(line);
  }
  return out.map((x) => ({ title: x.title, md: x.lines.join('\n').trim() }));
}
function scriptPlain(md) {
  return md.split('\n').filter((l) => !/^\s*>/.test(l)).join('\n')
    .replace(/\*\*(.+?)\*\*/g, '$1').replace(/^\s*[-*] /gm, '').replace(/\n{3,}/g, '\n\n').trim();
}
async function openScripts() {
  const body = $('#scriptsBody');
  body.innerHTML = '<p class="cl-none">正在读…</p>';
  $('#scriptsDlg').showModal();
  try {
    const d = await api('/api/consults/scripts');
    $('#scriptsEdit').href = d.obsidian;
    const secs = scriptSections(d.markdown || '');
    body._secs = secs;
    body.innerHTML = secs.length
      ? secs.map((x, i) => `<section class="sc-item"><div class="sc-h"><h3>${esc(x.title)}</h3><button class="btn small primary" type="button" data-sc-copy="${i}">复制</button></div><div class="md">${renderMarkdown(x.md)}</div></section>`).join('')
      : `<p class="cl-none">还没有话术。在 Obsidian 里建 ${esc(d.path)}，一条话术写一个「## 标题」。</p>`;
    body.scrollTop = 0;
  } catch (err) { body.innerHTML = `<p class="cl-none">${esc(err.message)}</p>`; }
}

window.VIEWS.consults = { render() { renderClients(); if (!CS.rows || Date.now() - CS.loadedAt > 5000) loadClients(); } };

document.addEventListener('DOMContentLoaded', () => {
  $('#consultUpload').onclick = openConsult;
  $('#playbookOpen').onclick = openPlaybook;
  $('#playbookClose').onclick = () => $('#playbookDlg').close();
  $('#scriptsOpen').onclick = openScripts;
  $('#scriptsClose').onclick = () => $('#scriptsDlg').close();
  $('#scriptsBody').addEventListener('click', async (e) => {
    const i = e.target.dataset && e.target.dataset.scCopy;
    if (i === undefined) return;
    try { await navigator.clipboard.writeText(scriptPlain($('#scriptsBody')._secs[+i].md)); toast('已复制，粘进微信就行'); } catch (err) { toast('复制失败：' + err.message); }
  });
  $('#csCancel').onclick = () => $('#consultDlg').close();
  $('#clientsBody').addEventListener('click', clientAction);
  $('#clientsBody').addEventListener('input', clientInput);
  $('#clientsBody').addEventListener('change', clientInput);
  $('#consultForm').onsubmit = async (e) => {
    e.preventDefault();
    const file = $('#csFile').files[0], msg = $('#csMsg'), btn = $('#csSubmit');
    msg.classList.remove('err');
    if (!file) { msg.classList.add('err'); msg.textContent = '先选一个录音或录像文件'; return; }
    if (!$('#csName').value.trim()) { msg.classList.add('err'); msg.textContent = '写一下客户是谁，会用作文件夹的名字'; return; }
    const clientName = $('#csName').value.trim(), draft = clientDraft(clientName);
    if (draft.deleting) { msg.classList.add('err'); msg.textContent = '这位客户正在删除，暂时不能上传。'; return; }
    const body = new FormData();
    body.append('file', file);
    body.append('name', $('#csName').value.trim());
    body.append('day', $('#csDay').value);
    btn.disabled = true; draft.uploading = true; updateClientSaveStatus(clientName);
    msg.textContent = `正在上传 ${(file.size / 1048576).toFixed(1)} MB…`;
    try {
      const res = await fetch('/api/consults', { method: 'POST', body, headers: { 'X-Content-Studio': '1' } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || `上传失败（${res.status}）`);
      $('#consultDlg').close();
      CS.generation++;
      toast('传好了，正在转文字。在客户表格右侧查看进度，做完会自动在 Obsidian 打开');
      loadClients(true);
    } catch (err) {
      msg.classList.add('err');
      msg.textContent = err.message;
    } finally {
      draft.uploading = false; updateClientSaveStatus(clientName);
      btn.disabled = false;
    }
  };
});
