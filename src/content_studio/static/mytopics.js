'use strict';
/* 选题 →「我的选题」（10/19 作者 拿掉排期）。
   他的流程：选题挑一条 → 写稿 → 口播稿 → 拍 → 剪辑 → 标题和封面 → 发。没有排期这一步。
   点「做这条」就是开始做它，接着进写稿；整条流水线上一次只有一条（从开始写到发出去），没有「换成这条」——
   正在做的没发完，别的「做这条」都是灰的；不想做了在它的页面点「不做了」。
   数据都在原处：旧的日历顺序（shoot_list）留在库里不用。 */

const MY = { data: null, at: 0, picker: null, trashOpen: false };

async function loadMyTopics(force) {
  if (!force && MY.data && Date.now() - MY.at < 15000) return MY.data;
  MY.data = await api('/api/my-topics');
  MY.at = Date.now();
  return MY.data;
}
window.invalidateMyTopics = () => { MY.data = null; };
window.myTopicsCount = () => (MY.data ? MY.data.pool.length : 0);

function myMeta(p) {
  if (p.series && !p.words && !p.skeleton) return `第 ${p.ep} 集 · 还没说`;
  if (p.words || p.script || p.skeleton) return '有你的原话';
  return '别人的材料 · 做的时候先口述一遍';
}

function myRow(p, held) {
  return `<div class="my-row"><div class="my-t"><b>${esc(p.title)}</b><small>${esc(myMeta(p))}</small></div>
    <button class="btn small" type="button" data-my-do="${p.id}" ${held ? `disabled title="${esc(held)}"` : ''}>做这条</button>
    <button class="linklike" type="button" data-my-drop="${p.id}">不做了</button></div>`;
}

function myNow(d) {
  const f = d.focus;
  if (!f) return '<div class="my-now empty"><span>现在没有正在做的。挑一条点「做这条」，左栏「写」就是它，接着写稿。</span></div>';
  return `<div class="my-now"><small>正在做</small><b>${esc(f.title)}</b><span class="spacer"></span>
    <button class="btn small" type="button" data-my-open="${f.id}">打开 →</button></div>`;
}

/* 从我的笔记里选：列出原始输出（不看时间），点一篇 = 进我的选题，已经是他的话 */
function myPickRows() {
  const q = (MY.picker.q || '').trim().toLowerCase();
  return (MY.picker.items || [])
    .filter((i) => !i.used_by || i.used_by.dropped)
    .filter((i) => !q || `${i.title} ${i.summary || ''}`.toLowerCase().includes(q))
    .sort((a, b) => String(b.modified_at).localeCompare(String(a.modified_at)))
    .slice(0, 30);
}
function myPickList() {
  if (MY.picker.error) return `<p class="bad">${esc(MY.picker.error)}</p>`;
  if (!MY.picker.items) return '<p class="my-empty">正在读 Obsidian…</p>';
  const rows = myPickRows();
  return rows.length ? rows.map((i) => `<button type="button" class="sc-pick-i" data-my-pickpath="${esc(i.path)}"><b>${esc(i.title)}</b><small>${esc(String(i.modified_at || '').slice(0, 10))}${i.summary ? ` · ${esc(i.summary.slice(0, 40))}` : ''}</small></button>`).join('')
    : '<p class="my-empty">没有找到。已经在我的选题里的不会再出现。</p>';
}
function myPickForm() {
  if (!MY.picker) return '';
  return `<div class="series-new" id="myPickForm">
    <label><span>从我的笔记里选一篇（${esc(rawFolder())}）</span><input id="myPickQ" type="search" autocomplete="off" placeholder="搜标题或开头" value="${esc(MY.picker.q || '')}"></label>
    <div class="sc-pick-list" id="myPickList">${myPickList()}</div>
    <div class="acts"><button class="btn ghost small" type="button" id="myPickClose">不选了</button></div>
  </div>`;
}

function myTrash(d) {
  if (!d.trash.length) return '';
  return `<details class="my-trash" id="myTrash"${MY.trashOpen ? ' open' : ''}><summary>不做了的 ${d.trash.length} 条</summary>
    ${d.trash.map((p) => `<div class="my-row"><div class="my-t"><s>${esc(p.title)}</s></div><button class="linklike" type="button" data-my-back="${p.id}">放回</button></div>`).join('')}</details>`;
}

/* 做这条：开始做它；有他原话的直接进写稿，只有别人材料的先口述一遍（系列没说过的集「说这集」） */
async function myStart(p) {
  try { await api(`/api/topics/${p.id}/focus`, { method: 'POST' }); } catch (err) { toast(err.message); return; }
  MY.data = null;
  if (window.refreshBoard) window.refreshBoard();
  if (p.words || p.skeleton || p.script) { toast('开始做这条：先写稿'); openWork(p.id); return; }
  const mode = p.start === 'say' ? 'series' : p.start === 'replicate' ? null : 'oral';
  try {
    await api(`/api/topics/${p.id}/replicate`, { method: 'POST', body: mode ? { mode } : {} });
    toast(mode === 'series' ? '说这集：左边是这个系列的每集，右边直接说' : mode ? '口述：看着左边的材料，在右边说一遍' : '复刻：看着左边的拆解，在右边说一遍');
    openWork(p.id, 'speak');
  } catch (err) { toast(err.message); openWork(p.id); }
}

function bindMyTopics(body, d) {
  const redraw = () => { body.dataset.sig = ''; renderView(); };
  const find = (id) => d.pool.find((p) => p.id === id);
  $$('[data-my-do]', body).forEach((b) => (b.onclick = () => { b.disabled = true; myStart(find(Number(b.dataset.myDo))); }));
  $$('[data-my-open]', body).forEach((b) => (b.onclick = () => openWork(Number(b.dataset.myOpen))));
  $$('[data-my-drop]', body).forEach((b) => (b.onclick = async () => {
    MY.data = null;
    await window.patchTopic(Number(b.dataset.myDrop), { archived: true }, '不做了。在最下面「不做了的」里能放回');
  }));
  $$('[data-my-back]', body).forEach((b) => (b.onclick = async () => {
    MY.data = null;
    await window.patchTopic(Number(b.dataset.myBack), { archived: false }, '放回我的选题了');
  }));
  const trash = $('#myTrash', body);
  if (trash) trash.ontoggle = () => { MY.trashOpen = trash.open; };
  const say = $('#mySay', body);
  if (say) say.onclick = async () => {
    say.disabled = true;
    try { const r = await api('/api/schedule/oral', { method: 'POST', body: {} }); MY.data = null; toast('口述一条：直接开口说，标题在下面改'); openWork(r.topic.id, 'speak'); } catch (err) { toast(err.message); say.disabled = false; }
  };
  const pick = $('#myPick', body);
  if (pick) pick.onclick = async () => {
    if (MY.picker) { MY.picker = null; redraw(); return; }
    MY.picker = { items: null, q: '' };
    redraw();
    try { MY.picker.items = (await api('/api/vault/inbox?days=1&source=raw')).items; } catch (err) { if (MY.picker) MY.picker.error = err.message; }
    const list = $('#myPickList'); if (list && MY.picker) { list.innerHTML = myPickList(); bindMyPickList(list); }
  };
  const form = $('#myPickForm', body);
  if (!form) return;
  $('#myPickClose', form).onclick = () => { MY.picker = null; redraw(); };
  const q = $('#myPickQ', form);
  q.oninput = () => { MY.picker.q = q.value; const list = $('#myPickList', form); list.innerHTML = myPickList(); bindMyPickList(list); };
  bindMyPickList($('#myPickList', form));
}
function bindMyPickList(list) {
  $$('[data-my-pickpath]', list).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try {
      const res = await api('/api/vault/triage', { method: 'PUT', body: { path: b.dataset.myPickpath, status: 'topic' } });
      toast(`进我的选题了：${res.topic ? res.topic.title.slice(0, 18) : ''}。这是你的话，不用口述`);
      MY.picker = null; MY.data = null;
      if (window.refreshTopics) await window.refreshTopics(); else renderView();
    } catch (err) { toast(err.message); b.disabled = false; }
  }));
}

/* 选题页的第一个 tab（input.js 调） */
window.renderMyTopics = async (body, bar) => {
  let d;
  try { d = await loadMyTopics(false); } catch (err) { body.innerHTML = `${bar()}<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
  if (MY.picker && body.dataset.sig && $('#myPickForm', body)) return;  // 选笔记的时候不自动重画，免得搜到一半被冲掉
  const sig = `mine|${MY.at}|${!!MY.picker}`;
  if (body.dataset.sig === sig) return;
  body.dataset.sig = sig;
  body.innerHTML = `${bar()}<section class="panel my-topics">
    ${myNow(d)}
    <div class="my-acts">${d.held ? `<small class="my-held">${esc(d.held)}</small>` : '<small>点「做这条」就开始做它，接着进写稿</small>'}<span class="spacer"></span>
      <button class="btn small ghost" type="button" id="myPick">从我的笔记里选</button><button class="btn small ghost" type="button" id="mySay">+ 口述一条</button></div>
    ${myPickForm()}
    <div class="my-list">${d.pool.map((p) => myRow(p, d.held)).join('') || '<p class="my-empty">还没有。去别的 tab 挑一条点「加入选题」，或者从你的笔记里选。</p>'}</div>
    ${myTrash(d)}
  </section>`;
  bindMyTopics(body, d);
};
