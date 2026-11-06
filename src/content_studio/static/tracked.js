'use strict';

/* 批注视图（10/12 作者）：AI 在他的原文上直接改，每一处都留痕，像 Word 的修订。
   他逐条接受、改一改、不要，也可以全部接受、全部不要；评论只提示，不改稿。
   post.trk = { base, changes: [{id, reason, op, anchor, text, note, start, end, pos, fresh, downgraded, inline, status, edit, source}], scores, budget, … }
   这个文件有两部分：纯函数（把原文和修改清单画成 HTML，测试里直接跑）和弹层（点按钮、调接口）。 */

const TRK_TYPE = { move: '挪', replace: '改', delete: '删', insert: '加', comment: '评论' };
const TRK_STATUS = { pending: '待处理', accepted: '已接受', rejected: '不要', edited: '你改过', resolved: '知道了' };
const TRK_REASONS = ['开头', '风格', '高密度', '痛点', '利他', '共鸣', '稀缺', '结尾', '完整度', '错字', '通顺', '导语'];
const TRK_TARGET = 80;
const trkPct = (trk) => Number((trk && (trk.pct_effective || trk.max_pct || trk.pct)) || 20);

const trkEsc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
/* 他的文字里的 **加粗** 显示成粗体，其余照原样转义 */
const trkText = (s) => trkEsc(s).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
const trkAfter = (c) => (c.edit != null ? c.edit : c.text || '');
const trkIsEdit = (c) => c.op !== 'comment';
const trkPendingEdits = (trk) => trk.changes.filter((c) => trkIsEdit(c) && c.status === 'pending').length;

/* 一处修改在正文里怎么画。kind: ins（新的）/ del（被去掉的）/ note（评论的那句话） */
function trkMark(c, kind, text, opt) {
  const plainText = trkText(text);
  if (opt.focus && opt.view !== 'orig' && c.id !== opt.focus) {  // 点了某一处：别的修改不带颜色，按当前状态显示成普通文字
    if (c.op === 'comment') return plainText;
    const applied = c.status === 'accepted' || c.status === 'edited';
    return kind === 'del' ? (applied ? '' : plainText) : (applied ? plainText : '');
  }
  const sel = c.id === opt.selected ? ' sel' : '';
  const dim = opt.filter.length && !opt.filter.includes(c.reason) ? ' dim' : '';
  const attrs = `data-trk-c="${trkEsc(c.id)}" data-reason="${trkEsc(c.reason)}" title="${trkEsc(c.reason)}"`;
  const tag = `<span class="trk-tag">${trkEsc(c.reason)}</span>`;
  const plain = trkText(text);
  if (opt.view === 'orig') return kind === 'del' ? plain : '';  // 原文：只有他自己的字，修改一概不显示
  if (c.op === 'comment' && opt.view === 'clean') return plain;
  if (c.op === 'comment' && c.status === 'resolved') return `<span class="trk-c done-resolved${sel}${dim}" ${attrs}>${plain}</span>`;  // 看过了也留个记号，位置不丢
  if (opt.view === 'clean') {
    if (c.status === 'accepted' || c.status === 'edited') return kind === 'del' ? '' : plain;
    return kind === 'del' ? plain : '';  // 没处理的、不要的：先不算进去
  }
  if (c.status === 'rejected') return kind === 'del' ? plain : '';
  if (c.status === 'accepted' || c.status === 'edited') return kind === 'del' ? '' : `<span class="trk-c done-${c.status}${sel}${dim}" ${attrs}>${plain}</span>`;
  if (kind === 'ins') return `<ins class="trk-c${c.fresh ? ' fresh' : ''}${sel}${dim}" ${attrs}>${plain}</ins>${tag}`;
  if (kind === 'del') return `<del class="trk-c${sel}${dim}" ${attrs}>${plain}</del>`;
  return `<mark class="trk-c${sel}${dim}" ${attrs}>${plain}</mark>${tag}`;
}

/* 原文 + 修改清单 → 一段一段的 HTML（第一段是标题）。修改的位置是原文里的字符位置（start / end）。 */
function trkParagraphs(trk, opt) {
  const base = trk.base, out = [];
  if (opt.view === 'orig') {  // 原文：整篇就是他自己的字，一个标记都没有
    return base.split('\n\n').filter((p) => p.trim()).map((p, i) => ({ title: i === 0, html: i === 0 ? trkEsc(p.replace(/^#+\s*/, '')) : trkEsc(p) }));
  }
  const marks = [], inserts = [], tops = [];
  for (const c of trk.changes) {
    if (c.op === 'move') { marks.push({ s: c.start, e: c.end, c, kind: 'del' }); tops.push({ c, text: c.anchor, kind: 'ins' }); }
    else if (c.op === 'insert' && c.pos === 'top') tops.unshift({ c, text: trkAfter(c), kind: 'ins' });
    else if (c.op === 'insert') inserts.push({ at: c.pos === 'before' ? c.start : c.end, c });
    else if (c.op === 'comment') { if (c.inline) marks.push({ s: c.start, e: c.end, c, kind: 'note' }); }
    else marks.push({ s: c.start, e: c.end, c, kind: 'del' });
  }
  marks.sort((a, b) => a.s - b.s);
  let pos = 0, first = true;
  for (const para of base.split('\n\n')) {
    const p0 = base.indexOf(para, pos), p1 = p0 + para.length;
    pos = p1;
    if (first) { first = false; out.push({ title: true, html: trkEsc(para.replace(/^#+\s*/, '')) }); for (const t of tops) { const h = trkMark(t.c, t.kind, t.text, opt); if (h) out.push({ html: h }); } continue; }
    let html = '', cur = p0;
    const here = marks.filter((m) => m.s >= p0 && m.e <= p1 && m.s >= cur);
    const ins = inserts.filter((i) => i.at >= p0 && i.at <= p1);
    const cuts = [...here.map((m) => ({ at: m.s, m })), ...ins.map((i) => ({ at: i.at, i }))].sort((a, b) => a.at - b.at);
    const emit = (until) => { if (until > cur) { html += trkEsc(base.slice(cur, until)); cur = until; } };
    for (const cut of cuts) {
      if (cut.m) {
        if (cut.m.s < cur) continue;  // 压在前一处上面的，不画（还在右边的列表里）
        emit(cut.m.s);
        const c = cut.m.c;
        // 只是加粗（字一样、多了 ** 记号）：不画「删了再加」，只画加粗后的样子，免得满屏红蓝
        const boldOnly = c.op === 'replace' && trkAfter(c).replace(/\*\*/g, '') === c.anchor;
        html += c.op === 'replace' && !boldOnly ? trkMark(c, 'del', c.anchor, opt) + trkMark(c, 'ins', trkAfter(c), opt)
          : c.op === 'replace' ? trkMark(c, 'ins', trkAfter(c), opt) : trkMark(c, cut.m.kind, base.slice(cut.m.s, cut.m.e), opt);
        cur = cut.m.e;
      } else {
        emit(cut.i.at);
        html += trkMark(cut.i.c, 'ins', trkAfter(cut.i.c), opt);
      }
    }
    emit(p1);
    if (html.trim()) out.push({ html });
  }
  return out;
}

/* 一处修改占的预算：[去掉或换掉的字, 新写的字]，只加粗、只改标点的算真正变了的字（和代码一样） */
function trkCost(c) {
  if (!trkIsEdit(c) || c.status === 'rejected') return [0, 0];
  if (c.op === 'move') return [c.anchor.length, c.anchor.length];
  if (c.op === 'insert') return [0, trkAfter(c).length];
  if (c.op === 'delete') return [c.anchor.length, 0];
  const m = trkCommon(c.anchor, trkAfter(c));
  return [c.anchor.length - m, trkAfter(c).length - m];
}
function trkBudget(trk) {
  const size = Math.max(trk.base.replace(/^#[^\n]*\n*/, '').length, 1);
  const costs = trk.changes.map(trkCost);
  return Math.max(costs.reduce((n, x) => n + x[0], 0), costs.reduce((n, x) => n + x[1], 0)) * 100 / size;
}
function trkCommon(a, b) {  // 两段话里一样的字数（够用的估算：最长公共子序列）
  const n = a.length, m = b.length;
  if (!n || !m) return 0;
  let prev = new Array(m + 1).fill(0);
  for (let i = 1; i <= n; i++) {
    const row = [0];
    for (let j = 1; j <= m; j++) row[j] = a[i - 1] === b[j - 1] ? prev[j - 1] + 1 : Math.max(prev[j], row[j - 1]);
    prev = row;
  }
  return prev[m];
}

function trkRow(c, selected) {
  const what = (c.op === 'comment' ? c.note : c.op === 'move' ? c.anchor : c.op === 'insert' ? trkAfter(c) : (c.anchor || ''));
  return `<button type="button" class="trk-row${c.id === selected ? ' sel' : ''}" data-trk-pick="${trkEsc(c.id)}"><span class="trk-badge">${trkEsc(c.reason)}</span><span class="trk-t">${TRK_TYPE[c.op]} · ${trkEsc(what)}</span><span class="trk-st ${c.status}">${TRK_STATUS[c.status]}</span></button>`;
}

function trkCard(trk, selected) {
  const c = trk.changes.find((x) => x.id === selected);
  if (!c) return '<div class="trk-card"><b>点正文里的一处修改</b><p>或者在下面的列表里选一条。</p></div>';
  const note = c.op === 'comment';
  const who = c.source === 'qa' ? '发前 QA' : c.fresh ? '新写 · 待你确认' : note ? '评论' : '直接改';
  const boldOnly = c.op === 'replace' && trkAfter(c).replace(/\*\*/g, '') === c.anchor;
  if (boldOnly) {
    return `<div class="trk-card"><h4><span class="trk-badge">${trkEsc(c.reason)}</span><span class="trk-badge">只加粗</span><span class="trk-badge">直接改</span><span class="trk-st ${c.status}">${TRK_STATUS[c.status]}</span></h4>
    <p class="trk-why">${trkEsc(c.note || '')}</p><p class="trk-diff">字一个没变，只是加粗：<strong>${trkEsc(trkAfter(c).replace(/\*\*/g, ''))}</strong></p>
    <div class="trk-acts"><button class="btn small primary" type="button" data-trk-act="accepted">接受</button><button class="btn small" type="button" data-trk-act="rejected" title="这条不要了：文字保持你的原文，而且算处理过，不再挡着你存草稿">不要</button><button class="btn small ghost" type="button" data-trk-act="pending" title="回到「待处理」：文字回到你的原文，但还算没处理，会挡着你存草稿">放回待处理</button></div>
    <small>只加粗不占预算。</small></div>`;
  }
  const diff = note ? '' : `<p class="trk-diff">${c.op === 'insert' ? '' : `<del>${trkText(c.op === 'move' ? '（在原来的位置）' : c.anchor)}</del> `}${c.op === 'delete' ? '' : `<ins>${trkText(c.op === 'move' ? c.anchor : trkAfter(c))}</ins>`}</p>`;
  const editable = c.op === 'replace' || c.op === 'insert';
  const edit = editable ? `<textarea id="trkEdit" aria-label="改一改">${trkEsc(trkAfter(c))}</textarea><small>用 **两个星号** 包起来的是加粗。</small>` : '';
  const acts = note
    ? `<button class="btn small" type="button" data-trk-act="resolved">知道了</button><button class="btn small ghost" type="button" data-trk-act="pending">还没想好</button>`
    : `<button class="btn small primary" type="button" data-trk-act="accepted">接受</button>${editable ? '<button class="btn small" type="button" data-trk-act="edited">用我改的</button>' : ''}<button class="btn small" type="button" data-trk-act="rejected" title="这条不要了：文字保持你的原文，而且算处理过，不再挡着你存草稿">不要</button><button class="btn small ghost" type="button" data-trk-act="pending" title="回到「待处理」：文字回到你的原文，但还算没处理，会挡着你存草稿">放回待处理</button>`;
  return `<div class="trk-card"><h4><span class="trk-badge">${trkEsc(c.reason)}</span><span class="trk-badge">${TRK_TYPE[c.op]}</span><span class="trk-badge${c.fresh ? ' fresh' : ''}">${who}</span><span class="trk-st ${c.status}">${TRK_STATUS[c.status]}</span></h4>
    <p class="trk-why">${trkEsc(c.note || '')}</p>${diff}${edit}<div class="trk-acts">${acts}</div>
    <small>${note ? '评论不改你的稿子，不占预算。' : `占预算约 ${Math.max(...trkCost({ ...c, status: 'pending' }))} 字。`}</small></div>`;
}

function trkScores(trk) {
  const before = (trk.scores || {}).before || {}, after = (trk.scores || {}).after || null;
  const names = Object.keys(before);
  if (!names.length) return '';
  const rows = names.map((n) => {
    const a = before[n].score, b = after && after[n] ? after[n].score : null;
    return `<tr><td>${trkEsc(n)}</td><td>${a}</td><td>${b == null ? '—' : `<b>${b}</b>`}</td><td><progress max="100" value="${b == null ? a : b}" class="${(b == null ? a : b) >= TRK_TARGET ? 'ok' : ''}"></progress></td></tr>`;
  }).join('');
  const left = trkPendingEdits(trk);
  const stale = !!(trk.scores || {}).stale;
  const err = trk.rescore_error ? `<small class="trk-bad">${trkEsc(trk.rescore_error)}</small>` : '';
  const state = trk.rescoring ? '<small>在重新打分，一两分钟…</small>'
    : stale ? '<small>这是改动之前那一版的分，修改都处理完会自动重打</small>'
      : (!after && !left ? '<small>修改都处理完了，马上自动打分</small>' : '');
  return `<div class="trk-card"><h4>分数 <small>目标 ${TRK_TARGET}</small></h4><table class="trk-tbl"><thead><tr><th>项</th><th>改前</th><th>改后</th><th></th></tr></thead><tbody>${rows}</tbody></table>
    ${state}<button type="button" class="btn small" data-trk-rescore${left || trk.rescoring ? ' disabled' : ''}>${trk.rescoring ? '在打分…' : '现在重打一次'}</button>${left ? `<small>还有 ${left} 处没处理，处理完会自动打分</small>` : ''}${err}</div>`;
}

/* 10/13 作者：「点了全部接受，关闭以后我不知道存没存」。每一下其实都已经存了；右上角改成「保存」（关掉，告诉他存了什么）
   和「不保存，关闭」（这次打开以后的处理全部退回去）。snap 是打开时各条的状态。 */
function trkSnap(trk) {
  return { state: Object.fromEntries(trk.changes.map((c) => [c.id, [c.status, c.edit == null ? null : c.edit]])), max_pct: trk.max_pct ?? null, overflow: trk.overflow || [],
    scores_fresh: !!((trk.scores || {}).after && !(trk.scores || {}).stale) };
}
function trkDirty(trk, snap) {
  if (!snap) return 0;
  const now = trkSnap(trk).state, ids = new Set([...Object.keys(now), ...Object.keys(snap.state)]);
  let n = 0;
  ids.forEach((id) => { if (JSON.stringify(now[id] || null) !== JSON.stringify(snap.state[id] || null)) n += 1; });
  return n + ((trk.max_pct ?? null) !== snap.max_pct ? 1 : 0);
}
function trkSaveBar(trk, snap) {
  const n = trkDirty(trk, snap);
  return `<span class="trk-save"><small>${n ? `这次处理了 ${n} 处，每一下都已经存进正文` : '还没有改动'}</small>
    <button type="button" class="btn small ghost" data-trk-discard${n ? '' : ' disabled'} title="这次打开以后做的处理全部退回去，再关掉">不保存，关闭</button>
    <button type="button" class="btn small primary" data-trk-close>保存</button></span>`;
}
/* 关掉以后在页面上说一句存了什么（纯函数，测试里跑） */
function trkSavedMsg(trk, n) {
  if (!n) return '没有改动';
  const left = trkPendingEdits(trk), sc = trk.scores || {};
  const used = trk.changes.filter((c) => trkIsEdit(c) && (c.status === 'accepted' || c.status === 'edited')).length;
  const score = left ? `还有 ${left} 处没处理，处理完自动重打分` : trk.rescoring || sc.stale || !sc.after ? '在按新正文重打分，一两分钟，卡片上会显示' : '改后打分已出来，卡片上看';
  return `存好了：${used} 处修改在正文里 · ${score}`;
}

/* 整个弹层的 HTML（纯函数：post + 视图状态 → 字符串） */
function trkHtml(post, st) {
  const trk = post.trk, opt = { view: st.view, filter: st.filter, selected: st.selected, focus: st.focus };
  const counts = { pending: 0, accepted: 0, rejected: 0, edited: 0, resolved: 0 };
  trk.changes.forEach((c) => { counts[c.status] += 1; });
  const used = trkBudget(trk), pct = trkPct(trk);
  const reasons = TRK_REASONS.filter((r) => trk.changes.some((c) => c.reason === r));
  const hist = trk.history || [];
  const paras = st.view === 'clean'
    ? `<p class="trk-note">干净结果：只含你接受和改过的，还没处理的先不算进去。</p>${trkCleanParagraphs(post)}`
    : st.view === 'orig' ? `<p class="trk-note">原文：这是你自己的字，一处修改都没有。</p>${trkParagraphs(trk, opt).map((p) => (p.title ? `<h3>${p.html}</h3>` : `<p>${p.html}</p>`)).join('')}`
    : trkParagraphs(trk, opt).map((p) => (p.title ? `<h3>${p.html}</h3>` : `<p>${p.html}</p>`)).join('');
  const dropped = (trk.dropped || []).length ? `<small>另有 ${trk.dropped.length} 条建议没用上（找不到原句、重叠、不是你的原词…）</small>` : '';
  return `<div class="trk-box" role="dialog" aria-modal="true" aria-label="批注视图">
    <header><h2>批注视图 <small>${trkEsc(post.source_title || '')}</small></h2>${trkSaveBar(trk, st.snap)}</header>
    <div class="trk-bar">
      <span class="trk-counts">待处理 <b>${counts.pending}</b> · 已接受 <b>${counts.accepted + counts.edited}</b> · 不要 <b>${counts.rejected}</b> · 评论已读 <b>${counts.resolved}</b></span>
      <span class="trk-budget">改动预算 <progress max="${pct}" value="${Math.min(used, pct).toFixed(2)}" class="${used > pct * 0.8 ? 'hot' : ''}"></progress> <b>${used.toFixed(1)}%</b> / <input type="number" id="trkPct" min="1" max="50" value="${pct}" aria-label="这一篇的改动预算百分比"><b>%</b> <button type="button" class="btn small ghost" data-trk-pct title="改这一篇的预算：调高会把「没放进来」的放进来，调低不会动已有的修改">改</button></span>
      <span class="trk-grow"></span>
      ${st.focus ? '<span class="trk-focus">只看这一处 <button type="button" class="btn small ghost" data-trk-unfocus>看全部</button></span>' : ''}
      <span class="trk-seg" role="group" aria-label="视图"><button type="button" data-trk-view="orig" aria-pressed="${st.view === 'orig'}">原文</button><button type="button" data-trk-view="marks" aria-pressed="${st.view === 'marks'}">带批注</button><button type="button" data-trk-view="clean" aria-pressed="${st.view === 'clean'}">干净结果</button></span>
      <span class="trk-seg" role="group" aria-label="着色"><button type="button" data-trk-color="type" aria-pressed="${st.color === 'type'}">按类型</button><button type="button" data-trk-color="reason" aria-pressed="${st.color === 'reason'}">按原因</button></span>
    </div>
    <div class="trk-bar">
      <span class="trk-chips">只看 ${reasons.map((r) => `<button type="button" class="trk-chip" data-trk-filter="${trkEsc(r)}" data-reason="${trkEsc(r)}" aria-pressed="${st.filter.includes(r)}">${trkEsc(r)}</button>`).join('')}</span>
      <span class="trk-grow"></span>
      <button type="button" class="btn small primary" data-trk-all="accepted">全部接受</button><button type="button" class="btn small" data-trk-step>逐条走</button><button type="button" class="btn small" data-trk-all="rejected">全部不要，我自己改</button>
      <button type="button" class="btn small ghost" data-trk-undo${hist.length ? ` title="撤销：${trkEsc(hist[hist.length - 1].label)}"` : ' disabled'}>撤销${hist.length ? `（${trkEsc(hist[hist.length - 1].label)}）` : ''}</button><button type="button" class="btn small ghost" data-trk-all="reset">全部还原</button>
    </div>
    <div class="trk-work">
      <article class="trk-paper${st.color === 'reason' ? ' byreason' : ''}">${paras}</article>
      <aside class="trk-side">${trkCard(trk, st.selected)}${trkScores(trk)}
        <div class="trk-card"><h4>全部修改 <span class="trk-badge">${trk.changes.length} 处</span></h4><div class="trk-list">${trk.changes.filter((c) => !st.filter.length || st.filter.includes(c.reason)).map((c) => trkRow(c, st.selected)).join('')}</div>${dropped}</div>
        ${(trk.overflow || []).length ? `<details class="trk-card trk-over"><summary>超出预算，没放进来 ${trk.overflow.length} 条</summary><ul>${trk.overflow.map((o) => `<li><span class="trk-badge">${trkEsc(o.reason)}</span> ${trkEsc(TRK_TYPE[o.op] || '')} · ${trkEsc(o.op === 'insert' ? trkAfter(o) : (o.anchor || ''))}${o.overflow_why && o.overflow_why !== '超出改动预算' ? `<small>${trkEsc(o.overflow_why)}</small>` : ''}</li>`).join('')}</ul><small>把上面的预算调高，放得下的就会放进来。</small></details>` : ''}
        ${post._topic ? '' : `<label class="trk-sum"><input type="checkbox" data-trk-summary${post.summary || post.summary_busy ? ' checked' : ''}${post.summary_busy ? ' disabled' : ''}> 带日期的 summary <small>${post.summary_busy ? '在写，一两分钟…' : post.summary_error ? `没写成：${trkEsc(post.summary_error)}` : '补发的老笔记才需要；今天写的不用'}</small></label>`}
      </aside>
    </div></div>`;
}

/* 干净结果：用文章现在的文字（只含接受的修改），配图用文章自己的文件 */
function trkCleanParagraphs(post) {
  // 文章的插图在 article-file 下面；口播稿没有图
  const base = post._doc === 'polish' ? `/api/topics/${encodeURIComponent(post.id)}/article-file/` : post._topic ? '' : `/api/xline/daily/${encodeURIComponent(post._key || '')}/${encodeURIComponent(post.id)}/file/`;
  return post.text.split(/\n\s*\n/).filter((b) => b.trim()).map((b, i) => {
    if (i === 0) return `<h3>${trkEsc(b.replace(/^#+\s*/, ''))}</h3>`;
    const img = b.match(/^!\[([^\]]*)\]\(([^)\s]+)\)$/);
    if (img) return `<figure><img src="${trkEsc(base + img[2].split('/').map(encodeURIComponent).join('/'))}" alt="${trkEsc(img[1])}" loading="lazy"></figure>`;
    return `<p>${trkText(b.trim())}</p>`;
  }).join('');
}

/* ---- 弹层：点按钮、调接口 ---- */
const TRK = { id: null, key: null, topic: false, doc: 'script', topicPost: null, selected: null, focus: null, view: 'marks', color: 'type', filter: [], timer: null, snap: null };
try { Object.assign(TRK, JSON.parse(localStorage.getItem('trk-view') || '{}')); TRK.filter = []; } catch (_) { /* 没有存过 */ }

/* 三个地方用同一个视图：X 的长文（接口在 /api/xline/daily/…）、加工中的口播稿（/api/topics/…/script）、
   「标题和封面」那篇文章的润色（/api/topics/…/polish，10/13）。差别只在这三处 */
function trkUrl(sub) {
  return TRK.topic ? `/api/topics/${TRK.id}/${TRK.doc}/${sub}` : `/api/xline/daily/${encodeURIComponent(TRK.key)}/${encodeURIComponent(TRK.id)}/${sub}`;
}
function trkPost() {
  if (TRK.topic) return TRK.topicPost;
  const [key, post] = typeof xdFind === 'function' ? xdFind(TRK.id) : [null, null];
  if (post) { post._key = key; TRK.key = key; }
  return post;
}
async function trkLoadTopic() {
  const r = await api(`/api/topics/${TRK.id}/${TRK.doc}`);
  const doc = r.script || r.polish;
  TRK.topicPost = doc ? { id: String(TRK.id), text: doc.text, trk: doc.trk, source_title: r.title || '', _topic: true, _doc: TRK.doc, summary: false } : null;
}
function trkPaint() {
  const dlg = document.querySelector('.trk-dlg');
  const post = trkPost();
  if (!dlg || !post || !post.trk) { trkClose(); return; }
  if (!TRK.snap) TRK.snap = trkSnap(post.trk);  // 打开时的样子：「不保存」退回到这里
  if (!post.trk.changes.some((c) => c.id === TRK.selected)) TRK.selected = (post.trk.changes.find((c) => trkIsEdit(c) && c.status === 'pending') || post.trk.changes[0] || {}).id;
  const keep = dlg.querySelector('.trk-paper'), top = keep ? keep.scrollTop : 0;
  dlg.innerHTML = trkHtml(post, TRK);
  const paper = dlg.querySelector('.trk-paper');
  if (paper) paper.scrollTop = top;
  dlg.dataset.color = TRK.color;
  trkBind(dlg, post);
  if (post.trk.rescoring || post.summary_busy) { clearTimeout(TRK.timer); TRK.timer = setTimeout(trkRefresh, 3000); }
}
async function trkRefresh() {
  try {
    if (TRK.topic) await trkLoadTopic(); else await xlLoad(false, 'daily');
  } catch (err) { toast(err.message); }
  if (document.querySelector('.trk-dlg')) trkPaint();  // 重新读完要重画：不然点了接受，界面还停在原来的样子
  if (TRK.topic && TRK.doc === 'polish') { if (typeof window !== 'undefined' && window.onPolishChange) window.onPolishChange(TRK.id); }
  else if (TRK.topic) { if (typeof window !== 'undefined' && window.onTrackedChange) window.onTrackedChange(TRK.id); }
  else if (typeof xlRender === 'function') xlRender();  // 卡片上的「改了几处、待处理几处」也跟着变
}
async function trkCall(path, body) {
  try { await api(trkUrl(path), { method: 'POST', body }); } catch (err) { toast(err.message); }
  await trkRefresh();
}
function trkNext(trk, after) {
  const list = trk.changes.filter((c) => trkIsEdit(c) && c.status === 'pending');
  return (list.find((c) => trk.changes.indexOf(c) > trk.changes.findIndex((x) => x.id === after)) || list[0] || {}).id;
}
function trkBind(dlg, post) {
  const trk = post.trk;
  const save = () => { try { localStorage.setItem('trk-view', JSON.stringify({ view: TRK.view, color: TRK.color })); } catch (_) { /* 存不了也能用 */ } };
  dlg.querySelector('[data-trk-close]').onclick = trkSave;
  const discard = dlg.querySelector('[data-trk-discard]');
  if (discard) discard.onclick = async () => {
    const n = trkDirty(trk, TRK.snap);
    if (n && !confirm(`这次打开以后处理的 ${n} 处全部退回去，正文回到打开时的样子？`)) return;
    try { await api(trkUrl('trk'), { method: 'POST', body: { all: 'restore', snapshot: TRK.snap } }); toast('没保存：退回到打开时的样子了'); } catch (err) { toast(err.message); return; }
    trkClose();
    await trkRefresh();
  };
  dlg.querySelectorAll('[data-trk-c],[data-trk-pick]').forEach((el) => (el.onclick = () => {
    const id = el.dataset.trkC || el.dataset.trkPick;
    // 点一处只看这一处，别的颜色全部去掉；再点同一处，回到全部都亮
    TRK.focus = TRK.focus === id ? null : id;
    TRK.selected = id;
    trkPaint();
  }));
  const unfocus = dlg.querySelector('[data-trk-unfocus]');
  if (unfocus) unfocus.onclick = () => { TRK.focus = null; trkPaint(); };
  const pctBtn = dlg.querySelector('[data-trk-pct]');
  if (pctBtn) pctBtn.onclick = async () => {
    const pct = Number(dlg.querySelector('#trkPct').value);
    if (!Number.isFinite(pct) || pct < 1 || pct > 50) { toast('预算要在 1% 到 50% 之间'); return; }
    try {
      const r = await api(trkUrl('trk/budget'), { method: 'POST', body: { pct } });
      toast(r.added ? `预算 ${pct}%，放进来 ${r.added} 条` : `预算 ${pct}%`);
    } catch (err) { toast(err.message); }
    await trkRefresh();
  };
  dlg.querySelectorAll('[data-trk-view]').forEach((b) => (b.onclick = () => { TRK.view = b.dataset.trkView; save(); trkPaint(); }));
  dlg.querySelectorAll('[data-trk-color]').forEach((b) => (b.onclick = () => { TRK.color = b.dataset.trkColor; save(); trkPaint(); }));
  dlg.querySelectorAll('[data-trk-filter]').forEach((b) => (b.onclick = () => {
    const r = b.dataset.trkFilter; TRK.filter = TRK.filter.includes(r) ? TRK.filter.filter((x) => x !== r) : [...TRK.filter, r]; trkPaint();
  }));
  dlg.querySelectorAll('[data-trk-act]').forEach((b) => (b.onclick = async () => {
    const status = b.dataset.trkAct, id = TRK.selected, edit = dlg.querySelector('#trkEdit');
    const next = trkNext(trk, id);
    await trkCall(`trk/${encodeURIComponent(id)}`, { status, ...(status === 'edited' && edit ? { edit: edit.value } : {}) });
    if (status !== 'pending' && next) TRK.selected = next;
    trkPaint();
  }));
  dlg.querySelectorAll('[data-trk-all]').forEach((b) => (b.onclick = () => trkCall('trk', { all: b.dataset.trkAll })));
  const step = dlg.querySelector('[data-trk-step]');
  if (step) step.onclick = () => { const n = trkNext(trk, TRK.selected); if (!n) { toast('都处理完了'); return; } TRK.selected = n; TRK.focus = n; TRK.view = 'marks'; trkPaint(); };
  const undo = dlg.querySelector('[data-trk-undo]');
  if (undo) undo.onclick = async () => {
    try { const r = await api(trkUrl('trk/undo'), { method: 'POST' }); toast(`撤销了：${r.undone || '上一步'}`); } catch (err) { toast(err.message); }
    await trkRefresh();
  };
  const rescore = dlg.querySelector('[data-trk-rescore]');
  if (rescore) rescore.onclick = () => trkCall('trk/rescore');
  const sum = dlg.querySelector('[data-trk-summary]');
  if (sum) sum.onchange = () => trkCall('trk/summary', { on: sum.checked });
}
function trkSave() {
  const post = trkPost();
  if (post && post.trk) toast(trkSavedMsg(post.trk, trkDirty(post.trk, TRK.snap)));
  trkClose();
}
function trkClose() {
  clearTimeout(TRK.timer);
  const dlg = document.querySelector('.trk-dlg');
  if (dlg) dlg.remove();
  document.removeEventListener('keydown', trkKey);
  document.body.classList.remove('trk-open');
}
function trkKey(e) { if (e.key === 'Escape') trkSave(); }  // Esc 和「保存」一样：已经存了的不会丢
function openTracked(id, opts = {}) {
  trkClose();
  TRK.topic = !!opts.topic;
  TRK.doc = opts.doc || 'script';
  TRK.topicPost = opts.post || null;
  TRK.id = id;
  TRK.selected = null;
  TRK.focus = null;
  TRK.snap = null;
  const dlg = document.createElement('div');
  dlg.className = 'trk-dlg';
  document.body.appendChild(dlg);
  document.body.classList.add('trk-open');
  document.addEventListener('keydown', trkKey);
  trkPaint();
}
window.openTracked = openTracked;
