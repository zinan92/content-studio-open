/* 产品（10/7 作品页起步；10/9 变现流程板拆开）：左栏「产品」一组，一个产品一个 tab，每页六段：产品 / 报价 / 收款 / 流量入口 / 投放 / 漏斗。
 * 有网址的每天第一次打开时后台截第一屏（电脑 / 手机按产品选），能翻以前的样子；没网址的（小程序）传截图。
 * 清单在本机配置里，这页上加、改、删；代码里不写死任何一个产品。 */
window.VIEWS = window.VIEWS || {};

const PROD = { data: null, day: null, editing: null, timer: null, reach: null };
const PROD_VIEWS = [['desktop', '电脑'], ['mobile', '手机']];

function prodShotUrl(p, v) {
  return `/api/products/${p.key}/shot/${p.shot.day}/${v}.png?t=${encodeURIComponent(p.shot.at || '')}`;
}

function prodFigure(src, label, { wide = false, del = '' } = {}) {
  return `<figure class="pd-fig${wide ? ' wide' : ''}"><a href="${src}" target="_blank" rel="noopener"><img src="${src}" alt="${esc(label)}" loading="lazy"></a>
    <figcaption><span>${esc(label)}</span>${del ? `<button type="button" class="linklike" data-pd-del="${esc(del)}">删掉</button>` : ''}</figcaption></figure>`;
}

const PROD_STATUS = [['live', '已上线'], ['demo', '演示'], ['off', '没上线']];

function prodForm(p) {
  const row = p || { name: '', for: '', url: '', views: ['desktop', 'mobile'], status: '', price: '', pay_channel: '', pay_link: '', landing: '', keyword: '', ad_plan: '', ad_budget: 0 };
  const field = (name, label, ph, extra = '') => `<label><span>${label}</span><input name="${name}" value="${esc(row[name] || '')}" placeholder="${esc(ph)}"${extra}></label>`;
  return `<form class="panel pd-form" id="pdForm">
    <label><span>名字</span><input name="name" required maxlength="40" value="${esc(row.name)}" placeholder="比如：轻练"></label>
    ${field('for', '给谁用', '比如：健身教练', ' maxlength="60"')}
    ${field('url', '体验链接', '有网址的每天截一次；小程序这类截不到的空着，传截图')}
    <label><span>状态</span><select name="status"><option value="">没填</option>${PROD_STATUS.map(([v, l]) => `<option value="${v}"${row.status === v ? ' selected' : ''}>${l}</option>`).join('')}</select></label>
    <fieldset><span>截哪几种</span>${PROD_VIEWS.map(([v, l]) => `<label class="pd-check"><input type="checkbox" name="views" value="${v}"${row.views.includes(v) ? ' checked' : ''}>${l}</label>`).join('')}</fieldset>
    ${field('price', '报价', '只写你说过的价格，空着就是「待定」', ' maxlength="200"')}
    ${field('pay_channel', '收款通道', '比如：Stripe、微信支付、支付宝', ' maxlength="40"')}
    ${field('pay_link', '付款链接', '贴你已经接好的付款链接')}
    ${field('landing', '落地页', '网站上这个产品的那一页')}
    ${field('keyword', '私信关键词', '比如：天机', ' maxlength="20"')}
    ${field('ad_plan', '投放计划', '投哪条、在哪投；先不投就写先不投', ' maxlength="300"')}
    <label><span>投放预算（每周，元）</span><input name="ad_budget" type="number" min="0" step="1" value="${row.ad_budget || ''}" placeholder="0"></label>
    <div class="pd-form-actions"><button class="btn primary" type="submit">${p ? '保存' : '加上'}</button>
      ${PROD.data && PROD.data.products.length ? '<button class="btn" type="button" id="pdCancel">取消</button>' : ''}
      ${p ? '<button class="linklike bad" type="button" id="pdRemove">从产品里拿掉</button>' : ''}</div>
  </form>`;
}

function prodShots(p) {
  if (!p.url) return '';
  const s = p.shot;
  if (!s) return p.running ? '<div class="panel empty"><span class="spin"></span><span>第一次截图，十几秒…</span></div>' : '';
  const latest = p.days[0] === s.day;
  const figs = PROD_VIEWS.filter(([v]) => s.variants.includes(v)).map(([v, l]) => prodFigure(prodShotUrl(p, v), `${l} · 第一屏`, { wide: v === 'desktop' })).join('');
  return `<div class="pt-meta">
      <span>${latest ? '最新一次' : '以前的样子'} · 截于 ${esc(portalTime(s.at))}${s.url && s.url !== p.url ? ' · 那时的网址是 ' + esc(s.url) : ''}</span>
      ${p.running && latest ? '<span><span class="spin"></span> 正在重新截…</span>' : ''}
      ${s.error ? `<span class="bad">这次没截成：${esc(s.error)}</span>` : ''}
    </div>
    ${figs ? `<div class="pd-gallery">${figs}</div>` : ''}
    ${p.days.length > 1 ? `<div class="pt-days"><small>以前的样子</small>${p.days.map((day) => `<button type="button" class="${day === s.day ? 'on' : ''}" data-pd-day="${day}">${day.slice(5).replace('-', '/')}</button>`).join('')}</div>` : ''}`;
}

function prodUploads(p) {
  if (!p.uploads.length) {
    return p.url ? '' : '<div class="panel empty pd-drop"><b>还没有截图</b><span>没网址的（比如小程序）截不到，点「传截图」或者把图拖进来</span></div>';
  }
  const figs = p.uploads.map((n) => prodFigure(`/api/products/${p.key}/uploads/${encodeURIComponent(n)}`, n.replace(/\.[^.]+$/, ''), { del: n })).join('');
  return `<section class="pd-section pd-drop">${p.url ? '<h3>传的截图</h3>' : ''}<div class="pd-gallery">${figs}</div></section>`;
}

const prodYuan = (n) => `¥${Number(n || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
const prodMd = (day) => day.slice(5).replace('-', '/');

function prodLink(url, empty) {
  return url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(url.replace(/^https?:\/\//, ''))}</a>` : `<span class="pd-todo">${empty}</span>`;
}

function prodSec(n, title, body, who = '') {
  return `<section class="panel pd-sec"><h3><span class="num">${n}</span>${title}${who ? `<small>${who}</small>` : ''}</h3>${body}</section>`;
}

/* 带它的内容（#590）：「标题和封面」① 里选了这个产品的那几条，触达读汇总表那一列（累计，发到哪都算） */
function prodContent(p) {
  const rows = p.content || [];
  if (!rows.length) return '<span class="pd-todo">还没有。在「标题和封面」① 选「带哪个产品」</span>';
  const reach = PROD.reach || {};
  const total = rows.reduce((n, r) => n + (reach[r.topic_id] || 0), 0);
  return `<ul class="pd-content">${rows.map((r) => `<li><span>${esc(r.title)}</span><span class="num">${PROD.reach ? (r.topic_id in reach ? reach[r.topic_id].toLocaleString('zh-CN') : '还没发') : '…'}</span></li>`).join('')}</ul>
    ${PROD.reach ? `<p class="pd-note">${rows.length} 条一共触达 <b class="num">${total.toLocaleString('zh-CN')}</b>（汇总表里的累计数）</p>` : ''}`;
}

async function prodLoadReach() {
  try {
    const m = await api('/api/outbox/matrix?limit=500');
    PROD.reach = Object.fromEntries((m.rows || []).filter((r) => r.topic_id != null).map((r) => [r.topic_id, Number(r.total) || 0]));
  } catch (_) { PROD.reach = {}; }
}

function prodSix(p) {
  const m = p.money || { month: 0, count: 0, last: null, weeks: [] };
  const status = (PROD_STATUS.find(([v]) => v === p.status) || [])[1];
  const product = `<dl class="pd-kv"><dt>给谁用</dt><dd>${p.for ? esc(p.for) : '<span class="pd-todo">没填</span>'}</dd>
      <dt>状态</dt><dd>${status ? `<span class="pd-status ${p.status}">${status}</span>` : '<span class="pd-todo">没填</span>'}</dd>
      <dt>体验链接</dt><dd>${prodLink(p.url, '没有网址，看下面的截图')}</dd></dl>
    ${prodShots(p)}${prodUploads(p)}`;
  const price = `<p class="pd-price">${p.price ? esc(p.price) : '待定'}</p><p class="pd-note">只写你亲口说过的价格。</p>`;
  const pay = `<dl class="pd-kv"><dt>通道</dt><dd>${p.pay_channel ? esc(p.pay_channel) : '<span class="pd-todo">没填</span>'}</dd>
      <dt>付款链接</dt><dd>${prodLink(p.pay_link, '没填')}</dd>
      <dt>本月</dt><dd><b class="num">${prodYuan(m.month)}</b> · ${m.count} 笔</dd>
      <dt>最近一笔</dt><dd>${m.last ? `${prodMd(m.last.day)} ${prodYuan(m.last.amount)}${m.last.note ? ' · ' + esc(m.last.note) : ''}` : '<span class="pd-todo">还没有。收了钱在「战况」收入那张卡里「记一笔」，来源选这个产品</span>'}</dd></dl>`;
  const traffic = `<dl class="pd-kv"><dt>落地页</dt><dd>${prodLink(p.landing, '还没有')}</dd>
      <dt>私信关键词</dt><dd>${p.keyword ? `「${esc(p.keyword)}」` : '<span class="pd-todo">没填</span>'}</dd>
      <dt>带它的内容</dt><dd>${prodContent(p)}</dd></dl>`;
  const ads = `<dl class="pd-kv"><dt>计划</dt><dd>${p.ad_plan ? esc(p.ad_plan) : '<span class="pd-todo">没填</span>'}</dd>
      <dt>每周预算</dt><dd>${p.ad_budget ? prodYuan(p.ad_budget) : '¥0'}</dd></dl><p class="pd-note">工作台只出计划和预算，花钱你自己按。</p>`;
  const weeks = m.weeks || [];
  const funnel = `<div class="pd-funnel"><table><thead><tr><th>这一周</th><th>触达</th><th>进落地页</th><th>私信</th><th>付款</th><th>收入</th></tr></thead>
      <tbody>${weeks.map((w) => `<tr><td>${prodMd(w.week)} 起</td><td class="pd-todo">—</td><td class="pd-todo">—</td><td class="pd-todo">—</td><td class="num">${w.paid}</td><td class="num">${prodYuan(w.amount)}</td></tr>`).join('')}</tbody></table></div>
    <p class="pd-note">付款和收入来自你记的账；触达、落地页、私信还没接上，接上以前写「—」，不估。</p>`;
  return prodSec('①', '产品', product)
    + `<div class="pd-grid">${prodSec('②', '报价', price, '你定')}${prodSec('③', '收款', pay, 'Wendy')}${prodSec('④', '流量入口', traffic, 'Anna')}${prodSec('⑤', '投放', ads, '你按')}</div>`
    + prodSec('⑥', '漏斗', funnel, 'Wendy · 按周');
}

function prodPage(d) {
  const p = d.product;
  if (!d.products.length || PROD.editing === 'new') {
    return `<header class="page-h"><div><div class="stage-eyebrow">产品</div><h1>${d.products.length ? '加一个产品' : '产品'}</h1>
        <p>每个产品一页：产品、报价、收款、流量入口、投放、漏斗。${d.products.length ? '' : '还没有产品，先加一个。'}</p></div></header>${prodForm(null)}`;
  }
  const actions = `${p.url ? `<a class="btn" href="${esc(p.url)}" target="_blank" rel="noopener">打开</a>
      <button class="btn" type="button" id="pdRefresh"${p.running ? ' disabled' : ''}>${p.running ? '正在截…' : '重新截'}</button>` : ''}
    <label class="btn">传截图<input type="file" id="pdFile" accept="image/png,image/jpeg,image/webp" multiple hidden></label>
    <button class="btn" type="button" id="pdEdit">${PROD.editing === p.key ? '收起' : '改'}</button>`;
  return `<header class="page-h"><div><div class="stage-eyebrow">产品</div><h1>${esc(p.name)}</h1>
      <p>${p.for ? `给${esc(p.for)}。` : ''}报价、收款、入口都在这一页改；价格只写你说过的。</p></div>
      <div class="page-h-actions">${actions}</div></header>
    ${PROD.editing === p.key ? prodForm(p) : ''}
    ${prodSix(p)}`;
}

/* 左栏「产品」一组：照本机产品清单画，一个产品一个 tab；加产品不改代码。 */
window.paintProductRail = async function paintProductRail() {
  const box = $('#railProducts');
  if (!box) return;
  let rows = [];
  try { rows = (await api('/api/products?list=1')).products || []; } catch (_) { return; }
  box.innerHTML = rows.map((r) => `<button type="button" class="ri" data-view="products" data-key="${esc(r.key)}" data-feature="products" title="${esc(r.for ? `${r.name} · 给${r.for}` : r.name)}"><span>${esc(r.name)}</span></button>`).join('')
    + '<button type="button" class="ri ri-add" id="railProductAdd" data-feature="products"><span>＋ 加一个</span></button>';
  if (window.bindNav) window.bindNav();
  const add = $('#railProductAdd');
  if (add) add.onclick = () => { PROD.editing = 'new'; S.productKey = null; go('products'); };
  if (typeof paintChrome === 'function' && S.view) paintChrome(S.view);
};

async function prodSend(path, init = {}) {
  PROD.data = await api(path, init);
  return PROD.data;
}

async function prodUpload(key, files) {
  const list = [...files].filter((f) => /^image\//.test(f.type));
  if (!list.length) { toast('只收图片'); return; }
  const body = new FormData();
  list.forEach((f) => body.append('file', f));
  toast(`正在传 ${list.length} 张…`);
  try {
    const res = await fetch(`/api/products/${key}/uploads`, { method: 'POST', body, headers: { 'X-Content-Studio': '1' } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || `上传失败（${res.status}）`);
    PROD.data = data;
    toast(`传好了 ${list.length} 张`);
  } catch (err) { toast(err.message); }
  window.VIEWS.products.render();
}

window.VIEWS.products = {
  async render() {
    const body = $('#productsBody');
    if (!PROD.data) body.innerHTML = '<div class="panel empty"><span class="spin"></span><span>正在读…</span></div>';
    let d;
    const want = S.productKey;
    try {
      d = await prodSend(`/api/products?${new URLSearchParams({ ...(want ? { key: want } : {}), ...(PROD.day ? { day: PROD.day } : {}) })}`);
    } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    if (S.view !== 'products' || S.productKey !== want) return;
    const p = d.product;
    if (p && !S.productKey && PROD.editing !== 'new') { S.productKey = p.key; paintChrome('products'); }
    if (p && (p.content || []).length && !PROD.reach) prodLoadReach().then(() => { if (S.view === 'products') window.VIEWS.products.render(); });
    body.innerHTML = prodPage(d);
    clearTimeout(PROD.timer);
    if (p && p.running) PROD.timer = setTimeout(() => { if (S.view === 'products') window.VIEWS.products.render(); }, 5000);

    const form = $('#pdForm');
    if (form) {
      form.onsubmit = async (e) => {
        e.preventDefault();
        const f = new FormData(form);
        const row = { views: f.getAll('views') };
        ['name', 'for', 'url', 'status', 'price', 'pay_channel', 'pay_link', 'landing', 'keyword', 'ad_plan'].forEach((k) => (row[k] = f.get(k) || ''));
        row.ad_budget = Number(f.get('ad_budget') || 0);
        const editing = PROD.editing;
        try {
          if (editing === 'new' || !p) await prodSend('/api/products', { method: 'POST', body: row });
          else await prodSend(`/api/products/${p.key}`, { method: 'PUT', body: row });
        } catch (err) { toast(err.message); return; }
        PROD.editing = null; PROD.day = null;
        S.productKey = PROD.data.product ? PROD.data.product.key : null;
        await window.paintProductRail();
        go('products');
      };
      const cancel = $('#pdCancel');
      if (cancel) cancel.onclick = () => { PROD.editing = null; window.VIEWS.products.render(); };
      const remove = $('#pdRemove');
      if (remove) remove.onclick = async () => {
        if (!confirm(`把「${p.name}」从产品里拿掉？截过、传过的图还留在本机文件夹里，记过的收入也还在账上。`)) return;
        try { await prodSend(`/api/products/${p.key}`, { method: 'DELETE' }); } catch (err) { toast(err.message); return; }
        PROD.editing = null; S.productKey = null;
        await window.paintProductRail();
        go('products');
      };
    }
    if (!p || PROD.editing === 'new') return;

    $('#pdEdit').onclick = () => { PROD.editing = PROD.editing === p.key ? null : p.key; window.VIEWS.products.render(); };
    $('#pdFile').onchange = (e) => prodUpload(p.key, e.target.files);
    const refresh = $('#pdRefresh');
    if (refresh) refresh.onclick = async () => {
      refresh.disabled = true;
      PROD.day = null;
      try { await prodSend(`/api/products/${p.key}/refresh`, { method: 'POST' }); toast('开始重新截'); } catch (err) { toast(err.message); }
      window.VIEWS.products.render();
    };
    $$('[data-pd-day]', body).forEach((b) => (b.onclick = () => {
      PROD.day = b.dataset.pdDay === p.days[0] ? null : b.dataset.pdDay;
      window.VIEWS.products.render();
    }));
    $$('[data-pd-del]', body).forEach((b) => (b.onclick = async () => {
      if (!confirm(`删掉这张截图？\n${b.dataset.pdDel}`)) return;
      try { await prodSend(`/api/products/${p.key}/uploads/${encodeURIComponent(b.dataset.pdDel)}`, { method: 'DELETE' }); } catch (err) { toast(err.message); return; }
      window.VIEWS.products.render();
    }));
    // 横图（电脑那种）占一整行，竖图（手机）一排排着
    $$('.pd-fig img', body).forEach((img) => {
      const mark = () => img.closest('.pd-fig').classList.toggle('wide', img.naturalWidth > img.naturalHeight);
      if (img.complete && img.naturalWidth) mark(); else img.addEventListener('load', mark, { once: true });
    });
    $$('.pd-drop', body).forEach((zone) => {
      zone.ondragover = (e) => { e.preventDefault(); zone.classList.add('over'); };
      zone.ondragleave = () => zone.classList.remove('over');
      zone.ondrop = (e) => { e.preventDefault(); zone.classList.remove('over'); prodUpload(p.key, e.dataTransfer.files); };
    });
  },
};

document.addEventListener("DOMContentLoaded", () => window.paintProductRail());
