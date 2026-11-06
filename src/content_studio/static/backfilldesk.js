'use strict';
/* 补发工作台（10/1 作者）：「我要每天看大家的情绪和 mood……自己想好今天最适合发什么」。
 * 一张和全平台追踪一样的表（一行一条内容、一列一个平台），点格子挑今天发什么，点的顺序就是发的顺序（1、2、3、4）。
 * 确认 → 换个样子再看一遍（每格发出去是什么样、怎么发）→ 再确认，工作台按顺序现场发。
 * B 站、YouTube、X 自己发出去；公众号进草稿箱，群发他点；视频号、小红书没有自动通道，文件夹备好他传，传完点「发了」。
 * 全平台追踪那张表还是只用来看和补记（那边点「·」是「在外面发过」），挑格子只在这里。
 * 10/3 作者：发布页的「跳过」「发布完毕」搬到这里——「标不发」点格子（这一条这个平台以后也不发），
 * 打包页还挂着的那条，标题下面给「发布完毕」（结了，打包、发布页不再显示；没发的格子以后照样能补）。 */

const BW = { data: null, picks: [], step: 'pick', preview: null, poll: null, busy: false, focus: null, skipMode: false, doneOpen: false };
const BW_HOW = { auto: '自动发', draft: '进草稿箱', hand: '你来传' };
const BW_STATE = { idle: '还没发出去', stuck: '上次发到一半被打断了', waiting: '排队', running: '正在发…', login: '要先登录', done: '✓ 发出去了', draft: '进了草稿箱：去后台点发布，发完点「发了」', hand: '文件夹备好了：你传，传完点「发了」', failed: '没发出去' };

// focus：从全平台追踪点「补发」进来时那一条，打开后滚到它、闪一下（10/1 作者：补发只走这一个窗口，不再先进打包）
// preselect：从打包页「去发其他平台」进来（10/3 作者：打包好了直接到挑格子）——这一条现在能发的格子按列的顺序先点好，他看一眼、去掉不发的就行
window.openBackfillDesk = async (focus, opts) => {
  BW.picks = []; BW.step = 'pick'; BW.preview = null; BW.focus = focus || null; BW.skipMode = false; BW.doneOpen = false;
  $('#bwBody').innerHTML = '<p class="td-note"><span class="spin"></span> 读全平台追踪…</p>';
  $('#bwDlg').showModal();
  await bwLoad();
  // 从打包页进来的那条已经发齐了：把折起来的「发齐了的」打开，滚到它
  if (focus && BW.data && (BW.data.done_rows || []).some((r) => r.video_id === focus)) { BW.doneOpen = true; bwDraw(); }
  if (opts && opts.preselect && BW.data && focus) {
    const row = BW.data.rows.find((r) => r.video_id === focus);
    if (row) {
      BW.picks = BW.data.platforms.filter((p) => (row.cells[p.key] || {}).state === 'open').map((p) => ({ video_id: focus, platform: p.key }));
      bwDraw();
    }
  }
};

async function bwLoad() {
  try { BW.data = await api('/api/backfill/desk'); } catch (err) { $('#bwBody').innerHTML = `<p class="td-note warn">${esc(err.message)}</p>`; return; }
  bwDraw();
  clearTimeout(BW.poll);
  const waiting = BW.data.run.items.some((it) => it.login && it.login.state === 'running');
  if (BW.data.run.running || waiting) BW.poll = setTimeout(() => { if ($('#bwDlg').open && BW.step === 'pick') bwLoad(); }, 3000);
}

const bwKey = (vid, p) => `${vid}|${p}`;
function bwIndex(vid, p) { return BW.picks.findIndex((x) => bwKey(x.video_id, x.platform) === bwKey(vid, p)); }

function bwCell(r, p) {
  const c = r.cells[p.key] || {};
  if (c.state === 'skipped') return BW.skipMode ? `<button type="button" class="bw-c skipped" data-bw-unskip="${esc(r.video_id)}" data-p="${p.key}" title="点一下恢复：${esc(p.label)}以后还要发">不发</button>` : `<span class="bw-c skipped" title="${esc(p.label)}：不发（点下面「标不发」可以恢复）">不发</span>`;
  if (BW.skipMode && ['open', 'blocked'].includes(c.state)) return `<button type="button" class="bw-c open skip" data-bw-skip="${esc(r.video_id)}" data-p="${p.key}" title="《${esc(r.title)}》${esc(p.label)}：标成不发">×</button>`;
  if (c.state === 'sent') return c.url ? `<a class="bw-c sent" href="${esc(c.url)}" target="_blank" rel="noopener" title="${esc(p.label)}：发过了">✓</a>` : `<span class="bw-c sent" title="${esc(p.label)}：发过了">✓</span>`;
  if (c.state === 'planned') return `<span class="bw-c planned" title="今天已经排上了">今天</span>`;
  if (c.state === 'auto') return `<span class="bw-c auto" title="${esc(p.label)}降权了：按排期自动发，不用挑">自动</span>`;
  if (c.state === 'blocked') return /定稿/.test(c.why || '') && r.topic_id ? `<button type="button" class="bw-c blocked" data-bw-pack="${r.topic_id}" title="${esc(c.why)}：点一下去打包页">–</button>` : `<span class="bw-c blocked" title="${esc(c.why || '')}">–</span>`;
  const i = bwIndex(r.video_id, p.key);
  return `<button type="button" class="bw-c open ${i >= 0 ? 'on' : ''}" data-bw-cell="${esc(r.video_id)}" data-p="${p.key}" title="《${esc(r.title)}》发到${esc(p.label)}" aria-pressed="${i >= 0}">${i >= 0 ? i + 1 : '+'}</button>`;
}

/* 10/3 作者：没发出去时，不是一屏 error——说清为什么、你要做什么，按钮就在这一行：
   登录（点了弹出平台的登录页，登好了工作台自己检测、自己再发）、再发一次、或者去后台改设置。原文收在「详情」里。 */
function bwFix(it) {
  const d = it.diag;
  if (!d) return { line: '', acts: '' };
  const lg = it.login || {};
  let acts = '';
  if (d.fix === 'login') {
    acts = lg.state === 'running' ? '<span class="bw-wait"><span class="spin"></span> 等你在弹出的窗口里登录…</span>'
      : `<button class="btn small go" type="button" data-bw-login="${it.platform}">${esc(d.label)}</button>`;
  } else if (d.fix === 'setup') {
    acts = `<a class="btn small" href="${esc(d.link)}" target="_blank" rel="noopener">${esc(d.label)}</a><button class="btn small" type="button" data-bw-now="${esc(it.video_id)}" data-p="${it.platform}">再发一次</button>`;
  } else {
    acts = `<button class="btn small go" type="button" data-bw-now="${esc(it.video_id)}" data-p="${it.platform}">再发一次</button>`;
  }
  const note = lg.state === 'failed' && d.fix === 'login' ? `<span class="bw-fix-bad">${esc(lg.message)}</span>` : '';
  const raw = it.message && d.why !== it.message ? `<details class="bw-raw"><summary>详情</summary><pre>${esc(it.message)}</pre></details>` : '';
  return { line: `<span class="bw-fix"><b>${esc(d.why)}</b><span>${esc(d.todo)}</span>${note}${raw}</span>`, acts };
}

function bwRunBlock(run) {
  if (!run.items.length) return '';
  const row = (it, i) => {
    const sent = it.sent || it.state === 'done';
    const hand = it.how === 'hand';
    const fix = !sent && it.diag ? bwFix(it) : null;
    // 还没发出去的（没起过、失败了、或者重启后没了进度）：自动发的能再点一次「现在发」；要他传的给文件夹和上传页
    const again = !fix && !hand && ['idle', 'failed'].includes(it.state) && !run.running ? `<button class="btn small" type="button" data-bw-now="${esc(it.video_id)}" data-p="${it.platform}">${it.state === 'failed' ? '再发一次' : '现在发'}</button>` : '';
    const open = sent && it.url ? `<a class="linklike" href="${esc(it.url)}" target="_blank" rel="noopener">打开 ↗</a>` : '';
    const tail = sent ? `<span class="bw-ok">✓ 发了</span>${open}${it.marked ? `<button class="linklike" type="button" data-bw-unsent="${esc(it.video_id)}" data-p="${it.platform}" title="审核没过、点错了：这一格回到没发出去">撤回</button>` : ''}`
      : fix ? `${run.running && fix.acts.includes('data-bw-now') ? '' : fix.acts}<button class="linklike" type="button" data-bw-drop="${esc(it.video_id)}" data-p="${it.platform}">不发这格</button>`
      : ['idle', 'stuck', 'hand', 'draft', 'failed'].includes(it.state)
      ? `${again}${hand ? `<button class="btn small" type="button" data-bw-folder="${it.topic_id}" data-p="${it.platform}">打开上传文件夹</button>` : ''}${it.upload_url ? `<a class="btn small" href="${esc(it.upload_url)}" target="_blank" rel="noopener">去${esc(it.label)}上传 ↗</a>` : ''}<button class="btn small go" type="button" data-bw-sent="${esc(it.video_id)}" data-p="${it.platform}">发了</button>${['idle', 'failed', 'stuck'].includes(it.state) ? `<button class="linklike" type="button" data-bw-drop="${esc(it.video_id)}" data-p="${it.platform}">不发这格</button>` : ''}` : '';
    const status = fix ? fix.line : `<small>${it.state === 'running' ? '<span class="spin"></span> ' : ''}${sent ? (it.platform === 'bilibili' && it.url ? 'B 站审核通过后链接才打得开' : '') : esc(BW_STATE[it.state] || it.state)}${it.message && !sent ? ` · ${esc(it.message)}` : ''}</small>`;
    return `<div class="bw-run-i ${sent ? 'sent' : it.state}"><span class="bw-n">${i + 1}</span><span class="t"><b>《${esc(it.title)}》→ ${esc(it.label)}</b>
      ${status}</span><span class="acts">${tail}</span></div>`;
  };
  return `<section class="bw-run"><h3>今天在发的 ${run.running ? '<small><span class="spin"></span> 一格一格发，前一格发完才发下一格</small>' : ''}</h3>${run.items.map(row).join('')}</section>`;
}

function bwPickView(d) {
  // 10/3 作者：抖音也放进表里，最左边——每条都是从抖音发出去的，点 ↗ 打开那一条
  // 10/4 作者：X 先发 → 抖音 · 小红书 · 视频号同时传 → B 站 · YouTube · 公众号降权（最右、淡、自动发）
  const lead = d.platforms.filter((p) => p.key === 'x');
  const rest = d.platforms.filter((p) => p.key !== 'x');
  const th = (p) => `<th class="c ${p.core === false ? 'minor' : ''}">${esc(p.label)}<small class="bw-how ${p.core === false ? 'auto' : p.how}" title="${esc(p.how_text)}">${p.key === 'x' ? '先发' : p.core === false ? '自动发' : BW_HOW[p.how] || ''}</small></th>`;
  const td = (r, p) => `<td class="c ${p.core === false ? 'minor' : ''}">${bwCell(r, p)}</td>`;
  const head = `<tr><th>内容</th>${lead.map(th).join('')}<th class="c">抖音<small class="bw-how">同时传</small></th>${rest.map(th).join('')}</tr>`;
  const close = (r) => r.closable ? `<button class="linklike bw-close" type="button" data-bw-close="${r.topic_id}" title="这条结了：打包、发布页不再显示它；没发的格子以后照样能在这里补">发布完毕</button>` : '';
  const dy = (r) => {
    const x = r.douyin || {};
    if (x.hidden) return '<span class="bw-c sent" title="抖音上设成了私密">藏</span>';
    return x.url ? `<a class="bw-c sent" href="${esc(x.url)}" target="_blank" rel="noopener" title="在抖音上打开">✓</a>` : '<span class="bw-c sent">✓</span>';
  };
  const tr = (r) => `<tr class="${BW.focus === r.video_id ? 'bw-focus' : ''}" data-bw-row="${esc(r.video_id)}"><td class="bw-t"><b>${esc(r.title)}</b><small>${esc((r.published_at || '').slice(0, 10))}${r.likes != null ? ` · 点赞 ${fmt(r.likes)}` : ''}${close(r)}</small></td>${lead.map((p) => td(r, p)).join('')}<td class="c">${dy(r)}</td>${rest.map((p) => td(r, p)).join('')}</tr>`;
  const rows = d.rows.map(tr).join('');
  // 发齐了的（每个平台都发了或标了不发）：不从这里消失，折在表下面，展开能看到每条发在了哪
  const doneRows = d.done_rows || [];
  const done = doneRows.length ? `<details class="bw-done" ${BW.doneOpen ? 'open' : ''}><summary>发齐了的 ${doneRows.length} 条<small>展开看每条发在了哪</small></summary>
      <div class="bw-tbl"><table><thead>${head}</thead><tbody>${doneRows.map(tr).join('')}</tbody></table></div></details>` : '';
  // 10/5 起补发不顶出摊（出摊 = 一条新视频），这里只说今天排了几格
  const note = `今天已排 ${d.planned} 格${BW.picks.length ? `，这次又选了 ${BW.picks.length} 格` : ''}。补发不算分，旧内容慢慢发完就好。`;
  if (BW.skipMode) {
    return `<p class="td-note bw-skipnote">点格子标成「不发」：这一条这个平台以后也不发，不算缺、补发不再挑它。再点一下恢复。</p>
    ${d.rows.length ? `<div class="bw-tbl skipping"><table><thead>${head}</thead><tbody>${rows}</tbody></table></div>` : '<p class="td-note">都发齐了。</p>'}${done}
    <div class="bw-bar"><span>标好了点右边，回去挑今天发什么。</span><span class="btns"><button class="btn go" type="button" data-bw-skipmode>标好了</button></span></div>`;
  }
  return `${bwRunBlock(d.run)}
    <p class="td-note">看今天大家的情绪，点格子挑今天发什么：点的顺序就是发的顺序，再点一下取消。✓ 是发过了，– 是现在发不了（鼠标停上去看为什么），「不发」是你标了不发的。</p>
    ${d.rows.length ? `<div class="bw-tbl"><table><thead>${head}</thead><tbody>${rows}</tbody></table></div>` : '<p class="td-note">都发齐了。</p>'}${done}
    <div class="bw-bar"><span>已选 <b>${BW.picks.length}</b> 格 · ${note}</span>
      <span class="btns"><button class="btn quiet" type="button" data-bw-skipmode title="有的平台这一条不打算发：标成不发，就不算缺">标不发</button><button class="btn quiet" type="button" data-bw-clear ${BW.picks.length ? '' : 'disabled'}>清空</button><button class="btn go" type="button" data-bw-review ${BW.picks.length && !BW.busy ? '' : 'disabled'}>确认，换个样子看一遍 →</button></span></div>`;
}

function bwPreviewView(pv) {
  const item = (x) => `<article class="bw-pv">
      <span class="bw-n">${x.n}</span>
      ${x.cover ? `<img src="${esc(x.cover)}" alt="" loading="lazy">` : '<span class="bw-nocover"></span>'}
      <div class="bw-pv-b"><h4>《${esc(x.title)}》→ ${esc(x.label)}</h4>
        <p class="bw-how-line ${x.how}">${esc(x.how_text)}</p>
        ${x.article && x.article.title ? `<p><b>文章：${esc(x.article.title)}</b></p>${x.article.head.map((h) => `<p class="bw-dim">${esc(h)}</p>`).join('')}${x.article.layout_url ? `<a class="linklike" href="${esc(x.article.layout_url)}" target="_blank" rel="noopener">看完整排版 ↗</a>` : ''}`
          : `${x.copy.title ? `<p><b>${esc(x.copy.title)}</b></p>` : ''}${x.copy.body ? `<p class="bw-dim">${esc(x.copy.body.slice(0, 160))}${x.copy.body.length > 160 ? '…' : ''}</p>` : ''}${x.copy.tags.length ? `<p class="bw-dim">${x.copy.tags.map((t) => '#' + esc(t)).join(' ')}</p>` : ''}`}
      </div></article>`;
  return `<p class="td-note">按这个顺序发。点「开始发」就是你的确认：自动发的马上发出去，公众号进草稿箱，视频号、小红书把文件夹备好。</p>
    <div class="bw-pvs">${pv.items.map(item).join('')}</div>

    <div class="bw-bar"><span>${pv.items.length} 格</span><span class="btns"><button class="btn quiet" type="button" data-bw-back>← 回去改</button><button class="btn go" type="button" data-bw-go ${BW.busy ? 'disabled' : ''}>开始发</button></span></div>`;
}

function bwDraw() {
  const body = $('#bwBody');
  const d = BW.data;
  if (!d) return;
  $('#bwStep').textContent = BW.step === 'preview' ? '第 2 步 · 再看一遍' : '第 1 步 · 挑格子';
  body.innerHTML = BW.step === 'preview' && BW.preview ? bwPreviewView(BW.preview) : bwPickView(d);
  $$('[data-bw-cell]', body).forEach((b) => (b.onclick = () => {
    const i = bwIndex(b.dataset.bwCell, b.dataset.p);
    if (i >= 0) BW.picks.splice(i, 1); else BW.picks.push({ video_id: b.dataset.bwCell, platform: b.dataset.p });
    bwDraw();
  }));
  const fold = $('.bw-done', body);
  if (fold) fold.addEventListener('toggle', () => { BW.doneOpen = fold.open; });
  const mode = $('[data-bw-skipmode]', body);
  if (mode) mode.onclick = () => { BW.skipMode = !BW.skipMode; bwDraw(); };
  const skip = async (vid, platform, on) => {
    try { await api(`/api/backfill/${vid}/skip`, { method: 'POST', body: { platform, skip: on } }); } catch (err) { toast(err.message); return; }
    BW.picks = BW.picks.filter((x) => bwKey(x.video_id, x.platform) !== bwKey(vid, platform));
    await bwLoad();
  };
  $$('[data-bw-skip]', body).forEach((b) => (b.onclick = () => skip(b.dataset.bwSkip, b.dataset.p, true)));
  $$('[data-bw-unskip]', body).forEach((b) => (b.onclick = () => skip(b.dataset.bwUnskip, b.dataset.p, false)));
  $$('[data-bw-close]', body).forEach((b) => (b.onclick = async () => {
    if (!confirm('这条发布完毕？打包、发布页不再显示它；没发的格子以后照样能在这里补。')) return;
    try { await api(`/api/topics/${b.dataset.bwClose}/close`, { method: 'POST' }); toast('结了。没发的格子还在表里，想补随时补'); } catch (err) { toast(err.message); return; }
    if (window.invalidatePack) window.invalidatePack();
    if (window.invalidatePublish) window.invalidatePublish();
    await bwLoad();
  }));
  const clear = $('[data-bw-clear]', body);
  if (clear) clear.onclick = () => { BW.picks = []; bwDraw(); };
  const review = $('[data-bw-review]', body);
  if (review) review.onclick = async () => {
    BW.busy = true; bwDraw();
    try { BW.preview = await api('/api/backfill/desk/preview', { method: 'POST', body: { cells: BW.picks } }); BW.step = 'preview'; } catch (err) { toast(err.message); }
    BW.busy = false; bwDraw();
    body.scrollTop = 0;
  };
  const back = $('[data-bw-back]', body);
  if (back) back.onclick = () => { BW.step = 'pick'; bwDraw(); };
  const goBtn = $('[data-bw-go]', body);
  if (goBtn) goBtn.onclick = async () => {
    BW.busy = true; bwDraw();
    try {
      const r = await api('/api/backfill/desk/go', { method: 'POST', body: { cells: BW.picks } });
      toast(`开始发：${r.started} 格，按你点的顺序`);
      BW.picks = []; BW.step = 'pick'; BW.preview = null;
    } catch (err) { toast(err.message); }
    BW.busy = false;
    await bwLoad();
    body.scrollTop = 0;
  };
  $$('[data-bw-folder]', body).forEach((b) => (b.onclick = async () => {
    try { await api(`/api/topics/${b.dataset.bwFolder}/upload-folder`, { method: 'POST', body: { platform: b.dataset.p, open: true } }); toast('文件夹打开了：视频、封面、文案.txt 都在里面'); } catch (err) { toast(err.message); }
  }));
  $$('[data-bw-login]', body).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try { await api(`/api/platforms/${b.dataset.bwLogin}/login`, { method: 'POST' }); toast('登录窗口打开了：登好了这里会自己检测、自己再发'); } catch (err) { toast(err.message); b.disabled = false; return; }
    bwLoad();
  }));
  $$('[data-bw-now]', body).forEach((b) => (b.onclick = async () => {
    if (!confirm('这一格现在发出去？')) return;
    try { await api('/api/backfill/desk/go', { method: 'POST', body: { cells: [{ video_id: b.dataset.bwNow, platform: b.dataset.p }] } }); toast('开始发了'); } catch (err) { toast(err.message); }
    bwLoad();
  }));
  $$('[data-bw-drop]', body).forEach((b) => (b.onclick = async () => {
    try { await api('/api/backfill/desk/drop', { method: 'POST', body: { video_id: b.dataset.bwDrop, platform: b.dataset.p } }); toast('拿掉了，可以在表里重新挑'); } catch (err) { toast(err.message); }
    bwLoad();
  }));
  $$('[data-bw-unsent]', body).forEach((b) => (b.onclick = async () => {
    if (!confirm('这一格撤回成「没发出去」？（审核没过、点错了）')) return;
    try { await api(`/api/backfill/${b.dataset.bwUnsent}/mark`, { method: 'POST', body: { platform: b.dataset.p, done: false } }); toast('撤回了，这一格回到没发出去'); } catch (err) { toast(err.message); }
    bwLoad();
  }));
  $$('[data-bw-pack]', body).forEach((b) => (b.onclick = () => {
    S.packId = Number(b.dataset.bwPack);
    if (window.invalidatePack) window.invalidatePack();
    $('#bwDlg').close();
    go('pack');
  }));
  if (BW.focus && BW.step === 'pick') {
    const row = $(`[data-bw-row="${BW.focus}"]`, body);
    if (row) row.scrollIntoView({ block: 'center' });
  }
  $$('[data-bw-sent]', body).forEach((b) => (b.onclick = async () => {
    try { await api(`/api/backfill/${b.dataset.bwSent}/mark`, { method: 'POST', body: { platform: b.dataset.p, done: true } }); } catch (err) { toast(err.message); }
    bwLoad();
  }));
}

document.addEventListener('DOMContentLoaded', () => {
  const dlg = $('#bwDlg');
  if (!dlg) return;
  $('#bwClose').onclick = () => dlg.close();
  dlg.addEventListener('close', () => {
    clearTimeout(BW.poll);
    const tb = $('#todayBody');
    if (tb) tb.dataset.sig = '';
    if (typeof S !== 'undefined' && S.view === 'pack' && window.invalidatePack) window.invalidatePack();
    if (typeof S !== 'undefined' && ['today', 'backfill', 'pack', 'platform'].includes(S.view)) { const sb = $('#fupanTable'); if (sb) sb.dataset.sig = ''; renderView(); }
  });
});
