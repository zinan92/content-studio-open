'use strict';
/* 复盘页下半（10/19 作者：「战况和汇总放到一起，改名叫复盘……核心是要 simplify」）：
   只剩「每条内容 × 每个平台」一张表，画在首页（VIEWS.today）KPI 和月历下面。
   原汇总上半的触达、往日、这周复盘、倍数图都拿掉了：数和 KPI 卡、抖音作品分析重复。 */
window.VIEWS = window.VIEWS || {};

/* One shared floating tooltip for every chart mark carrying data-tip. */
function bindTips(root) {
  let tip = $('#chartTip');
  if (!tip) { tip = document.createElement('div'); tip.id = 'chartTip'; tip.className = 'chart-tip'; tip.hidden = true; document.body.appendChild(tip); }
  const place = (e) => { tip.style.left = `${Math.min(e.clientX + 14, window.innerWidth - 300)}px`; tip.style.top = `${e.clientY + 14}px`; };
  $$('[data-tip]', root).forEach((el) => {
    el.onmouseenter = (e) => { tip.textContent = el.dataset.tip; tip.hidden = false; place(e); };
    el.onmousemove = place;
    el.onmouseleave = () => { tip.hidden = true; };
    if (el.classList.contains('help-q')) el.onclick = (e) => { e.stopPropagation(); const same = !tip.hidden && tip.textContent === el.dataset.tip; tip.textContent = el.dataset.tip; tip.hidden = same; place(e); };
  });
  document.addEventListener('click', () => { tip.hidden = true; }, { once: true });
}


const q = (text) => `<button class="help-q" type="button" data-tip="${esc(text)}" aria-label="怎么算的">?</button>`;

/* 往日详情里那张「每条内容在各平台的累计」（日结存的快照，只读） */
function matrixBlock(mx) {
  if (!mx || !mx.rows.length) return '';
  const all = mx.rows.flatMap((r) => Object.values(r.cells).filter((c) => c.state === 'views' && c.views).map((c) => c.views));
  const top = Math.max(1, ...all);
  // 10/8 作者：换回原来的格子——一格一个数，「已发」「—」，不在格子里摊开各形式
  const cell = (c) => {
    if (c.state === 'none') return '<td class="mx-none">—</td>';
    if (c.state === 'sent') return `<td class="mx-sent" title="${c.no_api ? '这个平台没有接口读数' : '发了，还没读到数'}">${c.no_api ? '没接口' : '已发'}</td>`;
    if (c.state !== 'views') return '<td class="mx-none">—</td>';
    const lvl = c.views >= top * 0.5 ? 3 : c.views >= top * 0.1 ? 2 : c.views ? 1 : 0;
    return `<td class="num mx-${lvl}">${fmt(c.views)}</td>`;
  };
  return `<section class="panel"><div class="panel-h"><h2>每条内容在每个平台的累计触达 <small>最近 ${mx.rows.length} 条 · 颜色越深越好</small></h2><small>倍数 = 抖音点赞 ÷ 你的中位数</small></div>
    <div class="mx-wrap"><table class="mx"><thead><tr><th>内容</th>${mx.platforms.map((p) => `<th>${esc(p.label)}</th>`).join('')}<th>合计</th><th>倍数</th></tr></thead>
      <tbody>${mx.rows.map((r) => `<tr><th title="${esc(r.title)}"><span>${esc(r.title)}</span><small>${day(r.published_at)}</small></th>${mx.platforms.map((p) => cell(r.cells[p.key] || { state: 'none' })).join('')}<td class="num"><b>${fmt(r.total)}</b>${r.metrics_complete === false ? '<small>部分已读合计</small>' : ''}</td><td class="num">${r.multiple === null ? '—' : `${r.multiple}×`}</td></tr>`).join('')}</tbody></table></div>
  </section>`;
}

/* 汇总那张表（10/6 作者）：「每条内容发在哪」和「每个平台的累计触达」原来是两张一样格子的表，合成一张。
   有数就是发了，点开看那条；「已发」是发了但读不到数；「·」是没发，点一下打开补发工作台（挑格子、预览、现场发）。 */
const SHEET = { data: null, at: 0, busy: {} };
async function loadSheet(force) {
  if (!force && SHEET.data && Date.now() - SHEET.at < 15000) return SHEET.data;
  SHEET.data = await api('/api/backfill'); SHEET.at = Date.now();
  return SHEET.data;
}
async function loadPublicationMatrix(sheet) {
  const count = sheet?.videos?.length || 30;
  const size = 500, pages = [];
  for (let offset = 0; offset < count; offset += size) {
    pages.push(api(`/api/outbox/matrix?limit=${Math.min(size, count - offset)}&offset=${offset}`));
  }
  const results = await Promise.all(pages);
  const warnings = new Map();
  for (const result of results) for (const warning of result.publication_warnings || []) warnings.set(JSON.stringify([warning.platform, warning.post_id, warning.topic_ids]), warning);
  const rows = [...new Map(results.flatMap((result) => result.rows).map((row) => [row.video_id, row])).values()];
  const loaded = new Set(rows.map((row) => row.video_id));
  const missing = (sheet?.videos || []).filter((video) => !loaded.has(video.video_id));
  return { ...results[0], rows, read_warning: missing.length ? `${missing.length} 条内容的发布状态尚未读到，请刷新后再核对。` : '', publication_warnings: [...warnings.values()], metrics_complete: results.every((result) => result.metrics_complete !== false) };
}
function sheetBlock(bf, mx) {
  if (!bf || !bf.videos.length) return '';
  const cols = bf.platforms;
  const byVid = Object.fromEntries(((mx && mx.rows) || []).map((r) => [r.video_id, r]));
  const all = Object.values(byVid).flatMap((r) => Object.values(r.cells).filter((c) => c.state === 'views' && c.views).map((c) => c.views));
  const top = Math.max(1, ...all);
  // 10/8 作者：这张表换回原来那版——数字 = 发了（点开那条）·「已发」= 发了读不到数 ·「·」= 没发，点一下补发
  const cell = (v, p) => {
    const url = (v.links || {})[p.key];
    const c = ((byVid[v.video_id] || {}).cells || {})[p.key];
    if (p.key === 'douyin' && v.hidden_on_douyin) return '<td class="mx-sent" title="抖音上已设为私密；别的平台照样补发">藏</td>';
    if (c && c.state === 'views') {
      const lvl = c.views >= top * 0.5 ? 3 : c.views >= top * 0.1 ? 2 : c.views ? 1 : 0;
      return `<td class="num mx-${lvl}">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener" title="在${esc(p.label)}打开">${fmt(c.views)}</a>` : fmt(c.views)}</td>`;
    }
    // 发布状态以 matrix 为准：旧补发记录说「发了」、但这一格其实还在草稿箱，就显示草稿
    if (c && c.publication_state === 'draft') return `<td class="mx-sent" title="在草稿箱，还没群发">草稿</td>`;
    const st = v.done[p.key];
    if (p.key === 'douyin') return `<td class="mx-sent">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener" title="在抖音上打开">↗</a>` : '—'}</td>`;
    if (v.cancelled && !st) return '<td class="mx-none" title="这条不补发了">–</td>';
    if (st === 'skip') return `<td class="mx-none" title="${esc(p.label)}：不发（补发工作台里标的）">不发</td>`;
    if (st === 'record' || st === 'mark') return `<td class="mx-sent" title="${st === 'mark' ? '你标过已经发过' : '发了，还没读到数'}">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">已发 ↗</a>` : '已发'}</td>`;
    const can = (v.video === 'master' || v.video === 'download') && v.topic_id;
    return `<td class="mx-none">${can ? `<button class="mx-dot" type="button" data-sheet-go="${esc(v.video_id)}" title="${esc(p.label)}：还没发。点一下去补发">·</button>` : `<span class="mx-dot" title="${esc(p.label)}：还没发${v.topic_id ? '' : '；先点「拿去补发」接上选题'}">·</span>`}</td>`;
  };
  // 10/14 作者：每条视频结尾送的鸡蛋，话术放在 Obsidian（005_我发出的内容/鸡蛋），这里只给个链接
  const eggCell = (v) => v.egg
    ? `<td class="mx-sent"><a href="${esc(v.egg.open_url)}" title="${esc(v.egg.sent)} 回复评论区的话术，在 Obsidian 里打开">${esc(v.egg.title)} ↗</a></td>`
    : '<td class="mx-none" title="这条没有记鸡蛋话术">—</td>';
  const firstMinor = cols.findIndex((p) => p.core === false);
  const head = `<tr><th>内容</th><th title="视频结尾送的东西：点开在 Obsidian 里看回复的话术">鸡蛋</th>${cols.map((p, i) => `<th class="${p.core === false ? 'minor' : ''} ${i === firstMinor ? 'minor-first' : ''}">${esc(p.label)}</th>`).join('')}<th>合计</th><th>倍数</th></tr>`;
  const act = (v) => {
    if (v.cancelled) return `<button class="linklike" type="button" data-sheet-cancel="${esc(v.video_id)}" data-on="0">不补发了 · 恢复</button>`;
    if (!v.missing.length) return '';
    const has = v.video === 'master' || v.video === 'download';
    if (!has) return '<span class="dim" title="原片在另一台电脑上：拷进作品库这条的「1 成片」，再点「在本机再找一遍」">作品库缺成片</span>';
    return `${v.topic_id ? `<button class="linklike" type="button" data-sheet-go="${esc(v.video_id)}">补发</button>` : `<button class="linklike" type="button" data-sheet-take="${esc(v.video_id)}" ${SHEET.busy[v.video_id] ? 'disabled' : ''}>拿去补发</button>`}<button class="linklike dim" type="button" data-sheet-cancel="${esc(v.video_id)}" data-on="1" title="没有时效性了：不再往别的平台补">不补发</button>`;
  };
  const row = (v) => { const m = byVid[v.video_id]; return `<tr class="${v.cancelled ? 'bf-cancelled' : ''}"><th title="${esc(v.title)}"><span>${esc(v.headline || v.title.slice(0, 30))}</span><small>${day(v.published_at)} · 点赞 ${fmt(v.likes)}</small><div class="mx-acts">${act(v)}</div></th>${eggCell(v)}${cols.map((p) => cell(v, p)).join('')}<td class="num"><b>${m ? fmt(m.total) : '—'}</b></td><td class="num">${v.multiple === null ? '—' : `${v.multiple}×`}</td></tr>`; };
  const todo = bf.videos.filter((v) => v.missing.length);
  const a = bf.archive || {};
  // 10/20：新发的、还没对上抖音作品的内容排在最上面：发了的格子写「已发」，数等读到了再有；没发的点一下去「发」
  const fresh = (bf.fresh || []).map((f) => `<tr class="sheet-fresh"><th title="${esc(f.title)}"><span>${esc(f.title.slice(0, 30))}</span><small>${day(f.published_at)} · 已发，等数据</small></th><td class="mx-none">—</td>${cols.map((p) => {
    const got = f.done[p.key];
    if (got) return `<td class="mx-sent">${typeof got === 'string' ? `<a href="${esc(got)}" target="_blank" rel="noopener">已发 ↗</a>` : '已发'}</td>`;
    return p.key === 'douyin' ? '<td class="mx-none" title="抖音还没对上这条">等数据</td>' : `<td class="mx-none"><button class="mx-dot" type="button" data-sheet-fa="${f.topic_id}" title="${esc(p.label)}：还没发。点一下去「发」">·</button></td>`;
  }).join('')}<td class="num">—</td><td class="num">—</td></tr>`).join('');
  return `${!mx || mx.read_warning ? `<p class="publication-warning" role="status">${esc(mx?.read_warning || '发布状态暂未读到，请刷新后再核对；当前不把旧链接当作发布回执。')}</p>` : ''}<section class="panel"><div class="panel-h"><h2>每条内容 × 每个平台 <small>${bf.videos.length + (bf.fresh || []).length} 条 · ${todo.length} 条还有平台没发</small></h2>
      <small>数字 = 发了，点开那条 · 「已发」= 发了但读不到数 · 「·」= 没发，点一下补发</small>
      <button class="btn small" type="button" id="sheetDesk">补发旧内容 →</button></div>
    <div class="mx-wrap"><table class="mx sheet"><thead>${head}</thead><tbody>${fresh}${bf.videos.map(row).join('')}</tbody></table></div>
    <details class="sheet-archive"><summary>作品库${a.archived !== undefined ? ` · 有成片 ${a.archived} / ${a.total} 条` : ''}</summary><div id="sheetArchive"></div></details>
  </section>`;
}
function bindSheet(root) {
  $$('[data-sheet-fa]', root).forEach((b) => (b.onclick = () => { S.packId = Number(b.dataset.sheetFa); go('pack'); }));
  const open = (vid) => { if (window.openBackfillDesk) window.openBackfillDesk(vid); };
  $$('[data-sheet-go]', root).forEach((b) => (b.onclick = () => open(b.dataset.sheetGo)));
  const desk = $('#sheetDesk', root); if (desk) desk.onclick = () => open();
  $$('[data-sheet-take]', root).forEach((b) => (b.onclick = async () => {
    const vid = b.dataset.sheetTake; SHEET.busy[vid] = true; b.disabled = true;
    try { await api(`/api/backfill/${vid}/take`, { method: 'POST' }); open(vid); } catch (err) { toast(err.message); }
    SHEET.busy[vid] = false; SHEET.data = null; const sb = $('#fupanTable'); if (sb) sb.dataset.sig = ''; window.renderFupanTable();
  }));
  $$('[data-sheet-cancel]', root).forEach((b) => (b.onclick = async () => {
    // 10/9 作者：改了立刻变——这一行先划掉 / 恢复，接口回来再按真实结果重画；失败了重画就变回去
    const row = b.closest('tr'), cancel = b.dataset.on === '1';
    if (row) { row.classList.toggle('bf-cancelled', cancel); row.classList.remove('just-changed'); void row.offsetWidth; row.classList.add('just-changed'); }
    b.disabled = true;
    try { await api(`/api/backfill/${b.dataset.sheetCancel}/cancel`, { method: 'POST', body: { cancel } }); toast(cancel ? '这条不补发了，能点回来' : '恢复了'); } catch (err) { toast(err.message); }
    SHEET.data = null; const sb = $('#fupanTable'); if (sb) sb.dataset.sig = ''; window.renderFupanTable(); if (window.refreshTodayBadge) window.refreshTodayBadge();
  }));
  const arch = $('.sheet-archive', root);
  if (arch) arch.ontoggle = async () => {
    if (!arch.open) return;
    const box = $('#sheetArchive', root);
    let a;
    try { a = await api('/api/archive'); } catch (err) { box.innerHTML = `<p class="dim">${esc(err.message)}</p>`; return; }
    const p = a.progress || {};
    const running = p.state === 'downloading';
    box.innerHTML = !a.path ? '<p>还没设作品库目录。去「设置」填一个（建议放在外接硬盘上）。</p>'
      : !a.available ? `<p class="bad">作品库所在的硬盘没插：${esc(a.path)}</p>`
      : `<p>作品库有成片 <b>${a.archived}</b> / ${a.total} 条（本机原片 ${a.local}，其余是抖音下载版） · <code>${esc(a.path)}</code></p>
        ${running ? `<p><span class="spin"></span> 正在存：这一轮 ${p.total || '…'} 条，已存 ${p.done || 0} 条</p>` : a.pending ? `<button class="btn small" type="button" id="sheetArchiveAll">在本机再找一遍（缺 ${a.pending} 条）</button>` : '<p class="ok">都有成片了</p>'}
        <small>按时长和日期在本机找原片，不从抖音下。</small>`;
    const all = $('#sheetArchiveAll', root);
    if (all) all.onclick = async () => { try { await api('/api/archive/run', { method: 'POST' }); toast('开始找了'); } catch (err) { toast(err.message); } };
  };
}

/* 复盘页的表：VIEWS.today 每次画完调一下；表自己记 sig，不跟着上面的卡一起重画 */
const OUT = { renderRequest: 0 };
window.renderFupanTable = async () => {
  const box = $('#fupanTable');
  if (!box) return;
  const request = ++OUT.renderRequest;
  let sheet, matrix;
  try { sheet = await loadSheet(false); matrix = await loadPublicationMatrix(sheet).catch(() => null); } catch (err) { if (request === OUT.renderRequest) box.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
  if (S.view !== 'today' || request !== OUT.renderRequest) return;
  const sig = JSON.stringify([SHEET.at, matrix]);
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  box.innerHTML = sheet && sheet.videos.length ? sheetBlock(sheet, matrix) : matrixBlock(matrix);
  bindTips(box);
  bindTeardownButtons(box);
  bindSheet(box);
};
