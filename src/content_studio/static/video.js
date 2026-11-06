'use strict';
/* 加工中 · 一条视频：拍摄提纲 → 剪辑进度 → 发布 → 研习室文章（可选）（各页签由模块注册） */
window.VIEWS = window.VIEWS || {};
window.VIDEO_TABS = window.VIDEO_TABS || [];

const VD = { topicId: null, tab: 'outline', outline: null, dirty: false, mode: 'preview', qaOpen: false };

/* 只给骨架：暴论候选 + 论点证据 + 一句结尾。规则在 Anna 的工作流文件里，他随时能改。 */
const BOOKEND_LABEL = '写骨架';

async function startOutline(topicId) {
  try {
    const res = await api(`/api/topics/${topicId}/outline`, { method: 'POST' });
    toast(res.message);
    if (window.refreshTopics) await window.refreshTopics();
  } catch (err) { toast(err.message); }
}

// 落点：这集落到哪个案例、结尾承接哪个入口。框架（一勾式骨架）只在备注里给了承接时才用，
// 没给就只收一句判断——所以它是可选的一行备注，不是必填的 CTA。
const LANDING = /^落点[:：]\s*(.*)$/m;
function landingOf(memo) { const m = (memo || '').match(LANDING); return m ? m[1].trim() : ''; }
function withLanding(memo, text) {
  const rest = (memo || '').split('\n').filter((l) => !LANDING.test(l)).join('\n').trim();
  return text ? `${rest ? rest + '\n' : ''}落点：${text}` : rest;
}

function bindOutlineButtons(root) {
  $$('[data-outline]', root).forEach((b) => (b.onclick = async () => {
    if (b.textContent.startsWith('重写') && !confirm('重写会覆盖现在的骨架，继续吗？')) return;
    b.disabled = true;
    const box = $('#landingIn', root);
    if (box) {
      const id = Number(b.dataset.outline);
      const topics = await api('/api/topics?archived=true');
      const t = topics.find((x) => x.id === id);
      const next = withLanding(t && t.memo, box.value.trim());
      if (t && next !== (t.memo || '')) { try { await api(`/api/topics/${id}`, { method: 'PATCH', body: { memo: next } }); } catch (err) { toast(err.message); } }
    }
    await startOutline(Number(b.dataset.outline));
  }));
}

const QA_POINTS = [['pain', '痛点具象度'], ['contrast', '认知反差度'], ['delivery', '交付可行性']];
const QA_VERDICT = { go: ['可以拍', 'ok'], patch: ['先补再拍', 'warn'], thin: ['素材太薄', 'bad'] };

async function renderQA(topic, box) {
  if (!box) return;
  let d;
  try { d = await api(`/api/topics/${topic.id}/qa`); } catch (err) { box.innerHTML = ''; return; }
  const r = d.result;
  const again = `<button class="btn small ghost" type="button" data-qa-run>${r ? '重评' : '按三点评分'}</button>`;
  if (d.state === 'running') {
    box.innerHTML = '<section class="qa qa-wait"><span class="spin"></span>正在按三点评分（痛点、反差、交付），半分钟左右</section>';
    setTimeout(() => { if (S.view === 'work' && VD.tab === 'outline' && VD.topicId === topic.id) renderQA(topic, $('#qaBox')); }, 4000);
    return;
  }
  if (!r) {
    box.innerHTML = `<section class="qa qa-wait">${d.state === 'failed' ? `<span class="bad">${esc(d.error || '评分失败')}</span>` : '<span>还没评过。</span>'}${again}</section>`;
  } else {
    // 作者: 写提纲的时候不要把评分摊在眼前（Don't mess up with my mind）。
    // 默认只留一行结论，点「评估」才展开三点；「最该改」和「不要讲过头」不在这里露面——
    // 它们是给 Anna 看的，她会在对话里说。
    const [label, tone] = QA_VERDICT[r.verdict] || ['', ''];
    box.innerHTML = `<section class="qa">
      <div class="qa-h"><b class="qa-verdict ${tone}">${label}</b><span class="num">${r.total}/15</span><small>评于 ${day(r.generated_at)}${r.guide === 'rubric' ? ' · 没找到你的 skill 文件，用的是简版标准' : ''}</small><span class="spacer"></span><button class="linklike" type="button" id="qaFold">${VD.qaOpen ? '收起' : '评估'}</button>${again}</div>
      ${VD.qaOpen ? `<div class="qa-grid">${QA_POINTS.map(([k, name]) => {
        const p = r[k];
        return `<div class="qa-pt ${p.score <= 2 ? 'low' : ''}">
          <div class="qa-top"><span>${name}</span><b class="num">${p.score}</b></div>
          <div class="qa-bar" aria-hidden="true">${[1, 2, 3, 4, 5].map((i) => `<i class="${i <= p.score ? 'on' : ''}"></i>`).join('')}</div>
          <p>${esc(p.reason)}</p>${p.evidence ? `<blockquote>${esc(p.evidence)}</blockquote>` : ''}
        </div>`;
      }).join('')}</div>` : ''}
    </section>`;
    const fold = $('#qaFold', box);
    if (fold) fold.onclick = () => { VD.qaOpen = !VD.qaOpen; renderQA(topic, box); };
  }
  $$('[data-qa-run]', box).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try { const res = await api(`/api/topics/${topic.id}/qa`, { method: 'POST' }); toast(res.message); setTimeout(() => renderQA(topic, box), 400); } catch (err) { toast(err.message); b.disabled = false; }
  }));
}

/* Document drafts are local to topic + kind, including empty strings and edits made during a save. */
VD.documents = {};
function workDocument(id, kind) {
  const docs = VD.documents[id] || (VD.documents[id] = {});
  return docs[kind] || (docs[kind] = { data: null, draft: undefined, revision: 0, mode: 'preview', saving: false, error: '', request: 0, generation: 0 });
}
function workDocumentText(doc) { return doc.draft !== undefined ? doc.draft : doc.data?.markdown || ''; }
function editWorkDocument(id, kind, text) {
  const doc = workDocument(id, kind);
  doc.revision++; doc.draft = text === (doc.data?.markdown || '') ? undefined : text; doc.error = ''; doc.saved = false;
}
function workDocumentStatus(doc) {
  return doc.error ? `保存失败：${doc.error}。草稿已保留，可重试。` : doc.saving ? '保存中…可继续编辑' : doc.draft !== undefined ? '未保存 · 切页后草稿仍保留' : doc.saved ? '已保存' : '已读取保存的内容';
}
const workDocumentActive = (id, kind, el) => el.isConnected && S.view === 'work' && S.workId === id && VD.topicId === id && VD.tab === kind;
async function saveWorkDocument(id, kind) {
  const doc = workDocument(id, kind);
  if (doc.saving) return false;
  const revision = doc.revision, markdown = workDocumentText(doc);
  doc.saving = true; doc.error = ''; doc.generation++;
  try {
    const result = await api(`/api/topics/${id}/${kind}`, { method: 'PUT', body: { markdown } });
    const currentText = workDocumentText(doc);
    doc.data = { ...doc.data, ...(kind === 'outline' ? result : result.coupon || {}), markdown };
    // A successful response only acknowledges the revision that was sent.
    if (doc.revision === revision) { doc.draft = undefined; doc.saved = true; }
    else doc.draft = currentText === markdown ? undefined : currentText;
    return true;
  } catch (err) { doc.error = err.message; return false; }
  finally { doc.saving = false; }
}
function refreshWorkDocument(id, kind, el) {
  if (!workDocumentActive(id, kind, el)) return;
  VD.forceRender = true; renderView();
}
function drawWorkDocument(topic, kind, el, extra = {}) {
  const doc = workDocument(topic.id, kind), text = workDocumentText(doc), outline = kind === 'outline';
  el.innerHTML = `${outline && featureOn('qa') ? '<div id="qaBox"></div>' : ''}${extra.error ? `<p class="journey-save-state bad" role="alert">${esc(extra.error)}${extra.retry ? ' <button class="btn small" type="button" data-document-retry>重试读取</button>' : ''}</p>` : ''}<div class="art-head"><small>${outline ? '骨架' : '付息稿'} · 最后修改 ${day(doc.data?.updated_at)}</small>
    <div class="seg-toggle" role="group" aria-label="阅读或编辑"><button type="button" class="${doc.mode === 'preview' ? 'on' : ''}" data-document-mode="preview">预览</button><button type="button" class="${doc.mode === 'edit' ? 'on' : ''}" data-document-mode="edit">编辑</button></div></div>
    <p class="journey-save-state${doc.error ? ' bad' : ''}" role="status" aria-live="polite" data-document-status>${esc(workDocumentStatus(doc))}</p>
    ${doc.mode === 'edit' ? `<textarea class="big-text" id="${outline ? 'outlineText' : 'cpnText'}" aria-label="${outline ? '骨架' : '密度'}正文" spellcheck="false">${esc(text)}</textarea>` : `<article class="md art-md">${renderMarkdown(text)}</article>`}
    <div class="art-foot">${doc.mode === 'edit' || doc.draft !== undefined ? `<button class="btn primary" type="button" data-document-save${doc.saving ? ' disabled' : ''}>保存${outline ? '骨架' : '密度'}</button>` : ''}
      <button class="btn" type="button" data-document-copy>复制</button>
      <button class="btn" type="button" ${outline ? `data-outline="${topic.id}"` : 'data-coupon-redo'}${doc.saving || doc.draft !== undefined ? ' disabled title="先保存当前草稿，再重写"' : ''}>重写</button></div>${outline ? '<div id="proofBox"></div>' : ''}`;
  const retry = $('[data-document-retry]', el);
  if (retry && extra.retry) retry.onclick = extra.retry;
  const status = $('[data-document-status]', el);
  const updateStatus = () => { status.textContent = workDocumentStatus(doc); status.className = `journey-save-state${doc.error ? ' bad' : ''}`; };
  const input = $('textarea', el);
  if (input) input.oninput = () => { editWorkDocument(topic.id, kind, input.value); updateStatus(); const redo = $('[data-outline], [data-coupon-redo]', el); if (redo) redo.disabled = doc.draft !== undefined || doc.saving; };
  $$('[data-document-mode]', el).forEach((button) => { button.onclick = () => { doc.mode = button.dataset.documentMode; refreshWorkDocument(topic.id, kind, el); }; });
  const save = $('[data-document-save]', el);
  if (save) save.onclick = async () => {
    const pending = saveWorkDocument(topic.id, kind); save.disabled = true; updateStatus();
    await pending;
    if (workDocumentActive(topic.id, kind, el)) { updateStatus(); save.disabled = false; refreshWorkDocument(topic.id, kind, el); }
  };
  $('[data-document-copy]', el).onclick = () => navigator.clipboard.writeText(workDocumentText(doc)).then(() => toast('已复制'), () => toast('复制失败'));
  if (outline) {
    bindOutlineButtons(el); renderQA(topic, $('#qaBox', el));
    if (window.renderProof && featureOn('proof')) renderProof(topic, $('#proofBox', el));
  } else $('[data-coupon-redo]', el).onclick = extra.redo;
}

function workDocumentReadError(topic, kind, el, message, retry, redo) {
  const doc = workDocument(topic.id, kind);
  const error = `读取最新${kind === 'outline' ? '骨架' : '密度'}失败：${message}。${doc.data || doc.draft !== undefined ? '当前内容和草稿已保留。' : ''}`;
  if (doc.data || doc.draft !== undefined) drawWorkDocument(topic, kind, el, { error, retry, redo });
  else {
    el.innerHTML = `<div class="empty" role="alert"><b>${esc(error)}</b><button class="btn" type="button" data-document-retry>重试读取</button></div>`;
    $('[data-document-retry]', el).onclick = retry;
  }
}

window.VIDEO_TABS.push({
  key: 'outline', label: '骨架', badge: (t) => t.outline_state === 'running' ? '生成中' : t.outline_path ? '已写' : '',
  async render(topic, el) {
    const doc = workDocument(topic.id, 'outline');
    clearTimeout(VD.outlinePoll);
    if (topic.outline_state === 'running') {
      if (doc.draft === undefined) {
      el.innerHTML = `<div class="empty"><span class="spin"></span><b>正在写《${esc(topic.title)}》的骨架</b><span>一般 1–2 分钟。</span></div>`;
      doc.data = null; VD.outline = null;
      VD.outlinePoll = setTimeout(() => { if (workDocumentActive(topic.id, 'outline', el)) { window.invalidateWork(); renderView(); } }, 4000); return;
      }
    }
    if (!topic.outline_path && doc.draft === undefined) {
      el.innerHTML = `<div class="empty"><b>还没有骨架</b>${topic.outline_state === 'failed' ? `<span class="bad">${esc(topic.outline_error || '')}</span>` : ''}<span>从你的原话整理开头候选、论点与证据，再收一句判断。</span>
        ${topic.memo ? `<pre class="memo">${esc(topic.memo)}</pre>` : ''}<label class="landing"><span>落点（可选）：这集承接的案例或入口</span><input id="landingIn" value="${esc(landingOf(topic.memo))}" placeholder="没有就留空"></label>
        <div class="track-pick"><button class="btn primary" type="button" data-outline="${topic.id}">${BOOKEND_LABEL}</button></div></div>`;
      bindOutlineButtons(el); return;
    }
    // Revalidate on each actual document render, including return after a background rewrite.
    // Keeping the baseline is useful for drafts, but it must never suppress reading a newer file.
    const request = ++doc.request, generation = doc.generation;
    try {
      const data = await api(`/api/topics/${topic.id}/outline`);
      if (request !== doc.request) return;
      if (generation === doc.generation && !doc.saving) doc.data = data;
    } catch (err) {
      if (request === doc.request && workDocumentActive(topic.id, 'outline', el)) workDocumentReadError(topic, 'outline', el, err.message, () => this.render(topic, el));
      return;
    }
    if (!workDocumentActive(topic.id, 'outline', el)) return;
    VD.outline = { ...doc.data, topic_id: topic.id };
    drawWorkDocument(topic, 'outline', el);
  },
});

const CPN = { data: null, poll: null };
window.VIDEO_TABS.push({
  key: 'coupon', label: '密度', badge: (t) => workDocument(t.id, 'coupon').data ? '已写' : '',
  async render(topic, el) {
    const doc = workDocument(topic.id, 'coupon');
    const start = async (event) => {
      if (doc.draft !== undefined || doc.saving) return;
      if (doc.data && !confirm('重写会覆盖现在的密度，继续吗？')) return;
      event.target.disabled = true;
      try { const result = await api(`/api/topics/${topic.id}/coupon`, { method: 'POST' }); toast(result.message); } catch (err) { toast(err.message); }
      refreshWorkDocument(topic.id, 'coupon', el);
    };
    let data;
    const request = ++doc.request, generation = doc.generation;
    try { data = await api(`/api/topics/${topic.id}/coupon`); }
    catch (err) {
      if (request === doc.request && workDocumentActive(topic.id, 'coupon', el)) workDocumentReadError(topic, 'coupon', el, err.message, () => this.render(topic, el), start);
      return;
    }
    if (request !== doc.request || !workDocumentActive(topic.id, 'coupon', el)) return;
    CPN.data = { ...data, topic_id: topic.id }; clearTimeout(CPN.poll);
    if (data.coupon && !doc.saving && generation === doc.generation) doc.data = data.coupon;
    if (data.running && doc.draft === undefined) {
      el.innerHTML = '<div class="empty"><span class="spin"></span><b>正在按密度把骨架排成口播节奏</b><span>一般 1–3 分钟。</span></div>';
      CPN.poll = setTimeout(() => refreshWorkDocument(topic.id, 'coupon', el), 5000); return;
    }
    if (!doc.data && doc.draft === undefined) {
      el.innerHTML = `<div class="empty"><b>还没有密度</b>${data.error ? `<span class="bad">${esc(data.error)}</span>` : ''}<span>按骨架整理口播节奏：开头说清收获，正文持续给出判断和证据，结尾回应开头。</span>${topic.outline_path ? '<button class="btn primary" type="button" data-coupon-start>排密度</button>' : '<span>先写骨架。</span>'}</div>`;
      const button = $('[data-coupon-start]', el); if (button) button.onclick = start; return;
    }
    drawWorkDocument(topic, 'coupon', el, { redo: start, error: data.error ? `上一次重写未完成：${data.error}` : '' });
  },
});

// 研习室文章 9/29 搬去「03 打包」了：加工中只管骨架和剪辑
const TAB_ORDER = ['speak', 'outline', 'coupon', 'script', 'review', 'edit'];  // 视频页只显示这几个页签，按这个顺序（10/2 加了付息稿；10/4 复刻 / 借结构的第一步「你说一遍」）
// 10/20：页面里的 1-2-3 步骤条拿掉了，左栏「写 剪 发」就是它（board.js paintRailStages）
VD.tabs = {};
function selectWorkTab(tab) { VD.tab = tab; VD.tabs[VD.topicId] = tab; VD.forceRender = true; renderView(); }
const WK = { topics: null, at: 0 };

window.invalidateWork = () => { WK.topics = null; const body = $('#videoBody'); if (body) body.dataset.sig = ''; };


window.VIEWS.work = {
  async render() {
    const root = $('#workBody');
    if (VD.topicId === S.workId && VD.tab === 'speak' && VD.dirty) return;
    const topicId = S.workId, request = VD.renderRequest = (VD.renderRequest || 0) + 1;
    if (VD.topicId !== topicId) { VD.topicId = topicId; VD.outline = null; VD.dirty = false; VD.tab = VD.tabs[topicId] || 'outline'; VD.fresh = !VD.tabs[topicId]; }
    let wantWrite = false;
    if (VD.requested?.id === topicId) { if (VD.requested.tab === 'write') { wantWrite = true; VD.fresh = false; } else if (VD.requested.tab) { VD.tab = VD.requested.tab; VD.fresh = false; } VD.requested = null; }
    try {
      if (!WK.topics || Date.now() - WK.at > 5000) {
        WK.topics = await api('/api/topics?archived=true');
        WK.at = Date.now();
      }
      if (typeof BD !== 'undefined' && !BD.data) await loadBoard(false);
    } catch (err) { if (request === VD.renderRequest && S.view === 'work') root.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    if (request !== VD.renderRequest || S.view !== 'work' || S.workId !== topicId) return;
    const topic = WK.topics.find((t) => t.id === topicId);
    if (!topic) { root.innerHTML = '<div class="panel empty"><b>找不到这条视频</b><button class="btn" type="button" onclick="go(\'board\')">回到看板</button></div>'; return; }
    const card = BD.data && BD.data.cards.find((c) => c.id === topic.id);
    const stage = (topic.published_video_id || topic.closed_at) ? 'shipped' : card ? card.stage : 'outline';
    const tabs = window.VIDEO_TABS.filter((x) => TAB_ORDER.includes(x.key) && (x.key !== 'coupon' || featureOn('coupon')) && (!x.show || x.show(topic))).sort((a, b) => TAB_ORDER.indexOf(a.key) - TAB_ORDER.indexOf(b.key));
    // 10/13 作者：口述完（或本来就是自己的话）走同一条线：只走 park-writing 第一轮，页签只剩「口播稿」。
    // 骨架、密度是工作台自己的老提示词，装了 park-writing 的机器上不再出现；没装的机器（试用版）照老的走。
    const own = tabs.some((x) => x.key === 'script');
    if (own) {
      if (!VD.tabs[topicId] && VD.tab === 'outline') VD.tab = 'script';
      for (let k = tabs.length - 1; k >= 0; k--) if (['outline', 'coupon'].includes(tabs[k].key)) tabs.splice(k, 1);
      tabs.sort((a, b) => (a.key === 'script' ? -1 : b.key === 'script' ? 1 : 0));
    }
    // 10/19 作者：已经到录制与剪辑的这一条，打开就落在剪辑上（他自己点过别的页签就照他点的）
    if (VD.fresh && ['record', 'edit'].includes(stage) && tabs.some((x) => x.key === 'edit')) { VD.fresh = false; VD.tab = 'edit'; }
    // 复刻 / 借结构还没说过：一进来就落在「你说一遍」
    if (VD.fresh) { VD.fresh = false; if (topic.replicate && topic.replicate.mode && !topic.replicate.note_path && !topic.outline_path) VD.tab = 'speak'; }
    // 10/20：拍后批注不是「写」的一部分（拍完才有），收在「剪」页底下
    const reviewTab = tabs.find((x) => x.key === 'review');
    for (let k = tabs.length - 1; k >= 0; k--) if (tabs[k].key === 'review') tabs.splice(k, 1);
    if (wantWrite || VD.tab === 'review') VD.tab = own ? 'script' : 'outline';
    if (!tabs.some((x) => x.key === VD.tab)) VD.tab = own ? 'script' : 'outline';
    VD.tabs[topicId] = VD.tab;
    if (typeof paintChrome === 'function') paintChrome('work');  // 左栏亮「写」还是「剪」看这一下定的页签
    let body = $('#videoBody');
    const sig = JSON.stringify([VD.topicId, VD.tab, VD.mode, topic.replicate && [topic.replicate.mode, topic.replicate.note_path], VD.outline && VD.outline.updated_at, stage, card && card.next.text, topic.outline_state, Boolean(topic.outline_path), topic.video_project, topic.status, topic.published_video_id, topic.write_state, Boolean(topic.article_path), topic.archived_at, own, topic.content_mode && topic.content_mode.mode]);
    if (body && body.dataset.sig === sig && !VD.forceRender) return;
    VD.forceRender = false;
    const selectedStep = VD.tab === 'edit' ? 'edit' : 'outline';
    const prepareTabs = tabs.filter((tab) => tab.key !== 'edit');
    // 10/20 作者 走查：左栏就是步骤条（找 写 剪 发 盘），页面里不再有 1-2-3；页头一个字说这是哪一步。
    // 「准备内容」那个点不动的字、机器剪辑的步骤名（「Hook 拼接与字幕」）都不再出现在写页上。
    const writing = selectedStep !== 'edit';
    const nextLine = writing && card && ['outline'].includes(card.stage) ? (own && card.next.text === '写拍摄提纲' ? '准备稿子：用你的原话' : card.next.text) : '';
    root.innerHTML = `<header class="work-h zx-h">
        <div class="work-title"><div><div class="stage-eyebrow">${writing ? '写 · 口播稿' : '剪 · 成片'}</div><h1>${esc(topic.title)}</h1></div>
          <div class="work-acts">${topic.archived_at ? '<span class="chip-state">已归档</span>' : '<button class="btn small ghost" type="button" id="workArchive">不做了</button>'}</div></div>
        ${nextLine ? `<p class="work-next ${card.next.mine ? 'mine' : ''}"><i></i>${esc(nextLine)}</p>` : ''}
      </header>
      <div class="panel work-main" id="videoBody">
        ${writing && prepareTabs.length > 1 ? `<div class="video-tabs" role="tablist" aria-label="写">${prepareTabs.map((tab) => `<button type="button" role="tab" aria-selected="${VD.tab === tab.key}" class="${VD.tab === tab.key ? 'on' : ''}" data-vtab="${tab.key}">${tab.label}${tab.badge(topic) ? `<small>${esc(tab.badge(topic))}</small>` : ''}</button>`).join('')}</div>` : ''}
        <div id="videoTab"></div>
        ${!writing && reviewTab ? '<details class="vp-fold cut-review" id="cutReview"><summary>拍后批注<span class="spacer"></span><small>按 9 项给拍完的成片打分，下一条要注意的</small></summary><div id="cutReviewBody"></div></details>' : ''}
      </div>`;
    body = $('#videoBody');
    body.dataset.sig = sig;
    const rvFold = $('#cutReview', root);
    if (rvFold) rvFold.ontoggle = () => { if (rvFold.open && !rvFold.dataset.done) { rvFold.dataset.done = '1'; reviewTab.render(topic, $('#cutReviewBody', root)); } };
    $$('[data-vtab]', root).forEach((button) => { button.onclick = () => selectWorkTab(button.dataset.vtab); });
    const archive = $('#workArchive');
    if (archive) archive.onclick = async () => {
      if (!confirm(`不做《${topic.title}》了？会从看板拿掉，笔记和文件都不删。`)) return;
      await window.patchTopic(topic.id, { archived: true }, '已从看板拿掉');
      go('input');
    };
    const tab = tabs.find((x) => x.key === VD.tab) || tabs[0]; await tab.render(topic, $('#videoTab'));
  },
};
