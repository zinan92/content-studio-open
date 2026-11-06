'use strict';

/* ================= helpers ================= */
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (n) => {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const v = Number(n);
  if (Math.abs(v) >= 10000) return (v / 10000).toFixed(v >= 100000 ? 0 : 1).replace(/\.0$/, '') + '万';
  return Math.round(v).toLocaleString('en-US');
};
const pct = (v, digits = 1) => (v === null || v === undefined ? '—' : (v * 100).toFixed(digits) + '%');
const mmss = (s) => {
  if (s === null || s === undefined) return '—';
  const t = Math.max(0, Math.floor(s));
  return Math.floor(t / 60) + ':' + String(t % 60).padStart(2, '0');
};
const day = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
};
const cleanTitle = (t) => {
  const text = String(t || '').replace(/#[^\s#]+/g, '').replace(/\s+/g, ' ').trim();
  return text || String(t || '').trim() || '（无标题）';
};
const ago = (iso) => {
  if (!iso) return '从未同步';
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return '刚刚同步';
  if (mins < 60) return `${mins} 分钟前同步`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} 小时前同步`;
  return `${Math.round(mins / 1440)} 天前同步`;
};

function toast(message) {
  const t = $('#toast');
  t.textContent = message;
  t.classList.add('show');
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove('show'), 2600);
}

async function api(path, options = {}) {
  const init = { ...options, headers: { 'Content-Type': 'application/json', 'X-Content-Studio': '1', ...(options.headers || {}) } };
  if (init.body && typeof init.body !== 'string') init.body = JSON.stringify(init.body);
  let res;
  try {
    res = await fetch(path, init);
  } catch (err) {
    throw new Error('连不上本机服务：请确认终端里的 content-studio serve 还在运行');
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) {
    const detail = data && (data.error || data.detail);
    throw new Error(typeof detail === 'string' ? detail : `请求失败（${res.status}）`);
  }
  return data;
}

const STAGES = [
  ['downloading', '下载'],
  ['transcribing', '转文字'],
  ['analyzing', '结构拆解'],
  ['done', '报告'],
];
const STAGE_INDEX = { queued: -1, downloading: 0, transcribing: 1, analyzing: 2, done: 4, failed: -2 };
const STAGE_NAME = { queued: '排队中', downloading: '下载中', transcribing: '转文字中', analyzing: '拆解中', done: '已完成', failed: '失败' };

function teardownButton(item, { source } = {}) {
  if (item.has_report) return `<button class="btn small primary" type="button" data-report="${esc(item.video_id)}">看报告</button>`;
  const job = item.job;
  if (job && job.stage !== 'failed') {
    const cls = job.stage === 'queued' ? 'queued' : 'running';
    return `<span class="stage-pill ${cls}">${STAGE_NAME[job.stage] || job.stage}</span>`;
  }
  const label = job && job.stage === 'failed' ? '重新拆解' : '拆解';
  return `<button class="btn small" type="button" data-enqueue="${esc(item.video_id)}" data-source="${esc(source || '')}">${label}</button>`;
}

function bindTeardownButtons(root) {
  $$('[data-report]', root).forEach((b) => (b.onclick = () => openReport(b.dataset.report)));
  $$('[data-enqueue]', root).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try {
      const res = await api('/api/jobs', { method: 'POST', body: { video_id: b.dataset.enqueue, source: b.dataset.source || undefined } });
      toast(res.message);
      await refreshAll();
    } catch (err) {
      toast(err.message);
      b.disabled = false;
    }
  }));
}

/* ================= state & routing ================= */
window.VIEWS = window.VIEWS || {};
const CORE_VIEWS = ['mine', 'radar', 'report', 'settings'];
// 10/5 作者：老师和对标、拆解报告是东西进来的地方，归「进项」；「已发出」只看自己发了什么、数据怎么样。
const INPUT_FAMILY = ['input', 'radar', 'report'];
// 10/19 作者：战况和汇总并成「复盘」（view 还叫 today，首页），抖音作品分析是它的子页。
const OUTPUT_FAMILY = ['today', 'mine', 'plats'];  // 10/20 平台页的数据归「盘」：各平台一页列出来，点进去是那个平台
const PLATFORM_KEYS = ['douyin', 'channels', 'xiaohongshu', 'x', 'youtube', 'bilibili', 'others'];
const SUBNAV = {
  // 10/20 走查：选题以前两排页签（上排「进来的…」、下排又有「我的选题」「老师」「对标」）。现在一排：我的选题在最前
  in: [['input@mine', '我的选题'], ['input@feed', '进来的'], ['radar', '老师和对标名单'], ['report', '拆解报告']],
  out: [['today', '复盘'], ['plats', '各平台'], ['mine', '抖音作品分析']],
};
const S = {
  view: 'today',
  platformKey: 'douyin',   // 平台页：看哪个平台
  portalKey: 'github',     // 门户页：GitHub 还是网站
  productKey: null,        // 作品页：看哪一个（空 = 第一个）
  platformTopic: null,     // 平台页：从「今天」或「标题和封面」点过来时先滚到哪条
  workId: null,
  packId: null,
  accountId: (() => { try { return Number(localStorage.getItem('cs-account')) || null; } catch (_) { return null; } })(),
  state: null,
  mine: null,
  accounts: [],
  followed: { posts: [] },
  platforms: [],
  standard: null,
  outliers: [],
  jobs: [],
  reports: [],
  reportId: null,
  report: null,
  sort: 'multiple',
  radarDays: 7,
  radarAccount: null,   // 点了哪个对标账号：只看它
  radarScope: 'hot',    // hot 只看爆款 / all 全部作品
  radarQuery: '',
  radarVideos: {},      // accountId → 全部作品（切到「全部作品」时按需拉）
  mineSort: { key: 'published_at', dir: -1 },
  addMode: 'benchmark',
};

/* 试用版（10/8，#526）：/api/state.edition 说关了哪些（表在 edition.py）。带 data-feature 的入口藏起来，关掉的页回到今天。 */
const featureOn = (key) => !(((S.state || {}).edition || {}).off || []).includes(key);
window.featureOn = featureOn;
window.platformOff = (key) => (((S.state || {}).edition || {}).platforms_off || []).includes(key);
const VIEW_FEATURE = { portal: 'portal', products: 'products', consults: 'consults', positioning: 'positioning' };
const viewOff = (view) => Boolean(S.state) && ((VIEW_FEATURE[view] && !featureOn(VIEW_FEATURE[view])) || (view === 'platform' && ['others', 'youtube', 'bilibili'].includes(S.platformKey) && !featureOn('others')));
function applyEdition() {
  $$('[data-feature]').forEach((el) => { if (!featureOn(el.dataset.feature)) el.hidden = true; });
  const brand = $('[data-brand-link]');
  if (brand && !featureOn('positioning')) { brand.onclick = null; brand.removeAttribute('title'); brand.classList.add('static'); }
  if (typeof SET !== 'undefined' && !featureOn(SET.tab)) SET.tab = 'general';
  if (viewOff(S.view)) go('today', { push: false });
}

function railKey(view) {
  if (INPUT_FAMILY.includes(view)) return 'input';
  if (OUTPUT_FAMILY.includes(view) || view === 'platform') return 'today';  // 10/20：平台的数据在「盘」里看
  return view;
}
// 左栏 找 写 剪 发 盘 里哪个亮：写和剪是同一页（work）的两半，按现在开的是哪个页签
function zxKey(view) {
  if (view === 'work') return typeof VD !== 'undefined' && VD.tab === 'edit' ? 'cut' : 'write';
  if (view === 'pack') return 'fa';
  return null;
}

function paintChrome(view) {
  const key = railKey(view);
  const zx = zxKey(view);
  $$('.rail [data-view]').forEach((b) => { const active = zx ? b.dataset.zx === zx : b.dataset.view === key && (!b.dataset.key || b.dataset.key === (key === 'portal' ? S.portalKey : key === 'products' ? S.productKey : S.platformKey)); b.classList.toggle('on', active); if (active) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current'); });
  document.body.dataset.stage = ($(`#v-${view}`) || {}).dataset ? $(`#v-${view}`).dataset.stage : '';
  $$('.view').forEach((s) => s.classList.toggle('on', s.id === 'v-' + view));
  $$('[data-subnav]').forEach((nav) => {
    const subOn = (k) => { const [v, sub] = k.split('@'); return v === view && (!sub || (sub === 'mine') === (typeof C !== 'undefined' && C.tab === 'mine')); };
    nav.innerHTML = (SUBNAV[nav.dataset.subnav] || []).map(([k, l]) => `<button type="button" class="${subOn(k) ? 'on' : ''}" data-sub="${k}">${l}${k === 'report' && S.reports.length ? ` <span class="num">${S.reports.filter((r) => !r.archived_at).length || ''}</span>` : ''}</button>`).join('');
    $$('[data-sub]', nav).forEach((b) => (b.onclick = () => {
      const [v, sub] = b.dataset.sub.split('@');
      if (sub) window.openInputTab(sub === 'mine' ? 'mine' : (typeof C !== 'undefined' && C.tab !== 'mine' ? C.tab : 'all'));
      else go(v);
    }));
  });
}

const WORK_ORIGINS = WorkbenchUI.createWorkOrigins();
let navigationRevision = 0;
const VIEW_SCROLLS = new Map();
window.captureWorkOrigin = (id) => WORK_ORIGINS.capture(id, { view: S.view, hash: location.hash, scrollY: window.scrollY });
window.workReturnLabel = (id) => WORK_ORIGINS.label(id);
window.returnFromWork = (id) => {
  const origin = WORK_ORIGINS.get(id);
  if (location.hash !== origin.hash) history.pushState(null, '', origin.hash);
  go(readHash(), { push: false, restoreScroll: origin.scrollY });
};

function go(view, { push = true, restoreScroll = null } = {}) {
  const revision = ++navigationRevision;
  if (S.routeHash) VIEW_SCROLLS.set(S.routeHash, window.scrollY);
  if (!push && restoreScroll === null && VIEW_SCROLLS.has(location.hash)) restoreScroll = VIEW_SCROLLS.get(location.hash);
  view = OLD_ROUTES[view] || view;
  if (viewOff(view)) { view = 'today'; if (location.hash !== '#today') history.replaceState(null, '', '#today'); }
  S.view = view;
  paintChrome(view);
  if (push) {
    const hash = view === 'report' && S.reportId ? `#report/${S.reportId}` : view === 'work' && S.workId ? `#work/${S.workId}` : view === 'pack' && S.packId ? `#pack/${S.packId}`
      : view === 'platform' ? `#platform/${S.platformKey}${S.platformTopic ? `/${S.platformTopic}` : ''}` : view === 'portal' ? `#portal/${S.portalKey}` : view === 'products' && S.productKey ? `#products/${S.productKey}` : view === 'settings' && typeof SET !== 'undefined' ? `#settings/${SET.tab}`
      : view === 'positioning' && typeof POS !== 'undefined' ? `#positioning/${POS.tab}` : `#${view}`;
    if (location.hash !== hash) { if (S.replaceNext) history.replaceState(null, '', hash); else history.pushState(null, '', hash); }
  }
  S.replaceNext = false;
  S.routeHash = location.hash;
  window.scrollTo(0, 0);
  const rendered = renderView();
  if (restoreScroll !== null) Promise.resolve(rendered).then(() => {
    requestAnimationFrame(() => { if (revision === navigationRevision) window.scrollTo(0, restoreScroll); });
  }).catch(() => { /* renderer displays its own failure; keep current page */ });
}

// 旧书签：打包、发布、已发出、X 线这些站 10/6 起拆进了各平台页和汇总；旧的 #publish/#backfill/#output/#xline 都有地方落。
const OLD_ROUTES = { brief: 'board', topics: 'board', video: 'board', article: 'board', hot: 'board', collect: 'input', weekly: 'today', queue: 'report', skills: 'settings',
  output: 'today', backfill: 'today', kpi: 'today', summary: 'today', schedule: 'input' };  // 10/13 战况就是首页；10/19 汇总并进来叫复盘；10/19 排期拿掉，落到选题（默认「我的选题」）

function readHash() {
  let [view, id, id2] = location.hash.replace(/^#/, '').split('/');
  if (view === 'publish') { S.platformKey = 'douyin'; S.platformTopic = id ? Number(id) : null; view = 'platform'; id = null; }
  else if (view === 'xline') { S.platformKey = 'x'; S.platformTopic = null; view = 'platform'; id = null; }
  else view = OLD_ROUTES[view] || view; // old bookmarks
  if (view === 'platform') {
    if (id && PLATFORM_KEYS.includes(id)) S.platformKey = id;
    S.platformTopic = id2 ? Number(id2) : null;
  }
  if (view === 'portal' && ['github', 'site'].includes(id)) S.portalKey = id;
  if (view === 'products') S.productKey = id || null;
  if (view === 'report' && id) S.reportId = id;
  if (view === 'settings' && id && typeof SET !== 'undefined' && SET_TABS.includes(id)) SET.tab = id;
  if (view === 'positioning' && id && typeof POS !== 'undefined' && (window.POS_TAB_KEYS || []).includes(id)) POS.tab = id;
  if (view === 'pack') S.packId = id ? Number(id) : null;
  if (view === 'work') {
    if (!id) return 'board';
    S.workId = Number(id);
  }
  if (!view) return 'today'; // 9/29 作者：打开工作台先看「今天」，现在做哪一件
  return [...CORE_VIEWS, ...Object.keys(window.VIEWS)].includes(view) ? view : 'board';
}

window.bindNav = bindNav;
function bindNav() {
  $$('.rail [data-view]').forEach((b) => (b.onclick = () => {
    if (['write', 'cut', 'fa'].includes(b.dataset.zx)) { window.goStage(b.dataset.zx); return; }
    if (b.dataset.view === 'portal') S.portalKey = b.dataset.key;
    else if (b.dataset.view === 'products') S.productKey = b.dataset.key || null;
    else if (b.dataset.key) { S.platformKey = b.dataset.key; S.platformTopic = null; }
    go(b.dataset.view);
  }));
  // 单点功能是单独一页（/tools），新开一个标签，不进工作台的页面切换
  $$('.rail [data-open]').forEach((b) => (b.onclick = () => window.open(b.dataset.open, '_blank')));
}
/* 从「今天」「标题和封面」这类地方跳到某个平台页，顺便指着那一条 */
window.goPlatform = (key, topicId) => { S.platformKey = PLATFORM_KEYS.includes(key) ? key : 'douyin'; S.platformTopic = topicId || null; go('platform'); };
window.addEventListener('popstate', () => go(readHash(), { push: false }));

$('#themeBtn').onclick = () => {
  const r = document.documentElement;
  const dark = r.dataset.theme ? r.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  r.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('cs-theme', r.dataset.theme); } catch (_) { /* ignore */ }
};
try { const t = localStorage.getItem('cs-theme'); if (t) document.documentElement.dataset.theme = t; } catch (_) { /* ignore */ }

/* ================= data loading ================= */
async function refreshAll() {
  const refreshVersion = S.refreshVersion = (S.refreshVersion || 0) + 1;
  const threshold = S.state ? S.state.settings.threshold : undefined;
  const [state, mine, accounts, followed, platforms, jobs, reports] = await Promise.all([
    api('/api/state'),
    api('/api/mine' + (S.accountId ? `?account_id=${S.accountId}` : '')),
    api('/api/accounts'),
    api('/api/followed/posts'),
    api('/api/platforms'),
    api('/api/jobs'),
    api('/api/reports'),
  ]);
  if (refreshVersion !== S.refreshVersion) return;
  S.state = state;
  S.mine = mine;
  S.accounts = accounts;
  S.followed = followed;
  S.platforms = platforms.platforms || [];
  S.jobs = jobs;
  S.reports = reports;
  S.outliers = await api('/api/outliers' + (threshold ? `?threshold=${state.settings.threshold}` : ''));
  renderChrome();
  renderView();
  if (typeof loadBoard === 'function') loadBoard(false).catch(() => { /* 左栏的写剪发标记下次再画 */ });
  if (window.refreshTodayBadge && S.view !== 'today') window.refreshTodayBadge();
}

function renderChrome() {
  const st = S.state;
  const banner = [];
  // 10/6：第一次装的人看到的不是两条红色报错，是「开始用」三步，都在这页上做
  if (setupNeeded(st)) banner.push(setupCard(st));
  const stopped = st.last_full_sync && (st.last_full_sync.stopped || st.last_full_sync.error);
  if (stopped) banner.push(`<div class="banner warn"><div><b>上次同步中断：</b>${esc(stopped)}</div></div>`);
  const gb = $('#globalBanner');
  const setupPanel = $('#setupCard', gb), setupFile = setupPanel ? $('#suCookieFile', setupPanel) : null;
  // A selected file belongs to its native input. Polling must not replace that node after focus moves.
  const setupPending = setupPanel && setupNeeded(st) && (Boolean(setupFile?.files.length) || Object.values(setupCard.state?.saving || {}).some(Boolean));
  if (!setupPending && !(gb.contains(document.activeElement) && document.activeElement.matches('input'))) {
    gb.innerHTML = banner.length ? `<div style="display:flex;flex-direction:column;gap:10px;margin:0 0 18px;max-width:1180px">${banner.join('')}</div>` : '';
    bindSetup(gb);
  }
  renderPlatformStrip();
  applyBrand(S.state.brand);
  applyEdition();
  const failedJobs = S.jobs.filter((j) => j.stage === 'failed').length;
  $('#qSummary').textContent = `${st.active_jobs ? `${st.active_jobs} 条进行中` : '没有进行中的'}${failedJobs ? ` · ${failedJobs} 条失败` : ''}`;
  paintChrome(S.view);
  $$('[data-sync-all]').forEach((b) => { b.disabled = st.full_sync_running || st.benchmarks_running; b.textContent = st.full_sync_running ? '同步中…' : '同步全部账号'; });
  $$('[data-sync-bench]').forEach((b) => { b.disabled = st.full_sync_running || st.benchmarks_running; b.textContent = st.benchmarks_running ? '同步中…' : '同步老师和对标'; });
  $('#syncState').innerHTML = st.full_sync_running ? '<span class="spin"></span><span>正在同步你自己的账号</span>'
    : st.benchmarks_running ? `<span class="spin"></span><span>正在同步 ${st.benchmark_count} 个对标账号</span>`
    : `<span class="dot"></span><span>${st.active_jobs} 个拆解进行中</span>`;
  const thr = $('#thr');
  if (document.activeElement !== thr) {
    thr.value = st.settings.threshold;
    $('#thrV').textContent = st.settings.threshold + '×';
  }
}


const PLAT_STATE = { linked: '已连接', ready: '凭据就绪', stale: '要重新登录', blocked: '平台限制了', setup: '差一步配置', manual: '手动发布' };

/** 左下角的平台条。10/20 走查：一排小图标新人看不出是登录状态，还像和上面的平台重复。
 *  现在平时什么都不显示；哪个平台要重新登录 / 差一步配置，才出一行，点了去那个平台的页。 */
function renderPlatformStrip() {
  const box = $('#platStrip');
  if (!box) return;
  const bad = S.platforms.filter((p) => p.on !== false && (['stale', 'setup'].includes(p.state) || p.alert));
  box.innerHTML = bad.map((p) => `<button type="button" class="plat-alert" data-plat-alert="${esc(p.key)}" title="${esc(p.note || '')}">${esc(p.label)} · ${esc(p.alert || PLAT_STATE[p.state])}${p.can_login && p.state === 'stale' ? '，点这里重新登录' : ''}</button>`).join('');
  $$('[data-plat-alert]', box).forEach((b) => (b.onclick = () => {
    const p = S.platforms.find((x) => x.key === b.dataset.platAlert) || {};
    if (p.can_login && p.state === 'stale') window.reconnect(p.key); else window.goPlatform(p.key);
  }));
}

/* 10/20 作者：「每一个 channel 连不上的话，给用户一个提示，让他去 reconnect」。
   哪里报连不上（左下角、复盘顶上、「发」表里没发成的那一行）都点到这一个框：开登录窗口 → 他扫码 → 这里自己看着登没登好。
   抖音登好了顺手再读一遍作品；B 站、YouTube 登好了，后台会把刚才没发出去的再发一遍。 */
window.reconnect = async (key) => {
  const p = (S.platforms || []).find((x) => x.key === key) || { label: key };
  const url = key === 'douyin' ? '/api/douyin/login' : `/api/platforms/${key}/login`;
  let dlg = $('#rcDlg');
  if (!dlg) { dlg = document.createElement('dialog'); dlg.id = 'rcDlg'; dlg.className = 'rc-dlg'; document.body.append(dlg); }
  let timer = null;
  const paint = (st) => {
    const done = st.state === 'ok', failed = st.state === 'failed';
    dlg.innerHTML = `<div class="rc-box"><h3>重新连接${esc(p.label)}</h3>
      <p class="rc-msg ${failed ? 'bad' : done ? 'ok' : ''}">${st.state === 'running' ? '<span class="spin"></span> ' : ''}${esc(st.message || '')}</p>
      ${st.state === 'running' ? `<small>弹出来的是工作台自己的浏览器窗口，不是你平时用的 Chrome。在里面用${esc(p.label)} App 扫码就行。</small>` : ''}
      <div class="rc-acts">${failed ? '<button class="btn primary" type="button" data-rc-again>再试一次</button>' : ''}<button class="btn${done ? ' primary' : ''}" type="button" data-rc-close>${done ? '好了' : st.state === 'running' ? '先关掉这个框（窗口照样开着）' : '关掉'}</button></div></div>`;
    $('[data-rc-close]', dlg).onclick = () => { clearTimeout(timer); dlg.close(); };
    const again = $('[data-rc-again]', dlg); if (again) again.onclick = () => { clearTimeout(timer); window.reconnect(key); };
  };
  const follow = async (st) => {
    paint(st);
    if (st.state === 'running') { timer = setTimeout(async () => { if (!dlg.open) return; try { follow(await api(url)); } catch (_) { follow(st); } }, 2000); return; }
    if (st.state === 'ok') {
      if (key === 'douyin') { try { await api('/api/sync', { method: 'POST' }); } catch (_) { /* 同步在跑也没关系 */ } }
      try { await refreshAll(); } catch (_) { /* 下一轮会刷 */ }
    }
  };
  paint({ state: 'running', message: '正在打开登录窗口…' });
  if (!dlg.open) dlg.showModal();
  try { follow(await api(url, { method: 'POST' })); } catch (err) { follow({ state: 'failed', message: err.message }); }
};
document.addEventListener('click', (e) => { const b = e.target.closest && e.target.closest('[data-reconnect]'); if (b) { e.preventDefault(); window.reconnect(b.dataset.reconnect); } });

/* 「同步全部账号」= 你自己的全部账号；对标只在对标雷达页单独同步（9/29 作者：别占抖音额度）。 */
async function syncAll(btn, path = '/api/sync') {
  if (btn) btn.disabled = true;
  try {
    const res = await api(path, { method: 'POST' });
    toast(res.message);
    await refreshAll();
  } catch (err) { toast(err.message); if (btn) btn.disabled = false; }
}
$$('[data-sync-all]').forEach((b) => (b.onclick = () => syncAll(b)));
$$('[data-sync-bench]').forEach((b) => (b.onclick = () => syncAll(b, '/api/sync/benchmarks')));

/* 10/8 作者：让页面「动起来」——只在切到一页的头一秒半：卡片依次浮现、大数字从 0 数上去、柱子长出来。
   之后的轮询刷新不再动，读的时候不晃；系统设了「减少动态效果」就全不动。 */
const MOTION = { view: null, until: 0, seen: new WeakSet(), timer: null };
const reducedMotion = () => Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
function armEntrance() {
  const main = document.querySelector('main');
  if (!main || reducedMotion()) return;
  MOTION.until = performance.now() + 1500;
  main.classList.add('is-entering');
  clearTimeout(MOTION.timer);
  MOTION.timer = setTimeout(() => main.classList.remove('is-entering'), 1500);
}
function countUp(el) {
  const text = el.textContent.trim();
  const m = text.match(/^([\d,]+(?:\.\d+)?)(\s*[^\d\s,.][^]*)?$/);
  if (!m) return;
  const raw = m[1], target = Number(raw.replace(/,/g, ''));
  if (!Number.isFinite(target) || target === 0) return;
  const decimals = (raw.split('.')[1] || '').length, comma = raw.includes(','), suffix = m[2] || '';
  const show = (v) => (comma ? v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : v.toFixed(decimals));
  const start = performance.now(), duration = 700;
  const step = (now) => {
    if (!el.isConnected) return;
    const t = Math.min(1, (now - start) / duration);
    el.textContent = t < 1 ? show(target * (1 - Math.pow(1 - t, 3))) + suffix : text;
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
if (typeof MutationObserver !== 'undefined' && document.querySelector('main')) {
  new MutationObserver((records) => {
    if (performance.now() > MOTION.until) return;
    for (const record of records) for (const node of record.addedNodes) {
      if (node.nodeType !== 1) continue;
      node.querySelectorAll('b.num, .num > b, .rs-h > b, .ov-k > b').forEach((el) => { if (!MOTION.seen.has(el)) { MOTION.seen.add(el); countUp(el); } });
    }
  }).observe(document.querySelector('main'), { childList: true, subtree: true });
}

/* 10/9 作者：选中的东西「滑过去」——分段选择的白色滑块、页签下面那条线，从旧位置滑到新位置。
   这些控件每次都整块重画，所以按「哪一组」记住上一次的位置（同一组 = 同一个外框 id + 同一串选项），新画出来的那组从旧位置滑到新位置。 */
const SLIDE = { last: new Map(), groups: '.seg-toggle, .ms-segments, .subnav, .in-tabs', };
function slideKey(group) {  // 选项上的数字（待处理条数）会变，不算进「哪一组」
  const owner = group.closest('[id]');
  return `${group.className}|${group.getAttribute('aria-label') || ''}|${owner ? owner.id : ''}|${[...group.querySelectorAll(':scope > button')].map((b) => b.textContent.replace(/[\d\s]+/g, '')).join(',')}`;
}
function slideSync(group, animate = true) {
  const tabs = !group.matches('.seg-toggle, .ms-segments');
  const on = group.querySelector(':scope > button.on, :scope > button[aria-pressed="true"], :scope > button[aria-selected="true"]');
  let mark = group.querySelector(':scope > .slide-mark');
  if (!on || !on.offsetWidth) { if (mark && !on) mark.remove(); return; }
  if (!mark) {
    mark = document.createElement('i');
    mark.className = `slide-mark ${tabs ? 'is-tab' : 'is-thumb'}`;
    mark.setAttribute('aria-hidden', 'true');
    group.prepend(mark);
    group.classList.add('has-slide');
  }
  const to = { x: on.offsetLeft, y: tabs ? on.offsetTop + on.offsetHeight - 2 : on.offsetTop, w: on.offsetWidth, h: tabs ? 2 : on.offsetHeight };
  const key = slideKey(group), prev = SLIDE.last.get(key), now = performance.now();
  const same = (a, b) => a && b && a.x === b.x && a.y === b.y && a.w === b.w;
  // 点了之后这一组马上又被重画一次（读数据回来）：还在滑的半路，就从原来的起点接着滑，不要直接跳到终点
  const from = prev && same(prev.to, to) && prev.from && now - prev.at < 260 ? prev.from : prev && prev.to;
  const moved = from && !same(from, to);
  SLIDE.last.set(key, { to, from: moved ? from : null, at: moved ? now : 0 });
  const place = (r) => { mark.style.setProperty('--x', `${r.x}px`); mark.style.setProperty('--y', `${r.y}px`); mark.style.setProperty('--w', `${r.w}px`); mark.style.setProperty('--h', `${r.h}px`); };
  if (!animate || !moved || reducedMotion()) { mark.classList.add('no-anim'); place(to); void mark.offsetWidth; mark.classList.remove('no-anim'); return; }
  if (mark.dataset.placed) { place(to); return; }   // 同一个元素，CSS transition 自己滑
  mark.classList.add('no-anim'); place(from); void mark.offsetWidth; mark.classList.remove('no-anim'); place(to);
  mark.dataset.placed = '1';
}
function slideScan(root, animate = true) {
  if (root.nodeType !== 1) return;
  if (root.matches(SLIDE.groups)) slideSync(root, animate);
  root.querySelectorAll(SLIDE.groups).forEach((group) => slideSync(group, animate));
}
if (typeof MutationObserver !== 'undefined') {
  new MutationObserver((records) => {
    const groups = new Set();
    for (const record of records) {
      // 只看选项按钮自己的选中状态变化；滑块和外框自己的 class 变化不算（否则自己触发自己，死循环）
      if (record.type === 'attributes') { const t = record.target; if (t.matches?.('.slide-mark') || t.matches?.(SLIDE.groups)) continue; const group = t.parentElement?.matches(SLIDE.groups) ? t.parentElement : null; if (group) groups.add(group); continue; }
      if ([...record.addedNodes].every((node) => node.nodeType === 1 && node.classList.contains('slide-mark'))) continue;
      const group = record.target.closest?.(SLIDE.groups); if (group) groups.add(group);
      record.addedNodes.forEach((node) => { if (node.nodeType === 1) { if (node.matches(SLIDE.groups)) groups.add(node); node.querySelectorAll?.(SLIDE.groups).forEach((g) => groups.add(g)); } });
    }
    groups.forEach((group) => { if (group.isConnected) slideSync(group); });
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'aria-pressed', 'aria-selected', 'hidden'] });
  window.addEventListener('resize', () => slideScan(document.body, false));
}

/* 左栏分组可折叠（10/9：入口 28 个，13 寸屏放不下）：门户、产品默认收起，只露组名和个数；
   收起时当前所在的那一项照样显示。开合记在本机浏览器里。 */
const RAIL_FOLD_KEY = 'cs-rail-folds';
function railFolds() { try { return JSON.parse(localStorage.getItem(RAIL_FOLD_KEY) || '{}'); } catch (_) { return {}; } }
function paintRailFolds() {
  const open = railFolds();
  $$('[data-rail-fold]').forEach((head) => {
    const key = head.dataset.railFold, body = $(`[data-rail-fold-body="${key}"]`);
    if (!body) return;
    const expanded = Boolean(open[key]);
    head.setAttribute('aria-expanded', String(expanded));
    body.classList.toggle('is-folded', !expanded);
    const n = $$('.ri:not(.ri-add)', body).filter((b) => !b.hidden).length;
    $('.rail-fold-n', head).textContent = n ? String(n) : '';
  });
}
document.addEventListener('click', (e) => {
  const head = e.target.closest('[data-rail-fold]');
  if (!head) return;
  const open = railFolds(); open[head.dataset.railFold] = !open[head.dataset.railFold];
  try { localStorage.setItem(RAIL_FOLD_KEY, JSON.stringify(open)); } catch (_) { /* 无痕窗口：只这次有效 */ }
  paintRailFolds();
});
new MutationObserver(paintRailFolds).observe(document.querySelector('#railProducts') || document.body, { childList: true });
paintRailFolds();

/* ⌘K（10/9 作者 同意）：打字找页面或选题，回车直接过去。左栏 17 个入口 + 一堆选题，不用一个个点。
   页面从左栏现成的按钮里读（开关关掉的不出现），选题读 /api/topics，一分钟内不重读。 */
const CMDK = { el: null, items: [], shown: [], sel: 0, topics: null, at: 0 };
function cmdkItems() {
  // 左栏按钮里平台图标的那个字（抖、视、红、GH…）不算名字
  const label = (el) => { const box = (el.querySelector('span') || el).cloneNode(true); box.querySelectorAll('i').forEach((i) => i.remove()); return box.textContent.replace(/\s+/g, ' ').trim(); };
  // 10/20 走查：搜「发布」什么也搜不到。找写剪发盘带上那个字和常说的词；平台页（不在左栏了）也能搜到
  const pages = $$('.rail button.ri').filter((b) => !b.hidden && b.offsetParent !== null).map((b) => ({ label: b.dataset.zx ? `${$('.zx-k', b).textContent} · ${label(b)}` : label(b), keys: ZX_WORDS[b.dataset.zx] || '', kind: '页面', run: () => b.click() }));
  const plats = ['douyin', 'channels', 'xiaohongshu', 'x', 'youtube', 'bilibili'].filter((k) => !(window.platformOff && window.platformOff(k))).map((k) => ({ label: `平台 · ${(S.platforms.find((p) => p.key === k) || {}).label || k}`, keys: '数据 账号', kind: '页面', run: () => window.goPlatform(k) }));
  const sets = $$('#setTabs button').filter((b) => !b.hidden).map((b) => ({ label: `设置 · ${b.textContent.trim()}`, kind: '设置', run: () => { location.hash = `#settings/${b.dataset.set}`; } }));
  const topics = (CMDK.topics || []).map((t) => ({ label: t.title, kind: t.memo && /系列/.test(t.memo) ? '系列' : '选题', run: () => window.openWork && window.openWork(t.id) }));
  return [...pages, ...plats, ...sets, ...topics];
}
const ZX_WORDS = { find: '找选题 日报 对标 老师 热榜', write: '写稿 口播稿 口述 批注 稿子', cut: '剪辑 成片 素材 Hook 动效 拍后', fa: '发布 待发 上传 标题 封面 发出去', pan: '复盘 数据 KPI 战况 汇总 月历' };
function cmdkPaint() {
  const q = $('#cmdkQ', CMDK.el).value.trim().toLowerCase();
  const all = cmdkItems();
  CMDK.shown = (q ? all.filter((x) => `${x.label} ${x.keys || ''}`.toLowerCase().includes(q)) : all.filter((x) => x.kind !== '选题' && x.kind !== '系列').concat(all.filter((x) => x.kind === '选题' || x.kind === '系列').slice(0, 8))).slice(0, 40);
  CMDK.sel = Math.min(CMDK.sel, Math.max(0, CMDK.shown.length - 1));
  $('#cmdkList', CMDK.el).innerHTML = CMDK.shown.length
    ? CMDK.shown.map((x, i) => `<li role="option" id="cmdk-${i}" aria-selected="${i === CMDK.sel}" data-cmdk="${i}"><span>${esc(x.label)}</span><small>${esc(x.kind)}</small></li>`).join('')
    : '<li class="cmdk-empty">没有找到。换个词试试。</li>';
  $('#cmdkQ', CMDK.el).setAttribute('aria-activedescendant', CMDK.shown.length ? `cmdk-${CMDK.sel}` : '');
  $(`#cmdk-${CMDK.sel}`, CMDK.el)?.scrollIntoView({ block: 'nearest' });
}
function cmdkRun(i) { const item = CMDK.shown[i]; if (!item) return; CMDK.el.close(); item.run(); }
function cmdkOpen() {
  if (!CMDK.el) {
    const d = document.createElement('dialog');
    d.className = 'cmdk'; d.id = 'cmdk'; d.setAttribute('aria-label', '搜索页面和选题');
    d.innerHTML = '<div class="cmdk-box"><input id="cmdkQ" type="text" role="combobox" aria-controls="cmdkList" aria-expanded="true" placeholder="去哪？输入页面或选题名字" autocomplete="off"><ul id="cmdkList" role="listbox"></ul><p class="cmdk-foot"><kbd>↑</kbd><kbd>↓</kbd> 选 · <kbd>回车</kbd> 去 · <kbd>esc</kbd> 关</p></div>';
    document.body.appendChild(d);
    CMDK.el = d;
    const input = $('#cmdkQ', d);
    input.oninput = () => { CMDK.sel = 0; cmdkPaint(); };
    input.onkeydown = (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); const n = CMDK.shown.length; if (n) { CMDK.sel = (CMDK.sel + (e.key === 'ArrowDown' ? 1 : n - 1)) % n; cmdkPaint(); } }
      else if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); cmdkRun(CMDK.sel); }
    };
    d.onclick = (e) => { const li = e.target.closest('[data-cmdk]'); if (li) cmdkRun(Number(li.dataset.cmdk)); else if (e.target === d) d.close(); };
    d.onmousemove = (e) => { const li = e.target.closest('[data-cmdk]'); if (li && Number(li.dataset.cmdk) !== CMDK.sel) { CMDK.sel = Number(li.dataset.cmdk); cmdkPaint(); } };
  }
  const input = $('#cmdkQ', CMDK.el);
  input.value = ''; CMDK.sel = 0;
  cmdkPaint();
  CMDK.el.showModal(); input.focus();
  if (!CMDK.topics || Date.now() - CMDK.at > 60000) api('/api/topics?archived=false').then((list) => { CMDK.topics = list; CMDK.at = Date.now(); if (CMDK.el.open) cmdkPaint(); }).catch(() => {});
}
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k') { e.preventDefault(); if (CMDK.el?.open) CMDK.el.close(); else cmdkOpen(); }
});
$('#railSearch')?.addEventListener('click', cmdkOpen);

/* 10/9 作者：工作台要有「这是我的」感觉——只在几个时刻放他的卡通头像：今天出摊了、手上没有要发的、没有在剪的。
   头像读形象文件夹（个人形象功能关着或没有定稿头像，就什么都不放）。 */
api('/api/persona').then((d) => {
  const avatar = d && d.ready && (d.base || []).find((x) => x.file === 'avatar.png');
  if (!avatar) return;
  document.documentElement.style.setProperty('--me-avatar', `url("/api/persona/file?path=avatar.png&v=${encodeURIComponent(avatar.v || '')}&thumb=1")`);
  document.documentElement.classList.add('has-avatar');
}).catch(() => {});

/* 10/9 作者：读数据时先画出页面的形状（几张数字卡 + 一张有几行的大卡），读到了直接替换，不再「空白 → 突然冒出来」 */
window.skeletonPage = ({ cards = 3, rows = 5 } = {}) => `<div class="sk-page" role="status" aria-label="正在读取">
  <div class="sk-cards">${'<div class="sk-card"><span class="sk sk-meta"></span><span class="sk sk-num"></span><span class="sk sk-line"></span></div>'.repeat(cards)}</div>
  <div class="sk-panel"><span class="sk sk-title"></span>${'<div class="sk-row"><span class="sk sk-line"></span><span class="sk sk-meta"></span></div>'.repeat(rows)}</div></div>`;

function renderView() {
  if (!S.state) return;
  if (S.view !== MOTION.view) { MOTION.view = S.view; armEntrance(); }
  const rendering = window.VIEWS[S.view] ? window.VIEWS[S.view].render() : null;
  if (S.view === 'settings') { renderSettings(); if (window.renderSkills) window.renderSkills.render(); if (window.renderUpdate) window.renderUpdate(); }
  if (S.view === 'mine') renderMine();
  if (S.view === 'radar') renderRadar();
  if (S.view === 'report') { renderReport(); renderQueue(); }
  if (window.renderAnna) window.renderAnna();
  return rendering;
}

/* 「开始用」三步（10/6）：你是谁、连上抖音、素材在哪。三步都好了这张卡就不出现。 */
function setupSteps(st) {
  return {
    who: Boolean(st.setup && st.setup.present && st.self_account),
    douyin: Boolean(st.cookies && st.cookies.ok),
    vault: Boolean(st.vault && st.vault.ok && (st.settings || {}).obsidian_vault),
  };
}
function setupNeeded(st) { const s = setupSteps(st); return !(s.who && s.douyin && s.vault); }
function setupCard(st) {
  const steps = setupSteps(st), brand = st.brand || {}, me = st.self_account || {};
  const ui = setupCard.state || (setupCard.state = { drafts: {}, errors: {}, saving: {} });
  if (ui.expanded === undefined) {
    try { const stored = localStorage.getItem('cs-setup-expanded'); if (stored === 'open' || stored === 'closed') ui.expanded = stored === 'open'; } catch (_) { /* local preference is optional */ }
  }
  const names = { who: '身份与账号', douyin: '抖音登录', vault: '素材库' };
  const missing = Object.keys(names).filter((key) => !steps[key]);
  if (!missing.length) return '';
  const errors = Object.values(ui.errors).some(Boolean);
  const expanded = errors || (ui.expanded ?? !(steps.who && steps.vault));
  const value = (id, fallback = '') => esc(id in ui.drafts ? ui.drafts[id] : fallback);
  const error = (key, id) => `<small class="bad" id="${id}" role="alert">${esc(ui.errors[key] || '')}</small>`;
  const completed = Object.keys(names).filter((key) => steps[key]);
  return `<details class="panel setup su-disclosure" id="setupCard"${expanded ? ' open' : ''}>
    <summary class="su-summary"><span><b>开始使用 · 还差 ${missing.length} 步</b><small>${missing.map((key) => names[key]).join('、')}</small></span><span class="su-toggle-label" data-su-toggle>${expanded ? '收起设置' : '继续设置'}</span></summary>
    <div class="su-content">${completed.length ? `<p class="su-completed">已完成：${completed.map((key) => key === 'who' ? `${names[key]}${brand.name ? `（${esc(brand.name)}）` : ''}${me.nickname ? ` · ${esc(me.nickname)}` : ''}` : names[key]).join(' · ')}</p>` : '<p class="su-intro">先填写身份、连接抖音，再选择素材库。进度以实际配置检查为准。</p>'}
    <div class="su-steps">
      ${steps.who ? '' : `<section class="su-step" data-setup-group="profile"><i class="su-mark">1</i><div><h3>身份与账号</h3><form class="su-form" id="suProfile">
        ${st.setup?.present ? '<small>名字已记下，还差你的抖音主页：数据从这个号读。</small>' : `<label><span>工作台叫什么</span><input id="suBrand" value="${value('suBrand', brand.name || '')}" placeholder="你的品牌名，显示在左上角" maxlength="24" autocomplete="off"></label>
          <label><span>你的名字</span><input id="suName" value="${value('suName')}" placeholder="写稿时的作者名字" maxlength="24" autocomplete="off"></label>`}
        <label><span>你的抖音主页链接</span><input id="suDouyin" value="${value('suDouyin')}" placeholder="https://www.douyin.com/user/…" autocomplete="off"></label>
        ${st.setup?.present ? '' : `<label><span>两位虚拟同事叫什么</span><span class="su-two"><input id="suEditor" value="${value('suEditor', brand.editor || 'Anna')}" placeholder="流量 CEO" aria-label="流量 CEO 的名字" maxlength="20"><input id="suBoss" value="${value('suBoss', brand.boss || 'Wendy')}" placeholder="变现 CEO" aria-label="变现 CEO 的名字" maxlength="20"></span></label>`}
        <div class="su-row"><button class="btn primary" type="submit">${ui.saving.profile ? '正在保存…' : '保存身份与账号'}</button>${error('profile', 'suProfileErr')}</div></form></div></section>`}
      ${steps.douyin ? '' : `<section class="su-step" data-setup-group="cookies"><i class="su-mark">2</i><div><h3>连接抖音</h3><small>${esc(st.cookies?.message || '还没有导入登录信息')}。在 Chrome 用 Cookie-Editor 等扩展，登录 douyin.com 和创作者中心后导出 JSON，再选择该文件。</small>
        <div class="su-row"><input type="file" id="suCookieFile" accept=".json,application/json" aria-label="抖音登录信息文件"><button class="btn primary" type="button" id="suCookieGo" disabled>${ui.saving.cookies ? '正在导入…' : '导入'}</button>${error('cookies', 'suCookieErr')}</div></div></section>`}
      ${steps.vault ? '' : `<section class="su-step" data-setup-group="vault"><i class="su-mark">3</i><div><h3>素材库</h3><small>你写的东西、收藏的东西都从 Obsidian 库里读。${st.vault?.message ? ` ${esc(st.vault.message)}` : ''}</small><label class="su-vault-label" for="suVault">Obsidian 文件夹</label><div class="su-row"><input id="suVault" value="${value('suVault', (st.settings || {}).obsidian_vault || '')}" placeholder="~/我的笔记库" autocomplete="off"><button class="btn primary" type="button" id="suVaultGo">${ui.saving.vault ? '正在保存…' : '保存素材库位置'}</button>${error('vault', 'suVaultErr')}</div></div></section>`}
    </div></div></details>`;
}
function bindSetup(root) {
  const panel = $('#setupCard', root);
  if (!panel) return;
  const ui = setupCard.state || (setupCard.state = { drafts: {}, errors: {}, saving: {} });
  const label = $('[data-su-toggle]', panel);
  const summary = $('.su-summary', panel);
  if (summary) summary.onclick = (event) => {
    event.preventDefault(); panel.open = !panel.open; ui.expanded = panel.open;
    if (label) label.textContent = panel.open ? '收起设置' : '继续设置';
    try { localStorage.setItem('cs-setup-expanded', panel.open ? 'open' : 'closed'); } catch (_) { /* display preference only */ }
  };
  $$('input:not([type="file"])', panel).forEach((input) => { input.oninput = () => { ui.drafts[input.id] = input.value; }; });
  const busy = (key, pending) => {
    ui.saving[key] = pending;
    const group = $(`[data-setup-group="${key}"]`, root);
    if (group) $$('input, button', group).forEach((control) => {
      control.disabled = pending;
      if (control.tagName === 'BUTTON') control.textContent = pending ? key === 'cookies' ? '正在导入…' : '正在保存…' : ({ profile: '保存身份与账号', cookies: '导入', vault: '保存素材库位置' })[key];
    });
    if (key === 'cookies' && !pending) { const go = $('#suCookieGo', root), file = $('#suCookieFile', root); if (go) go.disabled = !file?.files.length; }
  };
  const fail = (key, id, message) => {
    ui.errors[key] = message;
    const out = $(id, root); if (out) out.textContent = message;
    const current = $('#setupCard', root);
    if (message && current) { current.open = true; const toggle = $('[data-su-toggle]', current); if (toggle) toggle.textContent = '收起设置'; }
  };
  const submit = async (key, id, action, done, submitted = {}) => {
    if (ui.saving[key]) return;
    fail(key, id, ''); busy(key, true);
    try {
      const result = await action();
      if (key === 'cookies') { const selected = $('#suCookieFile', root); if (selected) selected.value = ''; }
      Object.entries(submitted).forEach(([field, text]) => { if (ui.drafts[field] === text) delete ui.drafts[field]; });
      toast(typeof done === 'function' ? done(result) : done);
      try { await refreshAll(); } catch (ex) { fail(key, id, `已保存，但状态刷新失败：${ex.message}`); }
    } catch (ex) { fail(key, id, ex.message); }
    finally { busy(key, false); if (typeof renderChrome === 'function') renderChrome(); }
  };
  ['profile', 'cookies', 'vault'].forEach((key) => busy(key, Boolean(ui.saving[key])));
  const form = $('#suProfile', root);
  if (form) form.onsubmit = (event) => {
    event.preventDefault();
    const val = (id) => { const input = $(id, root); return input ? input.value : ''; };
    const fields = { brand: 'suBrand', name: 'suName', douyin: 'suDouyin', editor: 'suEditor', boss: 'suBoss' };
    const body = Object.fromEntries(Object.entries(fields).map(([key, id]) => [key, val('#' + id)]));
    const submitted = Object.fromEntries(Object.entries(fields).map(([key, id]) => [id, body[key]]));
    return submit('profile', '#suProfileErr', () => api('/api/setup/profile', { method: 'POST', body }), '身份与账号已保存', submitted);
  };
  const file = $('#suCookieFile', root), go = $('#suCookieGo', root);
  if (file && go) {
    file.onchange = () => { go.disabled = ui.saving.cookies || !file.files.length; };
    go.onclick = () => {
      if (ui.saving.cookies || !file.files.length) return;
      fail('cookies', '#suCookieErr', ''); busy('cookies', true);
      const reader = new FileReader();
      reader.onerror = () => { fail('cookies', '#suCookieErr', '无法读取这个文件，请重新选择。'); busy('cookies', false); };
      reader.onload = () => {
        // Keep file contents local to this request; never store them with form drafts or preferences.
        ui.saving.cookies = false;
        return submit('cookies', '#suCookieErr', () => api('/api/setup/cookies', { method: 'POST', body: { text: String(reader.result || '') } }), (result) => `导入了 ${result.count} 条，正在读你的抖音号`);
      };
      reader.readAsText(file.files[0]);
    };
  }
  const vault = $('#suVault', root), vgo = $('#suVaultGo', root);
  if (vault && vgo) vgo.onclick = () => submit('vault', '#suVaultErr', () => api('/api/settings', { method: 'PUT', body: { obsidian_vault: vault.value } }), '素材库位置已保存', { suVault: vault.value });
}

/* 品牌：profile.yaml 的 brand 项；不填就是 index.html 里写的内容工作台，这里什么都不改。两位虚拟同事的名字也跟着它。 */
function applyBrand(b) {
  if (!b || !b.name) return;
  if ($('#brandName').textContent !== b.name) { $('#brandName').textContent = b.name; document.title = `${b.name} · 内容工作台`; }
  if (b.slogan && $('#brandSlogan').textContent !== b.slogan) $('#brandSlogan').textContent = b.slogan;
  // 10/9 晚 作者：三个人都在左栏。Michael 住在 X 页最上面，点他就是去 X 页
  const names = [['#railAnna', b.editor || 'Anna', b.editor_role || '流量 CEO'], ['#railWendy', b.boss || 'Wendy', b.boss_role || '负责人'], ['#railMichael', b.xops || 'Michael', b.xops_role || 'X 运营']];
  names.forEach(([id, name, role]) => {
    const el = $(`${id} > span`); if (el && el.textContent !== name) el.innerHTML = `<i class="an-dot"></i>${esc(name)}`;
    const tag = $(`${id} > .count`); if (tag && tag.textContent !== role) tag.textContent = role;
  });
  const mark = $('.brand-mark');
  if (b.logo && mark && mark.tagName.toLowerCase() === 'svg') {
    const img = document.createElement('img');
    img.className = 'brand-mark'; img.src = b.logo; img.alt = '';
    mark.replaceWith(img);
  }
}

/* ================= SETTINGS ================= */
function renderSettingsAvailability() {
  const writer = featureOn('skills'), portal = featureOn('portal'), xline = featureOn('xline');
  const writerField = $('#writerSkillField'), linksPanel = $('#meLinksPanel'), linksNote = $('#meLinksNote');
  if (writerField) writerField.hidden = !writer;
  if (linksPanel) linksPanel.hidden = !portal && !xline;
  if (linksNote) linksNote.textContent = portal && xline ? '门户截图使用这两个链接；X 素材也从这里读取公开资料。' : portal ? '门户截图使用这里保存的 GitHub 和个人网站链接。' : xline ? 'X 素材从这里读取 GitHub 和个人网站的公开资料。' : '';
  return { writer, links: portal || xline };
}
function renderSettings() {
  const st = S.state;
  const available = renderSettingsAvailability();
  const fields = { obsidian_vault: '#setVault', video_projects_root: '#setVideoRoot', douyin_archive: '#setArchive', writer_skill: '#setWriterSkill' };
  const baseline = Object.fromEntries(Object.keys(fields).map((k) => [k, st.settings[k] || '']));
  const draft = FormState.load('general', baseline);
  Object.entries(fields).filter(([k]) => k !== 'writer_skill').forEach(([k, selector]) => { const el = $(selector); if (el && document.activeElement !== el) el.value = draft.values[k]; });
  renderWriterSkill(draft.values.writer_skill);
  bindFormDraft('general', $('#settingsForm'), readGeneralSettings);
  renderTagRows();
  renderFlowRows();
  if (available.links && window.fillMeLinksForm) window.fillMeLinksForm();
  paintSettingsTabs();
  $('#setVaultNote').textContent = st.vault.ok ? '已找到这个库' : st.vault.message;
  $('#setVaultNote').className = st.vault.ok ? '' : 'bad';
  const mineList = st.my_accounts || [];
  $('#myAccounts').innerHTML = mineList.length
    ? `<div class="acct-list">${mineList.map((a) => `<div class="acct-row"><b>${esc(a.nickname || '同步中…')}</b><span>${esc(a.platform)} · 粉丝 ${fmt(a.follower_count)}</span></div>`).join('')}</div>`
    : '<div class="empty"><span>还没有连接自己的账号：粘贴你的抖音主页链接。</span></div>';
}

/* 设置分七页（10/6；10/9 加了「流程」）：通用 · 流程 · 视频动效 · Skills · 内容框架 · 助手读什么 · 版本。个人形象 10/7 挪到了定位 ·「我的形象」。记住上次看的那页；#settings/motion 这样能直达。 */
const SET = { tab: (() => { try { return localStorage.getItem('cs-set-tab') || 'general'; } catch (_) { return 'general'; } })() };
const SET_TABS = ['general', 'flow', 'motion', 'skills', 'frames', 'team', 'update'];
function paintSettingsTabs() {
  if (!SET_TABS.includes(SET.tab) || !featureOn(SET.tab)) SET.tab = 'general';
  $$('#setTabs button').forEach((b) => { const active = b.dataset.set === SET.tab; b.classList.toggle('on', active); b.setAttribute('aria-pressed', String(active)); });
  $$('[data-set-tab]').forEach((el) => { el.hidden = el.dataset.setTab !== SET.tab; });
  if (featureOn('xline')) {
    const xqa = $('#xqaPanel');
    if (SET.tab === 'flow' && xqa && !xqa.dataset.loaded) loadXqaRules();
    if (SET.tab === 'flow' && window.loadWriteFlow && $('#wfBody') && !$('#wfBody').innerHTML) window.loadWriteFlow();
  }
  if (SET.tab === 'frames' && window.loadFrames) window.loadFrames();
  const v2d = $('#v2Defaults');
  // 动效那页打开时才读一次：读 pv2 要一两秒，没保存的改动留在 VP.set.default.draft 里
  if (SET.tab === 'motion' && v2d && window.loadV2Settings && !v2d.dataset.loaded) { v2d.dataset.loaded = '1'; window.loadV2Settings({ id: 'default' }, v2d); }
}
$$('#setTabs button').forEach((b) => (b.onclick = () => {
  SET.tab = b.dataset.set;
  try { localStorage.setItem('cs-set-tab', SET.tab); } catch (_) { /* ignore */ }
  if (location.hash !== `#settings/${SET.tab}`) history.replaceState(null, '', `#settings/${SET.tab}`);
  paintSettingsTabs();
}));

/* 设置 · 流程（10/9 作者）：流程是他那一套，顺序不让改；用户只能开关其中的组件。
   按六个阶段排；这个版本本来就没有的（edition.cut）不列出来。存完整页重载：藏起来的入口、后台跳步都按新的来。 */
// 10/20：分组和左栏一样叫「找 写 剪 发」。「X 每日短帖和长文」那个开关拿掉了：#711 起那套已经关了；
// xline 这个键还管着「写」里的口播稿和「剪」里的拍后批注，不能让人在这里顺手关掉
const FLOW_STAGES = [
  ['找', [['dailies', 'AI 日报', '每天的日报出现在「找」里，可以一键加入选题']]],
  ['写', [['series', '系列', '一个系列一行一课，每集在「我的选题」里'],
            ['qa', '三点评分', '骨架写完按痛点、反差、交付打分，告诉你能不能拍'],
            ['coupon', '密度', '骨架后面接着按密度排口播节奏：开头发债、每段付息、结尾兑付'],
            ['proof', '证据单', '进了「正在做」自己出证据单：每个论点定用截图、外面的证据还是插图；截图没传先不发']]],
  ['剪', [['motion', '视频动效', '给口播视频加动效层']]],
  ['发', [['figs', '插图', '给讲概念的论点画插图，放进文章'],
            ['autopost', '机器代发', '做好了自己发到能自动发的平台；关掉就只备好上传文件夹，你自己传']]],
];
function renderFlowRows() {
  const box = $('#flowRows');
  if (!box) return;
  const ed = S.state.edition || {};
  const cut = new Set(ed.cut || []), userOff = new Set(ed.user_off || []), known = new Set(ed.switches || []);
  if (box.contains(document.activeElement)) return;
  box.innerHTML = FLOW_STAGES.map(([stage, items]) => {
    const rows = items.filter(([key]) => known.has(key) && !cut.has(key));
    if (!rows.length) return '';
    return `<section class="flow-stage"><h3>${esc(stage)}</h3>${rows.map(([key, label, note]) => `<label class="flow-sw"><input type="checkbox" data-flow-key="${key}"${userOff.has(key) ? '' : ' checked'}><span><b>${esc(label)}</b><small>${esc(note)}</small></span></label>`).join('')}</section>`;
  }).join('');
}
const flowForm = $('#flowForm');
if (flowForm) flowForm.onsubmit = async (e) => {
  e.preventDefault();
  const btn = flowForm.querySelector('button[type=submit]');
  const off = $$('#flowRows [data-flow-key]').filter((el) => !el.checked).map((el) => el.dataset.flowKey);
  // 这个版本没有的不在页面上：原样留着，不当成「用户打开了」
  const keep = ((S.state.edition || {}).user_off || []).filter((k) => !$(`#flowRows [data-flow-key="${k}"]`));
  btn.disabled = true;
  try {
    await api('/api/settings', { method: 'PUT', body: { components_off: [...new Set([...off, ...keep])] } });
    toast('流程已保存，页面马上按新的来');
    setTimeout(() => location.reload(), 600);
  } catch (err) { toast(err.message); btn.disabled = false; }
};

/* X 发前 QA 规则；整个功能分支在 Trial 构建时裁掉。 */
async function loadXqaRules() {
  if (featureOn('xline')) {
    const panel = $('#xqaPanel'), form = $('#xqaForm'), input = $('#xqaText');
    if (!panel || panel.dataset.loaded) return;
    panel.dataset.loaded = '1';
    const reset = $('#xqaReset'), note = $('#xqaNote'), save = form.querySelector('button[type=submit]');
    let baseline = input.value, busy = false;
    const fill = (rules, replace = document.activeElement !== input && !input.dataset.dirty) => {
      $('#xqaPath').textContent = rules.path + (rules.bundled ? '（自带的通用版）' : '');
      reset.hidden = !rules.resettable;
      if (replace) {
        input.value = rules.text;
        baseline = rules.text;
        delete input.dataset.dirty;
      }
    };
    input.oninput = () => {
      if (input.value === baseline) delete input.dataset.dirty;
      else input.dataset.dirty = '1';
      note.textContent = input.dataset.dirty ? '还没保存' : '';
    };
    const mutate = async (method) => {
      if (busy) return;
      busy = true;
      save.disabled = reset.disabled = true;
      const submitted = input.value;
      note.textContent = method === 'PUT' ? '正在保存…' : '正在恢复…';
      try {
        const rules = await api('/api/xline/qa-rules', { method, ...(method === 'PUT' ? { body: { text: submitted } } : {}) });
        // 请求期间继续输入的字保留，不能被保存回执覆盖。
        const unchanged = input.value === submitted;
        fill(rules, unchanged);
        baseline = rules.text;
        if (input.value === baseline) delete input.dataset.dirty;
        else input.dataset.dirty = '1';
        note.textContent = input.dataset.dirty ? '还有改动没保存' : '已保存';
        toast(method === 'PUT' ? 'QA 规则存好了，下一篇就按新的' : '已恢复成自带的 QA 规则');
      } catch (err) { note.textContent = err.message; toast(err.message); }
      finally { busy = false; save.disabled = reset.disabled = false; }
    };
    form.onsubmit = (e) => { e.preventDefault(); return mutate('PUT'); };
    reset.onclick = () => {
      if (!busy && confirm('恢复成自带的 QA 规则？当前修改会被替换。')) return mutate('DELETE');
    };
    save.disabled = true;
    note.textContent = '正在读取…';
    try {
      fill(await api('/api/xline/qa-rules'));
      note.textContent = input.dataset.dirty ? '还没保存' : '';
    } catch (err) { delete panel.dataset.loaded; note.textContent = err.message; }
    finally { save.disabled = false; }
  }
}

/* 写作 skill 的空位：作者自己选「不用」，客户可以选「写文」那一步里的任何一个（10/4） */
async function renderWriterSkill(current) {
  const sel = $('#setWriterSkill');
  if (!sel) return;
  const wanted = FormState.get('general')?.values.writer_skill ?? current;
  if (!featureOn('skills')) {
    // Preserve the configured value while this capability is unavailable; do not fetch a missing picker.
    sel.innerHTML = `<option value="${esc(wanted)}">${wanted ? esc(wanted) : '只整理我的原话'}</option>`;
    sel.value = wanted; sel.disabled = true; sel.dataset.loading = '0'; return;
  }
  if (document.activeElement === sel) return;
  sel.innerHTML = `<option value="${esc(wanted)}">${wanted ? esc(wanted) : '不用 skill，只整理我的原话'}</option>`;
  sel.value = wanted; sel.disabled = true; sel.dataset.loading = '1';
  let names = [];
  try { names = (await api('/api/skills')).skills.filter((s) => s.stage === 'write').map((s) => [s.name, s.title || s.name]); } catch (_) { /* 列不出就只留「不用」 */ }
  if (current && !names.some(([n]) => n === current)) names.push([current, current]);
  sel.innerHTML = `<option value="">不用 skill，只整理我的原话</option>${names.map(([n, t]) => `<option value="${esc(n)}">${esc(t)}（${esc(n)}）</option>`).join('')}`;
  const selected = FormState.get('general')?.values.writer_skill ?? current;
  if (selected && !names.some(([n]) => n === selected)) sel.innerHTML += `<option value="${esc(selected)}">${esc(selected)}</option>`;
  sel.value = selected; sel.disabled = false; sel.dataset.loading = '0';
}

function readGeneralSettings() {
  return { obsidian_vault: $('#setVault').value, video_projects_root: $('#setVideoRoot').value, douyin_archive: $('#setArchive').value, writer_skill: $('#setWriterSkill').dataset.loading === '1' ? FormState.get('general').values.writer_skill : $('#setWriterSkill').value };
}
$('#setWriterSkill').onchange = () => { FormState.edit('general', readGeneralSettings()); paintFormState('general', $('#settingsForm')); };

/* 各平台常用话题（10/8 作者）：一页看全所有平台，只在这里改；平台页、打包页只显示，点「去设置改」跳到这里。 */
function renderTagRows() {
  const box = $('#tagsRows');
  if (!box || box.contains(document.activeElement)) return;
  const tags = S.state.settings.traffic_tags || {};
  const baseline = Object.fromEntries((S.state.tag_platforms || []).map((p) => [p.key, (tags[p.key] || []).join('，')]));
  const draft = FormState.load('tags', baseline);
  box.innerHTML = (S.state.tag_platforms || []).map((p) => {
    const mine = tags[p.key] || [];
    const note = mine.length >= p.cap ? `最多带 ${p.cap} 个，填满了，这条自己的内容话题带不上` : `最多带 ${p.cap} 个，剩下的位置给这条自己的内容话题`;
    return `<label><span>${esc(p.label)}</span><input data-tag-plat="${esc(p.key)}" value="${esc(draft.values[p.key] ?? '')}" placeholder="用逗号隔开，# 可带可不带" autocomplete="off"><small>${note}</small></label>`;
  }).join('');
  bindFormDraft('tags', $('#tagsForm'), readTagSettings);
}
function readTagSettings() { return Object.fromEntries($$('[data-tag-plat]').map((el) => [el.dataset.tagPlat, el.value])); }

window.goTagSettings = () => {
  SET.tab = 'general';
  go('settings');
  setTimeout(() => { const el = $('#tagsPanel'); if (el) el.scrollIntoView({ block: 'start' }); }, 50);
};

$('#tagsForm').onsubmit = async (e) => {
  e.preventDefault();
  const saved = await submitFormDraft('tags', $('#tagsForm'), readTagSettings, async (values) => {
    const changed = Object.fromEntries(Object.entries(values).map(([key, text]) => [key, text.split(/[,，\s]+/).map((t) => t.replace(/^#/, '').trim()).filter(Boolean)]));
    const saved = await api('/api/settings', { method: 'PUT', body: { traffic_tags: { ...(S.state.settings.traffic_tags || {}), ...changed } } });
    return { savedValues: Object.fromEntries(Object.keys(values).map((k) => [k, (saved.traffic_tags[k] || []).join('，')])) };
  });
  if (saved) { toast('常用话题已保存'); try { await refreshAll(); } catch (_) { /* successful save remains saved */ } }
};

$('#settingsForm').onsubmit = async (e) => {
  e.preventDefault();
  const saved = await submitFormDraft('general', $('#settingsForm'), readGeneralSettings, async (values) => { const saved = await api('/api/settings', { method: 'PUT', body: values }); return { savedValues: Object.fromEntries(Object.keys(values).map((k) => [k, saved[k] || ''])) }; });
  if (saved) { toast('通用设置已保存'); try { await refreshAll(); } catch (_) { /* successful save remains saved */ } }
};

$('#myAcctForm').onsubmit = async (e) => {
  e.preventDefault();
  try {
    const res = await api('/api/accounts', { method: 'POST', body: { url: $('#myAcctIn').value, is_self: true } });
    $('#myAcctIn').value = '';
    S.accountId = res.account.id;
    try { localStorage.setItem('cs-account', String(S.accountId)); } catch (_) { /* ignore */ }
    toast('已添加，正在同步这个账号的作品');
    await refreshAll();
  } catch (err) { toast(err.message); }
};

/* ================= MY VIDEOS ================= */
function renderMine() {
  const m = S.mine;
  const body = $('#mineBody');
  if (!m.account) {
    $('#mineActions').innerHTML = '';
    body.innerHTML = `<div class="panel onboard">
      <h2>先连上你自己的抖音号</h2>
      <p>在抖音网页版打开你的主页，把地址栏里 <b>douyin.com/user/</b> 开头的链接粘贴到下面。之后这里会显示你每条视频的数据和后台指标。</p>
      <form class="inline-form" id="selfForm"><input id="selfIn" placeholder="https://www.douyin.com/user/MS4wLjAB…" aria-label="我的主页链接"><button class="btn primary" type="submit">连接</button></form>
    </div>`;
    $('#selfForm').onsubmit = async (e) => {
      e.preventDefault();
      try {
        await api('/api/accounts', { method: 'POST', body: { url: $('#selfIn').value, is_self: true } });
        toast('已连接，正在同步你的作品');
        await refreshAll();
      } catch (err) { toast(err.message); }
    };
    return;
  }
  const acct = m.account;
  $('#mineActions').innerHTML = `<span class="sync-note">${acct.syncing ? '<span class="spin"></span> 同步中' : esc(ago(acct.last_synced_at))}</span>
    <button class="btn" type="button" id="mineSync" ${acct.syncing ? 'disabled' : ''}>同步全部账号</button>`;
  $('#mineSync').onclick = async () => {
    try { const r = await api('/api/sync', { method: 'POST' }); toast(r.message); await refreshAll(); } catch (err) { toast(err.message); }
  };
  if (acct.status === 'error' && acct.last_error) {
    body.innerHTML = `<div class="banner warn" style="margin-bottom:18px"><div><b>同步失败：</b>${esc(acct.last_error)}</div></div>`;
  } else body.innerHTML = '';
  if (!m.videos.length) {
    body.innerHTML += `<div class="panel empty"><b>还没有作品数据</b><span>${acct.syncing ? '正在同步，稍等片刻…' : '点右上角「同步我的数据」拉取作品和后台指标。'}</span></div>`;
    return;
  }

  const videos = m.videos;
  const withCreator = videos.filter((v) => v.creator);
  const recent10 = videos.filter((v) => !v.is_image_post).slice(0, 10)
    .map((v) => (v.creator ? v.creator.view_count : v.views)).filter((x) => x !== null && x !== undefined).sort((a, b) => a - b);
  const med10 = recent10.length ? (recent10.length % 2 ? recent10[(recent10.length - 1) / 2] : (recent10[recent10.length / 2 - 1] + recent10[recent10.length / 2]) / 2) : null;
  const recent5 = withCreator.filter((v) => !v.is_image_post).slice(0, 5);
  const fans5 = recent5.reduce((a, v) => a + (v.creator.fan_increment || 0), 0);
  const avgWatch = recent5.map((v) => v.creator.avg_view_second).filter((x) => x !== null && x !== undefined);
  const likes = videos.reduce((a, v) => a + (v.likes || 0), 0);
  const collects = videos.reduce((a, v) => a + (v.collects || 0), 0);
  const topFan = recent5.slice().sort((a, b) => (b.creator.fan_increment || 0) - (a.creator.fan_increment || 0))[0];

  const kpis = `<div class="kpis">
    <div class="kpi"><div class="l">粉丝</div><div class="v">${fmt(acct.follower_count)}</div><div class="s">获赞 ${fmt(acct.total_favorited)}</div></div>
    <div class="kpi"><div class="l">近 10 条播放中位数</div><div class="v">${fmt(med10)}</div><div class="s">商单预估播放的基准</div></div>
    <div class="kpi"><div class="l">近 ${recent5.length || 5} 条视频涨粉</div><div class="v">${recent5.length ? fmt(fans5) : '—'}</div><div class="s">${topFan ? '最多：' + esc(cleanTitle(topFan.title).slice(0, 12)) : '需要后台数据'}</div></div>
    <div class="kpi"><div class="l">平均观看时长</div><div class="v ${avgWatch.length ? 'bad' : ''}">${avgWatch.length ? Math.round(Math.min(...avgWatch)) + '–' + Math.round(Math.max(...avgWatch)) + ' 秒' : '—'}</div><div class="s">近 ${avgWatch.length} 条视频</div></div>
    <div class="kpi"><div class="l">收藏 / 赞</div><div class="v">${likes ? pct(collects / likes) : '—'}</div><div class="s">全部 ${videos.length} 条作品</div></div>
  </div>`;

  const note = withCreator.length ? '' : `<div class="banner info"><div>还没有创作者后台数据（涨粉、完播、跳出）。点「同步我的数据」会一并抓取最近 90 天。</div></div>`;

  body.innerHTML += `${kpis}${note}
    <div class="panel"><div class="panel-h"><h2>时长 × 播放</h2><small>圆点大小 = 点赞 · 纵轴对数刻度 · 金色 = 点赞 ≥ 账号中位数 3 倍</small></div><div class="chart" id="scatter"></div></div>
    <div class="panel"><div class="panel-h"><h2>作品明细</h2><small>点击表头排序 · 中位数 ${fmt(m.median_likes)} 赞</small></div><div class="tbl-wrap"><table id="mineTbl"></table></div></div>`;
  drawScatter(videos, m.median_likes);
  drawMineTable(videos, m.median_likes);
}

function drawScatter(videos, median) {
  const pts = videos.filter((v) => !v.is_image_post && v.duration_seconds && (v.creator ? v.creator.view_count : v.views));
  const el = $('#scatter');
  if (pts.length < 2) { el.innerHTML = '<div class="empty">视频数量不足，暂时画不出分布</div>'; return; }
  const W = 1100, H = 300, m = { l: 52, r: 16, t: 14, b: 34 };
  const plays = pts.map((v) => (v.creator ? v.creator.view_count : v.views));
  const maxDur = Math.max(...pts.map((v) => v.duration_seconds)) / 60;
  const xMax = Math.max(5, Math.ceil(maxDur / 5) * 5);
  const lo = Math.floor(Math.log10(Math.max(1, Math.min(...plays)))), hi = Math.ceil(Math.log10(Math.max(...plays) + 1));
  const xs = (d) => m.l + (d / 60) / xMax * (W - m.l - m.r);
  const ys = (p) => m.t + (1 - (Math.log10(Math.max(p, 1)) - lo) / Math.max(1, hi - lo)) * (H - m.t - m.b);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="时长与播放散点图">`;
  for (let e = lo; e <= hi; e++) {
    const p = 10 ** e;
    s += `<line class="gridl" x1="${m.l}" x2="${W - m.r}" y1="${ys(p)}" y2="${ys(p)}"/><g class="axis"><text x="${m.l - 6}" y="${ys(p) + 3}" text-anchor="end">${fmt(p)}</text></g>`;
  }
  const step = xMax <= 10 ? 2 : 5;
  for (let x = 0; x <= xMax; x += step) s += `<g class="axis"><text x="${xs(x * 60)}" y="${H - m.b + 16}" text-anchor="middle">${x}分</text></g>`;
  pts.forEach((v, i) => {
    const hot = median && v.likes / median >= 3;
    const r = 4 + Math.sqrt(v.likes || 0) / 9;
    s += `<circle cx="${xs(v.duration_seconds)}" cy="${ys(plays[i])}" r="${Math.min(r, 26)}" fill="${hot ? 'var(--hot)' : 'var(--accent)'}" fill-opacity="${hot ? 0.8 : 0.45}" stroke="${hot ? 'var(--hot)' : 'var(--accent)'}"><title>${esc(v.title)}\n${mmss(v.duration_seconds)} · 播放 ${fmt(plays[i])} · 赞 ${fmt(v.likes)}</title></circle>`;
  });
  el.innerHTML = s + '</svg>';
}

function drawMineTable(videos, median) {
  const cols = [
    ['title', '作品', 'l'], ['published_at', '发布'], ['duration_seconds', '时长'], ['plays', '播放'], ['likes', '点赞'],
    ['save', '收藏/赞'], ['fans', '涨粉'], ['c5', '5s完播'], ['j2', '2s跳出'], ['aw', '均看'], ['ctr', '封面点击'], ['multiple', '倍数'], ['act', '拆解'],
  ];
  const rows = videos.map((v) => ({
    ...v,
    plays: v.creator ? v.creator.view_count : v.views,
    save: v.likes ? (v.collects || 0) / v.likes : null,
    fans: v.creator ? v.creator.fan_increment : null,
    c5: v.creator ? v.creator.completion_rate_5s : null,
    j2: v.creator ? v.creator.bounce_rate_2s : null,
    aw: v.creator ? v.creator.avg_view_second : null,
    ctr: v.creator ? v.creator.cover_click_rate : null,
    multiple: median && v.likes !== null ? v.likes / median : null,
  }));
  const { key, dir } = S.mineSort;
  const val = (r) => (r[key] === null || r[key] === undefined ? -Infinity : r[key]);
  rows.sort((a, b) => (typeof a[key] === 'string' ? String(a[key]).localeCompare(String(b[key])) : val(a) - val(b)) * dir);
  const maxP = Math.max(1, ...rows.map((r) => r.plays || 0));
  const na = '<td class="na" title="没有后台数据（后台只保留 90 天）">—</td>';
  const tbl = $('#mineTbl');
  tbl.innerHTML = `<thead><tr>${cols.map(([k, l, c]) => `<th class="${c || ''} ${k === key ? 'sorted' : ''}" data-k="${k}" ${k === 'act' ? 'style="cursor:default"' : ''}>${l}${k === key ? (dir > 0 ? ' ↑' : ' ↓') : ''}</th>`).join('')}</tr></thead>
  <tbody>${rows.map((v) => `<tr data-vid="${esc(v.video_id)}">
    <td class="l title">${v.is_top ? '<span class="tag pin">置顶</span>' : ''}${v.is_image_post ? '<span class="tag img">图文</span>' : ''}${v.creator && v.save > 0.6 && v.fans !== null && v.collects && v.fans / v.collects < 0.3 ? '<span class="tag warn" title="每 100 个收藏换不到 30 个粉">收藏≠关注</span>' : ''}<span class="clamp" title="${esc(v.title)}">${esc(cleanTitle(v.title))}</span></td>
    <td>${day(v.published_at)}</td><td>${v.is_image_post ? '—' : mmss(v.duration_seconds)}</td>
    <td>${fmt(v.plays)}<span class="bar" style="width:${Math.max(2, (v.plays || 0) / maxP * 60)}px"></span></td>
    <td>${fmt(v.likes)}</td><td>${pct(v.save)}</td>
    ${v.creator ? `<td>${fmt(v.fans)}</td><td>${pct(v.c5)}</td><td class="${v.j2 >= 0.35 ? 'bad' : ''}">${pct(v.j2)}</td><td>${v.aw === null ? '—' : Math.round(v.aw) + '秒'}</td><td>${pct(v.ctr)}</td>` : na + na + na + na + na}
    <td>${v.multiple === null ? '—' : `<span class="pill ${v.multiple >= 3 ? 'hot' : v.multiple >= 1 ? 'mid' : 'low'}">${v.multiple.toFixed(1)}×</span>`}</td>
    <td><div class="acts">${v.is_image_post ? '<span class="muted">图文</span>' : teardownButton(v, { source: '我的视频' })}</div></td>
  </tr>`).join('')}</tbody>`;
  $$('th', tbl).forEach((th) => {
    if (th.dataset.k === 'act') return;
    th.onclick = () => {
      S.mineSort = { key: th.dataset.k, dir: th.dataset.k === key ? -dir : -1 };
      drawMineTable(videos, median);
    };
  });
  bindTeardownButtons(tbl);
  // 从进项「看数据 →」跳过来：把那一条滚到眼前，亮一下。
  if (S.mineFocus) {
    const tr = tbl.querySelector(`tr[data-vid="${CSS.escape(S.mineFocus)}"]`);
    S.mineFocus = null;
    if (tr) { tr.classList.add('focus'); setTimeout(() => tr.scrollIntoView({ block: 'center' }), 50); setTimeout(() => tr.classList.remove('focus'), 3000); }
  }
}

/* ================= RADAR ================= */
function spark(values, median, threshold) {
  const W = 260, H = 64, p = 4;
  if (!values.length) return `<svg class="spark" viewBox="0 0 ${W} ${H}" aria-hidden="true"></svg>`;
  const lo = Math.log10(Math.max(1, Math.min(...values))), hi = Math.log10(Math.max(...values) + 1);
  const x = (i) => p + (values.length === 1 ? 0.5 : i / (values.length - 1)) * (W - 2 * p);
  const y = (v) => p + (1 - (Math.log10(Math.max(v, 1)) - lo) / Math.max(0.01, hi - lo)) * (H - 2 * p);
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  let s = `<svg class="spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="点赞走势（对数刻度）"><polygon class="area" points="${p},${H - p} ${pts.join(' ')} ${W - p},${H - p}"/><polyline class="ln" points="${pts.join(' ')}"/>`;
  if (median) s += `<line class="med" x1="${p}" x2="${W - p}" y1="${y(median)}" y2="${y(median)}"/>`;
  values.forEach((v, i) => { if (median && v / median >= threshold) s += `<circle class="hot" cx="${x(i)}" cy="${y(v)}" r="3.2"><title>${fmt(v)} 赞 · ${(v / median).toFixed(1)}×</title></circle>`; });
  return s + '</svg>';
}

function mixBar(v) {
  if (!v.likes) return '';
  const s = (v.collects || 0) / v.likes, h = (v.shares || 0) / v.likes, c = (v.comments || 0) / v.likes, tot = Math.max(0.0001, s + h + c);
  const type = h >= 0.9 ? '转发型' : s >= 0.6 && h >= 0.35 ? '收藏+转发' : s >= 0.6 ? '收藏型' : h >= 0.35 ? '转发型' : c >= 0.1 ? '评论型' : '点赞型';
  return `<div class="mix" title="收藏/赞 ${pct(s)} · 转发/赞 ${pct(h)} · 评论/赞 ${pct(c)}"><i style="width:${s / tot * 100}%;background:var(--save)"></i><i style="width:${h / tot * 100}%;background:var(--share)"></i><i style="width:${c / tot * 100}%;background:var(--talk)"></i></div><div class="mixlab">${type} · 收藏 ${pct(s)}</div>`;
}

function renderRadar() {
  const threshold = S.state.settings.threshold;
  // 9/30 作者：老师（学理念）和对标（看要不要复刻）分开。对标排前面，老师在后面；卡片上能切换。
  const ordered = [...S.accounts].sort((x, y) => (x.kind === 'teacher') - (y.kind === 'teacher'));
  const cards = ordered.map((a) => {
    const status = a.platform !== '抖音'
      ? `<div class="wait">${esc(a.pending_note)}</div>`
      : a.syncing ? '<div class="status"><span class="spin"></span>正在同步近期作品…</div>'
        : a.status === 'error' ? `<div class="status"><span class="err">同步失败：${esc(a.last_error)}</span></div>`
          : `<div class="status">${esc(ago(a.last_synced_at))}</div>`;
    const title = a.nickname || (a.platform === '抖音' ? '新账号（同步后显示昵称）' : a.external_id ? '@' + a.external_id : '新账号');
    return `<div class="panel acct pick ${S.radarAccount === a.id ? 'on' : ''}" data-pick="${a.id}" title="点一下只看这个账号，再点一下看全部">
      <div class="acct-top"><h3 title="${esc(title)}"><button type="button" class="kind-pill ${a.kind === 'teacher' ? 'teacher' : ''}" data-kind="${a.id}" data-to="${a.kind === 'teacher' ? 'benchmark' : 'teacher'}" title="点一下换成${a.kind === 'teacher' ? '对标' : '老师'}">${a.kind === 'teacher' ? '老师' : '对标'}</button>${esc(title)}</h3><span class="fans">${a.follower_count !== null ? fmt(a.follower_count) + ' 粉' : ''} <button class="acct-x" data-rm="${a.id}" title="移出对标库" aria-label="移出对标库">×</button></span></div>
      ${a.platform === '抖音' ? spark(a.spark, a.median_likes, threshold) : `<div class="url">${esc(a.profile_url)}</div>`}
      ${a.platform === '抖音' ? `<div class="meta"><span>中位 <b>${fmt(a.median_likes)}</b></span><span>作品 <b>${a.video_count}</b></span><span style="color:var(--hot)">爆款 <b style="color:var(--hot)">${a.breakout_count}</b></span></div>` : ''}
      ${status}
      ${a.platform === '抖音' ? `<div class="row-actions"><button class="btn small ghost" type="button" data-sync="${a.id}" ${a.syncing ? 'disabled' : ''}>同步</button><a class="btn small ghost" href="${esc(a.profile_url)}" target="_blank" rel="noopener">主页 ↗</a></div>` : ''}
    </div>`;
  }).join('');
  $('#accts').innerHTML = cards + `<button class="panel acct add" id="addBtn" type="button"><span class="plus">+</span>加一个老师或对标<span>抖音 · 小红书 · X · 视频号</span></button>`;
  $('#addBtn').onclick = () => openAdd('benchmark');
  bindAccountActions($('#accts'), '对标库');
  $$('#accts [data-kind]').forEach((b) => (b.onclick = async (e) => {
    e.stopPropagation();
    try { await api(`/api/accounts/${b.dataset.kind}`, { method: 'PATCH', body: { kind: b.dataset.to } }); toast(b.dataset.to === 'teacher' ? '改成老师了' : '改成对标了'); await refreshAll(); } catch (err) { toast(err.message); }
  }));

  $$('#accts [data-pick]').forEach((card) => (card.onclick = (e) => {
    if (e.target.closest('button, a')) return;  // 卡片上的按钮和链接照旧
    const id = Number(card.dataset.pick);
    S.radarAccount = S.radarAccount === id ? null : id;
    renderRadar();
  }));

  const cutoff = S.radarDays ? Date.now() - S.radarDays * 86400000 : 0;
  const douyinAccounts = S.accounts.filter((a) => a.platform === '抖音');
  const picked = S.radarAccount ? S.accounts.find((a) => a.id === S.radarAccount) : null;
  if (S.radarAccount && !picked) S.radarAccount = null;
  let pool;
  if (S.radarScope === 'all') {
    const ids = picked ? [picked.id] : douyinAccounts.map((a) => a.id);
    const missing = ids.filter((id) => !S.radarVideos[id]);
    if (missing.length) {
      $('#outs').innerHTML = '<div class="empty"><span class="spin"></span> 正在读全部作品…</div>';
      Promise.all(missing.map((id) => api(`/api/accounts/${id}/videos`).then((d) => { S.radarVideos[id] = d.videos; }).catch(() => { S.radarVideos[id] = []; })))
        .then(() => { if (S.view === 'radar') renderRadar(); });
      return;
    }
    pool = ids.flatMap((id) => S.radarVideos[id] || []);
  } else {
    pool = S.outliers.filter((v) => !picked || v.account_id === picked.id);
  }
  const q = S.radarQuery.trim().toLowerCase();
  const inWindow = pool.filter((v) => !cutoff || (v.published_at && new Date(v.published_at).getTime() >= cutoff));
  const list = inWindow.filter((v) => !q || String(v.title || '').toLowerCase().includes(q))
    .sort((a, b) => (S.sort === 'published_at' ? String(b.published_at).localeCompare(String(a.published_at)) : (b[S.sort] ?? -1) - (a[S.sort] ?? -1)));
  const hidden = pool.length - inWindow.length;
  $('#outsTitle').textContent = S.radarScope === 'all' ? '全部作品' : '爆款样本';
  $('#hotN').textContent = `${list.length} 条${hidden ? ` · 更早的 ${hidden} 条在「全部」里` : ''}`;
  const earliest = picked && S.radarScope === 'all' ? (S.radarVideos[picked.id] || []).reduce((m, v) => (!m || (v.published_at && v.published_at < m) ? v.published_at : m), null) : null;
  $('#radarPick').innerHTML = picked
    ? `<span class="rp-chip">只看 <b>${esc(picked.nickname || '这个账号')}</b><button type="button" id="rpClear" aria-label="看全部账号">×</button></span>
       ${S.radarScope === 'all' ? `<span class="muted">库里 ${(S.radarVideos[picked.id] || []).length} 条${earliest ? `，最早 ${day(earliest)}` : ''}。</span>
       <button class="btn small ghost" type="button" id="rpDeep" ${picked.syncing ? 'disabled' : ''} title="平时同步只拉最近约 60 条；往回翻最多 300 条，一页一页慢慢拉，遇到抖音验证就停">${picked.syncing ? '正在同步…' : '拉更早的作品'}</button>` : ''}`
    : '';
  const clear = $('#rpClear');
  if (clear) clear.onclick = () => { S.radarAccount = null; renderRadar(); };
  const deep = $('#rpDeep');
  if (deep) deep.onclick = () => syncOneAccount(picked.id, deep, { deep: true });
  const threshold2 = S.state.settings.threshold;
  $('#outs').innerHTML = list.length ? list.map((v) => {
    const hot = v.multiple !== null && v.multiple !== undefined && v.multiple >= threshold2;
    const label = `${v.account_nickname || ''} · ${v.multiple === null || v.multiple === undefined ? '' : v.multiple.toFixed(1) + '×'}`;
    return `<div class="out ${hot ? '' : 'cold'}">
      <div class="mult">${v.multiple === null || v.multiple === undefined ? '—' : v.multiple.toFixed(1) + '×'}<small>中位倍数</small></div>
      <div><div class="t clamp" title="${esc(v.title)}">${esc(cleanTitle(v.title))}</div><div class="by">${esc(v.account_nickname || '')} · ${day(v.published_at)} · ${v.is_image_post ? '图文' : mmss(v.duration_seconds)}${v.is_top ? ' · 置顶' : ''}</div></div>
      <div class="stats">赞 ${fmt(v.likes)}<br>收藏 ${fmt(v.collects)} · 转发 ${fmt(v.shares)}</div>
      <div class="mixcol">${mixBar(v)}</div>
      <div style="display:flex;gap:6px;justify-content:flex-end;align-items:center">${v.is_image_post ? '<span class="muted">图文</span>' : teardownButton(v, { source: `${hot ? '对标爆款' : '对标作品'} · ${label}` })}</div>
    </div>`;
  }).join('')
    : `<div class="empty"><b>${!douyinAccounts.length ? '还没有抖音对标账号' : q ? `没有标题里带「${esc(S.radarQuery.trim())}」的` : S.radarScope === 'all' ? (S.radarDays ? `这 ${S.radarDays} 天没有作品` : '还没有作品') : (S.radarDays ? `这 ${S.radarDays} 天没有新爆款` : '当前门槛下没有爆款')}</b><span>${!douyinAccounts.length ? '点上面的「加入对标账号」，粘贴对方主页链接。' : hidden ? `更早的 ${hidden} 条在「全部」里。` : S.radarScope === 'hot' ? '切到「全部作品」能看到没爆的。' : picked ? '点「拉更早的作品」往回翻。' : ''}</span></div>`;
  bindTeardownButtons($('#outs'));
}

/* 单个账号同步（9/20 改版时这个函数丢了，卡片上的「同步」点了没反应）。deep=true 往回翻更早的作品。 */
async function syncOneAccount(id, btn, { deep = false } = {}) {
  const before = S.accounts.find((a) => a.id === id) || {};
  const was = before.video_count || 0;
  btn.disabled = true;
  try {
    const started = await api(`/api/accounts/${id}/sync${deep ? '?deep=true' : ''}`, { method: 'POST' });
    toast(started.message);
    if (!started.started) { btn.disabled = false; return; }
    for (let i = 0; i < 150; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      await refreshAll();
      const now = S.accounts.find((a) => a.id === id);
      if (!now) return;
      if (now.syncing) continue;
      delete S.radarVideos[id];
      if (S.view === 'radar') renderRadar();
      if (now.status === 'error') { toast(`同步失败：${now.last_error || '未知原因'}`); return; }
      const added = (now.video_count || 0) - was;
      toast(`${now.nickname || '账号'}：${added > 0 ? `多了 ${added} 条` : '没有新的作品'}，库里现在 ${now.video_count} 条`);
      return;
    }
    toast('还在同步，稍后看这张卡片上的时间');
  } catch (err) { toast(err.message); btn.disabled = false; }
}

/** Remove / sync — the 对标 card grid. */
function bindAccountActions(root, what) {
  $$('[data-rm]', root).forEach((b) => (b.onclick = async () => {
    const acct = S.accounts.find((a) => String(a.id) === b.dataset.rm);
    if (!confirm(`把「${acct.nickname || acct.profile_url}」移出${what}？它的作品数据会一起删除，已生成的拆解报告保留。`)) return;
    try { await api(`/api/accounts/${b.dataset.rm}`, { method: 'DELETE' }); toast(`已移出${what}`); await refreshAll(); } catch (err) { toast(err.message); }
  }));
  $$('[data-sync]', root).forEach((b) => (b.onclick = () => syncOneAccount(Number(b.dataset.sync), b)));
}

let thrTimer;
$('#thr').oninput = (e) => {
  const value = Number(e.target.value);
  $('#thrV').textContent = value + '×';
  S.state.settings.threshold = value;
  clearTimeout(thrTimer);
  thrTimer = setTimeout(async () => {
    try {
      await api('/api/settings', { method: 'PUT', body: { threshold: value } });
      $('#thrSaved').textContent = '已保存';
      setTimeout(() => ($('#thrSaved').textContent = ''), 1500);
      await refreshAll();
    } catch (err) { toast(err.message); }
  }, 350);
};
$$('#v-radar [data-days]').forEach((b) => (b.onclick = () => {
  S.radarDays = Number(b.dataset.days);
  $$('#v-radar [data-days]').forEach((x) => x.classList.toggle('on', x === b));
  renderRadar();
}));
$$('#v-radar [data-scope]').forEach((b) => (b.onclick = () => {
  S.radarScope = b.dataset.scope;
  $$('#v-radar [data-scope]').forEach((x) => x.classList.toggle('on', x === b));
  renderRadar();
}));
$('#radarQ').oninput = (e) => { S.radarQuery = e.target.value; renderRadar(); };
$$('#v-radar [data-sort]').forEach((b) => (b.onclick = () => {
  S.sort = b.dataset.sort;
  $$('#v-radar [data-sort]').forEach((x) => x.classList.toggle('on', x === b));
  renderRadar();
}));

/* add-account dialog */
function detectPlat(u) {
  if (/douyin\.com\/user\/|v\.douyin\.com\/|iesdouyin\.com/.test(u)) return '抖音';
  if (/xiaohongshu\.com\/user\/profile|xhslink\.com\//.test(u)) return '小红书';
  if (/(^|\/\/|\s)(www\.|mobile\.)?(x|twitter)\.com\/[A-Za-z0-9_]+/.test(u)) return 'X';
  if (/weixin\.qq\.com/.test(u)) return '视频号';
  return null;
}
function showDetect() {
  const u = $('#addIn').value.trim(), pl = detectPlat(u), d = $('#addDetect');
  $$('#addPlats span').forEach((x) => x.classList.toggle('on', x.textContent === pl));
  d.classList.remove('err');
  d.textContent = !u ? '支持以上四个平台的主页链接' : pl ? (pl === '抖音' ? '识别为抖音主页，加入后立即同步' : `识别为${pl}主页，先入库，抓取待接入`) : '还没认出平台，请粘贴完整的主页链接';
}
function openAdd(mode) {
  S.addMode = mode;
  $('#addIn').value = '';
  showDetect();
  $('#addDlg').showModal();
  $('#addIn').focus();
}
$('#addIn').oninput = showDetect;
$('#addCancel').onclick = () => $('#addDlg').close();
$('#addForm').onsubmit = async (e) => {
  e.preventDefault();
  const btn = $('#addSubmit');
  btn.disabled = true;
  try {
    const res = await api('/api/accounts', { method: 'POST', body: { url: $('#addIn').value } });
    $('#addDlg').close();
    toast(res.account.platform === '抖音' ? '已加入对标库，正在同步近期作品' : `已加入对标库（${res.account.platform}，抓取待接入）`);
    await refreshAll();
  } catch (err) {
    const d = $('#addDetect');
    d.classList.add('err');
    d.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
};

/* ================= QUEUE ================= */
function renderQueue() {
  const jobs = S.jobs;
  const done = jobs.filter((j) => j.stage === 'done').length;
  const failed = jobs.filter((j) => j.stage === 'failed').length;
  $('#qMeta').textContent = `${done} 完成 · ${jobs.length - done - failed} 进行中 · ${failed} 失败`;
  if (!jobs.length) {
    $('#qList').innerHTML = '<div class="empty"><b>队列是空的</b><span>在上面粘贴视频链接，或去对标雷达把爆款加进来。</span></div>';
    return;
  }
  // Running first, then waiting jobs in the order they will run, then failures, then finished work.
  const rank = (j) => (['downloading', 'transcribing', 'analyzing'].includes(j.stage) ? 0 : j.stage === 'queued' ? 1 : j.stage === 'failed' ? 2 : 3);
  const ordered = jobs.slice().sort((a, b) => rank(a) - rank(b) || (rank(a) === 1 ? a.id - b.id : b.id - a.id));
  $('#qList').innerHTML = ordered.map((j) => {
    const idx = STAGE_INDEX[j.stage];
    const steps = STAGES.map(([key, label], k) => {
      let cls = '';
      if (j.stage === 'done' || idx > k) cls = 'ok';
      else if (idx === k) cls = 'run';
      return `<div class="step ${cls}"><i></i>${label}</div>`;
    }).join('');
    const action = j.stage === 'done'
      ? (j.has_report ? `<button class="btn small primary" type="button" data-report="${esc(j.video_id)}">看报告</button>` : '<span class="muted">报告缺失</span>')
      : j.stage === 'failed' ? `<button class="btn small" type="button" data-retry="${j.id}">重试</button>`
        : j.stage === 'queued' ? `<span class="stage-pill queued">排队中</span><button class="btn small ghost" type="button" data-cancel="${j.id}">取消</button>`
          : `<span class="stage-pill running">${STAGE_NAME[j.stage]}</span>`;
    return `<div class="q">
      <div><div class="src">${esc(j.source)} · ${day(j.created_at)}</div><div class="clamp q-title">${esc(j.title ? cleanTitle(j.title) : j.url)}</div>${j.error ? `<p class="q-error-hint">${esc(WorkbenchUI.failureHint(j.error))}</p><details class="q-error-details"><summary>错误详情${j.attempts > 1 ? ` · 已失败 ${j.attempts} 次` : ''}</summary><p>${esc(j.error)}</p><p>不会自动重试；确认原因已处理后再重试。</p></details>` : ''}</div>
      <div class="steps">${steps}</div>
      <div class="q-actions">${action}</div>
    </div>`;
  }).join('');
  bindTeardownButtons($('#qList'));
  $$('[data-cancel]').forEach((b) => (b.onclick = async () => {
    try { await api(`/api/jobs/${b.dataset.cancel}`, { method: 'DELETE' }); toast('已取消'); await refreshAll(); } catch (err) { toast(err.message); }
  }));
  $$('[data-retry]').forEach((b) => (b.onclick = async () => {
    try { await api(`/api/jobs/${b.dataset.retry}/retry`, { method: 'POST' }); toast('已重新排队'); await refreshAll(); } catch (err) { toast(err.message); }
  }));
}

$('#linkForm').onsubmit = async (e) => {
  e.preventDefault();
  try {
    const res = await api('/api/jobs', { method: 'POST', body: { url: $('#linkIn').value } });
    $('#linkIn').value = '';
    toast(res.message);
    await refreshAll();
  } catch (err) { toast(err.message); }
};

/* ================= REPORT ================= */
const SEGC = { 钩子: 'var(--seg1)', 承诺: 'var(--seg6)', 论点: 'var(--seg3)', 案例: 'var(--seg2)', 跑题: 'var(--seg5)', 收束: 'var(--seg4)', 引导: 'var(--seg6)' };
const FACTS = [
  ['multiple_of_median', '账号中位数倍数', (v) => v + '×', true], ['likes', '点赞', fmt], ['collect_per_like', '收藏/赞', pct],
  ['share_per_like', '转发/赞', pct], ['comment_per_like', '评论/赞', pct], ['account_median_likes', '账号点赞中位数', fmt],
  ['views', '播放', fmt], ['creator_fan_increment', '涨粉', fmt], ['creator_avg_view_second', '平均观看', (v) => Math.round(v) + ' 秒'],
  ['creator_bounce_rate_2s', '2 秒跳出', pct], ['creator_completion_rate_5s', '5 秒完播', pct], ['creator_completion_rate', '完播率', pct],
  ['creator_homepage_visit_count', '主页访问', fmt], ['creator_cover_click_rate', '封面点击率', pct],
];

async function toggleArchive(videoId, isArchived) {
  const btn = $('#archiveBtn');
  btn.disabled = true;
  try {
    await api(`/api/reports/${videoId}/archive`, { method: isArchived ? 'DELETE' : 'POST' });
    if (isArchived) {
      toast('已取消归档');
    } else {
      const unread = S.reports.filter((x) => !x.archived_at && x.video_id !== videoId);
      toast(unread.length ? `已归档，还剩 ${unread.length} 份没看` : '已归档，报告都看完了');
      if (!S.showArchived) {
        S.reportId = unread.length ? unread[0].video_id : null;
        S.report = null;
        history.replaceState(null, '', S.reportId ? `#report/${S.reportId}` : '#report');
      }
    }
    S.reports = await api('/api/reports');
    renderChrome();
    renderReport();
  } catch (err) {
    toast(err.message);
    btn.disabled = false;
  }
}

async function openReport(videoId) {
  S.reportId = videoId;
  S.report = null;
  go('report');
}

async function loadReport(videoId) {
  try {
    S.report = await api(`/api/reports/${videoId}`);
  } catch (err) {
    S.report = { error: err.message };
  }
  if (S.view === 'report') renderReport();
}

/* 10/4 作者：拆完的爆款可以直接入选题池（候选）；10/5 起在选题池里只有一个「复刻」 */
async function paintReportPool(videoId) {
  const box = $('#repPool');
  if (!box) return;
  let st;
  try { st = await api(`/api/reports/${videoId}/pool`); } catch (_) { return; }
  if (!document.body.contains(box)) return;
  box.innerHTML = st.topic ? '<button type="button" class="btn" id="repPoolGo">在我的选题里 →</button>' : '<button type="button" class="btn primary" id="repPoolAdd">加入选题</button>';
  const add = $('#repPoolAdd');
  if (add) add.onclick = async () => {
    add.disabled = true;
    try { await api(`/api/reports/${videoId}/pool`, { method: 'POST' }); toast('加进我的选题了：在那里点「做这条」'); if (window.refreshTopics) await window.refreshTopics(); } catch (err) { toast(err.message); }
    paintReportPool(videoId);
  };
  const goPool = $('#repPoolGo');
  if (goPool) goPool.onclick = () => window.openInputTab('mine');
}

function renderReport() {
  const pick = $('#repPick');
  const unread = S.reports.filter((r) => !r.archived_at);
  const archivedCount = S.reports.length - unread.length;
  const shown = S.showArchived ? S.reports : unread;
  // 左边一列：谁发的 / 标题 / 什么时候拆的。最新拆的排最上面（后端已按 generated_at 倒序）。
  pick.innerHTML = `<div class="panel-h"><h2>拆过的 <span class="num">${shown.length}</span></h2><small>最新在上</small></div>`
    + shown.map((r) => `<button type="button" class="rep-item ${r.video_id === S.reportId ? 'on' : ''} ${r.archived_at ? 'archived' : ''}" data-rid="${esc(r.video_id)}">
        <span class="rep-by">${r.is_self ? '我的' : esc(r.author || '对标')}</span>
        <b class="clamp2">${esc(cleanTitle(r.title))}</b>
        <small>${r.generated_at ? day(r.generated_at) : ''}${r.multiple ? ` · ${r.multiple}×` : ''}</small>
      </button>`).join('')
    + (archivedCount ? `<button type="button" class="toggle-archived" id="toggleArchived">${S.showArchived ? '收起已归档' : `已归档 ${archivedCount}`}</button>` : '');
  $$('[data-rid]', pick).forEach((b) => (b.onclick = () => openReport(b.dataset.rid)));
  if ($('#toggleArchived')) $('#toggleArchived').onclick = () => { S.showArchived = !S.showArchived; renderReport(); };
  const body = $('#repBody');
  if (!S.reports.length && !S.reportId) {
    body.innerHTML = '<div class="panel empty rep-empty"><b>还没有拆解报告</b><span>去「拆解队列」粘贴视频链接，或在对标雷达里点「拆解」。</span></div>';
    return;
  }
  if (!S.reportId && !unread.length) {
    body.innerHTML = `<div class="panel empty rep-empty"><b>报告都看完了</b><span>已归档 ${archivedCount} 份，点上面的「已归档 ${archivedCount}」可以再翻出来看。</span></div>`;
    body.dataset.rendered = '';
    return;
  }
  if (!S.reportId) { S.reportId = unread[0].video_id; history.replaceState(null, '', `#report/${S.reportId}`); }
  if (!S.report || (S.report.content_id && S.report.content_id !== S.reportId)) {
    if (!S.report || S.report.content_id !== S.reportId) {
      body.innerHTML = '<div class="panel empty rep-empty"><span class="spin"></span><span>正在读取报告…</span></div>';
      if (!S._loading || S._loading !== S.reportId) { S._loading = S.reportId; loadReport(S.reportId).finally(() => (S._loading = null)); }
      return;
    }
  }
  const r = S.report;
  if (r.error) { body.innerHTML = `<div class="panel empty rep-empty"><b>${esc(r.error)}</b></div>`; body.dataset.rendered = ''; return; }
  const entry = S.reports.find((x) => x.video_id === r.content_id);
  const isArchived = Boolean(entry && entry.archived_at);
  if (body.dataset.rendered === r.content_id + r.generated_at + isArchived) return; // keep scroll and open sections during polling
  body.dataset.rendered = r.content_id + r.generated_at + isArchived;
  const total = r.transcript.duration_seconds || (r.segments.length ? r.segments[r.segments.length - 1].end : 1);
  const facts = FACTS.filter(([k]) => r.facts[k] !== null && r.facts[k] !== undefined)
    .map(([k, l, f, hot]) => `<div><div class="l">${l}</div><div class="v ${hot && r.facts[k] >= S.state.settings.threshold ? 'hot' : ''}">${f(r.facts[k])}</div></div>`).join('');

  body.innerHTML = `
    <div class="panel">
      <div class="rep-head">
        <div>
          <div class="eyebrow">${r.facts.creator_avg_view_second ? '我的视频 · 主线诊断' : '对标拆解'} · ${esc(r.author || '')}</div>
          <h2 title="${esc(r.title)}">${esc(cleanTitle(r.title))}</h2>
          <div class="by">时长 ${mmss(total)} · 生成于 ${day(r.generated_at)}</div>
        </div>
        <div class="rep-actions">
          ${r.facts.creator_avg_view_second ? '' : '<span id="repPool"></span>'}
          <button type="button" class="btn ${isArchived ? '' : 'primary'}" id="archiveBtn">${isArchived ? '取消归档' : '看完了，归档'}</button>
          ${r.source_url ? `<a class="btn" href="${esc(r.source_url)}" target="_blank" rel="noopener">在抖音打开 ↗</a>` : ''}
        </div>
      </div>
      <div class="facts">${facts}</div>
      ${r.facts.baseline_too_small ? `<p class="hint">这个账号近期作品太少或点赞普遍很低（${fmt(r.facts.account_post_count || 0)} 条，中位数 ${fmt(r.facts.account_median_likes || 0)}），倍数没有参考意义，所以不算。</p>` : ''}
    </div>
    ${r.opening ? `<div class="panel"><div class="panel-h"><h2>观众平均看到的前 ${Math.round(r.opening.seconds)} 秒</h2><small>来自创作者后台的平均观看时长</small></div>
      <div class="opening"><p>${esc(r.opening.analysis)}</p><blockquote>${esc(r.opening.transcript)}</blockquote></div></div>` : ''}
    ${reportGridHtml(r)}`;

  bindReportGrid(body, r);
  $('#archiveBtn').onclick = () => toggleArchive(r.content_id, isArchived);
  paintReportPool(r.content_id);
}

/* 主线结构 + 为什么爆：拆解报告页和复刻页（speak.js 的左边）用同一张。只在 root 里找元素，两页同时在 DOM 里也不串。 */
function reportGridHtml(r) {
  const total = r.transcript.duration_seconds || (r.segments.length ? r.segments[r.segments.length - 1].end : 1);
  const cite = (ev) => (ev && ev.length ? ev.map((e) => `<span class="evidence"><button type="button" data-seek="${e.start}">${mmss(e.start)}</button> ${esc(e.quote)}</span>`).join('') : '');
  return `<div class="rep-grid">
      <div class="panel">
        <div class="panel-h"><h2>主线结构</h2><span class="drift-sum">跑题 ${Math.round(r.drift.seconds)} 秒 · 占 ${pct(r.drift.share, 0)}</span></div>
        <div class="spine">
          <p class="thesis">${esc(r.thesis.text)}</p>
          <div class="tl">${r.segments.map((s, i) => `<button type="button" class="${s.drift ? 'drift' : ''}" style="flex:${Math.max(1, s.end - s.start)};background:${SEGC[s.label] || 'var(--seg6)'}" data-i="${i}" title="${esc(s.label)} ${mmss(s.start)}–${mmss(s.end)} · ${esc(s.summary)}">${(s.end - s.start) > total * 0.07 ? esc(s.label) : ''}</button>`).join('')}</div>
          <div class="tl-axis"><span>0:00</span><span>${mmss(total / 2)}</span><span>${mmss(total)}</span></div>
          <div class="legend">${[...new Set(r.segments.map((s) => s.label))].map((k) => `<span><i style="background:${SEGC[k] || 'var(--seg6)'}"></i>${k}</span>`).join('')}<span style="color:var(--warn)">斜纹 = 不服务主线</span></div>
        </div>
        <div class="transcript">${r.segments.map((s, i) => `<div class="line ${s.drift ? 'driftline' : ''}" data-i="${i}">
          <div class="ts">${mmss(s.start)}</div>
          <div class="lab" style="color:${s.drift ? 'var(--warn)' : 'var(--ink-2)'}"><i style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${SEGC[s.label] || 'var(--seg6)'};margin-right:5px"></i>${esc(s.label)}</div>
          <div class="seg-body"><b>${esc(s.summary)}</b><span class="seg-reason">${s.drift ? '不服务主线：' : ''}${esc(s.reason)}</span>
          <details><summary>展开这段原文（${mmss(s.start)}–${mmss(s.end)}）</summary><p>${esc(s.text)}</p></details></div>
        </div>`).join('')}</div>
      </div>
      <div class="side">
        <div class="panel"><div class="panel-h"><h2>为什么爆</h2></div><div class="why"><ul>${r.why_boom.map((w) => `<li><span style="color:var(--ink)">${esc(w.text)}</span>${cite(w.evidence)}</li>`).join('')}</ul></div></div>
        <div class="banner info"><div>${esc(String(r.hypothesis_note || '').replace(' / 为什么散', ''))}</div></div>
      </div>
    </div>`;
}

function bindReportGrid(root, r) {
  const seek = (i) => {
    $$('.tl button', root).forEach((x) => x.classList.toggle('on', x.dataset.i === String(i)));
    $$('.transcript .line', root).forEach((l) => l.classList.toggle('on', l.dataset.i === String(i)));
    const el = $(`.transcript .line[data-i="${i}"]`, root);
    if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); const d = $('details', el); if (d) d.open = true; }
  };
  $$('.tl button', root).forEach((b) => (b.onclick = () => seek(Number(b.dataset.i))));
  $$('[data-seek]', root).forEach((b) => (b.onclick = () => {
    const t = Number(b.dataset.seek);
    let idx = 0;
    r.segments.forEach((s, i) => { if (s.start <= t + 0.5) idx = i; });
    seek(idx);
  }));
}


/* ================= boot & polling ================= */
async function boot() {
  bindNav();
  S.view = readHash();
  S.routeHash = location.hash;
  paintChrome(S.view);
  try {
    await refreshAll();
  } catch (err) {
    $('#globalBanner').innerHTML = `<div class="banner warn" style="margin-bottom:18px"><div><b>加载失败：</b>${esc(err.message)}</div></div>`;
  }
}

setInterval(async () => {
  if (!S.state || document.hidden) return;
  const syncing = (a) => a.syncing;
  const busy = S.state.full_sync_running || S.state.active_jobs > 0 || S.accounts.some(syncing)
    || (S.mine.account && S.mine.account.syncing);
  if (!busy) return;
  const focus = document.activeElement;
  if (focus && (focus.tagName === 'INPUT' || $('#addDlg').open)) return;
  try { await refreshAll(); } catch (_) { /* transient */ }
}, 3000);

boot();
