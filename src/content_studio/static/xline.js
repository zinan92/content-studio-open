'use strict';
/* X 单独一条线。10/5 作者 改版：「随手写我直接去 X 上写就好了，代发也不用了。」
 * 现在分三块：
 *   今天的短帖——Wendy 前一晚从你的原始输出、原则、预测里排好 10 条（只删口语、不改词），每条一个勾一个叉；
 *     早上一分钟勾完，勾了的当天全天（0:00–24:00）排着发；没勾的不发。
 *   长文（10/7 #505 长帖，10/8 #537 改长文）——同一个队列里每天再排 3 篇：一篇原始输出，park-writing 改一遍、
 *     配个人形象插图，发成 X 图文文章；做好了才能勾，勾了才发。
 *   Wendy 从哪里挑——你自己的素材，折起来；不想让她排的点「放一边」。 */

const XL = { showDone: false, data: null, daily: null, tab: 'obsidian', showHidden: false, srcOpen: false, poll: null, showPosted: false, mode: 'pending', pending: {}, errors: {}, mounts: {}, openLong: new Set(), sel: null };
const XL_LIMIT = 280;
const XD_PREP = { null: '排着，等做', running: '在改写、配图…（十来分钟）', failed: '没做成' };

/* 和 x_post.weighted_length 一样：中日韩字符算 2 */
function xlWeight(text) { let n = 0; for (const ch of text) n += /[⺀-鿿＀-￯　-〿]/.test(ch) ? 2 : 1; return n; }

async function xlLoad(fresh = false, kind = XL.mode === 'sources' ? 'source' : 'daily') {
  if (XL.pending[kind]) return XL.pending[kind];
  delete XL.errors[kind];
  const url = kind === 'daily' ? '/api/xline/daily' : '/api/xline' + (fresh ? '?fresh=1' : '');
  // 写作清单（流程名、步骤）一起读；它读不到也不影响队列，卡片上就不出「换流程」
  XL.pending[kind] = Promise.all([api(url), kind === 'daily' && window.loadWriteModule ? window.loadWriteModule() : null])
    .then(([data]) => { XL[kind === 'daily' ? 'daily' : 'data'] = data; })
    .catch((err) => { XL.errors[kind] = err.message; throw err; })
    .finally(() => { delete XL.pending[kind]; });
  return XL.pending[kind];
}
function xlReadState(kind) {
  const label = kind === 'daily' ? 'X 待发队列' : XL.mode === 'sources' ? 'X 素材' : 'X 已发记录';
  if (XL.errors[kind]) return `<div class="empty" role="alert"><b>暂时读不到${label}</b><span>${esc(XL.errors[kind])}</span><button class="btn" type="button" data-xl-retry="${kind}">重试</button></div>`;
  return XL[kind === 'daily' ? 'daily' : 'data'] ? '' : `<div class="empty" role="status"><span class="spin"></span><b>正在读取${label}…</b></div>`;
}
function xlRequest(kind) {
  if (XL.pending[kind] || XL.errors[kind]) return;
  const repaint = () => {
    if (kind === 'daily') xlRender(XL.mounts.pending, 'pending');
    else { xlRender(XL.mounts.sources, 'sources'); xlRender(XL.mounts.pending, 'pending'); }
  };
  xlLoad(false, kind).then(repaint, repaint);
}
function xlBindRetry(box) {
  $$('[data-xl-retry]', box).forEach((button) => { button.onclick = () => { const kind = button.dataset.xlRetry; delete XL.errors[kind]; xlRequest(kind); xlRender(); }; });
}
function xlAgo(iso) {
  if (!iso) return '';
  const d = new Date(iso.length <= 10 ? iso + 'T00:00:00' : iso);
  if (Number.isNaN(d.getTime())) return '';
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  return days <= 0 ? '今天' : days === 1 ? '昨天' : days < 30 ? `${days} 天前` : `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}
const xlHm = (iso) => (iso ? new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }) : '');

function xlHidden(id) {
  const d = XL.data;
  return d.skipped.includes(id) || d.used.includes(id);
}

/* ---------- 今天的短帖：一条一行，勾 / 叉 ---------- */
const XD_STATE = { drafted: '存了草稿', pending: '', approved: '排着', rejected: '不发', sending: '在发', sent: '发了', failed: '没发成', unsure: '不确定', expired: '过期', moved: '挪到明天' };

/* 10/9 作者：长文开头一段 summary，第一句是写这篇的日期。日期只信笔记里写的和文件名里的，找不到就提醒他 */
function xdWritten(x) {
  if (!x.long || x.prep !== 'ready') return '';
  if (x.summary === false && x.summary_mode === 'off') return '<span>没写带日期的 summary（今天写的新内容不写；要的话在批注视图里打开）</span>';
  if (x.summary === false && !x.summary_error && x.trk) return '<span>没写带日期的 summary（今天写的新内容不写）</span>';
  if (x.summary === false) return `<span class="bad">开头那段 summary 没写上：${esc(x.summary_error || '')}（点「重做」）</span>`;
  if (!x.summary) return '';
  return x.written_on ? `<span>写于 ${esc(x.written_on)}</span>` : '<span class="bad">不知道这篇哪天写的，summary 里没写日期：在笔记属性里加 date，再点「重做」</span>';
}

/* 长文按空行切成块：0 是标题，有 summary 时 1 是 summary（CONTEXT.md 里的组件名），后面是正文段落、小标题、配图 */
const xdBlocks = (text) => text.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);

/* 长文预览：段落、小标题、插图照发出去的顺序排；图从这篇自己的文件夹读。
 * 10/9 作者「I need to be able to edit on the spot」：能改的时候每一段点一下就地改，summary 还能单独重写 */
function xdArticle(x, key, blocks, editable) {
  const base = `/api/xline/daily/${encodeURIComponent(key)}/${encodeURIComponent(x.id)}/file/`;
  const at = (i) => `data-xd-blk="${i}" data-xd-post="${esc(x.id)}"`;
  return blocks.map((b, i) => {
    if (i === 0) return '';  // 标题在折叠条上
    const img = b.match(/^!\[([^\]]*)\]\(([^)\s]+)\)$/);
    if (img) {
      return x.prep === 'ready' ? `<figure class="xd-fig"><img src="${esc(base + img[2].split('/').map(encodeURIComponent).join('/'))}" alt="${esc(img[1])}" loading="lazy"><figcaption>${esc(img[1])}${editable ? ` <button class="linkish" type="button" data-xd-blk-del ${at(i)}>去掉这张图</button>` : ''}</figcaption></figure>` : '';
    }
    const cls = editable ? ' class="xd-blk" title="点一下就能改"' : '';
    if (i === 1 && x.summary) {
      return `<div class="xd-summary"><div class="xd-comp"><span class="xd-tag">summary</span>${editable ? `<button class="linkish" type="button" data-xd-resum="${esc(x.id)}" title="重新读笔记的日期和内容，只换这一段">重写 summary</button>` : ''}</div>
        <p${cls} ${at(i)}>${esc(b.replace(/\*\*/g, ''))}</p></div>`;
    }
    if (x.intro && b === x.intro.trim()) {  // 10/10 晚 作者：开头直说这是什么（给 agent 的 prompt、原则、思考…），QA 加的
      return `<div class="xd-summary"><div class="xd-comp"><span class="xd-tag">导语</span><small>QA 加的：让读者一眼看懂这是什么</small></div>
        <p${cls} ${at(i)}>${esc(b)}</p></div>`;
    }
    const h = b.match(/^#{1,4}\s+(.*)$/);
    if (h) return `<h4${cls} ${at(i)}>${esc(h[1])}</h4>`;
    return `<p${cls} ${at(i)}>${esc(b.replace(/\*\*/g, ''))}</p>`;
  }).join('');
}

/* 10/9 晚 作者：长帖、长文放一个 section；像进项那样左右分栏——左边今天要发的标题，右边是展开的那一篇，像 Notion 一样看、改、勾 */
const XD_DOT = { drafted: '存了 X 草稿', pending: '等你勾', approved: '勾了', rejected: '不发', sending: '在发', sent: '发了', failed: '没发成', unsure: '不确定', expired: '作废' };

function xdTitle(x) { return (xdBlocks(x.text)[0] || '').replace(/^#+\s*/, '') || '（没有标题）'; }

// 10/12 作者：价值、完整度不过的不给他看（后台拼一篇顶上），hidden 的不列
/* 10/12 作者：「你每天帮我从 作者 的原始输出里选 10 个 candidates」，每篇四个按钮：发文 / 长帖 / 拆解 / 不发。
 * 还没选的一篇一行露出来；选过的收进下面一行，点开看每篇走到哪了。 */
const XK_ACT = [['article', '发文', '改写、配图、封面、QA 之后存进 X 文章草稿，你自己去发'], ['post', '长帖', '整篇原话一条纯文字长帖，QA 完整就自动发'],
  ['split', '拆解', '拆成几条能单独成立的短帖，过 QA 自动发'], ['skip', '不发', '放一边，以后不再推']];
function xkStatus(pk, posts) {
  const made = (pk.made || []).map((id) => posts.find((x) => x.id === id)).filter(Boolean);
  if (pk.choice === 'skip') return '不发';
  if (pk.choice === 'split') return pk.split === 'running' ? '<span class="spin"></span> 在拆' : pk.split === 'failed' ? `没拆出来${pk.split_error ? `：${esc(pk.split_error)}` : ''}`
    : `拆成 ${made.length} 条短帖 · 发了 ${made.filter((x) => x.state === 'sent').length}`;
  const x = made[0];
  if (!x) return '';
  if (pk.choice === 'article') return x.state === 'drafted' ? `已存进 X 草稿 <a href="${esc(x.url || 'https://x.com/compose/articles')}" target="_blank" rel="noopener">去 X 发布 ↗</a>`
    : x.prep !== 'ready' ? '<span class="spin"></span> 在改写、配图（十来分钟）' : '做好了，在下面「长文和长帖」里看一眼，点「存进 X 草稿」';
  return x.state === 'sent' ? `发了 ${xlHm(x.sent_at)}` : x.state === 'approved' ? '排着发' : x.qa === 'running' || !x.qa ? '等 QA' : x.qa_complete === false ? 'QA 说不完整，在下面看一眼' : '等 QA';
}
function xkPicks(dd) {
  const t = dd.today || {}, picks = t.picks || [], posts = t.posts || [];
  if (!picks.length) return '';
  const open = picks.filter((pk) => !pk.choice), done = picks.filter((pk) => pk.choice);
  const row = (pk) => `<li class="xk-row"><div class="xk-main"><b>${esc(pk.title || '（没有标题）')}</b><p>${esc(xaClip(String(pk.text || '').split('\n').slice(1).join(' '), 120))}</p><small>${fmt(pk.chars || 0)} 字</small></div>
    <div class="xk-acts">${XK_ACT.map(([a, label, tip]) => `<button type="button" class="btn small${a === 'split' ? ' primary' : a === 'skip' ? ' ghost' : ''}" data-xk="${esc(pk.id)}" data-xk-act="${a}" title="${esc(tip)}">${label}</button>`).join('')}</div></li>`;
  const label = Object.fromEntries(XK_ACT.map(([a, l]) => [a, l]));
  const doneRows = done.map((pk) => `<li><span class="xk-tag ${pk.choice}">${label[pk.choice]}</span><span class="xk-t">${esc(pk.title)}</span><small>${xkStatus(pk, posts)}</small></li>`).join('');
  return `<section class="panel xk" aria-label="今天的候选">
    <div class="panel-h"><h2>今天的候选 <small>${open.length ? `${open.length} 篇等你选` : '都选完了'}</small></h2><small>从你的原始输出挑的 · 发文你自己发，长帖和拆解过 QA 自动发</small></div>
    ${open.length ? `<ol class="xk-list">${open.map(row).join('')}</ol>` : ''}
    ${done.length ? `<details class="xk-done"${open.length ? '' : ' open'}><summary>选过的 ${done.length} 篇</summary><ol>${doneRows}</ol></details>` : ''}
  </section>`;
}

/* 10/12 作者：「拼接这件事现在正在做吗？我怎么能看到进度？」——藏起来的每一篇现在在哪一步，一行一篇 */
function xdMergeStrip(dd) {
  const t = dd.today, posts = t.posts || [];
  const hidden = posts.filter((x) => x.hidden);
  if (!hidden.length && !dd.merging) return '';
  const m = t.merge || {}, title = (id) => { const x = posts.find((p) => p.id === id); return x ? xdTitle(x) : id; };
  const status = (x) => x.merged_from ? '拼出来的这篇，QA 还是没过，不再拼'
    : x.merged_into ? `拼进了《${esc(title(x.merged_into))}》`
    : (x.merge_tries || 0) >= 2 ? `试了两次拼不出${x.merge_error ? `：${esc(x.merge_error)}` : ''}`
    : x.merge_tries ? `这一组拼不出共同主题，等新藏进来的一起再试`
    : dd.merging ? '排着拼' : '等着拼';
  const rows = hidden.map((x) => `<li><span class="xd-mg-t">${esc(xdTitle(x))}</span><small>${esc(x.hidden_reason || '')}</small><small class="xd-mg-s">${status(x)}</small></li>`).join('');
  const line = dd.merging ? '<span class="spin"></span> 正在把价值不够的几篇找共同主题拼成一篇（一两分钟）'
    : `${hidden.length} 篇没给你看（价值或完整度不够）· 今天拼了 ${m.count || 0} 次（最多 ${m.max || 6}）${m.waiting >= 2 ? ` · ${m.waiting} 篇等着拼，后台一会儿就拼` : m.waiting ? ' · 还剩 1 篇，等再藏进来一篇才能拼' : ''}`;
  return `<details class="xd-mg"><summary>${line}</summary><ol>${rows}</ol></details>`;
}

const xdIsLong = (x) => x.long && !x.quote_url && !x.swapped && !x.hidden && x.state !== 'moved';

/* 左边只列还要他管的（等勾、勾了排着、没发成）；发了的、不发的收进最下面一行，点开才看 */
function xdSplit(posts, key) {
  const items = posts.filter(xdIsLong);
  if (!items.length) return '<div class="empty"><span>今天没有要你勾的长文、长帖。</span></div>';
  const done = items.filter((x) => ['sent', 'rejected', 'expired', 'drafted'].includes(x.state));
  const live = items.filter((x) => !done.includes(x));
  const shown = XL.showDone ? items : live;
  if (!shown.some((x) => x.id === XL.sel)) XL.sel = (shown.find((x) => x.state === 'pending') || shown[0] || items[0]).id;
  const x = items.find((i) => i.id === XL.sel);
  const li = (i) => {
    const doing = i.prep && i.prep !== 'ready' ? (i.prep === 'failed' ? '没做成' : '在做') : '';
    const label = i.state === 'sent' && i.sent_at ? `发了 ${xlHm(i.sent_at)}` : doing || XD_DOT[i.state] || '';
    return `<li><button type="button" class="xd-li s-${esc(i.state)}${i.id === XL.sel ? ' on' : ''}" data-xd-sel="${esc(i.id)}">
      <span class="xd-li-t">${esc(xdTitle(i))}</span><span class="xd-li-m"><i>${i.merged_from ? '合并长帖' : i.format === 'post' ? '长帖' : '长文'}</i><i class="xd-li-s">${esc(label)}</i></span></button></li>`;
  };
  const more = done.length ? `<li><button type="button" class="xd-li-more" data-xd-done>${XL.showDone ? '收起发了的、不发的' : `发了 ${done.filter((i) => i.state === 'sent').length} · 不发 ${done.length - done.filter((i) => i.state === 'sent').length}`}</button></li>` : '';
  return `<div class="xd-split"><ol class="xd-list">${shown.map(li).join('')}${more}</ol><div class="xd-reader">${x ? xdReader(x, key) : ''}</div></div>`;
}

function xdReader(x, key, { noActs = false } = {}) {
  const open = ['pending', 'approved', 'rejected'].includes(x.state) && !x.swapped;
  const ready = !x.long || x.prep === 'ready';
  const isPost = x.format === 'post';
  const blocks = xdBlocks(x.text);
  const tracked = !!x.trk;  // 带修改清单的：正文不在卡片上改，去批注视图逐条处理
  const stuck = tracked && x.trk.changes.some((c) => c.op !== 'comment' && c.status === 'pending');
  const chip = XD_STATE[x.state] ? `<span class="xd-chip s-${x.state}">${XD_STATE[x.state]}${x.state === 'sent' && x.sent_at ? ` ${xlHm(x.sent_at)}` : ''}</span>` : '';
  const prep = !ready && open ? `<div class="xd-prep${x.prep === 'failed' ? ' bad' : ''}">${x.prep === 'running' ? '<span class="spin"></span>' : ''}${esc(XD_PREP[x.prep] || XD_PREP.null)}${x.prep_error ? `：${esc(x.prep_error)}` : ''}</div>` : '';
  const fix = ['failed', 'unsure'].includes(x.state)
    ? `<div class="xd-fix"><span>${esc(x.error || '')}</span><button class="btn small" type="button" data-xd-copy="${esc(x.id)}">复制去 X 发</button><button class="btn small ghost" type="button" data-xd-manual="${esc(x.id)}">我发了</button></div>` : '';
  const acts = open && !noActs ? `<div class="xd-r-acts">
      ${x.manual_publish ? `<button type="button" class="btn small primary" data-xd-draft="${esc(x.id)}" ${!ready ? 'disabled title="改写配图好了才能存"' : stuck ? 'disabled title="还有修改没处理，先打开批注视图"' : ''}>存进 X 草稿</button>`
        : `<button type="button" class="btn small ${x.state === 'approved' ? 'primary' : ''}" data-xd-mark="${esc(x.id)}" data-to="${x.state === 'approved' ? 'pending' : 'approved'}" ${!ready ? 'disabled title="做好了才能勾"' : stuck && x.state !== 'approved' ? 'disabled title="还有修改没处理，先打开批注视图"' : ''}>${x.state === 'approved' ? '✓ 勾了（点一下撤回）' : '✓ 发这篇'}</button>`}
      <button type="button" class="btn small ghost" data-xd-mark="${esc(x.id)}" data-to="${x.state === 'rejected' ? 'pending' : 'rejected'}">${x.state === 'rejected' ? '撤回「不发」' : '✕ 不发'}</button>
      ${!isPost ? `<button type="button" class="btn small ghost" data-xd-swap="${esc(x.id)}" title="这篇不发、放一边，换下一篇">换一篇</button>` : ''}
      ${!isPost && (x.prep === 'failed' || x.prep === 'ready') ? `<button type="button" class="btn small ghost" data-xd-redo="${esc(x.id)}" title="重新改写、重新配图">重做</button>` : ''}
    </div>` : '';
  const meta = [x.hot && x.quote_url ? `<a href="${esc(x.quote_url)}" target="_blank" rel="noopener">引用的原帖 ↗</a>` : '',
    xdWritten(x), x.note ? `<span>${esc(x.note)}</span>` : '', x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">${x.state === 'drafted' ? '去 X 草稿发布 ↗' : '看发出去的 ↗'}</a>` : ''].filter(Boolean).join('');
  const edit = open && ready && !tracked ? `<div class="xd-edit" hidden><textarea class="xd-text" data-xd-text="${esc(x.id)}">${esc(x.text)}</textarea></div><button class="linkish" type="button" data-xd-edit="${esc(x.id)}">改整篇（Markdown）</button>` : '';
  return `<article class="xd-doc s-${esc(x.state)}" data-xd="${esc(x.id)}">
    ${x.qa_value_held ? '<div class="xd-qa-warn">价值不够，没发；你再勾一次就照发</div>' : ''}
    <header><h3${open && ready ? ` class="xd-blk" title="点一下就能改标题" data-xd-blk="0" data-xd-post="${esc(x.id)}"` : ''}>${esc(xdTitle(x))}</h3>${chip}</header>
    ${acts}${prep}${fix}
    ${xdQA(x, open && ready)}
    ${xdFlow(x)}
    ${xdCover(x, key, open && ready)}
    ${meta ? `<div class="xd-meta">${meta}</div>` : ''}
    ${open && ready && !tracked ? '<p class="xd-hint">点任意一段就能直接改，改完点「保存」。</p>' : ''}
    ${tracked ? xdTrk(x) : `<div class="xd-article">${xdArticle(x, key, blocks, open && ready)}</div>`}
    ${edit}
  </article>`;
}

/* 10/12 作者：AI 在他的原文上直接改、留痕，他逐条接受（批注视图在 tracked.js）。卡片上只留一行：改了几处、还剩几处、预算 */
function xdTrk(x) {
  const t = x.trk, edits = t.changes.filter((c) => c.op !== 'comment'), notes = t.changes.filter((c) => c.op === 'comment');
  const left = edits.filter((c) => c.status === 'pending').length;
  const done = edits.length - left;
  return `<div class="xd-trk"><span>改了 <b>${edits.length}</b> 处（已处理 <b>${done}</b>）· 评论 <b>${notes.length}</b> 条${left ? ` · 待处理 <b>${left}</b>` : ' · 都处理完了'}</span>
    <span>预算 <progress max="${Number(t.pct_effective || t.max_pct || t.pct || 20)}" value="${Math.min(Number(t.budget || 0), Number(t.pct_effective || t.max_pct || t.pct || 20))}"></progress> <b>${Number(t.budget || 0).toFixed(1)}%</b> / ${Number(t.pct_effective || t.max_pct || t.pct || 20)}%${(t.overflow || []).length ? ` · 没放进来 <b>${t.overflow.length}</b>` : ''}</span>
    <button type="button" class="btn small primary" data-xd-trk="${esc(x.id)}">打开批注视图</button></div>`;
}

/* 10/12 作者：「我问了你才知道没跑过」。每一步跑没跑、什么时候、用哪一版规则，一步一行；每一步一行（顺序是 park-writing 清单定的），
   规则后来改过的标出来；整篇想换个流程重做，在底下选。 */
const XD_FLOW = { ran: ['跑了', 'ok'], bundled: ['没单独跑', 'warn'], none: ['还没做出来', 'mute'], never: ['没跑过', 'bad'], failed: ['没过', 'bad'], running: ['在跑', 'ok'], skipped: ['没动', 'mute'], off: ['这篇不走', 'mute'] };
function xdFlow(x) {
  const rows = x.flow || [];
  if (!rows.length) return '';
  const live = ['pending', 'approved'].includes(x.state) && x.prep === 'ready' && !x.compiled;
  const busy = x.flow_busy || '';
  const ran = rows.filter((r) => r.status === 'ran').length;
  const gaps = rows.filter((r) => ['bundled', 'never', 'failed'].includes(r.status)).length;
  const stale = x.flow_stale || [];
  const list = rows.map((r) => {
    const running = busy === r.id || r.status === 'running';
    const [label, tone] = running ? ['在跑', 'ok'] : (XD_FLOW[r.status] || [r.status, 'mute']);
    const when = [r.at ? xlHm(r.at) : '', r.rules ? `规则 ${r.rules}` : ''].filter(Boolean).join(' · ');
    const fails = (r.gate_failures || []).length ? `<ul class="xd-fl-fail">${r.gate_failures.map((f) => `<li>${esc(f)}</li>`).join('')}</ul>` : '';
    const report = (r.report || []).length ? `<details class="xd-fl-report"><summary>标了 ${r.report.length} 段</summary><ul>${r.report.map((l) => `<li>${esc(l)}</li>`).join('')}</ul></details>` : '';
    return `<li><span class="xd-fl-st ${tone}">${running ? '<span class="spin"></span>' : ''}${label}</span><b>${esc(r.title)}</b><span class="xd-fl-note">${esc(r.note || '')}</span>${when ? `<small>${esc(when)}</small>` : ''}${r.stale ? '<span class="xd-fl-st warn">规则改过</span>' : ''}${fails}${report}</li>`;
  }).join('');
  // 带修改清单的：第一轮用的规则变了，只重跑检查不会换掉清单——得重做第一轮（会清掉他已经处理的修改，所以要他点头）
  const round1 = new Set(Object.keys((x.trk && x.trk.rules) || {}));
  const staleRound1 = x.trk ? stale.filter((id) => round1.has(id)) : [];
  const rerun = stale.length && live
    ? `<div class="xd-fl-stale">${stale.length} 步是用旧规则跑的${staleRound1.length
      ? `<button type="button" class="btn small" data-xd-redo1="${esc(x.id)}" title="重新打分、重新提修改清单，你已经处理的接受 / 不要会清掉">用新规则重做第一轮</button>`
      : `<button type="button" class="btn small" data-xd-rerun="${esc(x.id)}">用新规则重跑检查</button>`}</div>` : '';
  const mod = window.writeModule ? window.writeModule() : null;
  const names = mod && mod.ok ? [...Object.keys(mod.flows), ...Object.keys(mod.custom)] : [];
  const picker = live && names.length
    ? `<div class="xd-fl-redo"><label>换个流程整篇重做 <select data-xd-flow="${esc(x.id)}">${names.map((n) => `<option value="${esc(n)}"${n === ((x.flow_run || {}).flow || mod.default) ? ' selected' : ''}>${esc(n)}</option>`).join('')}</select></label><button type="button" class="btn small ghost" data-xd-reflow="${esc(x.id)}" title="重新改写、重新配图，十来分钟；你改过的字会丢">重做</button></div>` : '';
  const err = x.flow_error ? `<div class="xd-qa-warn">${esc(x.flow_error)}</div>` : '';
  return `<details class="xd-flow"><summary>每一步的记录<small>${ran} 步跑了${gaps ? `，${gaps} 步没单独跑或没过` : ''}${stale.length ? `，${stale.length} 步规则改过` : ''}</small></summary><ul>${list}</ul>${err}${rerun}${picker}</details>`;
}

/* 10/10 作者：发之前过一遍 QA——错字、读不通、没讲完的结尾。只改单子上那几处，这里逐条列出来，不要就一键还原成他的原文 */
const XD_QA = { running: 'QA 在看：错字、读不通、整篇完整度', failed: 'QA 没做成，原文照旧', skipped: 'QA 没动', reverted: '已还原成你的原文' };
/* 10/13 作者：「接受了修改，价值和完整度是不是应该重新评估？我根本不知道存没存」。
 * 带修改清单的：他处理过修改，卡片最上面写他几点存的、按存下的正文重打的分（改前 → 改后，目标 80）；
 * 下面那块「价值 / 完整度 不过」是改之前原文的检查，收起来并写明，不再冒充现在的结论。 */
const XD_SCORE_TARGET = 80;
function xdScore(x) {
  const t = x.trk;
  if (!t) return '';
  const edits = t.changes.filter((c) => c.op !== 'comment');
  const left = edits.filter((c) => c.status === 'pending').length;
  if (!x.trk_saved_at && edits.length === left) return '';  // 还一处都没处理：只有原文的检查
  const used = edits.filter((c) => c.status === 'accepted' || c.status === 'edited').length;
  const sc = t.scores || {}, before = sc.before || {}, after = sc.after || null;
  const when = x.trk_saved_at ? `你 ${xlHm(x.trk_saved_at)} 存的` : '你存的';
  const head = `<b>改后打分</b><small>${when}版本 · ${used} 处修改在正文里 · 目标 ${XD_SCORE_TARGET}</small>`;
  const err = t.rescore_error ? `<small class="xd-qa-note">没打成：${esc(t.rescore_error)}</small>` : '';
  if (left) return `<div class="xd-score">${head}<small>还有 ${left} 处修改没处理，处理完自动重打分</small></div>`;
  if (t.rescoring || sc.stale || !after) return `<div class="xd-score">${head}<small>${t.rescoring ? '<span class="spin"></span> 在按存下的正文重打分，一两分钟' : '等着重打分'}</small>${err}</div>`;
  const rows = Object.keys(after).map((k) => {
    const a = before[k] ? before[k].score : null, b = after[k].score, ok = b >= XD_SCORE_TARGET;
    return `<li class="${ok ? 'ok' : 'low'}" title="${esc(after[k].why || '')}"><span>${esc(k)}</span>${a == null ? '' : `<s>${a}</s>→`}<b>${b}</b>${ok ? ' ✓' : ''}</li>`;
  }).join('');
  const low = Object.keys(after).filter((k) => after[k].score < XD_SCORE_TARGET);
  return `<div class="xd-score">${head}<ul>${rows}</ul><small>${low.length ? `还没到 ${XD_SCORE_TARGET}：${esc(low.join('、'))}（鼠标停在分数上看为什么）` : '每一项都到了'}${sc.after_at ? ` · ${xlHm(sc.after_at)} 打的` : ''}</small>${err}</div>`;
}

function xdQA(x, editable) {
  if (!x.long || x.prep !== 'ready' || !['pending', 'approved', 'rejected'].includes(x.state)) return '';
  const tag = `<span class="xd-tag">QA</span>${x.qa_note ? `<small class="xd-qa-note">${esc(x.qa_note)}</small>` : ''}`;
  const value = x.qa_value_ok === false ? `<div class="xd-qa-warn"><b>价值：不过</b><ul>${Object.entries(x.qa_value || {}).filter(([, v]) => v.ok === false).map(([k, v]) => `<li>${esc(k)}：${esc(v.why || '不过')}</li>`).join('')}</ul></div>` : x.qa_value_ok === true ? '<div class="xd-qa"><small>价值：痛点 ✓ 解法 ✓ 收藏 ✓</small></div>' : '';
  let warn = value + (x.qa_complete === false ? `<div class="xd-qa-warn"><b>完整度：不过</b><ul>${(x.qa_issues || []).map((issue) => `<li>${esc(issue)}</li>`).join('')}</ul><small>勾之前看一眼；整篇不行就点「不发」或「重做」</small></div>` : '');
  const score = xdScore(x);
  if (score && warn) {
    const fails = [x.qa_value_ok === false ? '价值不过' : '', x.qa_complete === false ? '完整度不过' : ''].filter(Boolean).join('、');
    warn = `${score}<details class="xd-qa-old"><summary>改之前原文的检查${fails ? `：${fails}` : ''}${x.qa_at ? `（${xlHm(x.qa_at)}）` : ''}</summary>${warn}</details>`;
  } else warn = score + warn;
  if (!x.qa) return `<div class="xd-qa">${tag}<small>排着，做好就改</small></div>${warn}`;
  if (x.qa !== 'ready') return `<div class="xd-qa${x.qa === 'failed' ? ' bad' : ''}">${tag}${x.qa === 'running' ? '<span class="spin"></span>' : ''}<small>${esc(XD_QA[x.qa] || '')}${x.qa_error ? `：${esc(x.qa_error)}` : ''}</small></div>${warn}`;
  const ch = x.qa_changes || [];
  if (!ch.length) return `<div class="xd-qa">${tag}<small>${score ? '看的是改之前的原文' : x.qa_complete === false ? '看过了，还有问题待你决定' : '看过了，没有要改的'}</small></div>${warn}`;
  const rows = ch.map((c) => {
    const change = c.kind === '删' ? `<del>${esc(c.before)}</del>（删掉）` : c.kind === '编号' ? esc(c.after) : `${c.before ? `<del>${esc(c.before)}</del> → ` : '补：'}<ins>${esc(c.after)}</ins>`;
    return `<li><i>${esc(c.kind)}</i>${change}${c.why ? `<small>${esc(c.why)}</small>` : ''}</li>`;
  }).join('');
  return `${warn}<details class="xd-qa"><summary>${tag}<small>改了 ${ch.length} 处（下面正文已经是改过的）</small>${editable && x.qa_before ? `<button class="linkish" type="button" data-xd-qa-revert="${esc(x.id)}">还原原文</button>` : ''}</summary><ol>${rows}</ol></details>`;
}

/* 10/10 作者：长文封面像抖音封面那样抓眼——他的 作者 形象、更多红色、为点击率写的标题。
 * 出好的封面放在右边最上面；封面标题有几个候选，点一个就用它重出，也能自己改 */
function xdCover(x, key, editable) {
  if (!x.long || x.format === 'post' || x.prep !== 'ready') return '';
  const src = `/api/xline/daily/${encodeURIComponent(key)}/${encodeURIComponent(x.id)}/file/x-cover.png?v=${encodeURIComponent(x.cover_title || '')}`;
  const state = x.cover === 'running' ? '<div class="xd-cover-ph"><span class="spin"></span>在出封面：写标题、用你的形象出图，几分钟</div>'
    : x.cover === 'failed' ? `<div class="xd-cover-ph bad">封面没出成：${esc(x.cover_error || '')}（发的时候用纯文字封面）</div>`
      : x.cover === 'ready' ? `<img class="xd-cover-img" src="${esc(src)}" alt="封面：${esc(x.cover_title || '')}">`
        : '<div class="xd-cover-ph">封面排着，等长文做好就出</div>';
  const busy = x.cover === 'running';
  const opts = (x.cover_titles || []).map((o) => `<button type="button" class="xd-ct${o.title === x.cover_title ? ' on' : ''}" data-xd-cover="${esc(x.id)}" data-title="${esc(o.title)}" title="${esc(o.pattern || '')}：${esc(o.basis || '')}" ${busy || !editable ? 'disabled' : ''}>${esc(o.title)}</button>`).join('');
  const tools = editable && x.cover && x.cover !== 'running' ? `<form class="xd-cover-own" data-xd-cover-own="${esc(x.id)}"><input name="t" maxlength="30" placeholder="自己写封面标题" value="${esc(x.cover_title || '')}"><button class="btn small" type="submit">用这个标题重出</button><button class="btn small ghost" type="button" data-xd-cover="${esc(x.id)}" data-title="">重写标题再出</button></form>` : '';
  return `<section class="xd-cover">${state}${opts ? `<div class="xd-cts"><small>封面标题（按点击率排，点一个就用它重出）</small>${opts}</div>` : ''}${tools}</section>`;
}

function xdToday(dd) {
  const t = dd.today;
  const key = t.day;
  const planning = dd.planning === key;
  const longs = t.posts.filter(xdIsLong);
  let body;
  if (!longs.length && !t.long_planned_at) {
    body = `<div class="empty"><b>${planning ? `<span class="spin"></span> ${esc(xlWho())} 在排今天的` : `${esc(xlWho())} 还没排今天的长文、长帖`}</b>
      ${dd.error && !planning ? `<span class="bad">${esc(dd.error)}</span>` : ''}
      ${planning ? '' : '<button class="btn primary" type="button" data-xd-plan="today">现在排</button>'}</div>`;
  } else body = xdSplit(t.posts, key);
  const waiting = longs.filter((x) => x.state === 'pending').length;
  const head = `<small>${waiting ? `${waiting} 篇等你勾 · ` : ''}勾了的 ${dd.window} 隔开发${t.halted ? ` · <b class="bad">今天停了：${esc(t.halted)}</b>` : ''}${t.articles_paused ? ` · <b class="bad">X 今天不让再发长文，勾了的挪到明天</b>` : ''}</small>
    <span class="xd-h-acts"><button class="btn small ghost" type="button" data-rawtidy-open>整理素材</button>${waiting ? `<button class="btn small primary" type="button" data-xd-all="${esc(key)}">剩下的全勾</button>` : ''}</span>`;
  return `<section class="panel xd">
    <div class="panel-h"><h2>长文和长帖</h2>${head}</div>
    ${xdMergeStrip(dd)}
    ${body}
  </section>`;
}

/* 10/9 作者「什么火我就说什么」：X 运营每 2 小时从持续在涨里挑他有观点的，写成引用帖形式的长帖草稿（10/9 晚：不发短帖）；
 * X 规则不许自动发热点，所以勾了才发；勾的算在每天的长帖数里 */
function xdHotBar(dd) {
  const c = dd.counts || {};
  if (!c.hot) return '';
  const made = dd.today.posts.filter((x) => x.hot).length;
  const posts = Math.round(c.long * c.post_share);
  return `<div class="xd-miss">${dd.hot_busy ? `<span class="spin"></span> ${esc(((S.state && S.state.brand) || {}).xops || 'Michael')} 在写这一批热点长帖` : `热点长帖：今天写了 ${made} / ${c.hot} 篇给你挑，每半小时一批；勾的算在今天 ${posts} 篇长帖里${dd.hot_error ? ` · <b class="bad">${esc(dd.hot_error)}</b>` : ''}`}
    ${dd.hot_busy || made >= c.hot ? '' : '<button class="btn small" type="button" data-xd-hot>现在写一批</button>'}</div>`;
}

/* 10/12 晚 作者：每天发多少放在 X 页最上面，打开就看见。改完点确认就锁成灰色，再改双击输入框或点「修改」 */
const XD_COUNT_FIELDS = [['articles', '长文', '篇', 10], ['own_short', '短帖', '条', 200], ['hot', 'Repost', '条', 200]];
function xdCounts(dd) {
  const c = dd.counts || {};
  if (c.own_short == null) return '';
  const edit = !!XL.countsEdit;
  return `<form class="xd-counts" data-xd-counts><b>每天发多少</b>
    ${XD_COUNT_FIELDS.map(([k, label, unit, max]) => `<label>${label} <input type="number" name="${k}" min="0" max="${max}" value="${c[k] ?? 0}"${edit ? '' : ' disabled'}> ${unit}</label>`).join('')}
    ${edit ? '<button class="btn small primary" type="submit">确认</button>' : '<button class="btn small" type="button" data-xd-counts-edit>修改</button>'}</form>`;
}
function xdBindCounts(root, dd) {
  const form = $('[data-xd-counts]', root);
  if (!form) return;
  const repaint = () => { root.innerHTML = xdCounts(XL.daily || dd); xdBindCounts(root, XL.daily || dd); const i = $('input', root); if (XL.countsEdit && i) i.focus(); };
  const unlock = () => { if (!XL.countsEdit) { XL.countsEdit = true; repaint(); } };
  const btn = $('[data-xd-counts-edit]', form);
  if (btn) btn.onclick = unlock;
  $$('input', form).forEach((i) => (i.ondblclick = unlock));
  form.onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(form);
    try {
      const r = await api('/api/xline/counts', { method: 'PUT', body: Object.fromEntries(XD_COUNT_FIELDS.map(([k]) => [k, Number(f.get(k))])) });
      if (XL.daily) XL.daily.counts = r.counts;
      XL.countsEdit = false;
      repaint();
      toast(`存好了：长文 ${r.counts.articles} 篇、短帖 ${r.counts.own_short} 条、Repost ${r.counts.hot} 条`);
    } catch (err) { toast(err.message); }
  };
}

/* X 这一页归 Michael（10/9 晚 作者）：排队列的是工作台后台每分钟跑的那一圈，页面上署他的名字 */
const xlWho = () => ((typeof S !== 'undefined' && S.state && S.state.brand) || {}).xops || 'Michael';

/* ---------- 从哪里挑：你自己的素材，只读；不想让她排的点「放一边」 ---------- */
const XL_KIND = { obsidian: '我写的', github: '我做的', principle: '原则', prediction: '预测', goodproduct: '我测评的', inbox: '选题' };

function xlPlain(md) {
  return md.split('\n').filter((l) => !/^\s*#/.test(l)).join('\n').replace(/\*\*|__|`/g, '').replace(/\n{3,}/g, '\n\n').trim();
}

function xlCard(c) {
  const plain = xlPlain(c.body || '');
  const body = plain ? `<p class="xl-body">${esc(plain.length > 200 ? plain.slice(0, 200) + '…' : plain)}</p>` : '<p class="xl-body dim">（没有描述）</p>';
  const meta = [c.tag, xlAgo(c.at)].filter(Boolean).map(esc).join(' · ');
  const skipped = XL.data.skipped.includes(c.id);
  return `<article class="xl-card">
    <header><b>${esc(c.title)}</b>${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener" title="打开原处">↗</a>` : ''}</header>
    ${meta ? `<div class="xl-meta">${meta}</div>` : ''}
    ${body}
    <footer><button class="btn small ghost" type="button" data-xl-skip="${esc(c.id)}">${skipped ? '捡回来' : '放一边'}</button></footer>
  </article>`;
}

function xlSources() {
  const own = XL.data.sources.filter((s) => ['obsidian', 'principle', 'prediction'].includes(s.key));
  const cur = own.find((s) => s.key === XL.tab) || own[0];
  if (!cur) return '<div class="panel empty"><b>还没有可用素材来源</b><span>连接原始输出后，这里会列出可选素材。</span></div>';
  const visible = cur.items.filter((c) => XL.showHidden || !xlHidden(c.id));
  const hiddenN = cur.items.filter((c) => xlHidden(c.id)).length;
  const left = own.reduce((n, s) => n + s.items.filter((c) => !xlHidden(c.id)).length, 0);
  return `<details class="panel xl-src" ${XL.srcOpen ? 'open' : ''}>
    <summary><b>${esc(xlWho())} 从这里挑</b><button class="btn small ghost" type="button" data-rawtidy-open>整理素材</button><span class="num">${left}</span><small>你自己的原始输出、网站上的原则和预测，还没发过的。不想让他排的点「放一边」</small></summary>
    <nav class="subnav xl-tabs">${own.map((s) => `<button type="button" class="${s.key === cur.key ? 'on' : ''}" aria-pressed="${s.key === cur.key}" data-xl-tab="${s.key}">${esc(s.label)} <span class="num">${s.error ? '!' : s.items.filter((c) => !xlHidden(c.id)).length || ''}</span></button>`).join('')}
      <button class="linkish" type="button" id="xlFresh">重新读</button></nav>
    ${cur.error ? `<div class="empty"><b>这一处读不到</b><span class="err">${esc(cur.error)}</span></div>` : ''}
    ${!cur.error && !visible.length ? `<div class="empty"><span>${cur.items.length ? '这一处的都发过或放一边了。' : '这一处还没有东西。'}</span></div>` : ''}
    <div class="xl-grid">${visible.map(xlCard).join('')}</div>
    ${hiddenN ? `<div class="xl-more"><button class="linkish" type="button" id="xlShowHidden">${XL.showHidden ? '藏起发过、放一边的' : `看发过、放一边的 ${hiddenN} 条`}</button></div>` : ''}
  </details>`;
}

/* 10/6 作者：X 短帖并进 X 那一页（platform.js 调 renderXDaily）；原来的 #xline 书签也落到 X 页。 */
function xlRender(box, mode) {
  if (!box) { if (mode) return; for (const [view, target] of Object.entries(XL.mounts)) xlRender(target, view); return; }
  if (!box.isConnected) return;
  XL.mode = mode || (XL.mounts.sources === box ? 'sources' : 'pending');
  XL.box = box;
  const required = XL.mode === 'sources' ? 'source' : 'daily';
  if (XL.mode === 'sources' && !XL.data) {
    box.innerHTML = xlReadState(required);
    xlBindRetry(box); xlRequest(required); return;
  }
  // 正在改某一条：别把他打到一半的字冲掉（就地改开着的时候也不重画）
  if (box.contains(document.activeElement) && document.activeElement.matches('textarea')) return;
  if (box.querySelector('.xd-blk-edit')) return;
  const dd = XL.daily;
  if (XL.mode === 'sources') { box.innerHTML = xlReadState('source') + xlSources(); xlBind(box); return; }
  box.innerHTML = `
    <div data-xl-live>${xlLive()}</div>
    ${dd ? `<div class="xtracks">${xvValue(dd)}<div data-xa>${xaAuto(dd)}</div></div>` : xlReadState('daily')}`;
  xlBind(box);
  xaBind(box);
  xlLiveLoad(box);
  // 「每天发多少」在页面最上面（platform.js 的 X 页顶）；改的时候不重画
  const slot = box.closest?.('.publication-sections')?.querySelector('[data-xd-counts-slot]');
  if (slot && dd && !XL.countsEdit) { slot.innerHTML = xdCounts(dd); xdBindCounts(slot, dd); }
  if (!dd) xlRequest('daily');
  if (XL.showPosted && !XL.data) xlRequest('source');
  clearTimeout(XL.poll);
  // 后台在排、或者今天还有排着的：隔一会儿自己刷新，不用他刷网页
  if (dd && (dd.planning || dd.hot_busy || dd.merging || (dd.today.merge && dd.today.merge.waiting >= 2) || dd.today.queued || [dd.today, dd.tomorrow].some((t) => t.posts.some((x) => x.state === 'sending' || (x.long && (x.prep === 'running' || x.cover === 'running' || x.qa === 'running')))))) {
    XL.poll = setTimeout(async () => { if (box.isConnected && XL.mounts.pending === box && S.view === 'platform' && S.platformKey === 'x') { try { await xlLoad(false, 'daily'); } catch (_) { /* 下次再读 */ } if (XL.mounts.pending === box) xlRender(box, 'pending'); } }, dd.planning ? 5000 : 30000);
  }
}

function xdFind(id) {
  for (const t of [XL.daily.today, XL.daily.tomorrow, ...(XL.daily.ahead || [])]) { const x = t.posts.find((p) => p.id === id); if (x) return [t.day, x]; }
  return [null, null];
}

function xlBind(box) {
  xlBindRetry(box);
  const reload = async () => { try { await xlLoad(false, 'daily'); } catch (err) { toast(err.message); } xlRender(); };
  $$('[data-xd-plan]', box).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try { toast((await api('/api/xline/daily/plan', { method: 'POST', body: { day: b.dataset.xdPlan } })).message); } catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xd-mark]', box).forEach((b) => (b.onclick = async () => {
    const [key] = xdFind(b.dataset.xdMark);
    const t = $(`[data-xd-text="${b.dataset.xdMark}"]`, box);
    try { await api(`/api/xline/daily/${key}/${encodeURIComponent(b.dataset.xdMark)}`, { method: 'PATCH', body: { state: b.dataset.to, ...(t ? { text: t.value } : {}) } }); } catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xd-edit]', box).forEach((b) => (b.onclick = () => {
    const ed = b.previousElementSibling;
    ed.hidden = !ed.hidden;
    b.textContent = ed.hidden ? '改字' : '收起';
    const t = $('textarea', ed); if (!ed.hidden && t) fit(t);
  }));
  $$('[data-xd-redo1]', box).forEach((b) => (b.onclick = async () => {
    const id = b.dataset.xdRedo1, [key, x] = xdFind(id);
    const done = x && x.trk ? x.trk.changes.filter((c) => c.op !== 'comment' && c.status !== 'pending').length : 0;
    if (!window.confirm(`用新规则重做第一轮：重新打分、重新提修改清单，十来分钟。${done ? `你已经处理的 ${done} 处接受 / 不要会清掉。` : ''}继续吗？`)) return;
    b.disabled = true;
    try { await api(`/api/xline/daily/${key}/${encodeURIComponent(id)}/prep`, { method: 'POST' }); toast('排回去重做第一轮了，十来分钟'); } catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xd-trk]', box).forEach((b) => (b.onclick = () => window.openTracked && window.openTracked(b.dataset.xdTrk)));
  $$('[data-xd-reflow]', box).forEach((b) => (b.onclick = async () => {
    const id = b.dataset.xdReflow, [key] = xdFind(id), flow = $(`[data-xd-flow="${id}"]`, box).value;
    b.disabled = true;
    try { await api(`/api/xline/daily/${key}/${encodeURIComponent(id)}/prep`, { method: 'POST', body: { flow } }); toast(`按「${flow}」排回去重做了，十来分钟`); } catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xd-rerun]', box).forEach((b) => (b.onclick = async () => {
    const [key] = xdFind(b.dataset.xdRerun);
    b.disabled = true;
    try { await api(`/api/xline/daily/${key}/${encodeURIComponent(b.dataset.xdRerun)}/qa/rerun`, { method: 'POST' }); toast('排上了：用新规则重新检查，几分钟'); } catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xd-redo]', box).forEach((b) => (b.onclick = async () => {
    const [key] = xdFind(b.dataset.xdRedo);
    b.disabled = true;
    try { await api(`/api/xline/daily/${key}/${encodeURIComponent(b.dataset.xdRedo)}/prep`, { method: 'POST' }); toast('排回去重做了：重新改写、配图，十来分钟'); } catch (err) { toast(err.message); }
    reload();
  }));
  const redoCover = async (id, title) => {
    const [key] = xdFind(id);
    try { toast((await api(`/api/xline/daily/${key}/${encodeURIComponent(id)}/cover`, { method: 'POST', body: { title } })).message); } catch (err) { toast(err.message); }
    reload();
  };
  $$('[data-xd-cover]', box).forEach((b) => (b.onclick = () => { b.disabled = true; redoCover(b.dataset.xdCover, b.dataset.title); }));
  $$('[data-xd-qa-revert]', box).forEach((b) => (b.onclick = async (e) => {
    e.preventDefault();
    const [key, x] = xdFind(b.dataset.xdQaRevert);
    if (!window.confirm('回到 QA 之前你自己的原文？QA 之后你在这篇里改过的字也会一起回去。')) return;
    b.disabled = true;
    try { await api(`/api/xline/daily/${key}/${encodeURIComponent(x.id)}/qa/revert`, { method: 'POST' }); toast('还原了，发的是你的原文'); } catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xd-cover-own]', box).forEach((f) => (f.onsubmit = (e) => { e.preventDefault(); const t = f.t.value.trim(); if (t) redoCover(f.dataset.xdCoverOwn, t); }));
  $$('[data-xv]', box).forEach((b) => (b.onclick = async () => {
    $$(`[data-xv="${b.dataset.xv}"]`, box).forEach((x) => { x.disabled = true; });
    try { await api(`/api/xline/value/${XL.daily.today.day}/${encodeURIComponent(b.dataset.xv)}`, { method: 'POST', body: { action: b.dataset.xvAct } }); toast(b.dataset.xvAct === 'split' ? '拆成短帖了，几分钟后进流量线；补了一篇长文顶上' : '放一边了，补了一篇长文顶上'); }
    catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xv-own]', box).forEach((c) => (c.onchange = async () => {
    try { await api(`/api/xline/value/${XL.daily.today.day}/own`, { method: 'POST', body: { [c.dataset.xvOwn]: c.checked } }); } catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xk]', box).forEach((b) => (b.onclick = async () => {
    $$(`[data-xk="${b.dataset.xk}"]`, box).forEach((x) => { x.disabled = true; });
    try { await api(`/api/xline/picks/${XL.daily.today.day}/${encodeURIComponent(b.dataset.xk)}`, { method: 'POST', body: { action: b.dataset.xkAct } }); }
    catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xd-draft]', box).forEach((b) => (b.onclick = async () => {
    const [key] = xdFind(b.dataset.xdDraft);
    b.disabled = true; b.textContent = '在存…';
    try { await api(`/api/xline/daily/${key}/${encodeURIComponent(b.dataset.xdDraft)}/draft`, { method: 'POST' }); toast('存进 X 文章草稿了，去 X 打开草稿点发布'); }
    catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xd-done]', box).forEach((b) => (b.onclick = () => { XL.showDone = !XL.showDone; xlRender(box, 'pending'); }));
  $$('[data-xd-sel]', box).forEach((b) => (b.onclick = () => { if (box.querySelector('.xd-blk-edit')) return; XL.sel = b.dataset.xdSel; xlRender(box, 'pending'); }));
  const hot = $('[data-xd-hot]', box);
  if (hot) hot.onclick = async () => {
    hot.disabled = true;
    try { toast((await api('/api/xline/hot', { method: 'POST' })).message); } catch (err) { toast(err.message); }
    reload();
  };
  $$('[data-xd-swap]', box).forEach((b) => (b.onclick = async () => {
    const [key] = xdFind(b.dataset.xdSwap);
    b.disabled = true;
    try { const r = await api(`/api/xline/daily/${key}/${encodeURIComponent(b.dataset.xdSwap)}/swap`, { method: 'POST' }); toast(r.post ? '换好了，新的一篇在下面，勾了才发' : '撤下了'); } catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xd-all]', box).forEach((b) => (b.onclick = async () => {
    try { const r = await api(`/api/xline/daily/${b.dataset.xdAll}/approve-all`, { method: 'POST' }); toast(`勾了 ${r.approved} 篇，会隔开发出去${r.left ? `；${r.left} 篇没勾上（还在做，或长帖今天勾满了）` : ''}`); } catch (err) { toast(err.message); }
    reload();
  }));
  const fit = (t) => { t.style.height = 'auto'; t.style.height = `${t.scrollHeight + 2}px`; };  // 卡片里字多的也整条露出来
  $$('[data-xd-text]', box).forEach((t) => {
    fit(t);
    t.oninput = () => {
      fit(t);
      const w = xlWeight(t.value);
      const el = $(`[data-xd-w="${t.dataset.xdText}"]`, box);
      const limit = Number(el.dataset.limit);
      if (!limit) return;  // 长文不限字数
      el.textContent = `${w} / ${limit}${w > limit ? ' · 太长' : ''}`;
      el.classList.toggle('over', w > limit);
    };
    t.onchange = async () => {
      const [key] = xdFind(t.dataset.xdText);
      try { await api(`/api/xline/daily/${key}/${encodeURIComponent(t.dataset.xdText)}`, { method: 'PATCH', body: { text: t.value } }); toast('改好了，发的是改过的'); } catch (err) { toast(err.message); }
    };
  });
  // 长文的全文折着：展开时才量得出高度
  // 长文开着就一直开着：页面隔一会儿自己刷新，别把他正在看的那篇合上
  $$('.xd-long', box).forEach((d) => (d.ontoggle = () => {
    if (d.open) XL.openLong.add(d.dataset.xdLong); else XL.openLong.delete(d.dataset.xdLong);
    const t = $('textarea', d); if (d.open && t) fit(t);
  }));
  xdBindBlocks(box, reload);
  $$('[data-xd-copy]', box).forEach((b) => (b.onclick = () => {
    const [, x] = xdFind(b.dataset.xdCopy);
    if (navigator.clipboard) navigator.clipboard.writeText(x.text).then(() => toast('复制了，去 X 发完回来点「我发了」'), () => toast('复制不了，手动选中复制'));
  }));
  $$('[data-xd-manual]', box).forEach((b) => (b.onclick = async () => {
    const [key] = xdFind(b.dataset.xdManual);
    try { await api(`/api/xline/daily/${key}/${encodeURIComponent(b.dataset.xdManual)}/manual`, { method: 'POST' }); toast('记上了'); } catch (err) { toast(err.message); }
    reload();
  }));

  const src = $('.xl-src', box);
  if (src) src.ontoggle = () => { XL.srcOpen = src.open; };
  $$('[data-xl-tab]', box).forEach((b) => (b.onclick = () => { XL.tab = b.dataset.xlTab; XL.showHidden = false; xlRender(); }));
  const fresh = $('#xlFresh', box);
  if (fresh) fresh.onclick = async () => { XL.data = null; const pending = xlLoad(true, 'source'); xlRender(); await pending.catch((e) => toast(e.message)); xlRender(); };
  const sh = $('#xlShowHidden', box); if (sh) sh.onclick = () => { XL.showHidden = !XL.showHidden; xlRender(); };
  $$('[data-xl-skip]', box).forEach((b) => (b.onclick = async () => {
    const id = b.dataset.xlSkip;
    const undo = XL.data.skipped.includes(id);
    try { XL.data.skipped = (await api('/api/xline/skip', { method: 'POST', body: { source_id: id, undo } })).skipped; xlRender(); } catch (err) { toast(err.message); }
  }));
}

window.renderXDaily = (box, mode = 'pending') => {
  for (const [view, target] of Object.entries(XL.mounts)) if (target === box && view !== mode) delete XL.mounts[view];
  XL.mounts[mode] = box;
  if (mode === 'pending') clearTimeout(XL.poll);
  xlRender(box, mode);
};

/* 就地改长文的一段：点哪段，哪段变成输入框；保存时只换这一段，其余原样，再整篇存回去 */
function xdBindBlocks(box, reload) {
  const save = async (id, i, value) => {
    const [key, x] = xdFind(id);
    const blocks = xdBlocks(x.text);
    if (i === 0) {  // 10/10 作者：标题也能点着改；存回去还是第一行的「# 标题」
      if (!value.trim()) throw new Error('标题不能是空的');
      blocks[0] = `# ${value.trim().replace(/^#+\s*/, '').replace(/\s*\n\s*/g, ' ')}`;
    } else if (value.trim()) blocks[i] = value.trim(); else blocks.splice(i, 1);
    await api(`/api/xline/daily/${key}/${encodeURIComponent(id)}`, { method: 'PATCH', body: { text: blocks.join('\n\n') + '\n' } });
  };
  $$('[data-xd-blk]:not([data-xd-blk-del])', box).forEach((el) => (el.onclick = () => {
    if (box.querySelector('.xd-blk-edit')) return;  // 一次改一段
    const id = el.dataset.xdPost, i = Number(el.dataset.xdBlk);
    const [, x] = xdFind(id);
    const raw = i === 0 ? xdTitle(x) : xdBlocks(x.text)[i] || '';
    const ed = document.createElement('div');
    ed.className = 'xd-blk-edit';
    ed.innerHTML = `<textarea>${esc(raw)}</textarea><div class="xd-blk-acts"><button class="btn small primary" type="button" data-act="save">保存</button><button class="btn small ghost" type="button" data-act="cancel">取消</button><small>${i === 0 ? '这是标题，发出去就是这一行' : '清空再保存 = 删掉这一段'}</small></div>`;
    el.replaceWith(ed);
    const t = $('textarea', ed);
    t.style.height = `${Math.max(t.scrollHeight + 2, 80)}px`;
    t.oninput = () => { t.style.height = 'auto'; t.style.height = `${t.scrollHeight + 2}px`; };
    t.focus();
    $('[data-act="cancel"]', ed).onclick = () => { ed.remove(); reload(); };
    $('[data-act="save"]', ed).onclick = async (e) => {
      e.target.disabled = true;
      try { await save(id, i, t.value); toast('改好了，发的是改过的'); ed.remove(); reload(); } catch (err) { toast(err.message); e.target.disabled = false; }
    };
  }));
  $$('[data-xd-blk-del]', box).forEach((b) => (b.onclick = async () => {
    try { await save(b.dataset.xdPost, Number(b.dataset.xdBlk), ''); toast('这张图去掉了'); } catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xd-resum]', box).forEach((b) => (b.onclick = async () => {
    const [key] = xdFind(b.dataset.xdResum);
    b.disabled = true; b.textContent = '在重写 summary…';
    try { await api(`/api/xline/daily/${key}/${encodeURIComponent(b.dataset.xdResum)}/summary`, { method: 'POST' }); toast('summary 重写好了'); } catch (err) { toast(err.message); }
    reload();
  }));
}



/* ---------- 10/11 晚 作者 重做 X 页 ----------
 * 「too much information」：最上面一张「今天」卡片（曝光、涨粉、离涨粉目标的进度、今天的量），
 * 中间「自动发」：短帖、引用、回复过了 QA 就发，不用他勾（10/11 晚 作者），每一路只露下一条，发出去就收进「今天已发」；
 * 下面才是要他勾的长文、长帖。素材来源不放这里了（166 条给 Michael 挑，对他没意义）。 */

const XR = { data: null, loaded: false, loading: false, error: '', timer: null, at: 0 };
const XA = { last: {} };  // 每一路上一次露出来的是哪条：换了就放进场动画
const xlNumber = (v) => (v == null ? '—' : fmt(v));
const xlBjHm = (iso) => (iso ? new Date(iso).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }) : '');
const xlMidnight = () => { const d = new Date(); return new Date(`${d.toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' })}T00:00:00+08:00`).toISOString(); };

function xrIntent(id, text) {
  return `https://x.com/intent/post?in_reply_to=${encodeURIComponent(id)}&text=${encodeURIComponent(text)}`;
}

/* 按小时的累计线：从 0 点起画（曝光 0 点是 0，粉丝 0 点是昨天最后一次读数）；真读数不到 2 个就不画，只看大数字 */
function xlSpark(rows, key, start, label) {
  const real = (rows || []).filter((r) => r[key] != null);
  if (real.length < 2 || typeof lineChart !== 'function') return '';
  const pts = [...(start == null ? [] : [{ at: xlMidnight(), v: start }]), ...real.map((r) => ({ at: r.at, v: r[key] }))]
    .map((p) => ({ ...p, day: String(p.at).slice(0, 10), axisLabel: xlBjHm(p.at), tip: `${xlBjHm(p.at)} · ${label} ${fmt(p.v)}` }));
  return `<div class="xt-chart"><small>${esc(label)} · 按小时</small>${lineChart(pts, { label: '', ariaLabel: `${label}按小时` })}</div>`;
}

/* 离目标的进度条：SVG 画，「应到」是一条竖线（不拼 style=） */
function xlGoalBar(now, expected, target) {
  if (now == null || !target) return '';
  const W = 400, x = (v) => Math.max(0, Math.min(W, (v / target) * W)).toFixed(1);
  return `<svg class="xt-goal" viewBox="0 0 ${W} 8" preserveAspectRatio="none" role="img" aria-label="粉丝 ${fmt(now)} / 目标 ${fmt(target)}">
    <rect class="trk" x="0" y="0" width="${W}" height="8" rx="4"/><rect class="val${expected != null && now < expected ? ' behind' : ''}" x="0" y="0" width="${x(now)}" height="8" rx="4"/>
    ${expected != null ? `<rect class="exp" x="${x(expected)}" y="0" width="2" height="8"/>` : ''}</svg>`;
}

function xlLive() {
  const d = XL_LIVE.data || {}, p = d.progress || {}, goal = p.target || {};
  const stop = XR.data?.halted_message || d.halted_message;
  const at = d.updated_at ? `截至 ${xlBjHm(d.updated_at)} · 每小时更新` : '还没读到今天的数';
  const ahead = p.gap == null ? '' : `<small class="xt-pace ${p.gap < 0 ? 'bad' : 'good'}">${p.gap < 0 ? '落后' : '超前'} ${fmt(Math.abs(p.gap))}</small>`;
  const gain = d.followers_today == null ? '—' : `${d.followers_today >= 0 ? '+' : ''}${fmt(d.followers_today)}`;
  const k = Object.fromEntries((d.kpi || []).map((x) => [x.key, x]));
  // 10/12 作者：动作看发帖数和曝光（和 impressions 几乎成正比），结果看涨粉和粉丝数
  const act = (x, label, sub) => {
    if (!x) return '';
    const done = x.done == null ? null : Number(x.done), target = Number(x.target) || 1;
    return `<div class="xt-stat${x.ok ? ' ok' : ''}"><span>${label}</span><b class="num">${xlNumber(done)}<small>/ ${fmt(target)}</small></b>
      <progress class="xt-bar${x.ok ? ' ok' : ''}" max="${target}" value="${Math.min(done || 0, target)}" aria-label="${label}"></progress><small>${sub}</small></div>`;
  };
  const charts = [xlSpark(d.impressions_hourly, 'impressions', 0, '今天曝光'), xlSpark(d.followers_hourly, 'followers', d.followers_midnight, '粉丝')].join('');
  return `<section class="panel xt" aria-label="X 今天">
    <div class="panel-h"><h2>今天</h2><small>${esc(at)}</small></div>
    ${stop ? `<p class="xt-halt" role="alert">${esc(stop)}</p>` : ''}
    ${XL_LIVE.error ? `<p class="xt-halt" role="alert">数没刷新：${esc(XL_LIVE.error)}</p>` : ''}
    <div class="xt-stats">
      ${act(k.posts, '发帖', `原创 + 引用，不含回复${k.replies && k.replies.done != null ? ` · 另回复 ${fmt(k.replies.done)}` : ''}`)}
      ${act(k.impressions, '曝光', `昨天验证曝光 ${xlNumber(d.verified_yesterday)}`)}
      <div class="xt-stat"><span>涨粉</span><b class="num">${esc(gain)}</b><small>收藏 ${xlNumber(d.bookmarks_today)} · 主页点击 ${xlNumber(d.profile_clicks_today)}</small></div>
      <div class="xt-stat"><span>粉丝${goal.end_day ? ` · ${Number(String(goal.end_day).slice(5, 7))}/${Number(String(goal.end_day).slice(8))} 前到 ${xlNumber(goal.end)}` : ''}</span>
        <b class="num">${xlNumber(d.followers_now)}</b>${ahead}${xlGoalBar(d.followers_now, p.expected, goal.end)}<small>今天应到 ${xlNumber(p.expected)}</small></div>
    </div>
    ${charts ? `<div class="xt-charts">${charts}</div>` : ''}
  </section>`;
}

/* ---------- 自动发：一路一张卡，只露下一条 ---------- */
function xaStack(id, inner, more, cls = '') {
  const enter = id && XA.last[cls] && XA.last[cls] !== id ? ' enter' : '';
  if (id) XA.last[cls] = id;
  return `<div class="xa-card${more > 1 ? ' more' : ''}${enter}" data-xa-card="${esc(id || '')}">${inner}</div>`;
}

function xaDone(label, rows) {
  if (!rows.length) return '';
  return `<details class="xa-done"><summary>${esc(label)} ${rows.length}</summary><ol>${rows.join('')}</ol></details>`;
}

const xaClip = (s, n) => { const t = String(s || '').replace(/\s+/g, ' ').trim(); return t.length > n ? `${t.slice(0, n)}…` : t; };

/* 短帖、引用：工作台 X 队列里的（x_daily），过了 QA 自动勾上，排着隔开发 */
function xaPosts(dd, kind) {
  const t = dd?.today || { posts: [] };
  const mine = t.posts.filter((x) => !x.swapped && (kind === 'quote' ? x.quote_url : !x.long && !x.quote_url));
  const label = kind === 'quote' ? '引用' : '短帖';
  const sent = mine.filter((x) => ['sent', 'handed'].includes(x.state));
  const dropped = mine.filter((x) => x.state === 'rejected');
  const manualQ = kind === 'quote' && dd?.quotes_mode === 'manual';  // X API 连引用也拦了：一张张点去 X 发
  const queue = mine.filter((x) => ['approved', 'sending', 'ready_manual'].includes(x.state));
  const checking = mine.filter((x) => x.state === 'pending');
  const nextAll = (t.posts || []).find((x) => x.state === 'approved' && (!x.long || x.prep === 'ready'));
  const next = queue[0] || checking[0];
  let card;
  if (!next) {
    const why = kind === 'quote' ? (dd?.hot_busy ? '<span class="spin"></span> 在挑正在涨的帖子写引用' : dd?.today?.hot_note ? esc(dd.today.hot_note) : '还没写；每 2 小时从正在涨的 AI 帖子里挑一批') : '今天没排短帖';
    card = `<div class="xa-card empty"><p>${mine.length ? '今天这一路发完了' : why}</p></div>`;
  } else {
    const late = String(t.next_at || '').startsWith('明天');  // 22:00 以后：短帖挪到明天，引用（热点）过夜就作废
    const when = next.state === 'sending' ? '<span class="spin"></span> 在发' : next.state === 'pending' ? (kind !== 'quote' ? '排着' : next.qa === 'running' ? '<span class="spin"></span> QA 在看' : '等 QA')
      : late && kind === 'quote' ? '今天发的时段过了，没发的过夜作废' : nextAll && nextAll.id === next.id && t.next_at ? `约 ${esc(t.next_at)} 发` : late ? '明天接着发' : '排着';
    const src = kind === 'quote' ? `<blockquote><a href="${esc(next.quote_url)}" target="_blank" rel="noopener"><b>引用 ${esc((next.source_kind || '').replace(/^热点 · /, '') || '原帖')}</b></a> ${esc(xaClip(next.source_title, 70))}</blockquote>` : '';
    const go = manualQ && next.state === 'ready_manual' && next.intent_url ? `<a class="btn small primary" data-xa-qhand="${esc(next.id)}" href="${esc(next.intent_url)}" target="_blank" rel="noopener noreferrer">去 X 发 ↗</a>` : `<span>${when}</span>`;
    card = xaStack(next.id, `${src}<p>${esc(xaClip(next.text, 200))}</p><footer>${go}<button class="linkish" type="button" data-xa-drop="${esc(next.id)}">这条不发</button></footer>`, queue.length + checking.length, kind);
  }
  const note = manualQ ? '<p class="xa-note">X 不让工作台直接发引用（API 只能引用 @ 了你的帖子）。每条写好了，点「去 X 发」，在 X 里按发送。<button class="linkish" type="button" data-xa-qretry>再试一次直接发</button></p>' : '';
  const done = sent.slice().reverse().map((x) => `<li><span>${x.state === 'handed' ? '去 X' : xlBjHm(x.sent_at)}</span><p>${esc(xaClip(x.text, 80))}</p>${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">↗</a>` : ''}</li>`);
  const out = dropped.map((x) => `<li><span>没发</span><p>${esc(xaClip(x.text, 60))}${x.auto_reason ? `<small>${esc(x.auto_reason)}</small>` : ''}</p></li>`);
  return `<div class="xa-row"><div class="xa-h"><b>${label}</b><small>已发 ${sent.length}</small>${queue.length ? `<small>排着 ${queue.length}</small>` : ''}</div>
    <div class="xa-main">${note}${card}<div class="xa-folds">${xaDone('今天已发', done)}${xaDone(kind === 'quote' ? '没过 QA' : '没发', out)}</div></div></div>`;
}

/* 回复：X 允许就工作台自己发；X 不让（API 只能回 @ 了你的帖子），每张卡点一下去 X，回复框里写好了 */
function xaReplies() {
  const d = XR.data || {};
  const manual = d.mode === 'manual';
  const next = d.next;
  const doneRows = (d.done_today || []).map((x) => `<li><span>${x.state === 'handed' ? '去 X' : '已回'}</span><p><b>@${esc(x.author || '')}</b> ${esc(xaClip(x.draft, 70))}</p>${x.reply_url ? `<a href="${esc(x.reply_url)}" target="_blank" rel="noopener">↗</a>` : ''}</li>`);
  let card;
  if (!XR.loaded) card = '<div class="xa-card empty"><p><span class="spin"></span> 在读</p></div>';
  else if (!next) {
    const h = Number(new Date().toLocaleString('en-US', { timeZone: 'Asia/Shanghai', hour: 'numeric', hour12: false }));
    card = `<div class="xa-card empty"><p>${d.busy ? '<span class="spin"></span> 在写下一批回复' : h >= 23 || h < 9 ? '明天 9:00 起自己写、自己发' : '下一批还没写好，半小时内自己写'}</p></div>`;
  }
  else {
    const go = manual ? `<a class="btn small primary" data-xa-hand="${esc(next.id)}" href="${esc(xrIntent(next.id, next.draft || ''))}" target="_blank" rel="noopener noreferrer">去 X 回复 ↗</a>` : `<span>${d.next_at ? `约 ${esc(d.next_at)} 发` : '排着'}</span>`;
    card = xaStack(next.id, `<blockquote><a href="${esc(next.url)}" target="_blank" rel="noopener noreferrer"><b>@${esc(next.author || '原帖')}</b></a> ${esc(xaClip(next.text || next.title, 70))}</blockquote>
      <p>${esc(next.draft || '')}</p>${next.source_note ? `<small class="xa-src">原话来自《${esc(String(next.source_note).split('/').pop().replace(/\.md$/, ''))}》</small>` : ''}<footer>${go}<button class="linkish" type="button" data-xa-skip="${esc(next.id)}">跳过</button></footer>`, d.queue || 1, 'reply');
  }
  const why = manual ? `<p class="xa-note">X 不让工作台直接回复别人的帖子（API 只能回 @ 了你的）。每条已经写好，点「去 X 回复」，在 X 里按发送就行。${d.api_blocked ? '<button class="linkish" type="button" data-xa-retry-api>再试一次直接发</button>' : ''}</p>` : '';
  const err = XR.error || d.error ? `<p class="xa-note bad" role="alert">${esc(XR.error || d.error)}</p>` : '';
  return `<div class="xa-row"><div class="xa-h"><b>回复</b><small>已回 ${(d.done_today || []).length}</small>${d.queue ? `<small>写好 ${d.queue}</small>` : ''}</div>
    <div class="xa-main">${why}${err}${card}<div class="xa-folds">${xaDone('今天已回', doneRows)}</div></div></div>`;
}

/* ---------- 10/12 晚 作者：两条线 ----------
 * 「X 平台确实要走一些流量的逻辑」：价值线 = 长文（工作台每天做 2 篇，存进 X 草稿他自己发；他自己再发 1 篇或一条视频）；
 * 流量线 = 短帖（反常识暴论，每天 20）+ repost（别人正在火的帖子 + 他的原话或暴论，每天 10），过 QA 就发。回复他自己来，页面上不放。
 * 每一路是一摞卡片，只露最上面一张（下一条），发出去收进「今天已发」。 */
/* 10/13：X API 余额用完（402）或者今天被停了：两条线最上面都说清楚，充值好了点一下接着发 */
function xaStopped(dd) {
  const why = dd?.credits_out ? 'X API 余额用完了，什么都发不出去、草稿也存不进去：去 console.x.com 充值（每小时会自己试一条）' : dd?.today?.halted;
  return why ? `<div class="xd-miss"><b class="bad">${esc(why)}</b><button class="btn small primary" type="button" data-xa-resume>充值好了，接着发</button></div>` : '';
}

function xaAuto(dd) {
  const c = dd?.counts || {};
  const sent = (kind) => (dd?.today?.posts || []).filter((x) => x.state === 'sent' && (kind === 'quote' ? x.quote_url : !x.long && !x.quote_url)).length;
  const lane = (kind, label, sub, target) => `<div class="xt-lane"><div class="xt-lane-h"><b>${label}</b><small>${sub}</small><span class="num">${sent(kind)} / ${target ?? '—'}</span></div>${xaPosts(dd, kind)}</div>`;
  return `<section class="xtrack traffic" aria-label="流量线"><div class="xtrack-h"><span class="xt-chip traffic">流量</span><h2>短帖 · repost</h2><small>不用你挑，自动发（Repost 过 QA）</small></div>${xaStopped(dd)}
    ${lane('short', '短帖', '反常识暴论，从你的原则、预测出发', c.own_short)}
    ${lane('quote', 'Repost', '别人正在火的帖子 + 你的原话或暴论', c.hot)}</section>`;
}

/* 10/13 作者：「显示正在改写，is working or not?」——昨晚就没做成的也在转圈。只有真的在跑才转圈；没做成的说原因、给「重做」 */
function xvPrepState(x) {
  if (x.prep === 'ready') return `<button type="button" class="btn small primary" data-xd-draft="${esc(x.id)}">存进 X 草稿</button>`;
  if (x.prep === 'failed') return `<button type="button" class="btn small primary" data-xd-redo="${esc(x.id)}" title="重新改写、重新配图">重做</button><span class="xv-prep bad" title="${esc(x.prep_error || '')}">没做成${x.prep_error ? `：${esc(x.prep_error.split('\n')[0].slice(0, 60))}` : ''}</span>`;
  if (x.prep === 'running') return '<span class="xv-prep"><span class="spin"></span> 在改写、配图、出封面（十来分钟）</span>';
  return '<span class="xv-prep">排着，前面的做完就开始</span>';
}

function xvValue(dd) {
  const t = dd?.today || { posts: [] }, key = t.day;
  const arts = (t.posts || []).filter((x) => x.manual_publish && ['pending', 'approved', 'drafted'].includes(x.state) && !x.swapped);
  const waiting = arts.filter((x) => x.state !== 'drafted'), drafted = arts.filter((x) => x.state === 'drafted');
  const x = waiting[0];
  let card;
  if (!x) {
    card = `<div class="xa-card empty"><p>${drafted.length ? `今天 ${drafted.length} 篇都存进 X 草稿了，去 X 发吧` : (t.picks || []).length ? '候选都用完了' : '在从你的原始输出里挑今天的长文'}</p></div>`;
  } else {
    const state = xvPrepState(x);
    const acts = `<div class="xv-acts">${state}
      <button type="button" class="btn small" data-xv="${esc(x.id)}" data-xv-act="split" title="这篇不发长文，拆成几条短帖进流量线">拆成短帖</button>
      <button type="button" class="btn small ghost" data-xv="${esc(x.id)}" data-xv-act="skip" title="这篇放一边，从候选里补一篇">不发</button></div>`;
    card = xaStack(x.id, `${acts}<div class="xv-reader" tabindex="0" aria-label="全文">${xdReader(x, key, { noActs: true })}</div>`, waiting.length, 'value');
  }
  const done = drafted.map((a) => `<li><span>草稿</span><p>${esc(xdTitle(a))}</p><a href="${esc(a.url || 'https://x.com/compose/articles')}" target="_blank" rel="noopener">去 X 发 ↗</a></li>`);
  return `<section class="xtrack value" aria-label="价值线"><div class="xtrack-h"><span class="xt-chip value">价值</span><h2>长文</h2><small>每天 ${(dd.counts || {}).articles ?? 4} 篇，做好存进 X 草稿，你自己发</small></div>${dd.credits_out ? xaStopped(dd) : ''}
    <div class="xt-lane"><div class="xt-lane-h"><b>工作台做的</b><small>从你的原始输出里挑，做好了存进 X 草稿，你自己发</small><span class="num">${drafted.length} / ${(dd.counts || {}).articles ?? 4}</span></div>
      ${card}<div class="xa-folds">${xaDone('今天存了草稿', done)}</div></div>
  </section>`;
}

function xrPaint(box) {
  const root = $('[data-xa]', box);
  if (!root || !box.isConnected) return;
  root.innerHTML = xaAuto(XL.daily); xaBind(box); xlLivePaint(box);
}

async function xrLoad(box) {
  if (XR.loading) return;
  XR.loading = true;
  try { XR.data = await api('/api/xline/replies'); XR.error = ''; XR.loaded = true; XR.at = Date.now(); }
  catch (err) { XR.error = err.message; XR.loaded = true; }
  finally { XR.loading = false; }
  xrPaint(box);
  clearTimeout(XR.timer);
  if (box.isConnected) XR.timer = setTimeout(() => { if (box.isConnected && S.view === 'platform' && S.platformKey === 'x') xrLoad(box); }, XR.data?.busy ? 5000 : 60000);
}

function xaBind(box) {
  const reload = async () => { try { await xlLoad(false, 'daily'); } catch (err) { toast(err.message); } xlRender(); };
  $$('[data-xa-drop]', box).forEach((b) => (b.onclick = async () => {
    const [key] = xdFind(b.dataset.xaDrop);
    b.disabled = true;
    try { await api(`/api/xline/daily/${key}/${encodeURIComponent(b.dataset.xaDrop)}`, { method: 'PATCH', body: { state: 'rejected' } }); } catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xa-skip]', box).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try { await api(`/api/xline/replies/${encodeURIComponent(b.dataset.xaSkip)}`, { method: 'POST', body: { state: 'skip' } }); } catch (err) { toast(err.message); }
    xrLoad(box);
  }));
  // 默认链接行为直接开新标签（浏览器才不拦）；同时记一笔「交给你了」，下一张卡上来
  $$('[data-xa-hand]', box).forEach((a) => (a.onclick = () => {
    api(`/api/xline/replies/${encodeURIComponent(a.dataset.xaHand)}/handed`, { method: 'POST' }).catch((err) => toast(err.message)).finally(() => xrLoad(box));
  }));
  $$('[data-xa-qhand]', box).forEach((a) => (a.onclick = () => {
    const [key] = xdFind(a.dataset.xaQhand);
    api(`/api/xline/daily/${key}/${encodeURIComponent(a.dataset.xaQhand)}/handed`, { method: 'POST' }).catch((err) => toast(err.message)).finally(reload);
  }));
  $$('[data-xa-resume]', box).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try { await api('/api/xline/daily/resume', { method: 'POST' }); toast('接着发了：下一分钟发第一条，还是 402 的话会再停'); } catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xa-qretry]', box).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try { await api('/api/xline/quotes/retry-api', { method: 'POST' }); toast('下一条引用会再试一次直接发'); } catch (err) { toast(err.message); }
    reload();
  }));
  $$('[data-xa-retry-api]', box).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try { await api('/api/xline/replies/retry-api', { method: 'POST' }); toast('下一条会再试一次直接发'); } catch (err) { toast(err.message); }
    xrLoad(box);
  }));
}

const XL_LIVE = { data: null, error: '', loading: false, at: 0, timer: null };
function xlLivePaint(box) {
  const live = $('[data-xl-live]', box);
  if (!box.isConnected) return;
  if (live) live.innerHTML = xlLive();
}
async function xlLiveLoad(box, fresh = false) {
  if (XL_LIVE.loading) return;
  clearTimeout(XL_LIVE.timer);
  if (fresh || !XL_LIVE.at || Date.now() - XL_LIVE.at >= 300000) {
    XL_LIVE.loading = true;
    try { XL_LIVE.data = await api('/api/xline/live'); XL_LIVE.error = ''; }
    catch (err) { XL_LIVE.error = err.message; }
    finally { XL_LIVE.loading = false; XL_LIVE.at = Date.now(); }
  }
  // 请求可能从已卸载的页面发起；响应和下一次刷新跟随现在的挂载。
  const current = XL.mounts.pending || box;
  if (current.isConnected && S.view === 'platform' && S.platformKey === 'x') {
    xlLivePaint(current);
    XL_LIVE.timer = setTimeout(() => {
      const target = XL.mounts.pending || current;
      if (target.isConnected && S.view === 'platform' && S.platformKey === 'x') return xlLiveLoad(target, true);
    }, Math.max(1000, 300000 - (Date.now() - XL_LIVE.at)));
  }
}
