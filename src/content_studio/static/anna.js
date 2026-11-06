'use strict';
/* Anna · 悬浮窗里的流量 CEO（10/9 起；原来叫内容主编）：一场贯穿所有页面的对话；作者 在哪一页，她就看着哪一页的资料；只动嘴，动作变成按钮 */

// Assistants open only when requested; preserve an explicit saved preference.
/* 两位虚拟同事叫什么：profile 的 brand.editor / brand.boss（10/6）；没填就是 Anna / Wendy */
const editorName = () => ((typeof S !== 'undefined' && S.state && S.state.brand) || {}).editor || 'Anna';
const bossName = () => ((typeof S !== 'undefined' && S.state && S.state.brand) || {}).boss || 'Wendy';
/* 头衔（10/9 变现流程板）：Anna 管触达，Wendy 管收入；profile 的 brand.editor_role / brand.boss_role 能改 */
const editorRole = () => ((typeof S !== 'undefined' && S.state && S.state.brand) || {}).editor_role || '流量 CEO';
const bossRole = () => ((typeof S !== 'undefined' && S.state && S.state.brand) || {}).boss_role || '负责人';
const AN = { open: (() => { try { const saved = localStorage.getItem('cs-anna'); return saved === 'open'; } catch (_) { return false; } })(), scope: null, data: null, poll: null, draft: {} };

const ANNA_PROMPTS = {
  input: ['今天有什么值得拿来做的？', '这篇讲的是什么，能不能拍？', '最近进来的东西里哪条最有反差？'],
  board: ['今天先拍哪条？', '看板上哪条卡最久，为什么？', '推荐的这两条，三点各差在哪？'],
  work: ['这个提纲第一句够不够狠？', '交付这一点怎么补？', '按三点看，这条能不能拍？'],
  output: ['这周哪条最好，为什么？', '下一条只改一件事，改什么？', '来的人对不对？'],
  settings: ['你现在读的是哪些文件？'],
  consults: ['这个客户下一步该怎么跟？', '哪场咨询能做成一条视频？'],
};

function annaScope() {
  if (S.view === 'work' && S.workId) return `work:${S.workId}`;
  if (OUTPUT_FAMILY.includes(S.view)) return 'output';
  if (['input', 'board', 'settings', 'positioning', 'consults'].includes(S.view)) return S.view;
  return 'board';
}

function annaKind(scope) { return scope.split(':')[0]; }

function annaTime(iso) {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

async function loadAnna(scope) {
  AN.data = await api(`/api/anna?scope=${encodeURIComponent(scope)}`);
  AN.scope = scope;
}

/* ---- Right-anchored assistant: only the left edge resizes, without repainting chat. ---- */
const AN_WIDTH = { min: 320, max: 640, initial: 368, rail: 236, workspace: 480, gap: 32 };
let annaResize = null;
function annaGeom() { try { return JSON.parse(localStorage.getItem('cs-anna-geom') || 'null'); } catch (_) { return null; } }
function saveAnnaGeom(g) { try { localStorage.setItem('cs-anna-geom', JSON.stringify({ w: g.w })); } catch (_) { /* optional storage */ } }
function annaWidthMax() {
  return Math.max(AN_WIDTH.min, Math.min(AN_WIDTH.max, window.innerWidth >= 1100 ? window.innerWidth - AN_WIDTH.rail - AN_WIDTH.workspace - AN_WIDTH.gap : window.innerWidth - AN_WIDTH.gap));
}
function clampAnnaWidth(width) {
  const value = Number(width);
  return Math.round(Math.max(AN_WIDTH.min, Math.min(Number.isFinite(value) && value > 0 ? value : AN_WIDTH.initial, annaWidthMax())));
}
function setAnnaWidth(box, width) {
  const value = clampAnnaWidth(width);
  document.body.style.setProperty('--anna-width', `${value}px`);
  Object.assign(box.style, { left: 'auto', right: '16px', top: '16px', bottom: '16px', width: `${value}px`, height: 'auto' });
  const grip = $('[data-an-edge="w"]', box);
  if (grip) { grip.setAttribute('aria-valuemin', AN_WIDTH.min); grip.setAttribute('aria-valuemax', annaWidthMax()); grip.setAttribute('aria-valuenow', value); }
  return value;
}
function applyAnnaGeom(box) {
  if (window.innerWidth < 900) { box.removeAttribute('style'); return; }
  setAnnaWidth(box, annaGeom()?.w ?? AN_WIDTH.initial);
}
function startAnnaGesture(e, box, mode) {
  if (window.innerWidth < 900 || mode !== 'w' || e.button !== 0 || box.hidden) return;
  e.preventDefault();
  if (annaResize) annaResize.cancel();
  const start = { x: e.clientX, width: box.getBoundingClientRect().width };
  const pointerId = e.pointerId, handle = e.currentTarget;
  let width = start.width;
  box.classList.add('an-dragging');
  const matches = (event) => event.pointerId === undefined || pointerId === undefined || event.pointerId === pointerId;
  const move = (event) => {
    if (!matches(event)) return;
    width = setAnnaWidth(box, start.width + start.x - event.clientX);
  };
  const finish = (commit) => {
    window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up);
    window.removeEventListener('pointercancel', cancel); window.removeEventListener('blur', cancel);
    handle?.removeEventListener?.('lostpointercapture', cancel);
    box.classList.remove('an-dragging'); annaResize = null;
    if (handle?.hasPointerCapture?.(pointerId)) handle.releasePointerCapture(pointerId);
    if (commit) saveAnnaGeom({ w: width }); else setAnnaWidth(box, start.width);
  };
  const up = (event) => { if (matches(event)) finish(true); };
  const cancel = (event = {}) => { if (matches(event)) finish(false); };
  annaResize = { cancel };
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
  window.addEventListener('pointercancel', cancel); window.addEventListener('blur', cancel);
  handle?.addEventListener?.('lostpointercapture', cancel);
  if (pointerId !== undefined) handle?.setPointerCapture?.(pointerId);
}
function bindAnnaWindow(box) {
  applyAnnaGeom(box);
  const head = $('.an-h', box);
  if (head) { head.onpointerdown = null; head.ondblclick = null; }
  $$('[data-an-edge]', box).forEach((grip) => {
    const left = grip.dataset.anEdge === 'w';
    grip.onpointerdown = left ? (event) => startAnnaGesture(event, box, 'w') : null;
    if (!left) return;
    grip.setAttribute('role', 'separator'); grip.setAttribute('aria-orientation', 'vertical');
    grip.setAttribute('aria-label', '调整助手宽度'); grip.tabIndex = 0;
    grip.onkeydown = (event) => {
      if (window.innerWidth < 900 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const step = event.shiftKey ? 32 : 16, current = box.getBoundingClientRect().width;
      const next = event.key === 'Home' ? AN_WIDTH.min : event.key === 'End' ? annaWidthMax() : current + (event.key === 'ArrowLeft' ? step : -step);
      saveAnnaGeom({ w: setAnnaWidth(box, next) });
    };
    if (window.innerWidth >= 900) setAnnaWidth(box, box.getBoundingClientRect().width);
  });
}
window.addEventListener('resize', () => { if (annaResize) annaResize.cancel(); const box = $('#anna'); if (box && !box.hidden) applyAnnaGeom(box); });

function annaActionButton(a, scope) {
  const kind = annaKind(scope);
  if ((a.kind === 'outline' || a.kind === 'qa' || a.kind === 'memo') && kind !== 'work') return '';
  if (a.kind === 'take' && !['input', 'board'].includes(kind)) return '';
  // 记进标准 has no topic and a lesson can come from any page, so it is not gated by scope.
  const text = a.kind === 'memo' ? `存进备注：${a.arg}` : a.kind === 'take' ? `拿来做：${a.arg}` : a.kind === 'standard' ? `记进标准：${a.arg}` : a.kind === 'positioning' ? `记进定位：${a.arg}` : a.kind === 'raw' ? `写进原始输出：${a.arg}` : a.label;
  return `<button class="btn small an-act" type="button" data-an-kind="${a.kind}" data-an-arg="${esc(a.arg || '')}"${a.body ? ` data-an-body="${esc(a.body)}"` : ''}>${esc(text)}</button>`;
}

async function runAnnaAction(kind, arg, scope, body) {
  const id = annaKind(scope) === 'work' ? Number(scope.split(':')[1]) : null;
  try {
    if (kind === 'memo' && id) {
      const topics = await api('/api/topics?archived=true');
      const t = topics.find((x) => x.id === id);
      const memo = `${t && t.memo ? t.memo.trimEnd() + '\n' : ''}Anna：${arg}`;
      await api(`/api/topics/${id}`, { method: 'PATCH', body: { memo } });
      toast('已存进备注');
    } else if (kind === 'outline' && id) {
      const r = await api(`/api/topics/${id}/outline`, { method: 'POST' });
      toast(r.message);
    } else if (kind === 'qa' && id) {
      const r = await api(`/api/topics/${id}/qa`, { method: 'POST' });
      toast(r.message);
    } else if (kind === 'standard') {
      // The sentence was distilled from someone else's video; 作者 approves the exact text.
      const where = (S.standard && S.standard.path) || '~/.claude/skills/content-qa/SKILL.md';
      if (!confirm(`把这一句写进你的三点评分标准？以后每条内容都会按它评分。\n\n${arg}\n\n写进：${where}`)) return;
      await api('/api/standard', { method: 'POST', body: { text: arg, source: 'Anna · ' + (AN.data ? AN.data.label : '') } });
      if (window.reloadStandard) await window.reloadStandard();
      toast('已记进标准');
    } else if (kind === 'positioning') {
      // Anna's sentence goes into 「待拍板」 only; 作者 moves it into the body by hand.
      if (!confirm(`把这一句记进定位的「待拍板」？\n\n${arg}`)) return;
      await api('/api/positioning', { method: 'POST', body: { text: arg, source: 'Anna' } });
      if (window.reloadPositioning) await window.reloadPositioning();
      toast('已记进待拍板');
    } else if (kind === 'raw') {
      // 10/1：Anna 整理好的一篇，写进 vault 的原始输出文件夹（不覆盖已有文件）
      if (!confirm(`把 ${editorName()} 整理的这一篇写进 ${rawFolder()}/${arg}.md？`)) return;
      const r = await api('/api/anna/raw', { method: 'POST', body: { target: arg, body: body || '' } });
      toast(`已写进 ${r.folder}/${r.name}`);
    } else if (kind === 'take') {
      await api('/api/topics', { method: 'POST', body: { title: arg, formats: 'both', account_id: S.mine && S.mine.account ? S.mine.account.id : null } });
      toast('已放进看板');
    }
    if (window.refreshTopics) await window.refreshTopics();
  } catch (err) { toast(err.message); }
}

function annaMessage(m, scope) {
  const where = m.page ? ` · 在${esc(m.page)}` : '';
  const at = m.scope || scope;  // an action applies to the page it was suggested on
  if (m.role === 'park') return `<div class="an-msg from-park"><div class="an-bubble">${esc(m.text)}</div><small>${annaTime(m.at)}${where}</small></div>`;
  const acts = (m.actions || []).map((a) => annaActionButton(a, at)).join('');
  return `<div class="an-msg from-anna"><div class="an-bubble md">${renderMarkdown(m.text || '')}</div>${acts ? `<div class="an-acts" data-an-scope="${esc(at)}">${acts}</div>` : ''}<small>Anna · ${annaTime(m.at)}${where}</small></div>`;
}

/* 屏幕上这一页的字，发消息时一起带给 Anna 和 Wendy（10/5 作者：页面加了全网粉丝，Wendy 说看不到）。
 * 后台给她们的资料是一条条写死的，页面一改就跟不上；带上屏幕，页面怎么改她们看到的就是他看到的。 */
function screenText() {
  const view = $$('main > section.view').find((v) => v.classList.contains('on'));
  return view ? view.innerText.slice(0, 16000) : '';
}

/* ---- Wendy：和 Anna 同一个窗口、同一套拖动和大小，一次只开一个（10/1 作者：「Wendy 是否能也像 Anna 一样放在右边」）。
 *      10/9 作者：左栏两个人都在，点谁开谁；内容编辑页（进项 → 排期 → 加工中 → 一条内容）只有 Anna。 ---- */
const WDP = { open: (() => { try { const saved = localStorage.getItem('cs-wendy'); return saved === 'open'; } catch (_) { return false; } })(), data: null, poll: null, draft: '' };
const CONTENT_VIEWS = ['input', 'radar', 'report', 'board', 'work', 'pack', 'swipe'];
const WENDY_HOME = ['today', 'positioning', 'consults', 'products'];  // 两个都开着（旧的存档）时，这几页先给 Wendy
// 10/9 作者：X 页归 X 运营，Anna、Wendy 都不出现
const onXPage = () => S.view === 'platform' && S.platformKey === 'x';
/* Michael（X 运营）：10/9 晚 作者「Michael 应该跟 Anna 和 Wendy 出现在同样的地方……他应该出现在右侧」。
 * 和她们同一个右边窗口、一次只开一个；左栏点他就开。X 页上默认开着（他常驻 X 页），你关了就记住。 */
const MIP = { state: (() => { try { return localStorage.getItem('cs-michael') || ''; } catch (_) { return ''; } })() };
// X 页上 Anna、Wendy 本来就不出现，所以只看你有没有亲手关过他（点「去忙吧」或再点一下他的名字）
// 10/12 作者：「Michael 暂时没有什么用，先拿掉。」前端不再开他（Obsidian 里的角色文件标了 paused，留着）
const MICHAEL_PAUSED = true;
// 10/12 作者：「安娜和 Michael 都隐藏，现在整个前台全部都是温迪。」Anna 的对话和接口都留着，前端不再开她；每一页右边都是 Wendy
const ANNA_PAUSED = true;
const michaelOpen = () => !MICHAEL_PAUSED && (MIP.state === 'open' || (onXPage() && MIP.state !== 'closed'));

function shownAssistant() {
  if (michaelOpen() && featureOn('xline') && (onXPage() || (!AN.open && !WDP.open))) return 'michael';
  if (ANNA_PAUSED) return WDP.open ? 'wendy' : null;
  if (onXPage()) return null;
  const wendy = WDP.open && !CONTENT_VIEWS.includes(S.view);
  if (wendy && AN.open) return WENDY_HOME.includes(S.view) ? 'wendy' : 'anna';
  return wendy ? 'wendy' : AN.open ? 'anna' : null;
}

function saveAssistantState() {
  try {
    localStorage.setItem('cs-anna', AN.open ? 'open' : 'closed'); localStorage.setItem('cs-wendy', WDP.open ? 'open' : 'closed');
    if (MIP.state) localStorage.setItem('cs-michael', MIP.state);
  } catch (_) { /* optional storage */ }
}

const ASSIST_INPUT = { anna: '#anIn', wendy: '#wdIn', michael: '#xoIn' };
const ASSIST_RAIL = { anna: '#railAnna', wendy: '#railWendy', michael: '#railMichael' };

function toggleAssistant(who) {
  const opening = shownAssistant() !== who;
  AN.open = who === 'anna' && opening;
  WDP.open = who === 'wendy' && opening;
  // 开 Michael = open；再点他一下 = 亲手关了（X 页上也不再自己弹）；开 Anna、Wendy 只是把他让开，不算关
  MIP.state = who === 'michael' ? (opening ? 'open' : 'closed') : (MIP.state === 'open' ? '' : MIP.state);
  saveAssistantState();
  const done = renderAnna();
  if (opening) setTimeout(() => { const i = $(ASSIST_INPUT[who]); if (i) i.focus(); }, 300);
  return done;
}

function closeAssistant() {
  const who = shownAssistant() || 'anna';
  if (who === 'wendy') WDP.open = false; else if (who === 'michael') MIP.state = 'closed'; else AN.open = false;
  saveAssistantState();
  renderAnna();
  $(ASSIST_RAIL[who])?.focus();
}

function pageLabel() {
  const h = $$('main > section.view').find((v) => v.classList.contains('on'));
  const title = h && h.querySelector('h1');
  return (title && title.textContent.trim()) || '这一页';
}
function assistantLoadError(box, name, error) {
  box.innerHTML = `<div class="an-h"><b>${esc(name)}</b><button type="button" class="btn small" id="assistantClose">关闭助手</button></div><div class="an-empty bad"><p>暂时读不到对话，工作台仍可继续使用。</p><p>${esc(error.message)}</p><button type="button" class="btn" id="assistantRetry">重试读取</button></div><i class="an-edge w" data-an-edge="w"></i>`;
  bindAnnaWindow(box);
  $('#assistantClose', box).onclick = closeAssistant;
  $('#assistantRetry', box).onclick = () => renderAnna();
  $('#assistantClose', box).focus();
}

async function renderWendyPanel(box) {
  const page = ['positioning', 'today'].includes(S.view) ? S.view : 'other';
  try { WDP.data = await api('/api/wendy'); } catch (err) { assistantLoadError(box, bossName(), err); return; }
  if (shownAssistant() !== 'wendy') return;  // 等数的时候换人了
  // 只有在她自己的输入框里打字才不重画（刚从 Anna、Michael 切过来时，焦点还留在他们的框里）
  if (document.activeElement && document.activeElement.id === 'wdIn' && box.contains(document.activeElement) && !WDP.data.busy && !WDP.pending) return;
  const w = WDP.data;
  const pos = page === 'positioning';
  const wasScrolled = $('#wdList') && $('#wdList').scrollTop + $('#wdList').clientHeight >= $('#wdList').scrollHeight - 40;
  const draft = $('#wdIn') ? $('#wdIn').value : WDP.draft;
  const list = w.messages.length ? w.messages.map((m) => wdMsg(m, false)).join('')
    : `<div class="an-empty"><p>我是 ${esc(bossName())}，${esc(bossRole())}。我背 KPI：抖音粉丝、X 粉丝、本月收入。你每天拍、发，我看数告诉你改什么。现在想说什么就说。</p></div>`;
  box.innerHTML = `<div class="an-h"><div><b>${esc(bossName())}</b><span class="an-role wd-role">${esc(bossRole())}</span></div><small class="an-where">${pos ? '在「我是谁」：聊方向，你拍板，她提案、守住' : page === 'today' ? '在「战况」：盯 KPI，盯你做没做到' : `正在看「${esc(pageLabel())}」`}${w.nudges.length ? ` · 今天在微信催过你 ${w.nudges.length} 次` : ''}</small>
      <div class="an-tools"><button class="btn small" type="button" id="wdClose" title="收起窗口，需要时再叫她">去忙吧</button></div></div>
    <div class="an-list" id="wdList">${list}${w.busy ? '<div class="an-msg from-anna"><div class="an-bubble an-wait"><span class="spin"></span>${esc(bossName())} 在看工作台…</div></div>' : ''}${w.error && !w.busy ? `<div class="an-msg from-anna"><div class="an-bubble bad">${esc(w.error)}</div></div>` : ''}</div>
    <form class="an-form" id="wdForm"><textarea id="wdIn" rows="2" placeholder="${pos ? '跟她聊方向：三问里哪一问还不够窄、我到底该卖什么…' : page === 'today' ? '回她一句：几点做、为什么没做、做完了…' : '问她这一页…'}（回车发送）">${esc(draft)}</textarea>
      <div class="wd-send"><button class="btn primary" type="submit" ${w.busy ? 'disabled' : ''}>${pos ? '问她' : '回她'}</button><button class="linklike" type="button" id="wdLook" ${w.busy ? 'disabled' : ''}>${pos ? '让她看一眼这一页' : '让她看一眼现在'}</button></div></form>
    <i class="an-edge w" data-an-edge="w"></i>`;
  bindAnnaWindow(box);
  const listEl = $('#wdList');
  if (wasScrolled || !WDP.rendered) listEl.scrollTop = listEl.scrollHeight;
  WDP.rendered = true;
  $('#wdClose').onclick = () => { WDP.open = false; saveAssistantState(); renderAnna(); };
  const say = async (message) => {
    WDP.pending = true;
    try { const r = await api('/api/wendy', { method: 'POST', body: { message, page, screen: screenText() } }); if (!r.started) toast(r.message); } catch (err) { toast(err.message); }
    WDP.pending = false;
    renderAnna();
    if (page === 'today' && window.VIEWS.today) { const tb = $('#todayBody'); if (tb) tb.dataset.sig = ''; window.VIEWS.today.render(); }
  };
  const input = $('#wdIn');
  input.oninput = () => { WDP.draft = input.value; };
  input.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('#wdForm').requestSubmit(); } };
  $('#wdForm').onsubmit = (e) => { e.preventDefault(); const text = input.value.trim(); if (!text || w.busy) return; input.value = ''; WDP.draft = ''; say(text); };
  $('#wdLook').onclick = () => say('');
  clearTimeout(WDP.poll);
  if (w.busy) WDP.poll = setTimeout(() => { if (shownAssistant() === 'wendy') renderAnna(); }, 3000);
}

window.openWendy = (prefill) => {
  WDP.open = true; AN.open = false;
  saveAssistantState();
  renderAnna();
  setTimeout(() => { const i = $('#wdIn'); if (i) { if (prefill && !i.value) i.value = prefill; i.focus(); } }, 300);
};

async function renderAnna() {
  const box = $('#anna');
  if (!box) return;
  if (!featureOn('team')) { if (annaResize) annaResize.cancel(); box.hidden = true; $('main').inert = false; document.body.classList.remove('anna-open'); return; }  // 试用版没有 AI 团队
  const who = shownAssistant();
  const wendyPage = who === 'wendy';
  const railW = $('#railWendy');
  const railM = $('#railMichael');
  if (railM) railM.classList.toggle('on', who === 'michael');
  $('#railAnna').hidden = ANNA_PAUSED || onXPage();
  if (railW) { railW.hidden = !ANNA_PAUSED && (CONTENT_VIEWS.includes(S.view) || onXPage()); railW.classList.toggle('on', wendyPage); }
  const open = who !== null;
  document.body.classList.toggle('anna-open', open);
  $('#railAnna').classList.toggle('on', who === 'anna');
  box.hidden = !open;
  if (!open && annaResize) annaResize.cancel();
  if (open) applyAnnaGeom(box);
  const drawer = open && window.innerWidth < 1100;
  $('main').inert = drawer;
  box.setAttribute('role', drawer ? 'dialog' : 'complementary');
  if (drawer) box.setAttribute('aria-modal', 'true'); else box.removeAttribute('aria-modal');
  box.classList.toggle('wd-panel', wendyPage);
  box.classList.toggle('xo-panel', who === 'michael');
  box.setAttribute('aria-label', who === 'michael' ? 'Michael' : wendyPage ? 'Wendy' : 'Anna');
  if (who === 'michael') {
    clearTimeout(AN.poll); clearTimeout(WDP.poll); AN.rendered = false; AN.scope = null; WDP.rendered = false;
    if (window.renderXOpsPanel) await window.renderXOpsPanel(box, { close: closeAssistant, bind: bindAnnaWindow, still: () => shownAssistant() === 'michael' });
    return;
  }
  if (wendyPage) { clearTimeout(AN.poll); AN.rendered = false; AN.scope = null; if (open) await renderWendyPanel(box); else clearTimeout(WDP.poll); return; }
  clearTimeout(WDP.poll);
  WDP.rendered = false;
  if (who !== 'anna') { clearTimeout(AN.poll); return; }
  const scope = annaScope();
  if (AN.scope !== scope || !AN.data) {
    if ($('#anIn')) AN.draft.main = $('#anIn').value;
    try { await loadAnna(scope); } catch (err) { assistantLoadError(box, editorName(), err); return; }
    if (shownAssistant() !== 'anna') return;  // 等数的时候换成了别人（Wendy、Michael）：别把她的对话写回去
  }
  const d = AN.data;
  const kind = annaKind(scope);
  const where = d.title ? `正在看《${d.title}》` : `正在看「${d.label}」`;
  const list = d.messages.length
    ? d.messages.map((m) => annaMessage(m, scope)).join('')
    : `<div class="an-empty"><p>我是 ${esc(editorName())}，${esc(editorRole())}。我管触达：选题、内容、各平台。我能看到你${d.title ? '这条视频' : '这一页'}的全部资料，说什么都行。</p><div class="an-chips">${(ANNA_PROMPTS[kind] || []).map((p) => `<button type="button" class="an-chip" data-an-prompt="${esc(p)}">${esc(p)}</button>`).join('')}</div></div>`;
  const wasScrolled = $('#anList') && $('#anList').scrollTop + $('#anList').clientHeight >= $('#anList').scrollHeight - 40;
  // One conversation, one draft: switching pages keeps what you were typing.
  const draft = $('#anIn') ? $('#anIn').value : (AN.draft.main || '');
  box.innerHTML = `<div class="an-h"><div><b>${esc(editorName())}</b><span class="an-role">${esc(editorRole())}</span></div><small class="an-where">${esc(where)}</small>
      <div class="an-tools"><button class="linklike" type="button" id="anClear" title="清掉和 Anna 的全部对话，从头聊">清空</button><button class="btn small" type="button" id="anClose" title="收起窗口，需要时再叫她">去忙吧</button></div></div>
    <div class="an-list" id="anList">${list}${d.busy ? '<div class="an-msg from-anna"><div class="an-bubble an-wait"><span class="spin"></span>Anna 在看资料…</div></div>' : ''}${d.error && !d.busy ? `<div class="an-msg from-anna"><div class="an-bubble bad">${esc(d.error)}</div></div>` : ''}</div>
    <form class="an-form" id="anForm"><textarea id="anIn" rows="2" placeholder="问 Anna…（回车发送，Shift+回车换行）">${esc(draft)}</textarea><button class="btn primary" type="submit" ${d.busy ? 'disabled' : ''}>发送</button></form>
    <i class="an-edge w" data-an-edge="w"></i>`;
  bindAnnaWindow(box);
  const listEl = $('#anList');
  if (wasScrolled || !AN.rendered) listEl.scrollTop = listEl.scrollHeight;
  AN.rendered = true;
  $('#anClose').onclick = () => { AN.open = false; saveAssistantState(); renderAnna(); };
  $('#anClear').onclick = async () => {
    if (!d.messages.length || !confirm('清掉和 Anna 的全部对话？')) return;
    try { await api(`/api/anna?scope=${encodeURIComponent(scope)}`, { method: 'DELETE' }); AN.data = null; renderAnna(); } catch (err) { toast(err.message); }
  };
  $$('[data-an-prompt]', box).forEach((b) => (b.onclick = () => { $('#anIn').value = b.dataset.anPrompt; $('#anIn').focus(); }));
  $$('[data-an-kind]', box).forEach((b) => (b.onclick = () => { b.disabled = true; runAnnaAction(b.dataset.anKind, b.dataset.anArg, b.closest('[data-an-scope]').dataset.anScope, b.dataset.anBody); }));
  const input = $('#anIn');
  input.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('#anForm').requestSubmit(); } };
  $('#anForm').onsubmit = async (e) => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message || d.busy) return;
    const body = { scope, message, screen: screenText() };
    if (kind === 'input' && typeof C !== 'undefined' && C.open) body.note_path = C.open;
    if (S.view === 'report' && S.reportId) body.report_id = String(S.reportId);  // 拆解报告页：让她看到这份报告本身
    try {
      const r = await api('/api/anna', { method: 'POST', body });
      if (!r.started) { toast(r.message); return; }
      input.value = '';
      AN.draft.main = '';
      await loadAnna(scope);
      renderAnna();
    } catch (err) { toast(err.message); }
  };
  clearTimeout(AN.poll);
  if (d.busy) AN.poll = setTimeout(async () => { if (shownAssistant() === 'anna' && annaScope() === scope) { try { await loadAnna(scope); } catch (_) { /* retry next tick */ } renderAnna(); } }, 2000);
}
window.renderAnna = renderAnna;

/** Open the panel from another page, optionally with a first line already typed. */
window.openAnna = (prefill) => {
  if (ANNA_PAUSED) { window.openWendy(prefill); return; }
  AN.open = true; WDP.open = false;
  saveAssistantState();
  renderAnna();
  setTimeout(() => { const i = $('#anIn'); if (i) { if (prefill && !i.value) i.value = prefill; i.focus(); } }, 80);
};

document.addEventListener('DOMContentLoaded', () => {
  const wendy = $('#railWendy');
  if (wendy) wendy.onclick = () => toggleAssistant('wendy');
  const michael = $('#railMichael');
  if (michael) michael.onclick = () => toggleAssistant('michael');
  const btn = $('#railAnna');
  if (btn) btn.onclick = () => toggleAssistant('anna');
});

// A narrow assistant is a drawer: keyboard users can leave it with Escape.
window.addEventListener('keydown', (event) => {
  const box = $('#anna');
  if (!box || box.hidden) return;
  if (event.key === 'Escape') {
    closeAssistant();
    event.preventDefault();
  }
  if (event.key === 'Tab' && window.innerWidth < 1100) {
    const targets = [...box.querySelectorAll('button,input,textarea,select,a[href],[tabindex="0"]')].filter((el) => !el.disabled && el.getClientRects().length);
    if (!targets.length) return;
    const first = targets[0], last = targets[targets.length - 1];
    if (event.shiftKey && (document.activeElement === first || !box.contains(document.activeElement))) { last.focus(); event.preventDefault(); }
    else if (!event.shiftKey && (document.activeElement === last || !box.contains(document.activeElement))) { first.focus(); event.preventDefault(); }
  }
});
window.addEventListener('resize', () => {
  const box = $('#anna');
  if (!box) return;
  const drawer = !box.hidden && window.innerWidth < 1100;
  $('main').inert = drawer;
  box.setAttribute('role', drawer ? 'dialog' : 'complementary');
  if (drawer) box.setAttribute('aria-modal', 'true'); else box.removeAttribute('aria-modal');
});
