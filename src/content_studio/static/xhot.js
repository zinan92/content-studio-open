'use strict';
/* X 上在火（10/8 作者，#539）：读 xzhishu.com 的热榜。X 页一块、进项一个 tab，同一份数据、同一个画法。
 * 三个榜：热门话题、热门长文、热门推文；24/48 小时；阅读最多 / 收藏最多 / 最新发布；按分类（默认 AI）。
 * 10/9 作者「过去 10 个小时什么东西在持续获得注意力……我自己有点看不过来」：先看「持续在涨」——几个分类合起来，
 * 最近 10 小时一直有人看、最后几小时还没掉的，每条带一条逐小时的线。
 * 每条两个动作：「引用它」按你的风格写一条引用帖建议稿（发 X 那个弹窗，你改完点了才发）；「收藏素材」存进「选题 → 我收藏的」。 */

const XH = { kind: 'rising', period: '24h', dim: {}, category: 'ai', data: {}, loadedAt: {}, pending: {}, errors: {}, timer: null, open: null, saved: {}, visible: 10, viewKey: null };
const XH_PAGE_SIZE = 10;
const XH_TTL = 10 * 60 * 1000;
const XH_DIM = { heat: '热度', reads: '阅读最多', bookmarks: '收藏最多', latest: '最新发布', velocity: '涨得最快' };

function xhKey() { return XH.kind === 'rising' ? 'rising' : [XH.kind, XH.period, XH.dim[XH.kind] || '', XH.kind === 'topics' ? 'all' : XH.category].join('|'); }

function xhLoad(fresh = false) {
  const key = xhKey();
  if (XH.pending[key]) return XH.pending[key];
  delete XH.errors[key];
  const q = new URLSearchParams({ kind: XH.kind, period: XH.period, category: XH.category, ...(XH.dim[XH.kind] ? { dimension: XH.dim[XH.kind] } : {}), ...(fresh ? { fresh: '1' } : {}) });
  XH.pending[key] = Promise.resolve().then(async () => {
    try {
      XH.data[key] = await api(`/api/xhot?${q}`);
      XH.loadedAt[key] = Date.now();
    } catch (err) { XH.errors[key] = err.message; }
  }).finally(() => {
    delete XH.pending[key];
    if (key === xhKey()) xhRender(); // 只重画当前筛选；旧请求仍可写入自己的缓存。
  });
  return XH.pending[key];
}

const xhNum = (n) => (n >= 10000 ? `${(n / 10000).toFixed(n >= 100000 ? 0 : 1)}万` : String(n || 0));

function xhActs(it) {
  if (!it.url) return '';
  const payload = { kind: 'xhot', quote: true, url: it.url, title: it.title, author: [it.author, it.handle].filter(Boolean).join(' '), text: it.text };
  const saved = XH.saved[it.url];
  return `<span class="xh-acts">
    ${window.xcBtn ? window.xcBtn(payload, `引用 ${it.author || ''}`, '引用它', '按你的风格写一条引用帖建议，你改完点了才发；引用帖算原创，回复不算') : ''}
    <button class="btn small ghost" type="button" data-xh-save="${esc(it.url)}" ${saved ? 'disabled' : ''}>${saved ? '已收藏' : '收藏素材'}</button>
    <a class="btn small ghost" href="${esc(it.url)}" target="_blank" rel="noopener" title="去 X 看原帖">原帖 ↗</a></span>`;
}

function xhPost(it) {
  const nums = [`读 ${xhNum(it.reads)}`, it.bookmarks ? `藏 ${xhNum(it.bookmarks)}` : '', it.likes ? `赞 ${xhNum(it.likes)}` : ''].filter(Boolean).map((x) => `<i>${x}</i>`).join('');
  const preview = it.kind === 'articles' && it.text && it.text !== it.title ? `<p class="xh-text">${esc(it.text.length > 140 ? it.text.slice(0, 140) + '…' : it.text)}</p>` : '';
  const title = it.kind === 'articles' ? it.title : (it.text.length > 160 ? it.text.slice(0, 160) + '…' : it.text);
  return `<li class="xh-row">
    <span class="xh-rank">${esc(String(it.rank || ''))}</span>
    <div class="xh-main"><b class="xh-title">${esc(title)}</b>${preview}
      <span class="xh-meta"><b>${esc(it.author)}</b>${it.category ? `<i>${esc(it.category)}</i>` : ''}${nums}</span></div>
    ${xhActs(it)}
  </li>`;
}

/* 逐小时的阅读线：最近 10 小时那段描粗 */
function xhSpark(trend) {
  const pts = (trend || []).slice(trend && trend[0] === 0 ? 1 : 0);
  if (pts.length < 2) return '';
  const w = 120, h = 28, max = Math.max(...pts, 1), step = w / (pts.length - 1);
  const xy = (v, i) => `${(i * step).toFixed(1)},${(h - 2 - (v / max) * (h - 4)).toFixed(1)}`;
  const from = Math.max(0, pts.length - 10);
  return `<svg class="xh-spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">
    <polyline class="xh-spark-all" points="${pts.map(xy).join(' ')}"/>
    <polyline class="xh-spark-10" points="${pts.slice(from).map((v, i) => xy(v, i + from)).join(' ')}"/></svg>`;
}

function xhRising(it) {
  const title = it.kind === 'articles' ? it.title : (it.text.length > 140 ? it.text.slice(0, 140) + '…' : it.text);
  return `<li class="xh-row">
    <span class="xh-rank">${esc(String(it.rank || ''))}</span>
    <div class="xh-main"><b class="xh-title">${esc(title)}</b>
      <span class="xh-meta"><b>${esc(it.author)}</b>${it.category ? `<i>${esc(it.category)}</i>` : ''}<i>${it.kind === 'articles' ? '长文' : '推文'}</i><i>近 10 小时 +${xhNum(it.gained)} 阅读</i><i>发出 ${it.hours} 小时</i></span></div>
    ${xhSpark(it.trend)}
    ${xhActs(it)}
  </li>`;
}

function xhTopic(t) {
  const open = XH.open === t.id;
  return `<li class="xh-row xh-topic">
    <span class="xh-rank">${esc(String(t.rank || ''))}</span>
    <div class="xh-main"><button class="linkish xh-title" type="button" data-xh-open="${esc(t.id)}" aria-expanded="${open}">${esc(t.title)}</button>
      <p class="xh-text">${esc(t.text)}</p>
      <span class="xh-meta"><i>热度 ${esc(String(t.heat ?? ''))}</i><i>${t.tweet_count} 条帖子</i><i>读 ${xhNum(t.reads)}</i>${t.tags.length ? `<i>${t.tags.map(esc).join(' / ')}</i>` : ''}</span>
      ${open ? `<ul class="xh-list xh-sub">${t.tweets.map((s) => xhPost({ ...s, rank: '' })).join('')}</ul>` : ''}</div>
    <span class="xh-acts"><button class="btn small ghost" type="button" data-xh-open="${esc(t.id)}" aria-expanded="${open}">${open ? '收起' : `看 ${t.tweets.length} 条帖子`}</button></span>
  </li>`;
}

// 重绘后保留键盘操作位置；后台刷新、收藏反馈不把读者送回页首。
function xhRestorePosition(box) {
  const active = typeof document !== 'undefined' ? document.activeElement : null;
  const attrs = ['data-xh-kind', 'data-xh-period', 'data-xh-dim', 'data-xh-cat', 'data-xh-fresh', 'data-xh-retry', 'data-xh-more', 'data-xh-less', 'data-xh-open', 'data-xh-save'];
  const attr = active && box.contains?.(active) ? attrs.find((name) => active.hasAttribute(name)) : null;
  const value = attr ? active.getAttribute(attr) : null;
  const focusIndex = attr ? $$(`[${attr}]`, box).filter((el) => el.getAttribute(attr) === value).indexOf(active) : -1;
  const scroll = typeof window.scrollY === 'number' ? { top: window.scrollY, left: window.scrollX } : null;
  return () => {
    if (attr) {
      const candidates = $$(`[${attr}]`, box);
      const matches = candidates.filter((el) => el.getAttribute(attr) === value && !el.disabled);
      const target = matches[focusIndex] || matches[0]
        || $('[data-xh-more]', box) || $('[data-xh-less]', box) || $('[data-xh-fresh]', box);
      target?.focus?.({ preventScroll: true });
    }
    if (scroll) window.scrollTo({ ...scroll, behavior: 'instant' });
  };
}

function xhRender(box) {
  box = box || XH.box;
  if (!box || !box.isConnected) return;
  XH.box = box;
  const restorePosition = xhRestorePosition(box);
  const key = xhKey();
  if (XH.viewKey !== key) {
    XH.viewKey = key;
    XH.visible = XH_PAGE_SIZE;
    XH.open = null;
  }
  const d = XH.data[key];
  const error = XH.errors[key];
  const remaining = d ? XH_TTL - (Date.now() - XH.loadedAt[key]) : 0;
  if (XH.timer) clearTimeout(XH.timer);
  XH.timer = null;
  if ((!d || remaining <= 0) && !XH.pending[key] && !error) xhLoad();
  else if (d && remaining > 0 && !error) {
    XH.timer = setTimeout(() => xhRender(), remaining); // 离开热榜后不再请求；回来时按时间重读。
  }
  const loading = !!XH.pending[key];
  const meta = d || Object.values(XH.data)[0];
  const dims = meta && meta.dimensions ? meta.dimensions[XH.kind] || [] : [];
  const rising = XH.kind === 'rising';
  const seg = (label, items, cur, attr) => `<div class="xh-filter"><span class="xh-filter-label">${label}</span><div class="seg-toggle" role="group" aria-label="${label}">${items.map(([k, l]) => `<button type="button" class="${k === cur ? 'on' : ''}" aria-pressed="${k === cur}" ${attr}="${esc(k)}">${esc(l)}</button>`).join('')}</div></div>`;
  const status = error ? `<div class="xh-status xh-error" role="alert"><div><b>${d ? '更新失败，保留上次的榜单' : '暂时读不到热榜'}</b><p>${esc(error)}</p></div><button class="btn small ghost" type="button" data-xh-retry>重试</button></div>`
    : loading && !d ? `<div class="xh-skeleton" role="status" aria-label="在读 X 指数榜">${'<div class="xh-row"><span class="sk sk-rank"></span><div><span class="sk sk-title"></span><span class="sk sk-line"></span><span class="sk sk-meta"></span></div></div>'.repeat(4)}</div>` : '';
  const count = d ? Math.min(XH.visible, d.items.length) : 0;
  const list = !d ? ''
    : !d.items.length ? '<div class="empty xh-empty"><b>这个筛选下暂时没有内容</b><span>换个榜单、分类或时间看看，也可以刷新再试。</span></div>'
      : `<ol class="xh-list">${d.items.slice(0, count).map((it) => (rising ? xhRising(it) : XH.kind === 'topics' ? xhTopic(it) : xhPost(it))).join('')}</ol>
        <div class="xh-pagination"><span role="status">${count} / ${d.items.length}</span><div>
          ${count < d.items.length ? `<button class="btn small ghost" type="button" data-xh-more>再看 ${Math.min(XH_PAGE_SIZE, d.items.length - count)} 条</button>` : ''}
          ${count > XH_PAGE_SIZE ? '<button class="btn small ghost" type="button" data-xh-less>收起到前 10 条</button>' : ''}
        </div></div>`;
  box.innerHTML = `<section class="panel xh${loading && d ? ' is-refreshing' : ''}" aria-label="X 上在火">
    <header class="xh-h"><div><h2>X 上在火</h2><small>来自 <a href="${esc((d && d.source) || 'https://xzhishu.com')}" target="_blank" rel="noopener">X 指数榜</a>${d && d.updated_at ? ` · ${esc(xlHmSafe(d.updated_at))} 更新` : ''} · 每 10 分钟一次</small></div>
      <button class="btn small ghost" type="button" data-xh-fresh aria-disabled="${loading}">${loading ? '更新中…' : '刷新'}</button></header>
    <div class="xh-bar">
      ${seg('榜单', [['rising', '持续在涨'], ['topics', '话题'], ['articles', '长文'], ['tweets', '推文']], XH.kind, 'data-xh-kind')}
      ${rising ? '<small class="xh-note">AI、科技、知识分享、独立开发、出海这几类合起来：最近 10 小时一直有人看、最后几小时还没掉下去的</small>' : ''}
      ${!rising ? seg('时间', [['24h', '24 小时'], ['48h', '48 小时']], XH.period, 'data-xh-period') : ''}
      ${!rising && dims.length > 1 ? seg('排序', dims.map((k) => [k, XH_DIM[k] || k]), XH.dim[XH.kind] || dims[0], 'data-xh-dim') : ''}
      ${!rising && XH.kind !== 'topics' && meta && meta.categories ? `<label class="xh-filter"><span class="xh-filter-label">分类</span><select class="xh-cat" data-xh-cat aria-label="分类">${meta.categories.map((c) => `<option value="${esc(c.key)}" ${c.key === XH.category ? 'selected' : ''}>${esc(c.label)}</option>`).join('')}</select></label>` : ''}
    </div>
    ${status}${list}
  </section>`;
  xhBind(box);
  restorePosition();
}

function xlHmSafe(iso) { try { return new Date(iso).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }); } catch (_) { return ''; } }

function xhBind(box) {
  const redo = () => xhRender(box);
  $$('[data-xh-kind]', box).forEach((b) => (b.onclick = () => { XH.kind = b.dataset.xhKind; XH.open = null; redo(); }));
  $$('[data-xh-period]', box).forEach((b) => (b.onclick = () => { XH.period = b.dataset.xhPeriod; redo(); }));
  $$('[data-xh-dim]', box).forEach((b) => (b.onclick = () => { XH.dim[XH.kind] = b.dataset.xhDim; redo(); }));
  const cat = $('[data-xh-cat]', box);
  if (cat) cat.onchange = () => { XH.category = cat.value; redo(); };
  const fresh = $('[data-xh-fresh]', box);
  const reload = () => { if (XH.pending[xhKey()]) return XH.pending[xhKey()]; const pending = xhLoad(true); xhRender(box); return pending; };
  if (fresh) fresh.onclick = reload;
  const retry = $('[data-xh-retry]', box);
  if (retry) retry.onclick = reload;
  const more = $('[data-xh-more]', box);
  if (more) more.onclick = () => { XH.visible += XH_PAGE_SIZE; redo(); };
  const less = $('[data-xh-less]', box);
  if (less) less.onclick = () => { XH.visible = XH_PAGE_SIZE; redo(); $('[data-xh-more]', box)?.scrollIntoView?.({ block: 'nearest' }); };
  $$('[data-xh-open]', box).forEach((b) => (b.onclick = () => { XH.open = XH.open === b.dataset.xhOpen ? null : b.dataset.xhOpen; xhRender(box); }));
  $$('[data-xh-save]', box).forEach((b) => (b.onclick = async () => {
    const d = XH.data[xhKey()];
    const all = d ? d.items.flatMap((it) => [it, ...(it.tweets || [])]) : [];
    const it = all.find((x) => x.url === b.dataset.xhSave);
    if (!it) return;
    b.disabled = true; b.textContent = '已收藏';
    b.classList.remove('just-changed'); void b.offsetWidth; b.classList.add('just-changed');
    try {
      const r = await api('/api/xhot/save', { method: 'POST', body: it });
      XH.saved[it.url] = true;
      if (window.invalidateInbox) window.invalidateInbox();
      toast(r.new ? '已收藏素材：在「选题 → 我收藏的」里查看' : '已经收藏过了：在「选题 → 我收藏的」里查看');
      xhRender();
    } catch (err) { toast(err.message); b.disabled = false; b.textContent = '收藏素材'; }
  }));
}

window.renderXHot = (box) => xhRender(box);
