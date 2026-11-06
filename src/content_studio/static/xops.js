'use strict';
/* X 运营 Michael（10/9 作者）：独立的运营 Agent——不是你，也不是 Anna、Wendy。
 * 他看得到队列、每天发多少、最近 7 天长帖 / 长文各自的数、「持续在涨」；只动嘴，
 * 建议引用的帖子、改每天发多少，变成按钮，你点了才发生。10/9 晚起和 Anna、Wendy 同一个右边窗口。 */

const XO = { data: null, poll: null, draft: '', pending: false };
const XO_PROMPTS = ['今天先做什么？', '长帖和长文，现在哪个数好？', '持续在涨里哪几条我该引用？', '进度条为什么不动？'];

async function xoLoad() { XO.data = await api('/api/xops'); }

function xoAction(a) {
  if (a.kind === 'quote' && window.xcBtn) {
    return window.xcBtn({ kind: 'xhot', quote: true, url: a.url, title: '', author: '', text: '' }, '引用这条', '引用这条', '按你的风格写一条引用帖建议，你改完点了才发');
  }
  if (a.kind === 'counts') {
    const c = a.change;
    const label = [c.long != null ? `长的 ${c.long} 篇` : '', c.post_share != null ? `长帖占 ${Math.round(c.post_share * 100)}%` : '', c.hot != null ? `热点长帖最多写 ${c.hot} 篇` : ''].filter(Boolean).join('、');
    return `<button class="btn small ghost" type="button" data-xo-counts="${esc(JSON.stringify(c))}">改成：${esc(label)}</button>`;
  }
  return '';
}

/* 他叫什么、头衔：profile 的 brand.xops / brand.xops_role（10/9 晚 作者：叫 Michael） */
const xoName = () => ((typeof S !== 'undefined' && S.state && S.state.brand) || {}).xops || 'Michael';
const xoRole = () => ((typeof S !== 'undefined' && S.state && S.state.brand) || {}).xops_role || 'X 运营';

/* 10/9 晚 作者：Michael 和 Anna、Wendy 在同一个右边窗口（anna.js 管开关、拖动、大小），这里只画里面 */
async function renderXOpsPanel(box, opts) {
  const { close, bind, still = () => true } = opts;
  try { await xoLoad(); } catch (err) {
    if (!still()) return;
    box.innerHTML = `<div class="an-h"><b>${esc(xoName())}</b><button type="button" class="btn small" data-xo-x>关闭</button></div><div class="an-empty bad"><p>叫不到 ${esc(xoName())}：${esc(err.message)}</p></div><i class="an-edge w" data-an-edge="w"></i>`;
    bind(box); $('[data-xo-x]', box).onclick = close; return;
  }
  if (!still()) return;  // 等数的时候换成了 Anna、Wendy：别把他的对话写回去
  const typing = document.activeElement && document.activeElement.id === 'xoIn' && box.contains(document.activeElement);  // 只认他自己的框
  if (typing && !XO.data.busy && !XO.pending) return;  // 打到一半的字别冲掉
  const d = XO.data;
  const listEl = $('#xoList', box);
  const atBottom = !listEl || listEl.scrollTop + listEl.clientHeight >= listEl.scrollHeight - 40;
  const draft = $('#xoIn', box) ? $('#xoIn', box).value : (XO.draft || '');
  const msgs = d.messages.map((m) => {
    const acts = (m.actions || []).map(xoAction).filter(Boolean).join('');
    const body = esc(m.text).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
    return `<div class="an-msg ${m.role === 'park' ? 'from-park' : 'from-anna'}"><div class="an-bubble">${body}</div>${acts ? `<div class="xo-acts">${acts}</div>` : ''}</div>`;
  }).join('');
  box.innerHTML = `<div class="an-h"><div><b>${esc(xoName())}</b><span class="an-role">${esc(xoRole())}</span></div>
      <small class="an-where">看得到 X 的队列、最近 7 天的数、持续在涨；只给建议，你点了才发生</small>
      <div class="an-tools">${d.messages.length ? '<button class="btn small ghost" type="button" data-xo-clear>清空</button>' : ''}<button class="btn small" type="button" data-xo-x title="收起窗口，需要时再叫他">去忙吧</button></div></div>
    <div class="an-list" id="xoList">${msgs || `<div class="an-empty"><p>我是 ${esc(xoName())}，${esc(xoRole())}。问我今天先做什么，或者点下面一个问题。</p></div>`}
      ${d.busy ? `<div class="an-msg from-anna"><div class="an-bubble an-wait"><span class="spin"></span>${esc(xoName())} 在看数、想…</div></div>` : ''}
      ${d.error && !d.busy ? `<div class="an-msg from-anna"><div class="an-bubble bad">${esc(d.error)}</div></div>` : ''}</div>
    <div class="xo-quick">${XO_PROMPTS.map((q) => `<button class="btn small ghost" type="button" data-xo-ask="${esc(q)}" ${d.busy ? 'disabled' : ''}>${esc(q)}</button>`).join('')}</div>
    <form class="an-form" data-xo-form><textarea id="xoIn" rows="2" placeholder="问 ${esc(xoName())}…（回车发送）">${esc(draft)}</textarea>
      <div class="wd-send"><button class="btn primary" type="submit" ${d.busy ? 'disabled' : ''}>发送</button></div></form>
    <i class="an-edge w" data-an-edge="w"></i>`;
  bind(box);
  const list = $('#xoList', box);
  if (atBottom) list.scrollTop = list.scrollHeight;
  const input = $('#xoIn', box);
  input.oninput = () => { XO.draft = input.value; };
  input.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('[data-xo-form]', box).requestSubmit(); } };
  const send = async (message) => {
    XO.pending = true;
    try { const r = await api('/api/xops', { method: 'POST', body: { message, screen: (document.querySelector('main') || document.body).innerText.slice(0, 8000) } }); if (!r.started) toast(r.message); } catch (err) { toast(err.message); }
    XO.pending = false;
    renderXOpsPanel(box, opts);
  };
  $('[data-xo-form]', box).onsubmit = (e) => { e.preventDefault(); const t = input.value.trim(); if (!t || d.busy) return; input.value = ''; XO.draft = ''; send(t); };
  $$('[data-xo-ask]', box).forEach((b) => (b.onclick = () => send(b.dataset.xoAsk)));
  $$('[data-xo-counts]', box).forEach((b) => (b.onclick = async () => {
    try { await api('/api/xline/counts', { method: 'PUT', body: JSON.parse(b.dataset.xoCounts) }); toast('改好了'); b.disabled = true; } catch (err) { toast(err.message); }
  }));
  $('[data-xo-x]', box).onclick = close;
  const clear = $('[data-xo-clear]', box);
  if (clear) clear.onclick = async () => { try { await api('/api/xops', { method: 'DELETE' }); } catch (err) { toast(err.message); } renderXOpsPanel(box, opts); };
  clearTimeout(XO.poll);
  if (d.busy) XO.poll = setTimeout(() => { if (box.isConnected && !box.hidden && still()) renderXOpsPanel(box, opts); }, 2500);
}

window.renderXOpsPanel = renderXOpsPanel;
