/* 定位页 = 工作台首页：公司 one pager，原生画在这一页里。
 * 内容来自 作者自己的 positioning.json（和 principles.md 放一起，不进仓库）；
 * 没有 json 时退回渲染 positioning.md。工作台唯一会写的地方是「待拍板」。
 * 10/6 作者：照 Codex 的稿子（studio-design-preview）做，一模一样，再加一点 monday.com 那样的彩色元素。
 * 版式在这里，字在 positioning.json（page / tabs / flow 和各块的字）；别人的 json 没有这些键时退回老字段。 */
window.VIEWS = window.VIEWS || {};

const POS = { data: null, loading: false, tab: 'overview' };

async function loadPositioning() {
  POS.loading = true;
  try { POS.data = await api('/api/positioning'); } finally { POS.loading = false; }
}
window.reloadPositioning = async () => { try { await loadPositioning(); } catch (_) { /* shown on next render */ } if (S.view === 'positioning') renderView(); };

function posUpdated(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

// 10/7 加「我的形象」：头像、全身、四视图、水印和配图里画过的自己（persona.js 画，原来在设置里）
const POS_TABS = [['overview', '定位三问'], ['growth', '增长飞轮'], ['difference', '差异化'], ['offers', '服务与定价'], ['profile', '对外简介'], ['principles', '原则与自测'], ['persona', '我的形象']];
POS.tab = (() => { try { return localStorage.getItem('cs-pos-tab') || 'overview'; } catch (_) { return 'overview'; } })();
window.POS_TAB_KEYS = POS_TABS.map(([k]) => k);

/* 几个线条图标（不接图标库）：飞轮五步、状态、复制 */
const POS_ICON = {
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3z"/>',
  eye: '<path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  funnel: '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
  hand: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.2-4 4.3-6 8-6s6.8 2 8 6"/>',
  files: '<path d="M8 3h8l4 4v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M15 3v5h5M9 13h6M9 17h4"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  cycle: '<path d="M20 12a8 8 0 0 1-14 5.3M4 12a8 8 0 0 1 14-5.3"/><path d="M18 3v4h-4M6 21v-4h4"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
};
const posIcon = (name, cls = '') => `<svg class="pi ${cls}" viewBox="0 0 24 24" aria-hidden="true">${POS_ICON[name] || POS_ICON.files}</svg>`;
const posLines = (s) => esc(s || '').replace(/\n/g, '<br>');
const posPill = (text) => (text ? `<span class="pos-pill">${posIcon('check')}${esc(text)}</span>` : '');

/* 每页的抬头（小字 · 大标题 · 一句话）：字在 tabs.<页>，没有就用页签名 */
function posLead(t, fallback) {
  const x = t || {};
  return `<div class="pos-lead">${x.eyeline ? `<div class="pos-eyeline">${esc(x.eyeline)}</div>` : ''}<h2>${posLines(x.h1 || fallback)}</h2>${x.lead ? `<p>${esc(x.lead)}</p>` : ''}</div>`;
}
function posSecHead(title, sub, meta = '') {
  return `<div class="pos-sh"><div><h3>${esc(title)}</h3>${sub ? `<p>${esc(sub)}</p>` : ''}</div>${meta}</div>`;
}

/* 飞轮：一排五步，客户那一格亮着；下面一行「素材再成为视频」，再下面博主渠道 */
function posFlow(p, compact) {
  const f = p.flow || { nodes: (p.flywheel ? p.flywheel.nodes : []).map((n) => ({ t: n.t, s: n.s })) };
  const icons = ['video', 'eye', 'funnel', 'hand', 'files'];
  const steps = f.nodes.map((n, i) => `${i ? `<span class="pos-flow-arrow">${posIcon('arrow')}</span>` : ''}
    <div class="pos-flow-step tone-${i + 1} ${n.hot ? 'hot' : ''}"><span class="pos-tile">${posIcon(n.icon || icons[i])}</span><b>${esc(n.t)}</b><small>${esc(n.s)}</small></div>`).join('');
  const br = f.branch;
  return `<div class="pos-flow ${compact ? 'compact' : ''}">
    <div class="pos-flow-track">${steps}</div>
    ${f.return ? `<div class="pos-flow-return">${posIcon('cycle')}<span>${esc(f.return)}</span></div>` : ''}
    ${br ? `<div class="pos-flow-branch"><span>${esc(br.label)}</span><span class="pos-branch-steps">${br.steps.map((x, i) => `${i ? posIcon('arrow') : ''}<b>${esc(x)}</b>`).join('')}</span></div>` : ''}
  </div>`;
}

function posOverview(p, d) {
  const c = p.company;
  const t = (p.tabs || {}).overview || {};
  const pend = d.proposals || [];
  const status = t.status || ((p.questions[p.questions.length - 1] || {}).status);
  const qs = p.questions.map((q, i) => `<article class="pos-question">
      <span class="pos-num tone-${i + 1}">0${i + 1}</span>
      <div><div class="pos-q-label">${esc(q.label || String(q.k || '').replace(/^.+?·\s*/, ''))}</div>
        <h3>${esc(q.title)}</h3><p>${esc(q.body)}</p>${q.bold ? `<span class="pos-note-line">${esc(q.bold)}</span>` : ''}</div>
    </article>`).join('');
  return `
    <div class="pos-card-head"><h2>${esc(t.title || '核心定位')}</h2>${posPill(status)}</div>
    <div class="pos-identity"><h2>${esc(c.core_title || c.tagline_lead || c.name)}</h2><p>${esc(c.core_line || c.tagline || '')}</p></div>
    <div class="pos-questions">${qs}</div>
    <div class="pos-entry"><span>对外的统一入口</span><b>私信「${esc(c.keyword)}」</b><button class="pos-text-btn" type="button" id="posCopyKw">${posIcon('copy')}复制</button></div>
    ${pend.length ? `<div class="pos-divider"></div>${posSecHead('待拍板', `有 ${pend.length} 条建议，采纳的自己挪进上面正文`)}
      <div class="pos-pend">${pend.map((x) => `<div class="pos-chip"><span>${esc(x.text)}</span><small>${esc(x.at)}${x.source ? ' · ' + esc(x.source) : ''}</small><button class="linklike" type="button" data-pos-drop="${esc(x.id)}">不采纳</button></div>`).join('')}</div>` : ''}
    <div class="pos-divider"></div>
    ${posSecHead(t.flow_title || '增长飞轮', t.flow_sub || '', `<button class="pos-text-btn" type="button" data-pos-tab="growth">展开查看 ${posIcon('arrow')}</button>`)}
    ${posFlow(p, true)}`;
}

function posGrowth(p) {
  const t = (p.tabs || {}).growth || {};
  return `${posLead(t, '增长飞轮')}
    ${posFlow(p, false)}
    <div class="pos-values">${p.creed.map((x, i) => `<article class="tone-${i + 1}"><h3>${esc(x.h)}${esc(x.hi)}</h3><p>${esc(x.p)}</p></article>`).join('')}</div>
    <div class="pos-divider"></div>
    ${posSecHead(t.steps_title || '从第一单走起来', t.steps_sub || '')}
    <ol class="pos-seq">${p.bootstrap.map((x, i) => `<li><span class="pos-num tone-${(i % 5) + 1}">${i + 1}</span><div><b>${esc(x.b)}</b><p>${esc(x.s)}</p></div></li>`).join('')}</ol>`;
}

function posDifference(p) {
  const t = (p.tabs || {}).difference || {};
  return `${posLead(t, '差异化')}
    <div class="pos-questions">${p.diff.map((x, i) => `<article class="pos-question"><span class="pos-num tone-${i + 1}">0${i + 1}</span>
      <div><div class="pos-q-label">${esc(x.vs)}</div><h3>${esc(x.h)}</h3><p>${esc(x.p)}</p></div></article>`).join('')}</div>`;
}

function posOffers(p) {
  const t = (p.tabs || {}).offers || {};
  const rows = p.pricing.rows.map((r) => `<tr><td class="svc"><i class="pos-dot tone-${esc(r.tone || 'base')}"></i>${esc(r.role)}</td>
      <td><span class="pos-price tone-${esc(r.tone || 'base')}">${esc(r.price)}</span></td><td class="unit">${esc(r.unit || '')}</td><td>${esc(r.what)}</td></tr>`).join('');
  return `${posLead({ eyeline: t.eyeline, h1: t.h1 || '服务与定价', lead: t.lead || p.pricing.sub }, '服务与定价')}
    ${t.note ? `<div class="pos-offer-note"><span class="pos-tile tone-4">${posIcon('hand')}</span><span>${esc(t.note)}</span></div>` : ''}
    <div class="pos-table"><table>
      <thead><tr><th>服务</th><th>价格</th><th>规格</th><th>交付内容</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <p class="pos-foot">${esc(p.pricing.note)}</p>
    <div class="pos-divider"></div>
    ${posSecHead(t.products_title || '产品线', t.products_sub || '')}
    <div class="pos-products">${p.products.map((x) => `<div><b>${esc(x.b)}</b><span>${esc(x.s)}</span><small class="pos-tag ${x.first ? 'hot' : ''}">${esc(x.first ? (x.em || '先卖这一条') : (x.tag || '作品集'))}</small></div>`).join('')}</div>`;
}

function posPrinciples(p) {
  const t = (p.tabs || {}).principles || {};
  const items = p.selftest.items;
  const done = items.filter((_, i) => POS.checks.includes(i)).length;
  return `${posLead(t, '原则与自测')}
    <div class="pos-check">
      <div class="pos-check-head"><h3>${esc(t.check_title || '这周的四个问题')}</h3><span>${done} / ${items.length} 已检查</span></div>
      <div class="pos-progress"><i data-done="${done}" data-total="${items.length}"></i></div>
      ${items.map((q, i) => `<label class="${POS.checks.includes(i) ? 'on' : ''}"><input type="checkbox" data-pos-check="${i}" ${POS.checks.includes(i) ? 'checked' : ''}><span>${esc(q)}</span></label>`).join('')}
    </div>
    ${posSecHead(t.principles_title || '通用原则', t.principles_sub || '')}
    <ol class="pos-principles">${p.principles.map((x, i) => `<li><span class="pos-num small tone-${(i % 5) + 1}">0${i + 1}</span><p>${esc(x.b)}${esc(x.s)}</p></li>`).join('')}</ol>`;
}

/* 自测四个勾：只存在这台电脑上，按周记（换一周就清空） */
function posWeek() { const d = new Date(); const day = (d.getDay() + 6) % 7; d.setDate(d.getDate() - day); return d.toLocaleDateString('sv-SE'); }
POS.checks = (() => { try { const x = JSON.parse(localStorage.getItem('cs-pos-checks') || '{}'); return x.week === posWeek() ? x.done || [] : []; } catch (_) { return []; } })();

function posPage(d) {
  const p = d.data;
  const pg = p.page || {};
  const tab = POS.tab;
  const body = tab === 'growth' ? posGrowth(p) : tab === 'difference' ? posDifference(p) : tab === 'offers' ? posOffers(p)
    : tab === 'principles' ? posPrinciples(p) : tab === 'profile' ? posLead((p.tabs || {}).profile, '对外简介')
    : tab === 'persona' ? '<div id="personaBody" class="pos-persona"></div>' : posOverview(p, d);
  const boss = (S.state && S.state.brand && S.state.brand.boss) || 'Wendy';
  return `<div class="pos">
    <header class="pos-page-head">
      <div><div class="pos-eyeline">${esc(pg.eyeline || '定位')}</div><h1>${esc(pg.h1 || p.company.name)}</h1><p>${esc(pg.lead || `${p.company.tagline_lead || ''}${p.company.tagline || ''}`)}</p></div>
      <div class="pos-actions"><button class="btn" type="button" id="posCopyBio">复制对外简介</button><button class="btn" type="button" id="posAskBoss">问 ${esc(boss)}</button>
        <button class="pos-text-btn faint" type="button" id="posReload" title="${esc(d.path.replace(/positioning\.md$/, 'positioning.json'))}">重新读</button></div>
    </header>
    <nav class="subnav pos-tabs" aria-label="定位">${POS_TABS.map(([k, l]) => `<button type="button" class="${tab === k ? 'on' : ''}" data-pos-tab="${k}">${l}</button>`).join('')}</nav>
    <div class="pos-doc-card ${tab === 'profile' ? 'with-profile' : ''}">${body}<div id="profilesSlot"></div></div>
  </div>`;
}

window.VIEWS.positioning = {
  async render() {
    const body = $('#positioningBody');
    const profiles = $('#profilesBody');
    if (body.contains(profiles)) $('#v-positioning').appendChild(profiles);  // 上次挪进卡里了：先拿出来，免得重画时被冲掉
    if (!POS.data && !POS.loading) {
      body.innerHTML = '<div class="panel empty"><span class="spin"></span><span>正在读定位…</span></div>';
      try { await loadPositioning(); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    }
    const d = POS.data;
    if (!d) return;
    if (!window.POS_TAB_KEYS.includes(POS.tab)) POS.tab = 'overview';
    if (d.data) {
      body.innerHTML = posPage(d);
      // 对外简介画进当前这张卡里（profiles.js 画到 #profilesBody，这里把它挪进来）
      const slot = $('#profilesSlot', body);
      if (POS.tab === 'profile') { slot.appendChild(profiles); profiles.hidden = false; } else { profiles.hidden = true; }
    } else if (d.exists) {
      // 没有 json：退回渲染 Markdown（老形态），对外简介照旧在下面
      body.innerHTML = `<div class="pos"><article class="panel pos-doc"><div class="md">${renderMarkdown(d.markdown)}</div></article>
        <div class="pos-bar"><span class="pos-bar-meta"><code>${esc(d.path)}</code> 改于 ${posUpdated(d.updated)} <button class="linklike" type="button" id="posReload">重新读</button></span></div></div>`;
      body.after(profiles);
      profiles.hidden = false;
    } else {
      body.innerHTML = `<div class="panel empty"><b>还没有定位文件。</b><span>在编辑器里新建 <code>${esc(d.path)}</code>，写下三问：我是谁、怎么找到客户、卖什么。</span></div>`;
      profiles.hidden = true;
      return;
    }
    if (!profiles.hidden && window.renderProfiles) window.renderProfiles();
    if (POS.tab === 'persona' && window.renderPersona) window.renderPersona();
    $('#posReload').onclick = () => window.reloadPositioning();
    $$('[data-pos-tab]', body).forEach((b) => (b.onclick = () => {
      POS.tab = b.dataset.posTab;
      try { localStorage.setItem('cs-pos-tab', POS.tab); } catch (_) { /* ignore */ }
      if (location.hash !== `#positioning/${POS.tab}`) history.replaceState(null, '', `#positioning/${POS.tab}`);
      window.scrollTo(0, 0);
      renderView();
    }));
    const copy = async (text, what) => { try { await navigator.clipboard.writeText(text); toast(`复制了${what}`); } catch (_) { toast('复制不了，手动选一下'); } };
    const kw = $('#posCopyKw', body);
    if (kw) kw.onclick = () => copy(d.data.company.keyword, `：${d.data.company.keyword}`);
    const bio = $('#posCopyBio', body);
    if (bio) bio.onclick = async () => {
      try {
        const pf = (typeof PFX !== 'undefined' && PFX.data) || await api('/api/profile');
        const first = pf.variants[0];
        copy((pf.profile.variants[first.key] || {}).bio || '', `${first.label}的简介`);
      } catch (err) { toast(err.message); }
    };
    const ask = $('#posAskBoss', body);
    if (ask) ask.onclick = () => { if (window.openWendy) window.openWendy(); };
    // 进度条宽度：按勾了几个画（不在 JS 里拼 style=）
    $$('.pos-progress i', body).forEach((bar) => { bar.style.width = `${Math.round((Number(bar.dataset.done) / Math.max(1, Number(bar.dataset.total))) * 100)}%`; });
    $$('[data-pos-check]', body).forEach((box) => (box.onchange = () => {
      const i = Number(box.dataset.posCheck);
      POS.checks = box.checked ? [...new Set([...POS.checks, i])] : POS.checks.filter((x) => x !== i);
      try { localStorage.setItem('cs-pos-checks', JSON.stringify({ week: posWeek(), done: POS.checks })); } catch (_) { /* ignore */ }
      renderView();
    }));
    $$('[data-pos-drop]', body).forEach((b) => (b.onclick = async () => {
      if (!confirm('把这一条从待拍板里删掉？')) return;
      try { await api(`/api/positioning/${b.dataset.posDrop}`, { method: 'DELETE' }); toast('已删掉'); await window.reloadPositioning(); } catch (err) { toast(err.message); }
    }));
  },
};
