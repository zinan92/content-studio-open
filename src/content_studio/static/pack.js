'use strict';
/* 03 打包：发之前把一条内容要的东西全备好，发布台那边就只剩一个个平台点出去。

   10/2 作者：「真正需要我 input 的就是标题……封面、插图、排版我都不需要审核。」
   「把它当成一个成熟的 SaaS：用户一看就知道点哪里，思考负担降到最低，而且要有视觉焦点。」

   所以这一页只有三段，任何时候只有一个主按钮：
     ① 定标题 —— 机器先出一批候选，点一条或自己写，点「用这个标题，开始准备」。
     ② 自动准备 —— 封面、X 图文、插图、公众号排版（小红书选了图文还有小红书图文）一步接一步做完、
        自动定稿（服务端 pack_auto.py，关了页面也接着做）。每一行能展开看、能改；失败了只给一个「重试」。
     ③ 发出去 —— 全好了才亮：还没发抖音就先发抖音、对上作品；发了就直接打开补发工作台挑其余平台。
   描述和话题已经自动填好，收在最下面，想改再打开。
   不再列别的视频（9/29 版顶上那排《为什么AI重度用户全体考公》这类，10/2 作者：分心）。 */
window.VIEWS = window.VIEWS || {};

const PK = { data: null, topic: null, view: null, at: 0, timer: null, editTitle: false, titlesAsked: new Set(), open: new Set(), request: 0, renderRequest: 0, formsOpen: false };

async function loadPack(force) {
  if (!force && PK.data && (!S.packId || (PK.data.topic && PK.data.topic.id === S.packId)) && Date.now() - PK.at < 15000) return PK.data;
  const id = S.packId, request = ++PK.request;
  const d = await api('/api/publish/desk' + (id ? `?topic_id=${id}` : ''));
  let view = null, topic = null;
  if (d.topic) {
    const result = await Promise.all([api(`/api/topics/${d.topic.id}/pack`), api('/api/topics')]);
    view = result[0]; topic = result[1].find((x) => x.id === d.topic.id) || null;
  }
  if (request === PK.request && S.packId === id) {
    PK.data = d; PK.at = Date.now(); PK.view = view; PK.topic = topic;
    if (d.topic) S.packId = d.topic.id;
  }
  return d;
}
const packActive = (id, box) => S.view === 'pack' && S.packId === id && (!box || box.isConnected !== false);

window.invalidatePack = () => { PK.data = null; PK.at = 0; const b = $('#packBody'); if (b) b.dataset.sig = ''; };

const locked = (d, key) => { const a = ((d && d.approvals) || {})[key]; return Boolean(a && a.approved && a.valid); };
window.packLocked = locked;

/* 子块（配图、排版、小红书）自己在轮询：它们一变，这里重新问一次自动档 */
window.prepTick = () => { if (S.view === 'pack' && PK.view && PK.view.busy) schedule(1500); };
window.rerenderPackRow = (key) => { const box = $(`#pkd-${key}`); if (box && S.view === 'pack') { delete box.dataset.done; renderDetail(key, box); } };


function schedule(ms) {
  clearTimeout(PK.timer);
  PK.timer = setTimeout(tick, ms);
}

/* 自动档往下走一步（POST：会启动下一步），再画进度 */
async function tick() {
  const d = PK.data;
  if (!d || !d.topic || S.view !== 'pack') return;
  let v;
  try { v = await api(`/api/topics/${d.topic.id}/pack/advance`, { method: 'POST' }); } catch (_) { schedule(8000); return; }
  if (!packActive(d.topic.id) || PK.data !== d) return;
  const changed = JSON.stringify(v.steps) !== JSON.stringify((PK.view || {}).steps);
  PK.view = v;
  if (changed) {
    // 有一步做好了：交付包（封面地址、定稿状态）也变了
    try { const fresh = await api(`/api/publish/desk?topic_id=${d.topic.id}`); Object.assign(d, { approvals: fresh.approvals, release: fresh.release, has_article: fresh.has_article, article: fresh.article }); } catch (_) { /* 下次 */ }
    if (!packActive(d.topic.id) || PK.data !== d) return;
    paintSteps();
    paintCta();
    if (window.invalidatePublish) window.invalidatePublish();
  }
  paintCta();
  if (v.busy) schedule(6000);
}

/* ---------- ① 定标题 ---------- */
function titleCard(d, v) {
  const done = v.armed && !PK.editTitle;
  if (done) {
    return `<section class="pk2-card pk2-done" id="pkTitle">
      <div class="pk2-step"><i>✓</i><span>标题</span></div>
      <div class="pk2-title-show"><b>${esc(v.title)}</b><button class="linklike" type="button" id="pkEditTitle">改标题</button></div>
      ${productBlock()}
      ${formsBlock()}
    </section>`;
  }
  const current = v.title || (d.entry && d.entry.title) || '';
  return `<section class="pk2-card pk2-focus" id="pkTitle">
    <div class="pk2-step"><i>1</i><span>定标题</span><small>封面上的字也是它。下面是机器按你的「标题」工作流出的候选，点一条，或者直接写。</small></div>
    <input class="pk2-input" id="pkTitleInput" value="${esc(current)}" placeholder="${esc(d.topic.title)}" autocomplete="off" maxlength="100">
    ${productBlock()}
    ${formsBlock()}
    <div class="pk2-go">
      <button class="btn primary big" type="button" id="pkGo">用这个标题，开始准备</button>
      <small>${v.armed ? '换了标题，封面会按新标题重出；文章、插图不受影响。' : `只做上面勾了的要用到的：发视频要封面，发文章要文章${featureOn('figs') ? '和插图' : ''}${platformOff('wechat_mp') ? '' : '，公众号还要排版'}。不用你一步步定稿，可以先去做别的。`}</small>
    </div>
    <div class="pk2-cands" id="pkCands"><p class="pk2-muted"><span class="spin"></span> 正在出候选标题，半分钟左右…</p></div>
  </section>`;
}

/* 带哪个产品（10/9 变现流程板，#590）：选了的，发出去时描述最后一行自动放这个产品的私信关键词（抖音、视频号、小红书）
   或落地页（其余平台），在产品页填；没填的平台什么都不加。产品页「流量入口」照这里列内容。 */
function productBlock() {
  return featureOn('products') ? '<div class="pk2-product" id="pkProduct"><span class="spin"></span></div>' : '';
}

async function paintProduct(topicId) {
  const box = $('#pkProduct');
  if (!box || !packActive(topicId, box)) return;
  let p;
  try { p = await api(`/api/topics/${topicId}/product`); } catch (err) { box.innerHTML = `<span class="pk2-muted bad">${esc(err.message)}</span>`; return; }
  if (!packActive(topicId, box)) return;
  const chip = (key, label) => `<button type="button" class="tk ${(p.product || '') === key ? 'on' : ''}" aria-pressed="${(p.product || '') === key}" data-pd-tag="${key}"><i>${(p.product || '') === key ? '✓' : ''}</i>${esc(label)}</button>`;
  box.innerHTML = `<b>带哪个产品</b><span class="pp-ticks">${chip('', '不带')}${p.products.map((r) => chip(r.key, r.name)).join('')}</span>
    <small>${p.product ? '描述最后会加一行它的私信关键词或落地页（在产品页填）' : '不带就不加'}</small>`;
  $$('[data-pd-tag]', box).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try { await api(`/api/topics/${topicId}/product`, { method: 'PUT', body: { product: b.dataset.pdTag || null } }); } catch (err) { toast(err.message); b.disabled = false; return; }
    if (window.invalidatePublish) window.invalidatePublish();
    paintProduct(topicId);
  }));
}

/* 发到哪、发什么（10/7 作者）：这一条唯一定格式的地方。勾了才做、才进那个平台的「待发」；
   一个平台一格都不勾 = 这条不发它。改了马上让自动档补做新要的，不要的那一步就从②里消失。 */
function formsBlock() {
  return `<details class="pk2-forms publication-forms" id="pkFormsFold" ${PK.formsOpen ? 'open' : ''}><summary>调整发布形式</summary><div class="pk2-forms-h"><small>勾了才做、才进那个平台的「待发」；一格都不勾就是这条不发它</small></div><div id="pkForms"><span class="spin"></span></div></details>`;
}

async function paintForms(topicId) {
  const box = $('#pkForms');
  if (!box || !packActive(topicId, box)) return;
  let f;
  try { f = await api(`/api/topics/${topicId}/forms`); } catch (err) { box.innerHTML = `<span class="pk2-muted bad">${esc(err.message)}</span>`; return; }
  if (!packActive(topicId, box)) return;
  box.innerHTML = `<div class="pk2-ftable">${f.platforms.map((p) => `<div class="pk2-frow ${p.forms.length ? '' : 'off'}"><b>${esc(p.label)}</b>
      <span class="pp-ticks">${p.choices.map((c) => `<button type="button" class="tk ${p.forms.includes(c.key) ? 'on' : ''}" aria-pressed="${p.forms.includes(c.key)}" data-fp="${p.key}" data-form="${c.key}"><i>${p.forms.includes(c.key) ? '✓' : ''}</i>${esc(c.label)}</button>`).join('')}</span>
      ${p.forms.length ? '' : '<small>这条不发</small>'}</div>`).join('')}</div>`;
  $$('[data-fp]', box).forEach((b) => (b.onclick = async () => {
    const p = f.platforms.find((x) => x.key === b.dataset.fp);
    const next = p.forms.includes(b.dataset.form) ? p.forms.filter((x) => x !== b.dataset.form) : [...p.forms, b.dataset.form];
    // 按能选的顺序存（视频在前），平台页、③ 的顺序就稳定
    const ordered = p.choices.map((c) => c.key).filter((k) => next.includes(k));
    b.disabled = true;
    try {
      await api(`/api/topics/${topicId}/forms`, { method: 'PUT', body: { forms: { [p.key]: ordered } } });
      if (window.invalidatePublish) window.invalidatePublish();
      await paintForms(topicId);
      if (!packActive(topicId, box)) return;
      // 开始准备了就让自动档补做新要的；还没开始只看一眼（GET 不启动任务），②跟着勾的变
      const view = PK.view && PK.view.armed ? await api(`/api/topics/${topicId}/pack/advance`, { method: 'POST' }) : await api(`/api/topics/${topicId}/pack`);
      if (!packActive(topicId, box)) return;
      PK.view = view; refreshSteps();
    } catch (err) { toast(err.message); b.disabled = false; }
  }));
}

async function paintCands(topicId) {
  const box = $('#pkCands');
  if (!box || !packActive(topicId, box)) return;
  let t;
  try { t = await api(`/api/topics/${topicId}/titles`); } catch (_) { box.innerHTML = ''; return; }
  if (!packActive(topicId, box)) return;
  // 打开页面没有候选就出一批（便宜，半分钟；是他唯一要填的那一格）。同一条只自动出一次。
  if (!t.result && !t.running && !t.error && !PK.titlesAsked.has(topicId)) {
    PK.titlesAsked.add(topicId);
    try { await api(`/api/topics/${topicId}/titles`, { method: 'POST' }); t = { running: true }; } catch (_) { /* 退回手写 */ }
  }
  if (!document.body.contains(box) || !packActive(topicId, box)) return;
  if (t.running) { box.innerHTML = '<p class="pk2-muted"><span class="spin"></span> 正在出候选标题，半分钟左右…</p>'; setTimeout(() => paintCands(topicId), 3000); return; }
  if (t.error || !t.result) { box.innerHTML = t.error ? `<p class="pk2-muted bad">候选没出来：${esc(t.error)}。直接在上面写也行。</p>` : ''; return; }
  const input = $('#pkTitleInput');
  const SHOW = 5;
  const cands = t.result.candidates;
  box.innerHTML = `<div class="pk2-cands-h">或者从候选里挑一条<small>点一下就填进上面</small></div>
    ${cands.map((c, i) => `<button type="button" class="pk2-cand ${input && input.value === c.title ? 'on' : ''}" data-cand="${i}" ${i >= SHOW ? 'hidden' : ''}>
      <b>${esc(c.title)}</b><small>${esc(c.pattern)}${c.over ? ` · ${c.title.length} 字，抖音会裁` : ''}</small></button>`).join('')}
    <div class="pk2-cands-f">${cands.length > SHOW ? `<button type="button" class="linklike" id="pkAll">再看 ${cands.length - SHOW} 条</button>` : ''}<button type="button" class="linklike" id="pkMore">换一批</button></div>`;
  const all = $('#pkAll', box);
  if (all) all.onclick = () => { $$('[data-cand][hidden]', box).forEach((b) => { b.hidden = false; }); all.remove(); };
  $$('[data-cand]', box).forEach((b) => (b.onclick = () => {
    input.value = t.result.candidates[Number(b.dataset.cand)].title;
    $$('[data-cand]', box).forEach((x) => x.classList.toggle('on', x === b));
    input.focus();
    input.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }));
  $('#pkMore', box).onclick = async () => {
    try { await api(`/api/topics/${topicId}/titles`, { method: 'POST' }); } catch (err) { toast(err.message); return; }
    box.innerHTML = '<p class="pk2-muted"><span class="spin"></span> 正在出新一批…</p>';
    setTimeout(() => paintCands(topicId), 3000);
  };
}

async function packGo(topicId) {
  const input = $('#pkTitleInput');
  const title = input ? input.value.trim() : '';
  if (!title) { toast('先写标题'); if (input) input.focus(); return; }
  const btn = $('#pkGo'); if (btn) { btn.disabled = true; btn.textContent = '开始了…'; }
  try {
    const view = await api(`/api/topics/${topicId}/pack/go`, { method: 'POST', body: { title } });
    if (!packActive(topicId)) return;
    PK.view = view;
  } catch (err) { toast(err.message); if (btn) { btn.disabled = false; btn.textContent = '用这个标题，开始准备'; } return; }
  PK.editTitle = false;
  if (input) input.blur();  // 输入框有焦点时页面不重画（防打字被冲掉），这里要让它画
  toast('开始准备了：封面、文章、插图、排版会一步接一步做完');
  refreshPack();
}

/* ---------- ② 自动准备 ---------- */
const STEP_ICON = { done: '✓', running: '', waiting: '·', error: '!', idle: '○' };

function stepsCard(v) {
  const rows = v.steps || [];
  const n = rows.filter((r) => r.state === 'done').length;
  return `<section class="pk2-card ${v.armed && !v.ready ? 'pk2-focus soft' : ''} ${v.armed ? '' : 'pk2-dim'}" id="pkSteps">
    <div class="pk2-step"><i class="${v.ready ? 'is-done' : ''}">${v.ready ? '✓' : '2'}</i><span>自动准备</span><small id="pkCount">${v.armed ? `${n} / ${rows.length} 好了` : '定了标题就开始'}</small></div>
    <div class="pk2-list" id="pkList">${rows.map(stepRow).join('')}</div>
  </section>`;
}

function stepRow(r) {
  const icon = r.state === 'running' ? '<span class="spin"></span>' : STEP_ICON[r.state];
  const canOpen = r.state === 'done' || r.state === 'error';
  return `<details class="pk2-row s-${r.state}" data-row="${r.key}" ${PK.open.has(r.key) ? 'open' : ''}>
    <summary><i class="pk2-dot">${icon}</i><b>${esc(r.label)}</b><span class="pk2-note">${esc(r.note)}</span>
      ${r.state === 'error' ? `<button class="btn small" type="button" data-retry="${r.key}">重试</button>` : canOpen ? '<span class="pk2-open">查看 / 改</span>' : ''}</summary>
    <div class="pk2-detail" id="pkd-${r.key}"></div>
  </details>`;
}

function paintSteps() {
  const v = PK.view;
  const list = $('#pkList');
  if (!v || !list) return;
  const rows = v.steps || [];
  rows.forEach((r) => {
    const det = $(`.pk2-row[data-row="${r.key}"]`, list);
    if (!det) return;
    if (det.className !== `pk2-row s-${r.state}` || $('.pk2-note', det).textContent !== r.note) {
      const fresh = document.createElement('div');
      fresh.innerHTML = stepRow(r);
      const row = fresh.firstElementChild;
      det.replaceWith(row);
      wireRow(row);
    }
  });
  const count = $('#pkCount');
  if (count) count.textContent = v.armed ? `${rows.filter((r) => r.state === 'done').length} / ${rows.length} 好了` : '定了标题就开始';
  const card = $('#pkSteps');
  if (card) card.classList.toggle('pk2-focus', v.armed && !v.ready);
}

function wireRow(det) {
  const key = det.dataset.row;
  const retry = $('[data-retry]', det);
  if (retry) retry.onclick = async (e) => {
    e.preventDefault();
    retry.disabled = true;
    try { PK.view = await api(`/api/topics/${PK.data.topic.id}/pack/retry`, { method: 'POST', body: { key } }); } catch (err) { toast(err.message); }
    paintSteps(); paintCta(); schedule(4000);
  };
  det.addEventListener('toggle', () => {
    if (det.open) { PK.open.add(key); renderDetail(key, $('.pk2-detail', det)); } else PK.open.delete(key);
  });
  if (det.open) renderDetail(key, $('.pk2-detail', det));
}

/* 每一行展开后：看产物、想改就改（改了自动档会重新定稿） */
function renderDetail(key, box) {
  const d = PK.data;
  if (!d || !d.topic || !box || box.dataset.done) return;
  const t = { ...d.topic, ...(PK.topic || {}) };
  box.dataset.done = '1';
  const id = d.topic.id;
  if (key === 'cover') {
    const urls = (d.release && d.release.cover_urls) || {};
    const shots = [['portrait', '竖版 3:4'], ['landscape', '横版 4:3'], ['wide', '16:9']].filter(([k]) => urls[k]);
    const stamp = Date.now();
    // 10/3：重出时这里还是上一版（旧标题）的封面，作者 以为已经出好了——要说清楚
    const redoing = ((PK.view && PK.view.steps) || []).some((r) => r.key === 'cover' && r.state === 'running');
    box.innerHTML = shots.length
      ? `${redoing ? '<p class="pk2-muted">正在按新标题重出，下面是上一版，出好会自动换上。</p>' : ''}<div class="pk2-covers${redoing ? ' old' : ''}">${shots.map(([k, l]) => `<a href="${urls[k]}" target="_blank" rel="noopener"><img class="${k}" src="${urls[k]}?t=${stamp}" alt="${l}"><small>${l}</small></a>`).join('')}</div>
         <p class="pk2-muted">封面上的字就是标题，想换字就改上面的标题。</p>`
      : '<p class="pk2-muted">还没出好。</p>';
  } else if (key === 'article') {
    const tab = (window.VIDEO_TABS || []).find((x) => x.key === 'article');
    if (!tab) { box.innerHTML = '<p class="pk2-muted">文章在「写」里。</p>'; return; }
    Promise.resolve(tab.render(t, box)).then(() => {
      if (!d.has_article || !document.body.contains(box)) return;
      polishPanel(box, id);
    });
  } else if (key === 'figs') {
    box.innerHTML = '<div id="pdlFigs"></div><div id="pdlEvid" class="ev"></div>';
    renderFigs(box, id); if (featureOn('proof')) renderEvidence(box, id);
  } else if (key === 'wx') {
    box.innerHTML = '<div class="pdl-wx" id="pdlWx"></div>';
    renderWx(box, id);
  } else if (key === 'xhs') {
    box.innerHTML = '<div id="pdlXhs" class="xhs"></div>';
    renderXhs(box, id);
  }
}

/* 润色（10/2 起有这个按钮）。10/13 作者：不再让模型整篇重写——走和口播稿、X 长文同一个批注视图：先打分，
   再在原文上提修改清单，他逐条接受、改一改或不要。原文就是这篇文章（拍了视频的，是照字幕 SRT 整理的他的原话）。 */
const POLISH = { poll: null };
async function polishPanel(box, id) {
  clearTimeout(POLISH.poll);
  let d;
  try { d = await api(`/api/topics/${id}/polish`); } catch (_) { return; }
  if (!document.body.contains(box)) return;
  const old = $('.pk2-polish', box);
  if (old) old.remove();
  if (!d.available || typeof window.openTracked !== 'function') return;
  const how = '先打分，再在你的原文上提修改（只用你的原话，改动不超过预算），你逐条接受、改一改或不要；插图跟着段落走。';
  let inner;
  if (d.running) {
    inner = `<span class="spin"></span><small>在润色：${esc(d.stage || '准备')}。几分钟，好了这里会变成「打开批注视图」。</small>`;
    POLISH.poll = setTimeout(() => polishPanel(box, id), 5000);
  } else if (d.polish) {
    const edits = d.polish.trk.changes.filter((c) => c.op !== 'comment');
    const left = edits.filter((c) => c.status === 'pending').length;
    inner = `<button class="btn small primary" type="button" id="pkPolishOpen">打开批注视图</button>
      <small>润色：改了 ${edits.length} 处，${left ? `待处理 ${left} 处` : '都处理完了'}。文章 = 原文 + 你接受的修改。</small>
      <button class="linklike" type="button" id="pkPolish">重新润色</button>`;
  } else {
    inner = `<button class="btn small" type="button" id="pkPolish">润色</button><small>${how}</small>${d.error ? `<small class="bad" role="alert">上次没做成：${esc(d.error)}</small>` : ''}`;
  }
  box.insertAdjacentHTML('afterbegin', `<div class="pk2-polish">${inner}</div>`);
  const open = $('#pkPolishOpen', box);
  if (open) open.onclick = () => window.openTracked(id, { topic: true, doc: 'polish', post: { id: String(id), text: d.polish.text, trk: d.polish.trk, source_title: d.title || '', _topic: true, _doc: 'polish', summary: false } });
  const go = $('#pkPolish', box);
  if (go) go.onclick = async () => {
    go.disabled = true;
    const start = (force) => api(`/api/topics/${id}/polish`, { method: 'POST', body: { force } });
    try { toast((await start(false)).message); } catch (err) {
      if (!/确定的话再点一次/.test(err.message) || !window.confirm(`${err.message}\n\n继续吗？`)) { toast(err.message); go.disabled = false; return; }
      try { toast((await start(true)).message); } catch (err2) { toast(err2.message); go.disabled = false; return; }
    }
    polishPanel(box, id);
  };
}
// 批注视图里接受了、改了：文章已经变了，这一格重新读
window.onPolishChange = () => {
  if (typeof AR !== 'undefined') AR.draft = null;
  if (window.rerenderPackRow) window.rerenderPackRow('article');
};

/* ---------- ③ 去各平台 ---------- */
function ctaCard(v) {
  return `<section class="pk2-cta" id="pkCta">${ctaInner(v)}</section>`;
}
/* ③ 发（10/20 作者 走查：「发」要有自己的地方）。以前点「放进待发」以后要去六个平台页各找一遍；
   现在这条要发的每个平台 × 形式一行，就在这里：机器能发的点「发」，要你传的备好上传包、传完点「发了」贴链接。
   每行的按钮和平台页「待发」是同一套（platform.js 的 ppFormActions / ppBind）。
   10/13 作者：各项发布不要互为依赖——材料齐的行先能发，没齐的说差什么。 */
const RELEASE = new Map();
function releaseState(id) {
  if (!RELEASE.has(id)) RELEASE.set(id, {busy:false,error:''});
  return RELEASE.get(id);
}
// 各平台的待发（同一份 /api/platform/{key}）：发页按平台取这一条的那几行，旧的没发完的也从这里数
const FA = { id: null, at: 0, data: {}, loading: null };
window.invalidateFa = () => { FA.at = 0; };
async function faLoad(id, keys) {
  if (FA.id === id && Date.now() - FA.at < 8000 && keys.every((k) => FA.data[k])) return FA.data;
  if (FA.loading) return FA.loading;
  FA.loading = (async () => {
    const got = await Promise.all(keys.map((k) => api(`/api/platform/${k}`).then((d) => [k, d && Array.isArray(d.pending) ? d : null], () => [k, null])));
    FA.id = id; FA.at = Date.now(); FA.data = Object.fromEntries(got.filter(([, d]) => d));
    return FA.data;
  })();
  try { return await FA.loading; } finally { FA.loading = null; }
}
function faLaneRow(lane, item, d) {
  const r = item && item.rows.find((x) => x.form === lane.form);
  if (r && d) return ppFormActions(item, r, d);
  const p = lane.presentation || {};
  const url = publicationUrl(p.state === 'published' ? p.url : p.draft_link);
  const link = url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener">${p.state === 'published' ? '回执' : '草稿'} ↗</a>` : '';
  if (p.state === 'published') return `<div class="pp-frow s-sent"><span class="fk">${esc(lane.form_label)}</span><span class="fv"><b class="ok">✓ 发了</b>${link}</span><span class="act"></span></div>`;
  const live = ['draft', 'running', 'awaiting_confirm', 'unknown'].includes(p.state);
  const why = lane.handed || live ? (p.label || '在等发') : lane.ready ? '素材齐了，点上面「开始发」' : (lane.why || p.reason || '素材还没齐');
  return `<div class="pp-frow s-wait"><span class="fk">${esc(lane.form_label)}</span><span class="fv">${esc(why)}${link}</span><span class="act"></span></div>`;
}
function faTable(id, lanes) {
  const keys = [...new Set(lanes.map((lane) => lane.key))];
  return `<div class="fa-table" aria-label="发到哪">${keys.map((k) => {
    const d = FA.id === id ? FA.data[k] : null;
    const item = d && (d.pending || []).find((it) => it.topic_id === id);
    const mine = lanes.filter((lane) => lane.key === k);
    const label = (d && d.label) || mine[0].label;
    return `<div class="fa-plat" data-fa-plat="${esc(k)}"><button class="fa-name linklike" type="button" data-fa-open="${esc(k)}" title="打开${esc(label)}这个平台的页面">${d ? ppPlat(d) : ''}<b>${esc(label)}</b></button>
      <div class="pp-frows">${mine.map((lane) => faLaneRow(lane, item, d)).join('')}</div></div>`;
  }).join('')}</div>`;
}
function faOlder(id) {
  const seen = new Map();
  Object.values(FA.id === id ? FA.data : {}).forEach((d) => (d.pending || []).forEach((it) => { if (it.topic_id !== id && !seen.has(it.topic_id)) seen.set(it.topic_id, it.title); }));
  if (!seen.size) return '';
  return `<details class="fa-older"><summary>还有 ${seen.size} 条旧的没发完</summary>${[...seen].map(([tid, title]) => `<button class="linklike" type="button" data-fa-older="${tid}">${esc(title)}</button>`).join('')}</details>`;
}
function releaseMarkup(id, v) {
  const st = releaseState(id), lanes = v.lanes || [];
  const remaining = lanes.filter((lane) => lane.presentation?.state !== 'published');
  const live = ['draft','running','awaiting_confirm','unknown'];
  const canHand = (lane) => !lane.handed && (lane.ready || live.includes(lane.presentation?.state));
  const handable = remaining.filter(canHand);
  const allPublished = lanes.length && !remaining.length;
  const names = (rows) => [...new Set(rows.map((lane) => lane.label))].join('、');
  const done = lanes.length - remaining.length;
  const count = `<span>发了 ${done} / ${lanes.length}</span>`;
  const head = allPublished ? `<b>都发了</b>${count}`
    : !v.copy_locked ? `<b>先定上面的标题</b><span>标题定了，下面每个平台才能发</span>${count}`
    : handable.length ? `<button class="btn primary" type="button" data-release="${id}"${st.busy ? ' disabled' : ''}>${st.busy ? '在备…' : '开始发'}</button><span>先备好 ${esc(names(handable))} 的上传包和文案；真的发出去要在下面那一行点</span>`
    : `<b>发到 ${new Set(lanes.map((lane) => lane.key)).size} 个平台</b>${count}`;
  // 10/20 走查：「做这条」被锁时提示说「发完点『发布完毕』」，可页面上没有这个按钮。发出去至少一个平台就能结：
  // 这条结了，下一条才能开始；没发的平台以后照样能在复盘那张表里补。都发了就是这一页的主按钮
  const close = done ? `<span class="spacer"></span><button class="btn${allPublished ? ' primary' : ''}" type="button" data-fa-close="${id}" title="这条结了，左栏的写剪发空出来给下一条；没发的平台以后在「盘」那张表里还能补">这条发完了，做下一条</button>` : '';
  return `<section class="release-handoff">
    <div class="release-action">${head}${close}</div>
    ${st.error ? `<p class="bad" role="alert">${esc(st.error)}。可以重试，已有发布记录不会改变。</p>` : ''}
    ${lanes.length ? faTable(id, lanes) : '<p class="pk2-muted">上面「调整发布形式」里还没勾平台。</p>'}
    ${faOlder(id)}
  </section>`;
}
function wireRelease(id, box, current) {
  box.faView = current;  // 平台那边的数回来晚了：只在画的还是这一版时换上去，别把「开始发」之后的新样子盖回旧的
  const button = $('[data-release]', box);
  if (button) button.onclick = async () => {
    const st = releaseState(id); if (st.busy) return;
    st.busy = true; st.error = ''; button.disabled = true; button.textContent = '在备…';
    let view = current;
    try {
      view = await api(`/api/topics/${id}/pack/handoff`, {method:'POST'});
      if (PK.data?.topic?.id === id) PK.view = view;
      if (window.invalidatePublish) window.invalidatePublish();
      if (window.invalidatePlatform) window.invalidatePlatform();
      if (window.refreshPlatformNav) window.refreshPlatformNav();
      FA.at = 0;
    } catch (err) { st.error = err.message; }
    finally { st.busy = false; }
    if (box.isConnected === false) return;
    box.innerHTML = releaseMarkup(id, view); wireRelease(id, box, view); faFill(id, box, view);
  };
  $$('[data-fa-open]', box).forEach((b) => (b.onclick = () => window.goPlatform(b.dataset.faOpen, id)));
  $$('[data-fa-close]', box).forEach((b) => (b.onclick = async () => {
    const left = (current?.lanes || []).filter((lane) => lane.presentation?.state !== 'published').map((lane) => lane.label);
    if (left.length && !confirm(`${[...new Set(left)].join('、')} 还没发。这条就算发完了？没发的以后在「盘」那张表里还能补。`)) return;
    b.disabled = true;
    try { await api(`/api/topics/${id}/close`, { method: 'POST' }); } catch (err) { toast(err.message); b.disabled = false; return; }
    toast('这条结了。去「找」挑下一条，点「做这条」');
    if (window.refreshTopics) await window.refreshTopics();
    window.openInputTab('mine');
  }));
  $$('[data-fa-older]', box).forEach((b) => (b.onclick = () => { S.packId = Number(b.dataset.faOlder); PK.data = null; go('pack'); }));
  $$('[data-fa-plat]', box).forEach((el) => { const d = FA.id === id && FA.data[el.dataset.faPlat]; if (d) ppBind(el, d); });
  if (PP.match === id) ppDouyinMatch($(`#ppMatch-${id}`, box), id);  // 抖音传完「去抖音核对」的那个框
}
// 平台那边的数是另一次请求：先画骨架，拿到了再整块换成带按钮的
async function faFill(id, box, v) {
  const keys = [...new Set((v.lanes || []).map((lane) => lane.key))];
  if (!keys.length) return;
  const fresh = FA.id === id && FA.at && Date.now() - FA.at < 8000 && keys.every((k) => FA.data[k]);
  if (fresh) return;
  try { await faLoad(id, keys); } catch (_) { return; }
  if (box.isConnected === false || releaseState(id).busy || box.faView !== v) return;
  box.innerHTML = releaseMarkup(id, v); wireRelease(id, box, v);
}
function ctaInner(v) { return releaseMarkup(PK.data.topic.id, v); }
function paintCta() {
  const el = $('#pkCta');
  if (el && PK.view && !releaseState(PK.data.topic.id).busy) { el.innerHTML = ctaInner(PK.view); wireCta(); }
}
// 在表里点了「发了」「撤回」「发到 X」：各平台那边和这条的发布状态都重读，表、计数、回执一起变（10/20 走查：补登小红书后要刷新才对）
window.paintFa = async () => {
  FA.at = 0;
  const id = PK.data?.topic?.id;
  if (!id) return;
  try { PK.view = await api(`/api/topics/${id}/pack`); } catch (_) { /* 读不到就用手上的 */ }
  if (S.view === 'pack' && PK.data?.topic?.id === id) paintCta();
};
function wireCta() { const box = $('#pkCta'); if (box && PK.data?.topic) { wireRelease(PK.data.topic.id, box, PK.view); if (PK.view) faFill(PK.data.topic.id, box, PK.view); } }
function paintPackNavigation(id) {
  const box = $('#packNavigation'); if (!box || !id) return;
  const title = PK.data?.topic?.id === id ? PK.data.topic.title : '';
  // 10/20：左栏就是步骤条，这里只说「发」和这条叫什么（一条内容一个名字：选题名）
  box.innerHTML = `<header class="work-h zx-h">${title ? `<div class="work-title"><div><div class="stage-eyebrow">发 · 定标题，发到各平台</div><h1>${esc(title)}</h1></div><div class="work-acts">${PK.data?.video ? `<small class="pack-size">成片 ${esc(String(PK.data.video.mb))} MB</small>` : ''}</div></div>` : ''}</header>`;
}

/* 勾掉 / 勾上一个平台后，②要做的几样变了：整块重画（行数变了，paintSteps 只改已有的行） */
function refreshSteps() {
  const card = $('#pkSteps');
  if (card && PK.view) { card.outerHTML = stepsCard(PK.view); $$('.pk2-row').forEach(wireRow); }
  paintCta();
  if (PK.view && PK.view.busy) schedule(4000);
}

/* 描述和话题：自动填好了，收在最下面 */
function copyFold() {
  return `<details class="pk2-fold" id="pkCopy"><summary>描述和话题<small id="pkCopyNote">读文案…</small></summary><div id="pkCopyBody"></div></details>`;
}
// 10/20 走查：这里写「已经自动填好」，打开一看描述、简介都是 0 字。照实写：哪几样是空的，空着能不能发
async function paintCopyNote(topicId) {
  const note = $('#pkCopyNote');
  if (!note) return;
  let c;
  try { c = await api(`/api/topics/${topicId}/copy`); } catch (_) { note.textContent = '想改再打开'; return; }
  const f = window.copyFields ? window.copyFields(c.copy) : { desc: '', intro: '', tags: [] };
  const empty = [!f.desc && '描述', !f.intro && '简介', !(f.tags || []).length && '内容话题'].filter(Boolean);
  if (!$('#pkCopyNote')) return;
  note.textContent = empty.length ? `${empty.join('、')}还空着：空着也能发，只带标题和常用话题；想填就打开` : '描述、简介、话题都填好了，想改再打开';
  note.classList.toggle('warn', empty.length > 0);
}

function refreshPack() {
  PK.data = null;
  const b = $('#packBody'); if (b) b.dataset.sig = '';
  if (window.invalidatePublish) window.invalidatePublish();
  if (S.view === 'pack') renderView();
}

function paintHead(d) {
  const figs = $('#packFigs');
  if (!figs) return;
  figs.innerHTML = d && d.topic && d.video ? `<div class="pub-figs"><span>成片 <b>${d.video.mb}</b> MB</span></div>` : '';
}

window.VIEWS.pack = {
  async render() {
    const body = $('#packBody');
    const id = S.packId, request = ++PK.renderRequest;
    paintPackNavigation(id);
    const valid = () => S.view === 'pack' && request === PK.renderRequest && (S.packId === id || (!id && S.packId === PK.data?.topic?.id));
    // 正在打字（文案、文章）就不重画，免得冲掉没保存的内容
    if ((typeof CP !== 'undefined' && CP.dirty) || (typeof AR !== 'undefined' && AR.dirty && body.querySelector('#artText'))) return;
    if (document.activeElement && document.activeElement.id === 'pkTitleInput') return;
    let d;
    try { d = await loadPack(false); } catch (err) {
      if (valid() && !PK.data) body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`;
      return;
    }
    if (!valid()) return;
    paintHead(d);
    if (d.topic) paintPackNavigation(d.topic.id);
    if (!d.topic) {
      const w = d.waiting;
      body.dataset.sig = 'empty';
      body.innerHTML = `<div class="pub-empty"><b>还没有能打包的成片</b>
        ${w ? `<span>最近的一条是《${esc(w.title)}》，还在<b>${esc(w.stage_label || w.stage)}</b>。成片出现在项目 final/ 里，它就会出现在这儿。</span>
          <button class="btn small" type="button" data-pk-work="${w.id}">去看这一条 →</button>` : '<span>手上的都发完了。正在做的那条剪完，就会出现在这里。</span><button class="btn small" type="button" onclick="go(\'backfill\')">看全平台追踪 →</button>'}</div>`;
      $$('[data-pk-work]', body).forEach((b) => (b.onclick = () => openWork(Number(b.dataset.pkWork))));
      return;
    }
    const v = PK.view || { armed: false, steps: [] };
    const sig = JSON.stringify([d.topic.id, v.armed, v.title, PK.editTitle]);
    if (body.dataset.sig === sig) { paintSteps(); paintCta(); if (v.busy) schedule(6000); return; }
    body.dataset.sig = sig;
    body.innerHTML = `<div class="pk2">
      ${titleCard(d, v)}
      ${stepsCard(v)}
      ${ctaCard(v)}
      ${v.armed ? copyFold() : ''}
    </div>`;
    if (!v.armed || PK.editTitle) {
      paintCands(d.topic.id);
      const input = $('#pkTitleInput');
      $('#pkGo').onclick = () => packGo(d.topic.id);
      input.onkeydown = (e) => { if (e.key === 'Enter') packGo(d.topic.id); };
      input.oninput = () => $$('[data-cand]').forEach((x) => x.classList.toggle('on', $('b', x).textContent === input.value));
    }
    paintForms(d.topic.id);
    if (featureOn('products')) paintProduct(d.topic.id);
    const formsFold = $('#pkFormsFold'); if (formsFold) formsFold.ontoggle = () => { PK.formsOpen = formsFold.open; };
    const edit = $('#pkEditTitle');
    if (edit) edit.onclick = () => { PK.editTitle = true; body.dataset.sig = ''; renderView(); };
    $$('.pk2-row', body).forEach(wireRow);
    wireCta();
    const fold = $('#pkCopy');
    if (fold) paintCopyNote(d.topic.id);
    if (fold) fold.addEventListener('toggle', () => {
      const box = $('#pkCopyBody');
      if (!fold.open || box.dataset.done) return;
      box.dataset.done = '1';
      renderCopyForm({ ...(PK.topic || {}), ...d.topic }, box, { release: d.release, onSaved: async () => {
        // 描述、话题改了：文字重新定稿。标题也在这里改了的话，按新标题重新走一遍（封面跟着重出）
        try {
          const c = await api(`/api/topics/${d.topic.id}/copy`);
          const title = ((c.copy && c.copy.platforms && (c.copy.platforms.douyin || Object.values(c.copy.platforms)[0])) || {}).title || '';
          if (title && title !== (PK.view || {}).title) PK.view = await api(`/api/topics/${d.topic.id}/pack/go`, { method: 'POST', body: { title } });
          else await api(`/api/topics/${d.topic.id}/approve`, { method: 'PUT', body: { key: 'copy', approved: true } });
        } catch (err) { toast(err.message); }
        refreshPack();
      } });
    });
    if (v.busy) schedule(3000);
  },
};
