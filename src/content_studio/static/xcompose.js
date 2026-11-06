'use strict';
/* 发 X（10/5 作者）：进项里每一条都有「发 X」。点了才写建议稿——你自己的原始输出照原话整理，
 * 别人的东西按你的风格写一条（说清是谁说的、带链接、加一句你的判断）。你删改，点「确定，发出去」才发。
 * 一个弹窗，三处共用（笔记、日报快讯、老师和对标）；列表怎么重画都不影响它。 */
const XC = { payload: null, title: '', posts: [], sid: null, own: false, style: null, loading: false, error: null };

window.xcBtn = (payload, title, label = '发 X', hint = '按你的风格写一条建议，你改完点了才发') => (!featureOn('xline') ? '' : `<button class="btn small ghost xc-btn" type="button" data-xc="${esc(JSON.stringify(payload))}" data-xc-title="${esc(title || '')}" title="${esc(hint)}">${esc(label)}</button>`);

function xcDialog() {
  let d = $('#xcDlg');
  if (!d) {
    d = document.createElement('dialog');
    d.id = 'xcDlg';
    d.className = 'xc-dlg';
    document.body.appendChild(d);
    d.addEventListener('close', () => { XC.payload = null; });
  }
  return d;
}

function xcPaint() {
  const d = xcDialog();
  const lim = typeof XL_LIMIT === 'number' ? XL_LIMIT : 280;
  const weight = (t) => (typeof xlWeight === 'function' ? xlWeight(t) : t.length * 2);
  const body = XC.loading
    ? `<div class="xc-wait"><span class="spin"></span><span>${XC.own ? '照你的原话整理…' : '按你的风格写一条…'}第一次要先从你发过的内容里找风格，会多等一会。</span></div>`
    : XC.error ? `<p class="bad">${esc(XC.error)}</p>`
      : XC.posts.map((p, i) => `<div class="xc-post">
          <textarea data-xc-text="${i}" rows="${Math.min(10, Math.max(4, Math.ceil(p.length / 28)))}">${esc(p)}</textarea>
          <div class="xc-acts"><small data-xc-count="${i}"></small>
            <button class="btn small primary" type="button" data-xc-send="${i}">确定，发出去</button>
            <button class="btn small" type="button" data-xc-copy="${i}" hidden>复制去 X 发</button>
            <button class="btn small ghost" type="button" data-xc-manual="${i}" hidden>我发了</button></div>
        </div>`).join('');
  d.innerHTML = `<form method="dialog" class="xc">
      <div class="xc-h"><div><small>${XC.own ? '发 X · 你自己的原话' : XC.payload && XC.payload.quote ? '引用帖 · 建议稿' : '发 X · 建议稿'}</small><b>${esc(XC.title)}</b></div><button class="linklike" value="close" aria-label="关掉">×</button></div>
      ${XC.own ? '<p class="xc-note">只删口语、不改你的词。几条就是原文里几个独立的意思。</p>'
        : XC.payload && XC.payload.quote ? `<p class="xc-note">发成引用帖：原帖跟着引用卡片出来（<a href="${esc(XC.payload.url)}" target="_blank" rel="noopener">看原帖 ↗</a>），稿子里只写你的判断，取自你的 世界观文件。你删改完再发。</p>`
          : '<p class="xc-note">这是别人的东西：稿子里说清是谁说的、带了链接，判断取自你的 世界观文件。你删改完再发。</p>'}
      ${body}
      <div class="xc-foot">${!XC.loading ? '<button class="btn small ghost" type="button" id="xcAgain">换一条</button>' : ''}
        ${XC.style ? `<small>风格照 <code>${esc(XC.style)}</code>，在 Obsidian 里直接改，下次就照新的写。</small>` : ''}</div>
    </form>`;
  const count = (i) => {
    const t = $(`[data-xc-text="${i}"]`, d).value;
    const n = weight(t);
    const over = n > lim;
    $(`[data-xc-count="${i}"]`, d).textContent = `${n} / ${lim}${over ? ' · 太长，接口发不了' : ''}`;
    $(`[data-xc-count="${i}"]`, d).classList.toggle('bad', over);
    $(`[data-xc-send="${i}"]`, d).hidden = over;
    $(`[data-xc-copy="${i}"]`, d).hidden = !over;
    $(`[data-xc-manual="${i}"]`, d).hidden = !over;
  };
  XC.posts.forEach((_, i) => { if (!XC.loading && !XC.error) { count(i); $(`[data-xc-text="${i}"]`, d).oninput = () => count(i); } });
  const textOf = (i) => $(`[data-xc-text="${i}"]`, d).value.trim();
  const done = (i, msg) => {
    XC.posts.splice(i, 1);
    toast(msg);
    if (!XC.posts.length) d.close(); else xcPaint();
  };
  $$('[data-xc-send]', d).forEach((b) => (b.onclick = async () => {
    const i = Number(b.dataset.xcSend);
    b.disabled = true;
    try {
      const quote = XC.payload && XC.payload.quote ? { quote_url: XC.payload.url } : {};
      const r = await api('/api/xline/post', { method: 'POST', body: { text: textOf(i), source_id: XC.sid, ...quote } });
      done(i, r.post && r.post.url ? `发出去了：${r.post.url}` : '发出去了');
    } catch (err) { toast(err.message); b.disabled = false; }
  }));
  $$('[data-xc-copy]', d).forEach((b) => (b.onclick = async () => {
    try { await navigator.clipboard.writeText(textOf(Number(b.dataset.xcCopy))); toast('复制好了，去 X 贴上发；发完点「我发了」'); } catch (_) { toast('复制不了：手动选中复制'); }
  }));
  $$('[data-xc-manual]', d).forEach((b) => (b.onclick = async () => {
    const i = Number(b.dataset.xcManual);
    try { await api('/api/xline/posted', { method: 'POST', body: { text: textOf(i), source_id: XC.sid } }); done(i, '记下了：今天又发了一条'); } catch (err) { toast(err.message); }
  }));
  const again = $('#xcAgain', d);
  if (again) again.onclick = () => xcLoad();
}

async function xcLoad() {
  const payload = XC.payload;
  XC.loading = true; XC.error = null; XC.posts = [];
  xcPaint();
  try {
    const r = await api('/api/xline/suggest', { method: 'POST', body: payload });
    if (XC.payload !== payload) return;  // 等的时候关掉了、换了一条
    Object.assign(XC, { posts: r.posts, sid: r.source_id, own: r.own, style: r.style || XC.style });
    if (r.style_new) toast('第一次用：按你发过的内容总结了一份风格，存在 Obsidian 里，可以改');
  } catch (err) {
    if (XC.payload !== payload) return;
    XC.error = err.message;
  }
  XC.loading = false;
  xcPaint();
}

function xcOpen(payload, title) {
  Object.assign(XC, { payload, title, own: payload.kind === 'note' && /^003_/.test(payload.path || '') });
  xcDialog().showModal();
  xcLoad();
}

// 抢在行自己的点击（打开笔记）前面接住：按钮在可点的行里面
document.addEventListener('click', (e) => {
  const b = e.target.closest && e.target.closest('[data-xc]');
  if (!b) return;
  e.stopPropagation();
  e.preventDefault();
  xcOpen(JSON.parse(b.dataset.xc), b.dataset.xcTitle);
}, true);
