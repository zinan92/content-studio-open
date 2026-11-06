'use strict';
/* 01 选题（10/13 作者：原「进项」，看什么热、别人在讲什么）：所有进来的东西在一排 tab 里，左边列表、右边读原文。
   一条只有一个动作：加入选题。10/19 起第一个 tab 是「我的选题」（mytopics.js）：点「做这条」开始做，排期拿掉了。 */
window.VIEWS = window.VIEWS || {};

// tab key → 它从哪来。daily 走 /api/vault/dailies，followed 走对标账号的新作品，其余是 Obsidian 笔记。
const NOTE_TABS = [
  { key: 'saved', label: '我收藏的', kind: 'note' },
  { key: 'clipping', label: 'Clippings', kind: 'note' },
];
// 日报 tab 由 profile.yaml 的 dailies 决定（/api/state.daily_sources）；没配的日报不出现。
const TABS = [{ key: 'mine', label: '我的选题', kind: 'mine' }, { key: 'all', label: '最近', kind: 'all' }];
function syncTabs() {
  const dailies = (S.state && S.state.daily_sources) || [];
  TABS.length = 2;
  // K 线日报有自己的看板 tab（kline_board.py），配了这份日报才出现；日报本身那份 md 就不再单列，不然两个「K 线日报」
  dailies.forEach((d) => { if (d.key !== 'kline_daily') TABS.push({ key: d.key, label: d.label, kind: 'daily' }); });
  if (dailies.some((d) => d.key === 'kline_daily')) TABS.push({ key: 'kline', label: 'K 线日报', kind: 'kline' });
  // 老师和对标新发的视频（9/30）：他自己去看，不拆、不筛。流量视频 10/5 起是左边单独一项，不在这排里。
  TABS.push({ key: 'teacher', label: '老师', kind: 'feed' });
  TABS.push({ key: 'benchmark', label: '对标', kind: 'feed' });
  NOTE_TABS.forEach((t) => TABS.push(t));
  // 10/8 作者：X 热榜两边都放——X 页一块、这里一个 tab，同一份数据（xhot.js）
  if (window.renderXHot) TABS.push({ key: 'xhot', label: 'X 热榜', kind: 'xhot' });
  if (!TABS.some((t) => t.key === C.tab)) C.tab = 'mine';
}
const DAY_TABS = [[1, '1 天'], [3, '3 天'], [7, '7 天'], [30, '30 天']];
/* 「我写的东西」在 Obsidian 里叫什么文件夹（profile 的 vault.folders.my_writing）：页面上提到它用这个名字 */
function rawFolder() { return ((typeof S !== 'undefined' && S.state && S.state.vault_folders) || {}).raw || '原始输出'; }

/* 从「今天」的读日报直接跳到那一份（9/30） */
window.openInputTab = (key) => { C.tab = key; C.open = null; C.note = null; go('input'); };
const C = { tab: 'mine', days: 1, items: null, since: null, open: null, note: null, dailies: {}, loadedAt: 0, groups: {}, renderSeq: 0, noteSeq: 0, inboxVersion: 0, inboxCache: {}, inboxPending: {}, inboxRequests: {} };

const tabDef = (key) => TABS.find((t) => t.key === key) || TABS[0];

// 异步读取可以填缓存，只有仍在原页面、原筛选的请求可以改画面。
function inputTicket(body) {
  const seq = ++C.renderSeq, tab = C.tab, days = C.days;
  return () => S.view === 'input' && C.renderSeq === seq && C.tab === tab && C.days === days && body.isConnected !== false;
}
function inputStatus(body, message, error = false) {
  body.dataset.sig = '';
  body.innerHTML = tabBar() + `<div class="panel empty in-status" role="${error ? 'alert' : 'status'}">${error ? '' : '<span class="spin" aria-hidden="true"></span>'}<b>${esc(message)}</b>${error ? '<button class="btn" type="button" data-in-retry>重试</button>' : ''}</div>`;
  bindTabs(body);
  const retry = $('[data-in-retry]', body);
  if (retry) retry.onclick = () => renderView();
}
window.invalidateInbox = () => { C.items = null; C.loadedAt = 0; C.inboxCache = {}; C.inboxVersion++; };

async function loadInbox(force) {
  if (force) { C.inboxCache = {}; C.inboxVersion++; }
  const days = C.days, version = C.inboxVersion;
  const cached = C.inboxCache[days];
  if (!force && cached && Date.now() - cached.loadedAt < 60000) {
    C.items = cached.items; C.since = cached.since; C.loadedAt = cached.loadedAt; return;
  }
  const key = `${version}:${days}:${force ? 'fresh' : 'cached'}`;
  if (!C.inboxPending[key]) {
    const request = (C.inboxRequests[days] || 0) + 1; C.inboxRequests[days] = request;
    C.inboxPending[key] = api(`/api/vault/inbox?days=${days}`).then((res) => {
      if (version !== C.inboxVersion || C.inboxRequests[days] !== request) return;
      const entry = { items: res.items, since: res.since, loadedAt: Date.now() };
      C.inboxCache[days] = entry;
      if (days === C.days) { C.items = entry.items; C.since = entry.since; C.loadedAt = entry.loadedAt; }
    }).finally(() => { delete C.inboxPending[key]; });
  }
  await C.inboxPending[key];
}

async function loadDaily(key, force) {
  if (!force && C.dailies[key]) return;
  C.dailies[key] = (await api(`/api/vault/dailies?key=${key}&limit=40`)).items;
}

/* ---- 一条进项的生命周期：只有五种状态 ----
 *   fresh    还没处理   → 入选题池（往前） / 拍过了 / 暂不拍（放到底下）
 *   working  在加工中   （在看板上，从那边管）
 *   shipped  已发出     （变成了视频，去已发出看数据）
 *   shot     拍过了     → 捡回来
 *   ignored  暂不拍     → 捡回来（标过「不做了」的选题也在这里）
 * 从底下两组只能捡回来，不能一步跳进选题池。 */
function noteState(i) {
  const u = i.used_by;
  if (u && u.shipped) return 'shipped';
  if (u && !u.dropped) return 'working';
  if (i.triage === 'shot') return 'shot';
  if (i.triage === 'ignored') return 'ignored';
  if (i.triage === 'back') return 'fresh';
  if (u && u.dropped) return 'ignored';
  return 'fresh';
}

/* ---- 把三种来源归一成同一种行 ---- */
const noteRow = (i) => ({
  // 对标转录显示博主的名字；其余笔记显示它来自哪个文件夹。
  id: 'n:' + i.path, path: i.path, title: i.title, sub: i.author || i.source_label,
  at: i.is_new ? i.created_at : i.modified_at, summary: i.summary,
  state: noteState(i),
  taken: noteState(i) === 'working' ? 'topic' : '',
  topicId: i.used_by ? i.used_by.topic_id : null, shipped: noteState(i) === 'shipped',
  videoId: i.used_by ? i.used_by.video_id : null,
  // 主窗口只放现在要看的。发出去的和拍过了在一组，标过不做了和暂不拍在一组。
  park: ['shipped', 'shot'].includes(noteState(i)) ? 'shot' : noteState(i) === 'ignored' ? 'ignored' : '',
  source: i.source,
  url: i.url || null, hot: i.breakout || null,
});
const dailyRow = (d) => ({
  id: 'd:' + d.path, path: d.path, title: d.title, sub: d.label, at: d.day || d.modified_at, summary: '',
  taken: '', topicId: null, shipped: false, park: '', source: 'daily', external: d.kind === 'html' ? d.path : null,
});

// 爆的排前面，其余保持时间顺序（sort 是稳定的）。时间窗仍然由上面的 3/7/30 决定——
// 这里只改窗口内的先后，不会把窗口外的东西捞进来。
const hotFirst = (rows) => rows.slice().sort((a, b) => (b.hot ? 1 : 0) - (a.hot ? 1 : 0));

function rowsFor(tab) {
  const def = tabDef(tab);
  if (def.kind === 'daily') return (C.dailies[tab] || []).map(dailyRow);
  if (def.kind === 'note') return hotFirst((C.items || []).filter((i) => i.source === tab).map(noteRow));
  // 全部 = 这段时间「新进来的」。原始输出不受时间窗限制（素材库，不是新闻流），
  // 67 条全塞进来会把当天真正新的东西压到看不见，所以它只在自己那一页整片出现。
  // 日报同理：一份摘要装着很多条，放进来也会淹掉别的。
  return hotFirst((C.items || []).filter((i) => i.source !== 'raw').map(noteRow));
}

function renderMarkdown(md) {
  if (window.marked && window.DOMPurify) {
    const html = window.marked.parse(md.replace(/!\[\[([^\]]+)\]\]/g, '（附件：$1）'), { breaks: true });
    // Clipped web pages carry inline styles (absolute-positioned videos) that break the reader.
    return window.DOMPurify.sanitize(html, { ADD_ATTR: ['target'], FORBID_ATTR: ['style'] });
  }
  return `<pre class="plain">${esc(md)}</pre>`;
}

async function openNote(path) {
  const here = S.view === 'input';
  const request = ++C.noteSeq, tab = C.tab;
  C.open = path;
  C.note = null;
  C.keepScroll = here;
  if (!here) go('input');
  else renderView();
  let note;
  try { note = await api(`/api/vault/note?path=${encodeURIComponent(path)}`); }
  catch (err) { note = { error: err.message }; }
  if (request !== C.noteSeq || C.open !== path || C.tab !== tab) return;
  C.note = note;
  C.keepScroll = true;
  if (S.view === 'input') renderView();
}

/** 唯一的动作：把这一条放进选题池。笔记走 triage，对标视频直接建选题。 */
async function intoPool(row) {
  try {
    const res = await api('/api/vault/triage', { method: 'PUT', body: { path: row.path, status: 'topic' } });
    toast(`已加入选题：${res.topic ? res.topic.title.slice(0, 18) : ''}，在「我的选题」里`);
    await loadInbox(true);
    if (window.refreshBoard) window.refreshBoard();
    if (window.refreshTopics) await window.refreshTopics();
    renderView();
  } catch (err) { toast(err.message); }
}

const hm = (iso) => {
  if (!iso) return '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso.slice(5).replace('-', '/');
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

// 这三个状态都是 作者自己手点的，所以每一个都得能反悔。
const TRIAGE_LABEL = { shot: '拍过了', ignored: '暂不拍', topic: '已加入选题', back: '捡回来' };
// 标过「拍过了」「暂不拍」的收到列表最下面两组里，默认折起来；点开仍能读原文、仍能捡回来。
const PARKED = ['ignored', 'shot'];

function rowActions(r) {
  if (r.state === 'working') return `<button class="chip-state working" type="button" data-work="${r.topicId}">查看选题 →</button>`;
  // 已经是视频了：去已发出看它的数据，不回加工中。
  if (r.state === 'shipped') return `<span class="chip-state shipped">已发出</span><button class="chip-state working" type="button" data-shipped="${esc(r.videoId || '')}">看数据 →</button>`;
  // 底下两组只有一个动作：捡回来，回到还没处理。
  if (r.state === 'shot' || r.state === 'ignored') return `<span class="chip-state">${r.state === 'shot' ? '拍过了' : '暂不拍'}</span><button class="btn small" type="button" data-mark="back" data-path="${esc(r.path)}">捡回来</button>`;
  // 还没处理的笔记：三个动作。
  const pool = `<button class="btn small primary" type="button" data-pool="${esc(r.id)}">加入选题</button>`;
  return pool;
}

function noteMore(r) {
  const park = r.path && !['working', 'shipped', 'shot', 'ignored'].includes(r.state) ? `<button class="btn small ghost" type="button" data-mark="shot" data-path="${esc(r.path)}">拍过了</button><button class="btn small ghost" type="button" data-mark="ignored" data-path="${esc(r.path)}">暂不拍</button>` : '';
  const quote = r.path ? xcBtn({ kind: 'note', path: r.path }, r.title) : '';
  const original = r.url && ['benchmark', 'saved', 'clipping'].includes(r.source) ? `<a class="btn small ghost" href="${esc(r.url)}" target="_blank" rel="noopener">${r.source === 'benchmark' ? '去抖音' : '原文'} ↗</a>` : '';
  return park || quote || original ? `<details class="in-more"><summary>更多操作</summary><div class="acts">${park}${quote}${original}</div></details>` : '';
}

window.VIEWS.input = {
  async render() {
    const body = $('#inputBody');
    if (S.view !== 'input') return;
    syncTabs();
    const valid = inputTicket(body);
    // 我的选题不读 Obsidian：库连不上也照样能挑、能做
    if (tabDef(C.tab).kind === 'mine') {
      await window.renderMyTopics(body, tabBar);
      $$('[data-tab]', body).forEach((b) => (b.onclick = () => { C.tab = b.dataset.tab; C.open = null; C.note = null; body.dataset.sig = ''; renderView(); }));
      return;
    }
    if (!S.state.vault.ok) {
      body.innerHTML = `<div class="panel empty"><b>${esc(S.state.vault.message)}</b><span><button class="btn small" type="button" onclick="go('settings')">去设置</button></span></div>`;
      return;
    }
    const def = tabDef(C.tab);
    if (!C.items) inputStatus(body, '正在读 Obsidian…');
    try {
      await loadInbox(false);
    } catch (err) { if (valid()) inputStatus(body, `选题读取失败：${err.message}`, true); return; }
    if (!valid()) return;
    // 日报不是笔记列表：一期整页铺开，一条条快讯各自入选题池。
    if (def.kind === 'daily') { await renderDaily(body, valid); return; }
    // K 线日报：100 多个标的，一张日线卡一个，一行铺满，往下扫一遍就看完。
    if (def.kind === 'kline') { await renderKline(body, valid); return; }
    if (def.kind === 'feed') { await renderFeed(body, def.key, valid); return; }
    if (def.kind === 'xhot') { renderXHotTab(body); return; }

    const rows = rowsFor(C.tab);
    const fresh = (C.items || []).filter((i) => i.source !== 'raw' && noteState(i) === 'fresh').length;
    $('#navIn').textContent = fresh || '';

    // 宽屏时右边不留空盒子：自动打开第一条可读的。
    if (!C.open && window.innerWidth > 900) {
      const first = rows.find((r) => r.path && !r.park) || rows.find((r) => r.path);
      if (first) { openNote(first.path); return; }
    }

    const sig = JSON.stringify([C.tab, C.days, C.open, C.note, C.loadedAt, rows.map((r) => [r.id, r.taken, r.topicId])]);
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;

    const count = (t) => {
      if (t.kind === 'note') return (C.items || []).filter((i) => i.source === t.key && noteState(i) === 'fresh').length;
      if (t.kind === 'all') return (C.items || []).filter((i) => i.source !== 'raw' && noteState(i) === 'fresh').length;
      return 0;
    };

    const rowHtml = (r) => `<div class="in-row ${C.open === r.path ? 'on' : ''} ${r.park ? 'state-' + r.park : r.taken ? 'state-' + r.taken : ''} ${r.hot ? 'blew' : ''}">
        ${r.hot ? `<span class="blew-x" title="${esc(r.hot.account || '')}平时中位 ${fmt(r.hot.median)} 赞，这条 ${fmt(r.hot.likes)}">${r.hot.multiple.toFixed(1)}×</span>` : ''}
        <div class="in-meta"><span class="src">${esc(r.sub)}</span><span class="num">${hm(r.at)}</span></div>
        <button class="in-read" type="button" data-note="${esc(r.path)}" aria-pressed="${C.open === r.path}">${esc(r.title)}</button>
        ${r.hot ? `<small class="blew-why">爆了 · 平时中位 ${fmt(r.hot.median)} 赞，这条 ${fmt(r.hot.likes)}</small>` : ''}
        ${r.summary ? `<p class="clamp">${esc(r.summary)}</p>` : ''}
        <div class="acts">${rowActions(r)}</div>${noteMore(r)}
      </div>`;
    const active = rows.filter((r) => !r.park);
    const parked = PARKED.map((k) => [k, rows.filter((r) => r.park === k)]).filter(([, rs]) => rs.length);
    const groups = parked.map(([k, rs]) => `<details class="in-group" data-group="${k}" ${C.groups[k] ? 'open' : ''}><summary><span>${k === 'shot' ? '拍过了 · 已发出' : '暂不拍'}</span><b class="num">${rs.length}</b></summary>${rs.map(rowHtml).join('')}</details>`).join('');
    const list = rows.length ? (active.length ? active.map(rowHtml).join('') : `<div class="empty small"><span>没处理的都处理完了。</span></div>`) + groups
      : `<div class="empty"><b>这里暂时没有东西</b><span>${C.tab === 'benchmark' ? '对标这一周发的、点赞到自己中位数 2 倍的，每天 9:30 同步后自动拆，拆完文字稿出现在这里；你在对标雷达点「拆解」的也会进来。预告、开播这类没内容的不会进来。' : def.kind === 'daily' ? '这份日报还没有出过。' : `从 ${hm(C.since)} 起没有新的。换一个时间范围看看。`}</span></div>`;

    let reader = `<div class="empty reader-empty"><span>${rows.length ? '点左边任意一条，在这里读原文。' : '这个 tab 暂时没有可读的。'}</span></div>`;
    if (C.open) {
      const n = C.note;
      if (!n) reader = '<div class="empty" role="status"><span class="spin"></span><span>正在读原文…</span></div>';
      else if (n.error) reader = `<div class="empty" role="alert"><b>原文读取失败</b><span>${esc(n.error)}</span><button class="btn" type="button" data-note-retry>重试原文</button></div>`;
      else reader = `<div class="reader-h"><h2>${esc(n.title)}</h2><div class="acts">${n.meta && (n.meta.source || n.meta.url) ? `<a class="btn small" href="${esc(n.meta.source || n.meta.url)}" target="_blank" rel="noopener">原文 ↗</a>` : ''}</div><span class="in-origin">来源：${esc((rows.find((r) => r.path === C.open) || {}).sub || tabDef(C.tab).label)}</span><details class="in-provenance"><summary>文件位置</summary><small>${esc(n.path)}</small></details></div><article class="md">${renderMarkdown(n.body || '')}</article>`;
    }

    // 点「暂不拍 / 捡回来」或点开一条读原文，列表停在原地；换 tab、换时间段才回到顶上。
    const keep = C.keepScroll ? { list: ($('.in-list', body) || {}).scrollTop || 0, win: window.scrollY } : null;
    C.keepScroll = false;
    body.innerHTML = `<div class="in-bar">
        <div class="in-tabs" role="tablist" aria-label="来源">${TABS.filter((t) => t.kind !== 'mine').map((t) => { const n = count(t); return `<button type="button" role="tab" aria-selected="${C.tab === t.key}" class="${C.tab === t.key ? 'on' : ''}" data-tab="${t.key}">${t.label}${n ? `<b class="num">${n}</b>` : ''}</button>`; }).join('')}</div>
        ${def.kind === 'daily' ? '' : `<div class="seg-toggle" role="group" aria-label="时间">${DAY_TABS.map(([d, l]) => `<button type="button" class="${C.days === d ? 'on' : ''}" aria-pressed="${C.days === d}" data-days="${d}">${l}</button>`).join('')}</div>`}
      </div>
      <p class="in-note">${C.tab === 'all' ? '最近不含日报，可从对应来源查看。' : ''}先点标题读原文，再「加入选题」，到「我的选题」点「做这条」。数字是待处理条数。</p>
      <div class="in-grid"><div class="panel in-list">${list}</div><div class="panel reader">${reader}</div></div>`;

    if (keep) { const l = $('.in-list', body); if (l) l.scrollTop = keep.list; window.scrollTo(0, keep.win); }
    $$('[data-tab]', body).forEach((b) => (b.onclick = () => { C.tab = b.dataset.tab; C.open = null; C.note = null; renderView(); }));
    $$('[data-days]', body).forEach((b) => (b.onclick = () => { C.days = Number(b.dataset.days); C.items = null; C.open = null; C.note = null; renderView(); }));
    $$('[data-note]', body).forEach((row) => {
      row.onclick = () => openNote(row.dataset.note);
    });
    const retryNote = $('[data-note-retry]', body);
    if (retryNote) retryNote.onclick = () => openNote(C.open);
    const stop = (fn) => (e) => { e.stopPropagation(); fn(e.currentTarget); };
    $$('[data-pool]', body).forEach((b) => (b.onclick = stop((el) => {
      const row = rowsFor(C.tab).find((r) => r.id === el.dataset.pool);
      if (row) intoPool(row);
    })));
    $$('[data-work]', body).forEach((b) => (b.onclick = stop((el) => openWork(Number(el.dataset.work)))));
    $$('[data-mark]', body).forEach((b) => (b.onclick = stop((el) => markNote(el.dataset.path, el.dataset.mark || null))));
    $$('[data-shipped]', body).forEach((b) => (b.onclick = stop((el) => { S.mineFocus = el.dataset.shipped || null; go('mine'); })));
    $$('details.in-group', body).forEach((d) => (d.ontoggle = () => { C.groups[d.dataset.group] = d.open; }));
  },
};

/** 拍过了 / 暂不拍 / 捡回来（status 为空）。只改选题里这一条的状态，不动选题。 */
async function markNote(path, status) {
  try {
    await api('/api/vault/triage', { method: 'PUT', body: { path, status } });
    C.keepScroll = true;
    toast(status === 'back' ? '已捡回来' : `已标${TRIAGE_LABEL[status]}`);
    await loadInbox(true);
    renderView();
  } catch (err) { toast(err.message); }
}


/* ================= 日报：今天这一期整页铺开，单条入选题池 ================= */
const D = { issue: {}, path: {}, open: {}, originals: {}, busy: {}, requests: {} };

function tabBar() {
  const count = (t) => {
    if (t.kind === 'note') return (C.items || []).filter((i) => i.source === t.key && noteState(i) === 'fresh').length;
    if (t.kind === 'all') return (C.items || []).filter((i) => i.source !== 'raw' && noteState(i) === 'fresh').length;
    if (t.kind === 'feed') return FD.data ? FD.data.counts[t.key].unseen : 0;
    if (t.kind === 'mine') return window.myTopicsCount ? window.myTopicsCount() : 0;
    return 0;
  };
  // 10/20：「我的选题」挪到上面一排（和进来的、老师和对标、拆解报告同一层），在它里面不再有第二排页签
  if (tabDef(C.tab).kind === 'mine') return '';
  return `<div class="in-bar"><div class="in-tabs" role="tablist" aria-label="来源">${TABS.filter((t) => t.kind !== 'mine').map((t) => { const n = count(t); return `<button type="button" role="tab" aria-selected="${C.tab === t.key}" class="${C.tab === t.key ? 'on' : ''}" data-tab="${t.key}">${t.label}${n ? `<b class="num">${n}</b>` : ''}</button>`; }).join('')}</div></div>`;
}

async function loadIssue(key, path) {
  const q = `/api/vault/daily/issue?key=${encodeURIComponent(key)}${path ? `&path=${encodeURIComponent(path)}` : ''}`;
  const request = (D.requests[key] || 0) + 1; D.requests[key] = request;
  const issue = await api(q);
  if (D.requests[key] !== request || D.path[key] !== path) return;
  D.issue[key] = issue; D.path[key] = issue.path;
}

function dailyItemHtml(key, it) {
  const open = D.open[it.id];
  const orig = D.originals[it.id];
  let action;
  if (it.topic_id && !it.topic_archived) action = `<button class="chip-state working" type="button" data-work="${it.topic_id}">在我的选题 →</button>`;
  else action = `<button class="btn small primary" type="button" data-dpick="${esc(it.id)}" ${D.busy[it.id] ? 'disabled' : ''}>${it.topic_archived ? '再捡回来' : '加入选题'}</button>`;
  const badge = it.has_original ? '' : '<span class="d-thin" title="日报管道只留最近几天的原文；这一条加入选题时只能带上摘要">只有摘要</span>';
  let more = '';
  if (open) {
    if (!orig) more = '<div class="d-orig"><span class="spin"></span></div>';
    else if (orig.error) more = `<div class="d-orig" role="alert"><p>原文读取失败：${esc(orig.error)}</p><button class="btn small" type="button" data-dretry="${esc(it.id)}">重试原文</button></div>`;
    else more = `<div class="d-orig">${orig.deep ? `<div class="d-deep"><b>深读</b>${renderMarkdown(orig.deep)}</div>` : ''}${orig.body ? `<div class="md">${renderMarkdown(orig.body)}</div>` : '<p class="d-none">原文已经不在日报管道里了，只有上面的摘要。</p>'}</div>`;
  }
  return `<div class="d-item ${open ? 'open' : ''}" data-ditem="${esc(it.id)}">
    <div class="d-head"><span class="d-src">${esc(it.source)}</span>${badge}</div>
    <div class="d-title"><button class="linklike" type="button" data-dtoggle="${esc(it.id)}">${esc(it.title)}</button>${it.url ? ` <a class="d-link" href="${esc(it.url)}" target="_blank" rel="noopener">原文 ↗</a>` : ''}</div>
    ${it.summary ? `<p class="d-sum">${esc(it.summary)}</p>` : ''}
    <div class="acts">${action}${xcBtn({ kind: 'daily', key, path: D.path[key], item: it.id }, it.title)}<button class="btn small ghost" type="button" data-dtoggle="${esc(it.id)}">${open ? '收起原文' : '展开原文'}</button></div>
    ${more}
  </div>`;
}

async function renderDaily(body, valid = inputTicket(body)) {
  const key = C.tab;
  if (!D.issue[key]) inputStatus(body, '正在读这期日报…');
  try { if (!D.issue[key]) await loadIssue(key, D.path[key]); } catch (err) {
    if (valid()) inputStatus(body, `日报读取失败：${err.message}`, true); return;
  }
  if (!valid() || !D.issue[key]) return;
  const iss = D.issue[key];
  const latest = !iss.history.length || iss.history[0].path === iss.path;
  const note = latest ? (iss.is_today ? '今天这一期' : `今天的还没出，这是最近一期（${iss.day}）`) : `历史一期 · ${iss.day}`;
  const sections = iss.sections.map((s) => {
    if (s.kind === 'markdown') return s.markdown ? `<details class="d-sec md-sec"><summary>${esc(s.name)}</summary><div class="md">${renderMarkdown(s.markdown)}</div></details>` : '';
    let group = null;
    const rows = s.items.map((it) => {
      const head = it.group && it.group !== group ? `<div class="d-group">${esc(it.group)}</div>` : '';
      group = it.group;
      return head + dailyItemHtml(key, it);
    }).join('');
    return `<section class="d-sec"><h3>${esc(s.name)} <small>${s.items.length} 条</small></h3>${rows}</section>`;
  }).join('');
  const hist = iss.history.map((h) => `<button type="button" class="d-hist ${h.path === iss.path ? 'on' : ''}" data-dissue="${esc(h.path)}">${esc(h.day)}</button>`).join('');
  body.innerHTML = tabBar() + `
    <div class="panel d-issue">
      <div class="d-top"><div><div class="d-eyebrow">${esc(note)}</div><h2>${esc(iss.title)}</h2></div>${latest || !iss.history.length ? '' : `<button class="btn small" type="button" data-dissue="${esc(iss.history[0].path)}">回到最新一期</button>`}</div>
      <p class="in-note">每条快讯可「加入选题」，在「我的选题」里点「做这条」。放进去的是那一条的原文（有深读就带上深读），不是整份日报。</p>
      ${sections || '<div class="empty"><b>这一期暂时没有内容</b><span>可以查看历史日报，或稍后回来。</span></div>'}
    </div>
    <details class="panel d-history" ${D.histOpen ? 'open' : ''}><summary>历史日报 <small>${iss.history.length} 期</small></summary><div class="d-hist-list">${hist}</div></details>`;
  bindTabs(body);
  $$('[data-dtoggle]', body).forEach((b) => (b.onclick = () => toggleOriginal(key, b.dataset.dtoggle)));
  $$('[data-dretry]', body).forEach((b) => (b.onclick = () => { D.open[b.dataset.dretry] = false; toggleOriginal(key, b.dataset.dretry); }));
  $$('[data-dpick]', body).forEach((b) => (b.onclick = () => pickDaily(key, b.dataset.dpick)));
  $$('[data-work]', body).forEach((b) => (b.onclick = () => openWork(Number(b.dataset.work))));
  $$('[data-dissue]', body).forEach((b) => (b.onclick = async () => { D.path[key] = b.dataset.dissue; D.issue[key] = null; D.open = {}; D.originals = {}; window.scrollTo(0, 0); renderView(); }));
  const hd = $('.d-history', body); if (hd) hd.ontoggle = () => { D.histOpen = hd.open; };
}

function bindTabs(body) {
  $$('[data-tab]', body).forEach((b) => (b.onclick = () => { C.tab = b.dataset.tab; C.open = null; C.note = null; body.dataset.sig = ''; renderView(); }));
}

async function toggleOriginal(key, id) {
  const path = D.path[key];
  D.open[id] = !D.open[id];
  if (D.originals[id]?.error) delete D.originals[id];
  renderView();
  if (D.open[id] && !D.originals[id]) {
    let original;
    try { original = await api(`/api/vault/daily/original?key=${encodeURIComponent(key)}&path=${encodeURIComponent(path)}&item=${encodeURIComponent(id)}`); }
    catch (err) { original = { body: '', deep: '', error: err.message }; }
    if (D.path[key] !== path) return;
    D.originals[id] = original;
    if (S.view === 'input' && C.tab === key) renderView();
  }
}

async function pickDaily(key, id) {
  D.busy[id] = true; renderView();
  try {
    const r = await api('/api/vault/daily/pick', { method: 'POST', body: { key, path: D.path[key], item: id } });
    toast((r.again ? '已经加入选题' : r.quality === '只有摘要' ? '已加入选题（只找到摘要）' : '已加入选题，带上了原文') + '，在「我的选题」里');
    D.issue[key] = null;
    if (window.refreshBoard) window.refreshBoard();
    if (window.refreshTopics) await window.refreshTopics();
  } catch (err) { toast(err.message); }
  D.busy[id] = false;
  renderView();
}


/* ================= K 线日报：紧凑网格，一个标的一张日线卡 ================= */
const K = { data: null, loadedAt: 0 };

/** 迷你收盘线：closes = [c, ...]。卡片这么小，OHLC 四个点看不清，只剩形态，所以直接画线。 */
function miniLine(closes, w = 160, h = 56) {
  if (!closes || closes.length < 2) return `<svg class="k-svg" viewBox="0 0 ${w} ${h}" aria-label="无数据"></svg>`;
  const hi = Math.max(...closes);
  const lo = Math.min(...closes);
  const rng = hi - lo || 1;
  const padX = 2, padTop = 4, padBot = 4;
  const step = (w - padX * 2 - 3) / (closes.length - 1);
  const x = (i) => padX + i * step;
  const y = (v) => padTop + ((hi - v) / rng) * (h - padTop - padBot);
  const pts = closes.map((c, i) => `${x(i).toFixed(1)} ${y(c).toFixed(1)}`);
  const line = 'M' + pts.join('L');
  const area = `${line}L${x(closes.length - 1).toFixed(1)} ${h}L${x(0).toFixed(1)} ${h}Z`;
  const lx = x(closes.length - 1), ly = y(closes[closes.length - 1]);
  return `<svg class="k-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="最近 ${closes.length} 个交易日收盘价"><path class="a" d="${area}"/><path class="l" d="${line}" vector-effect="non-scaling-stroke"/><circle class="p" cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="1.8"/></svg>`;
}

const kPx = (v) => {
  if (v == null) return '—';
  const a = Math.abs(v);
  return v.toFixed(a >= 1000 ? 0 : a >= 10 ? 2 : a >= 1 ? 3 : 4);
};
const kPct = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`);
const kCls = (v) => (v == null ? '' : v > 0 ? 'up' : v < 0 ? 'dn' : '');

function klineCard(c) {
  const tip = [c.name, c.symbol, c.sector, c.day ? `截至 ${c.day}` : '', c.note].filter(Boolean).join(' · ');
  return `<div class="k-card ${c.behind ? 'behind' : ''}" title="${esc(tip)}">
    <div class="k-top"><b class="k-name">${esc(c.name)}</b><span class="k-chg ${kCls(c.chg1d)}">${kPct(c.chg1d)}</span></div>
    <div class="k-sub"><span>${esc(c.symbol)}${c.behind ? ` · <i class="k-late">${esc((c.day || '').slice(5))}</i>` : ''}</span><span class="num">${kPx(c.close)}</span></div>
    ${miniLine(c.closes)}
    ${c.tags && c.tags.length ? `<div class="k-tags">${c.tags.map((t) => `<span>${esc(t)}</span>`).join('')}</div>` : c.sector ? `<div class="k-sector">${esc(c.sector)}</div>` : ''}
  </div>`;
}

/* X 热榜（10/8）：和 X 页那块是同一个画法（xhot.js）；在这里「收进选题」的会出现在「我收藏的」 */
function renderXHotTab(body) {
  body.innerHTML = tabBar() + '<div id="inXHot"></div>';
  bindTabs(body);
  window.renderXHot($('#inXHot', body));
}

async function renderKline(body, valid = inputTicket(body)) {
  if (!K.data || Date.now() - K.loadedAt > 10 * 60 * 1000) {
    if (!K.data) body.innerHTML = tabBar() + '<div class="panel empty"><span class="spin"></span><span>正在读 K 线…</span></div>';
    bindTabs(body);
    try { K.data = await api('/api/kline/board'); K.loadedAt = Date.now(); }
    catch (err) { if (valid()) inputStatus(body, `K 线读取失败：${err.message}`, true); return; }
  }
  if (!valid()) return;
  const d = K.data;
  const groups = d.groups.map((g) => `<section class="k-group"><h3>${esc(g.label)} <small>${g.items.length}${g.day ? ` · 收盘至 ${esc(g.day.slice(5))}` : ''}</small></h3><div class="k-grid">${g.items.map(klineCard).join('')}</div></section>`).join('');
  body.innerHTML = tabBar() + `<div class="panel k-board">
      <div class="k-head"><div><div class="d-eyebrow">收盘线 · ${d.count} 个标的 · 每组最新收盘日见组名</div>${d.conclusion ? `<h2 class="k-verdict">${esc(d.conclusion)}</h2>` : ''}</div></div>
      ${d.count ? groups : '<div class="empty"><b>还没有 K 线数据</b><span>每天 08:15 数据更新、08:20 出 K 线日报后这里就有了。</span></div>'}
      <p class="in-note">每张卡是最近 120 个交易日的收盘价连线，数字是最近一个已收盘交易日。数据每天 08:15、10:00、17:00 更新；比同组晚一天的卡会标出日期。鼠标停在卡片上看宏观的一句话结论。</p>
    </div>`;
  bindTabs(body);
}


/* ---------- 流量视频：看到就想复刻的单条视频（swipe.py）。10/5 作者：从进项拆出来，左边单独一项 ---------- */
const SW = { data: null, timer: null, playing: null };
const SW_STATUS = { saved: '存着', making: '在复刻', shipped: '发了', downloading: '下载中', failed: '没下下来' };

function swipeCard(v, collections) {
  const stats = [['赞', v.likes], ['藏', v.collects], ['转', v.shares], ['评', v.comments]].filter(([, n]) => n != null).map(([l, n]) => `${l} ${fmt(n)}`).join(' · ');
  const media = v.status === 'downloading' ? '<div class="sw-ph"><span class="spin"></span><small>下载中…</small></div>'
    : v.status === 'failed' ? `<div class="sw-ph bad"><small>${esc(v.error || '没下下来')}</small><button class="btn small" type="button" data-sw-retry="${v.id}">重试</button></div>`
      : SW.playing === v.id && v.video ? `<video src="${v.video}" controls autoplay playsinline></video>`
        : `<button type="button" class="sw-cover" data-sw-play="${v.id}" ${v.video ? '' : 'disabled'}>${v.cover ? `<img src="${v.cover}" alt="" loading="lazy">` : '<span class="sw-ph"><small>没有封面</small></span>'}${v.video ? '<i>▶</i>' : ''}</button>`;
  const ready = ['saved', 'making', 'shipped'].includes(v.status);
  return `<article class="sw-card s-${v.status}" data-sw="${v.id}">
    <div class="sw-media">${media}</div>
    <div class="sw-body">
      <div class="sw-top"><span class="pill ${v.status === 'saved' ? 'mid' : v.status === 'failed' ? 'low' : 'hot'}">${SW_STATUS[v.status]}</span><small>${esc(v.platform_label)}${v.author ? ' · ' + esc(v.author) : ''}</small>
        <a href="${esc(v.url)}" target="_blank" rel="noopener" title="打开原视频">↗</a><button type="button" class="linklike" data-sw-del="${v.id}" title="删掉这条和它的视频文件" aria-label="删掉">×</button></div>
      <b class="sw-title">${esc(v.title || v.url)}</b>
      ${stats ? `<small class="sw-stats">${stats}</small>` : ''}
      <input class="sw-note" data-sw-note="${v.id}" maxlength="300" placeholder="我为什么想转它？一句话" value="${esc(v.note)}" autocomplete="off">
      <label class="sw-col">换成我的，归哪个合集
        <select data-sw-col="${v.id}"><option value="">还没想</option>${collections.map((c) => `<option ${c === v.collection ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label>
      ${!ready ? '' : v.topic ? `<button class="btn small" type="button" data-sw-open="${v.topic.id}">${v.status === 'shipped' ? '复刻的那条 →' : '接着做 →'}</button>`
        : `<button class="btn small primary" type="button" data-sw-start="${v.id}">开始复刻</button>`}
    </div></article>`;
}

async function renderSwipe(body) {
  try { SW.data = await api('/api/swipe'); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
  const d = SW.data;
  if (document.activeElement && body.contains(document.activeElement) && document.activeElement.matches('input, select') && body.querySelector('.sw-grid')) return;
  const sig = JSON.stringify([d, SW.playing]);
  if (body.dataset.sig === 'sw' + sig) return;
  body.dataset.sig = 'sw' + sig;
  const navSwipe = $('#navSwipe');  // 10/19 起左栏没有流量视频这一项
  if (navSwipe) navSwipe.textContent = d.videos.filter((v) => v.status === 'saved').length || '';
  body.innerHTML = `<div class="panel sw-panel">
      <form class="sw-add" id="swAdd"><input id="swUrl" placeholder="贴一条视频链接（抖音、X、小红书），回车就存下来" autocomplete="off"><button class="btn primary" type="submit">存下来</button></form>
      <p class="in-note">看到就想转、想复刻的视频放这里。存的时候就把视频下到本机：这类视频常被删，而且复刻要看的是画面。抖音的用你的登录下，今天还能存 ${d.douyin_left} 条（一天最多 ${d.douyin_cap} 条）；X、小红书不限。</p>
      ${d.videos.length ? `<div class="sw-grid">${d.videos.map((v) => swipeCard(v, d.collections)).join('')}</div>`
        : '<div class="empty"><b>还没有存</b><span>刷到一条你一看就想转的，把链接贴在上面。</span></div>'}
    </div>`;
  const again = () => { body.dataset.sig = ''; renderView(); };
  const act = async (fn) => { try { await fn(); } catch (err) { toast(err.message); } again(); };
  $('#swAdd').onsubmit = (e) => { e.preventDefault(); const url = $('#swUrl').value.trim(); if (!url) return; $('#swUrl').value = ''; act(() => api('/api/swipe', { method: 'POST', body: { url } })); };
  $$('[data-sw-play]', body).forEach((b) => (b.onclick = () => { SW.playing = Number(b.dataset.swPlay); again(); }));
  $$('[data-sw-retry]', body).forEach((b) => (b.onclick = () => act(() => api(`/api/swipe/${b.dataset.swRetry}/retry`, { method: 'POST' }))));
  $$('[data-sw-del]', body).forEach((b) => (b.onclick = () => {
    if (b.dataset.armed) { act(() => api(`/api/swipe/${b.dataset.swDel}`, { method: 'DELETE' })); return; }
    b.dataset.armed = '1'; b.textContent = '再点一次删掉'; setTimeout(() => { if (document.body.contains(b)) { delete b.dataset.armed; b.textContent = '×'; } }, 3000);
  }));
  $$('[data-sw-note]', body).forEach((i) => (i.onchange = () => act(() => api(`/api/swipe/${i.dataset.swNote}`, { method: 'PATCH', body: { note: i.value } }))));
  $$('[data-sw-col]', body).forEach((sel) => (sel.onchange = () => act(() => api(`/api/swipe/${sel.dataset.swCol}`, { method: 'PATCH', body: { collection: sel.value } }))));
  $$('[data-sw-start]', body).forEach((b) => (b.onclick = () => act(async () => { await api(`/api/swipe/${b.dataset.swStart}/start`, { method: 'POST' }); toast('建成选题了，在「我的选题」里点「做这条」'); })));
  $$('[data-sw-open]', body).forEach((b) => (b.onclick = () => { location.hash = `#work/${b.dataset.swOpen}`; go(readHash(), { push: false }); }));
  clearTimeout(SW.timer);
  if (d.videos.some((v) => v.status === 'downloading')) SW.timer = setTimeout(() => { if (S.view === 'swipe') renderView(); }, 4000);
}


/* ---------- 老师 / 对标：他们新发的视频，作者自己去看（9/30） ----------
 * 不下载、不拆，照样全列；10/4 起标出「平时的几倍」，1.5 倍以上的排最上面。「去看」打开抖音，只记成点开过，行留在原地；只有点「看过了」才下去；老师的可以记一句学到什么；对标的可以点「想复刻」
 * 存进流量视频；哪一栏都能点「拆解」——点了才拆。 */
const FD = { data: null, days: 7, showSeen: false };

function feedRow(v, kind) {
  const when = v.published_at ? new Date(v.published_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
  const dur = v.duration_seconds ? `${Math.floor(v.duration_seconds / 60)}:${String(Math.round(v.duration_seconds % 60)).padStart(2, '0')}` : '';
  const torn = v.has_report ? `<button class="btn small" type="button" data-fd-report="${esc(v.video_id)}">看拆解</button>`
    : v.job && !['done', 'failed'].includes(v.job.stage) ? '<span class="fd-tag"><span class="spin"></span> 拆解中</span>'
      : `<button class="btn small ghost" type="button" data-fd-tear="${esc(v.video_id)}">拆解</button>`;
  const copy = kind !== 'benchmark' ? '' : v.swipe_id ? '<span class="fd-tag ok">在流量视频里</span>'
    : `<button class="btn small ghost" type="button" data-fd-swipe="${esc(v.url)}">想复刻</button>`;
  return `<div class="fd-row ${v.seen_at ? 'seen' : ''}" data-fd="${esc(v.video_id)}">
    <div class="fd-meta"><b>${esc(v.account)}${v.hot ? ` <i class="fd-hot" title="点赞 ${fmt(v.likes)}，这个号平时（中位数）${fmt(Math.round(v.account_median))}">${v.multiple}× 平时</i>` : ''}${v.opened_at && !v.seen_at ? ' <i class="fd-opened">点开过</i>' : ''}</b><small>${esc(when)}${dur ? ' · ' + dur : ''}${v.likes != null ? ' · ' + fmt(v.likes) + ' 赞' : ''}${v.multiple != null && !v.hot ? ` · 平时的 ${v.multiple} 倍` : ''}${v.is_image_post ? ' · 图文' : ''}</small></div>
    <div class="fd-title">${esc(cleanTitle(v.title) || '（没有标题）')}</div>
    <div class="fd-acts">
      <a class="btn small ${v.seen_at || v.opened_at ? '' : 'primary'}" href="${esc(v.url)}" target="_blank" rel="noopener" data-fd-open="${esc(v.video_id)}">${v.opened_at ? '再看 ↗' : '去看 ↗'}</a>
      <button class="btn small ghost" type="button" data-fd-seen="${esc(v.video_id)}" data-to="${v.seen_at ? '0' : '1'}">${v.seen_at ? '标成没看' : '看过了'}</button>
      ${copy}${torn}${xcBtn({ kind: 'feed', url: v.url, title: cleanTitle(v.title), author: v.account }, cleanTitle(v.title) || v.account)}
    </div>
    ${kind === 'teacher' ? `<input class="fd-note" data-fd-note="${esc(v.video_id)}" maxlength="300" placeholder="学到什么？记一句" value="${esc(v.note)}" autocomplete="off">` : v.note ? `<small class="fd-noted">${esc(v.note)}</small>` : ''}
  </div>`;
}

async function renderFeed(body, kind, valid = inputTicket(body)) {
  if (!body.querySelector?.('.fd-panel') || body.dataset.feedKind !== kind) inputStatus(body, '正在读新作品…');
  let d;
  try { d = await api(`/api/feed?days=${FD.days}`); } catch (err) { if (valid()) inputStatus(body, `作品读取失败：${err.message}`, true); return; }
  if (!valid()) return;
  FD.data = d;
  body.dataset.feedKind = kind;
  if (document.activeElement && body.contains(document.activeElement) && document.activeElement.matches('input')) return;
  const sig = 'fd' + JSON.stringify([kind, d, FD.showSeen]);
  if (body.dataset.sig === sig) return;
  body.dataset.sig = sig;
  const rows = d[kind];
  const unseen = rows.filter((r) => !r.seen_at), seen = rows.filter((r) => r.seen_at);
  const who = d.accounts[kind];
  const label = kind === 'teacher' ? '老师' : '对标';
  body.innerHTML = tabBar() + `<div class="panel fd-panel">
      <div class="fd-head"><div><b>${label}新发的 · ${unseen.length} 条没看</b>
        <small>${who.length ? esc(who.join('、')) : `还没有${label}`} · 每天 9:30 查一次有没有新发的</small></div>
        <div class="seg-toggle" role="group" aria-label="时间">${[[3, '3 天'], [7, '7 天'], [30, '30 天']].map(([n, l]) => `<button type="button" class="${FD.days === n ? 'on' : ''}" data-fd-days="${n}">${l}</button>`).join('')}</div></div>
      <p class="in-note">${kind === 'teacher' ? '老师是来学东西的：去看，学到什么记一句，没用的点「看过了」。' : '对标是看他在做什么：去看，值得照着做一条就点「想复刻」存进流量视频，没用的点「看过了」。'}点赞到这个号平时 1.5 倍以上的标出倍数、排在最上面，其余照发布时间；照样全列，不自动拆，想拆点那条的「拆解」。谁是老师谁是对标，在上面「老师和对标」里改。</p>
      ${unseen.length ? unseen.map((v) => feedRow(v, kind)).join('') : `<div class="empty"><b>${rows.length ? '都看过了' : `这 ${FD.days} 天${label}没有发新的`}</b></div>`}
      ${seen.length ? `<button class="btn quiet fd-more" type="button" id="fdMore">${FD.showSeen ? '收起' : `看过的 ${seen.length} 条`}</button>${FD.showSeen ? seen.map((v) => feedRow(v, kind)).join('') : ''}` : ''}
    </div>`;
  bindTabs(body);
  const again = () => { body.dataset.sig = ''; renderView(); };
  const act = async (fn) => { try { await fn(); } catch (err) { toast(err.message); } again(); };
  const mark = (id, payload) => api(`/api/feed/${id}`, { method: 'PUT', body: payload });
  $$('[data-fd-days]', body).forEach((b) => (b.onclick = () => { FD.days = Number(b.dataset.fdDays); again(); }));
  // 点「去看」只记成点开过，这一行留在原地：看完要复刻、要拆解还得在这儿点。没用的他自己点「看过了」。
  $$('[data-fd-open]', body).forEach((a) => a.addEventListener('click', () => { act(() => mark(a.dataset.fdOpen, { opened: true })); }));
  $$('[data-fd-seen]', body).forEach((b) => (b.onclick = () => act(() => mark(b.dataset.fdSeen, { seen: b.dataset.to === '1' }))));
  $$('[data-fd-note]', body).forEach((i) => (i.onchange = () => act(() => mark(i.dataset.fdNote, { note: i.value }))));
  $$('[data-fd-swipe]', body).forEach((b) => (b.onclick = () => act(async () => { await api('/api/swipe', { method: 'POST', body: { url: b.dataset.fdSwipe } }); toast('存进流量视频了，正在下载'); })));
  $$('[data-fd-tear]', body).forEach((b) => (b.onclick = () => act(async () => { await api('/api/jobs', { method: 'POST', body: { video_id: b.dataset.fdTear, source: label } }); toast('排进拆解了，几分钟后能看'); })));
  $$('[data-fd-report]', body).forEach((b) => (b.onclick = () => { S.reportId = b.dataset.fdReport; go('report'); }));
  const more = $('#fdMore');
  if (more) more.onclick = () => { FD.showSeen = !FD.showSeen; again(); };
}

window.VIEWS.swipe = { render: () => renderSwipe($('#swipeBody')) };
