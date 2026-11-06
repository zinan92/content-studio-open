// 知识树（10/18）：上面「内化」，下面是 ~/work/park-knowledge 这棵树——一枝一个领域，叶子是主干原理，果子是来源。
// 枝里的字来自别人的文章（提炼过），只用 textContent / setAttribute，不拼 HTML。
(() => {
  const $ = (id) => document.getElementById(id);
  const SVG = 'http://www.w3.org/2000/svg';
    const state = { data: null, sel: null, hot: -1, grown: false, timer: null };

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
    return el;
  }
  function s(tag, attrs, ...kids) {
    const el = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.setAttribute('class', v);
      else if (k === 'delay') el.style.setProperty('--d', `${v}ms`);
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return el;
  }

  async function api(path, body) {
    const opt = body === undefined ? {} : { method: 'POST', headers: { 'content-type': 'application/json', 'x-content-studio': '1' }, body: JSON.stringify(body) };
    const r = await fetch(path, opt);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `出错了（${r.status}）`);
    return data;
  }

  const ago = (iso) => {
    if (!iso) return '';
    const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (m < 1) return '刚刚';
    if (m < 60) return `${m} 分钟前`;
    if (m < 1440) return `${Math.round(m / 60)} 小时前`;
    return `${Math.round(m / 1440)} 天前`;
  };
  const shortName = (b) => String(b.domain || b.title || b.name).split(/\s*\/\s*/)[0];

  /* 这次刚长出来的：最近一条收完的任务改到的枝；没有任务就看 48 小时内有提交的 */
  function freshNames(d) {
    const done = (d.jobs || []).find((j) => j.status === 'done' && (j.branches || []).length);
    if (done && Date.now() - new Date(done.finished_at).getTime() < 3 * 86400000) return new Set(done.branches);
    const last = d.branches.map((b) => (b.history[0] ? b.history[0].at : '')).sort().pop();  // 只点亮最近一次长的那几枝
    if (!last || Date.now() - new Date(last).getTime() > 48 * 3600000) return new Set();
    return new Set(d.branches.filter((b) => b.history[0] && b.history[0].at === last).map((b) => b.name));
  }

  // ---------- 内化 ----------
  $('pasteToggle').addEventListener('click', () => { $('paste').hidden = !$('paste').hidden; if (!$('paste').hidden) $('paste').focus(); });
  $('form').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('msg').textContent = '';
    const input = $('input').value.trim();
    const text = $('paste').hidden ? '' : $('paste').value.trim();
    if (!input && !text) { $('msg').textContent = '贴一个链接，或者把正文粘进来'; return; }
    $('go').disabled = true;
    try {
      await api('/api/tree/internalize', { input, text });
      $('input').value = ''; $('paste').value = ''; $('paste').hidden = true;
      await load();
    } catch (err) { $('msg').textContent = err.message; }
    $('go').disabled = false;
  });

  function drawJobs(jobs) {
    const box = $('jobs');
    box.replaceChildren(...jobs.slice(0, 6).map((j) => {
      const cls = j.status === 'running' ? 'run' : j.status === 'done' ? 'done' : 'err';
      const when = j.status === 'running' ? `在读、提炼、考试…已经 ${ago(j.started_at).replace('前', '')}` : ago(j.finished_at);
      const li = h('li', { class: `kt-job ${cls}` },
        h('div', { class: 'kt-job-h' }, h('i'), h('b', { title: j.source || j.title }, j.title || j.source), h('span', {}, when),
          j.status === 'error' ? h('button', { class: 'btn', type: 'button', onclick: () => retry(j.id) }, '重试') : null));
      if (j.status === 'done' && j.receipt) li.append(h('p', { class: 'kt-receipt' }, j.receipt));
      if (j.status === 'error' && j.error) li.append(h('p', { class: 'kt-receipt' }, j.error));
      if (j.status === 'done' && (j.branches || []).length) {
        const names = new Map((state.data?.branches || []).map((b) => [b.name, shortName(b)]));
        li.append(h('div', { class: 'kt-grew' }, j.branches.map((n) => h('button', { type: 'button', onclick: () => select(n, true) }, `长在「${names.get(n) || n}」`))));
      }
      return li;
    }));
  }

  async function retry(id) {
    $('msg').textContent = '';
    try { await api(`/api/tree/jobs/${encodeURIComponent(id)}/retry`, {}); await load(); } catch (err) { $('msg').textContent = err.message; }
  }

  // ---------- 三棵树 + 地基（10/18 forest.json） ----------
  // 地基 = 通用原则（一块石头一条）；每棵树：根 = 这个领域的原则，大树杈 = 领域里的几类事，
  // 挂在大树杈上的小枝 = 收进来的分支（叶 = 主干原理，果 = 来源），树冠上方的 ◆ = 这棵树上下的注（预测）。
  const FW = 1200, FH = 640, BASE = 560, TOPY = 330, XS = [250, 680, 1010];
  const short = (b) => String(b.domain || b.title || b.name).split(/\s*\/\s*/)[0];
  const byName = () => new Map((state.data?.branches || []).map((b) => [b.name, b]));
  const fileName = (p) => String(p || '').split('/').pop().replace(/\.md$/, '');

  function drawLeaves(g, b, tip, rad, t0, on) {
    const n = b.principles.length || 1;
    b.principles.forEach((pr, k) => {
      const spread = Math.min(200, 40 + n * 24);
      const la = rad + (((k + 0.5) / n) - 0.5) * (spread * Math.PI / 180);
      const R = 24 + (k % 2) * 8;
      const lx = tip.x + R * Math.cos(la), ly = tip.y + R * Math.sin(la);
      g.append(s('line', { class: 'kt-twig', pathLength: 1, delay: t0 + 200, x1: tip.x, y1: tip.y, x2: lx, y2: ly }));
      const leaf = s('ellipse', { class: `kt-leaf${on && state.hot === k ? ' hot' : ''}`, delay: t0 + 260 + k * 25, cx: 0, cy: 0, rx: 10, ry: 5,
        onclick: (e) => { e.stopPropagation(); pick({ type: 'branch', key: b.name }, k); } }, s('title', {}, pr.title));
      g.append(s('g', { transform: `translate(${lx} ${ly}) rotate(${(la * 180) / Math.PI})` }, leaf));
    });
    b.sources.forEach((src, k) => {
      g.append(s('circle', { class: 'kt-fruit', delay: t0 + 420 + k * 40, cx: tip.x + (k - (b.sources.length - 1) / 2) * 14, cy: tip.y + 14, r: 6 },
        s('title', {}, `来源：${src.author || ''} ${src.date || ''}`.trim())));
    });
  }

  function drawOneTree(svg, t, cx, ti, fresh, names) {
    const sel = state.sel || {};
    const onTree = sel.type === 'tree' && sel.key === t.key;
    const g = s('g', { class: `kt-tree${onTree ? ' on' : ''}${sel.type && sel.type !== 'foundation' && !onTree && !(sel.type === 'branch' && t.limbs.some((l) => l.branches.includes(sel.key))) ? ' dim' : ''}` });
    const t0 = 150 + ti * 120;
    // 根：一条原则一根（最多画 14 根），扎进地基
    const roots = Math.min(14, t.principles.length);
    for (let k = 0; k < roots; k++) {
      const dx = ((k + 0.5) / roots - 0.5) * 150;
      g.append(s('path', { class: 'kt-root', pathLength: 1, delay: t0 + k * 15, d: `M${cx} ${BASE - 2} Q${cx + dx * 0.4} ${BASE + 8} ${cx + dx} ${BASE + 22 + (k % 3) * 6}` }));
    }
    g.append(s('path', { class: 'kt-trunk', pathLength: 1, delay: t0 + 80, d: `M${cx} ${BASE} C${cx - 5} ${BASE - 70} ${cx + 6} ${TOPY + 70} ${cx} ${TOPY - 4}` }));
    // 大树杈
    const n = t.limbs.length;
    t.limbs.forEach((lb, i) => {
      const span = n >= 5 ? 160 : 120, a = n === 1 ? -68 : -90 - span / 2 + (span * i) / (n - 1);
      const rad = (a * Math.PI) / 180, cos = Math.cos(rad), sin = Math.sin(rad);
      const R = (n >= 5 ? 178 : n >= 3 ? 150 : 118) - 8 * Math.abs(cos);
      const tip = { x: cx + R * cos, y: TOPY + R * sin * 0.9 };
      const base = { x: cx, y: TOPY + 44 * Math.abs(cos) };
      const empty = !lb.branches.length;
      const lt = t0 + 300 + i * 70;
      const lg = s('g', { class: `kt-limb-g${empty ? ' empty' : ''}` });
      lg.append(s('path', { class: 'kt-limb', pathLength: 1, delay: lt, d: `M${base.x} ${base.y} C${base.x + (tip.x - base.x) * 0.15} ${base.y - 50} ${tip.x - (tip.x - base.x) * 0.35} ${tip.y + 20} ${tip.x} ${tip.y}` }));
      lb.branches.forEach((name) => {
        const b = names.get(name);
        if (!b) return;
        const on = sel.type === 'branch' && sel.key === name;
        const bg = s('g', { class: `kt-br${on ? ' on' : ''}${fresh.has(name) ? ' new' : ''}`, tabindex: 0, role: 'button', 'aria-label': `${short(b)}：${b.principles.length} 条主干，${b.sources.length} 个来源` });
        bg.append(s('circle', { class: 'kt-glow', cx: tip.x, cy: tip.y, r: 26 }));
        drawLeaves(bg, b, tip, rad, lt, on);
        bg.append(s('circle', { class: 'kt-hit', cx: tip.x, cy: tip.y, r: 40 }, s('title', {}, short(b))));
        bg.addEventListener('click', (e) => { e.stopPropagation(); pick({ type: 'branch', key: name }); });
        bg.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick({ type: 'branch', key: name }); } });
        lg.append(bg);
      });
      // 名字放在枝头正上方（叶子外面），不往两边伸，最左最右的也不出框
      const ly = tip.y - (empty ? 14 : 46) - (n >= 3 && i % 2 ? 26 : 0);  // 树杈多时相邻的名字一高一低
      lg.append(s('text', { class: 'kt-label', delay: lt + 300, x: tip.x, y: ly - 14, 'text-anchor': 'middle' }, lb.name));
      lg.append(s('text', { class: 'kt-sub', delay: lt + 340, x: tip.x, y: ly + 2, 'text-anchor': 'middle' }, empty ? '还没有' : `${lb.branches.length} 枝`));
      g.append(lg);
    });
    if (!n) g.append(s('text', { class: 'kt-sub', delay: t0 + 400, x: cx, y: TOPY - 24, 'text-anchor': 'middle' }, '还没收进分支'));
    // 预测：树名下面一小簇 ◆（一行最多 9 个），像还没开的芽
    const preds = t.predictions.length, PER = 9;
    t.predictions.forEach((p, k) => {
      const row = Math.floor(k / PER), inRow = Math.min(PER, preds - row * PER), col = k - row * PER;
      const x = cx + (col - (inRow - 1) / 2) * 16 + (row % 2 ? 8 : 0), y = 88 + row * 15;
      g.append(s('path', { class: 'kt-bet', delay: t0 + 700 + k * 20, d: `M${x} ${y - 6} L${x + 5} ${y} L${x} ${y + 6} L${x - 5} ${y} Z`,
        onclick: (e) => { e.stopPropagation(); pick({ type: 'tree', key: t.key }, -1, p.id); } }, s('title', {}, p.quote)));
    });
    // 树名 + 数
    const go = (e) => { e.stopPropagation(); pick({ type: 'tree', key: t.key }); };
    g.append(s('text', { class: 'kt-tname', delay: t0 + 200, x: cx, y: 44, 'text-anchor': 'middle', onclick: go }, t.name));
    g.append(s('text', { class: 'kt-sub', delay: t0 + 240, x: cx, y: 64, 'text-anchor': 'middle', onclick: go }, `${t.principles.length} 条原则 · ${preds} 个预测`));
    g.append(s('rect', { class: 'kt-hit', x: cx - 12, y: TOPY, width: 24, height: BASE - TOPY, onclick: go }, s('title', {}, `${t.name}：看这棵树`)));
    svg.append(g);
  }

  function drawForest() {
    const d = state.data, f = d.forest, names = byName();
    const grow = !state.grown && !matchMedia('(prefers-reduced-motion: reduce)').matches;
    const svg = s('svg', { viewBox: `0 0 ${FW} ${FH}`, role: 'img', 'aria-label': `知识树：${f.trees.length} 棵树和地基`, class: grow ? 'kt-grow' : '' });
    const fresh = freshNames(d);
    f.trees.forEach((t, i) => drawOneTree(svg, t, XS[i] || 200 + i * 400, i, fresh, names));
    // 地基：一条通用原则一块石头
    const onF = (state.sel || {}).type === 'foundation';
    const fg = s('g', { class: `kt-found${onF ? ' on' : ''}`, onclick: () => pick({ type: 'foundation' }) });
    fg.append(s('rect', { class: 'kt-found-bed', x: 40, y: BASE, width: FW - 80, height: 64, rx: 10 }));
    const stones = f.foundation.principles, per = Math.ceil(stones.length / 2) || 1, sw = (FW - 112) / (per + 0.5);
    stones.forEach((p, k) => {
      const row = k < per ? 0 : 1, col = row ? k - per : k;
      fg.append(s('rect', { class: 'kt-stone', delay: 60 + k * 12, x: 56 + col * sw + (row ? sw / 2 : 0), y: BASE + 10 + row * 24, width: Math.max(8, sw - 6), height: 18, rx: 6,
        onclick: (e) => { e.stopPropagation(); pick({ type: 'foundation' }, -1, p.id); } }, s('title', {}, p.quote)));
    });
    fg.append(s('text', { class: 'kt-fname', x: FW / 2, y: FH - 6, 'text-anchor': 'middle' }, `${f.foundation.name} · ${stones.length} 条通用原则，三棵树都长在它上面`));
    svg.append(fg);
    const cap = h('div', { class: 'kt-cap' },
      h('span', {}, `${f.trees.length} 棵树 · ${d.branches.length} 枝 · ${f.foundation.principles.length + f.trees.reduce((n, t) => n + t.principles.length, 0)} 条原则 · ${f.trees.reduce((n, t) => n + t.predictions.length, 0) + f.worldview.length} 个预测`),
      h('span', {}, h('span', {}, h('i', { class: 'lf' }), '叶 = 分支的主干原理'), ' ', h('span', {}, h('i', { class: 'fr' }), '果 = 来源'), ' ', h('span', {}, h('i', { class: 'bt' }), '= 预测'), ' ', h('span', {}, h('i', { class: 'st' }), '石 = 通用原则')));
    $('canvas').replaceChildren(h('div', { class: 'kt-scroll' }, svg), cap);
    state.grown = true;
  }

  // ---------- 下面：点了什么看什么 ----------
  function sec(title, note, ...kids) {
    return h('section', { class: 'kt-card kt-sec' }, h('h3', {}, title, note ? h('small', {}, note) : null), ...kids);
  }
  // 一行放几张：row(2) 左右两栏，row(3) 三栏；窄屏自动变一栏
  const row = (n, ...cols) => h('div', { class: `kt-row kt-row${n}` }, ...cols.filter(Boolean));
  const col = (...cards) => h('div', { class: 'kt-col' }, ...cards.filter(Boolean));
  // 长清单只露前 keep 条，剩下的点「再看 N 条」才出来（10/18 作者：坑全展开整页太长）
  function clamp(items, keep, cls = 'kt-tiles') {
    const box = h('div', { class: cls }, items.map((el, i) => { if (i >= keep) el.classList.add('kt-extra'); return el; }));
    if (items.length <= keep) return box;
    const btn = h('button', { type: 'button', class: 'kt-morebtn' }, `再看 ${items.length - keep} 条`);
    btn.onclick = () => { const open = box.classList.toggle('open'); btn.textContent = open ? '收起' : `再看 ${items.length - keep} 条`; };
    return h('div', {}, box, btn);
  }
  function quotes(list, hotId, cls = '') {
    return h('ol', { class: `kt-quotes ${cls}` }, list.map((p) => h('li', { class: p.id === hotId ? 'hot' : '', id: `q-${p.id}` },
      h('p', {}, p.quote), h('small', {}, [p.horizon ? { long: '长期', medium: '中期', short: '短期', structural: '结构性' }[p.horizon] || p.horizon : '', fileName(p.source)].filter(Boolean).join(' · ')))));
  }

  function panelTree(t, hotId) {
    const names = byName();
    const head = h('section', { class: 'kt-card kt-head' }, h('code', {}, '一棵树'), h('h2', {}, t.name), t.about ? h('p', { class: 'kt-about' }, t.about) : null,
      h('p', {}, `${t.limbs.length} 根大树杈 · ${t.limbs.reduce((n, l) => n + l.branches.length, 0)} 枝 · ${t.principles.length} 条原则当根 · ${t.predictions.length} 个预测挂在上面`));
    const limbs = t.limbs.length ? sec('大树杈', '一根一类事，枝是收进来的分支', h('div', { class: 'kt-map' }, t.limbs.map((lb) => h('div', {},
      h('b', {}, lb.name),
      lb.branches.length ? lb.branches.map((n) => { const b = names.get(n); return b ? h('button', { type: 'button', class: 'kt-blink', onclick: () => pick({ type: 'branch', key: n }) }, `${short(b)} · ${b.principles.length} 条主干 ↗`) : null; })
        : h('p', {}, '还没有。收进来的第一篇会长在这。'))))) : sec('大树杈', null, h('p', { class: 'kt-muted' }, '还没收进这个领域的分支。贴一篇讲这个领域的链接，第一枝就从这里长出来。'));
    $('panel').replaceChildren(head, limbs,
      row(2, sec('根', '这个领域的原则：收进来的方法跟它冲突时，以它为准', quotes(t.principles, hotId)),
        sec('挂着的预测', '你在这个领域下的注，说中说错都记下来', t.predictions.length ? quotes(t.predictions, hotId, 'bets') : h('p', { class: 'kt-muted' }, '没有'))));
    scrollHot();
  }

  function panelFoundation(hotId) {
    const f = state.data.forest;
    $('panel').replaceChildren(
      h('section', { class: 'kt-card kt-head' }, h('code', {}, '地基'), h('h2', {}, '通用原则'), h('p', {}, `${f.foundation.principles.length} 条，不分领域，三棵树都长在它上面。`)),
      row(2, sec('通用原则', null, quotes(f.foundation.principles, hotId)),
        f.worldview.length ? sec('世界观', `没归到任何一棵树的预测 · ${f.worldview.length} 条`, quotes(f.worldview, hotId, 'bets')) : null));
    scrollHot();
  }

  function scrollHot() {
    const hot = $('panel').querySelector('li.hot');
    if (hot) hot.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function treeOf(name) {
    return (state.data.forest?.trees || []).find((t) => t.limbs.some((l) => l.branches.includes(name)));
  }

  function panelBranch(b) {
    const fresh = freshNames(state.data).has(b.name);
    const home = treeOf(b.name);
    const head = h('section', { class: 'kt-card kt-head' },
      home ? h('button', { type: 'button', class: 'kt-back', onclick: () => pick({ type: 'tree', key: home.key }) }, `← 回到「${home.name}」这棵树`) : null,
      h('code', {}, b.name), h('h2', {}, b.domain || b.title), h('p', {}, b.heading),
      b.wake.length ? h('div', { class: 'kt-wake' }, b.wake.map((w) => h('span', {}, `你说「${w}」时醒`))) : null,
      h('div', { class: 'kt-meta' }, fresh ? h('span', { class: 'kt-new' }, '刚长出来') : null,
        b.history[0] ? h('span', {}, `上次长：${ago(b.history[0].at)} · ${b.history[0].subject}`) : null));
    const trunks = h('ol', { class: 'kt-trunks' }, b.principles.map((p, k) => h('li', { class: state.hot === k ? 'hot' : '' }, h('div', {}, h('b', {}, p.title), p.text !== p.title ? h('span', {}, p.text) : null))));
    const map = b.map.length ? sec('领域地图', `这件事其实分这几类 · ${b.map.length} 类`, h('div', { class: 'kt-map wide' }, b.map.map((m) => h('div', {}, h('b', {}, m.kind), h('p', {}, m.line), m.fit ? h('small', {}, `适合：${m.fit}`) : null)))) : null;
    const qs = b.questions.length ? sec('先问的问题', '不问就会做错', h('ol', { class: 'kt-qs' }, b.questions.map((q) => h('li', {}, q)))) : null;
    const tile = (x, i) => h('div', { class: 'kt-tile' }, h('i', {}, String(i + 1)), h('p', {}, x));
    const pits = b.pitfalls.length ? sec('坑', `别人翻过的车 · ${b.pitfalls.length} 条`, clamp(b.pitfalls.map(tile), 6)) : null;
    const stds = b.standards.length ? sec('好坏标准', `${b.standards.length} 条`, clamp(b.standards.map(tile), 4)) : null;
    const srcs = b.sources.length ? sec('来源', `${b.sources.length} 篇`, h('ul', { class: 'kt-src' }, b.sources.map((x) => h('li', {},
      x.url ? h('a', { href: x.url, target: '_blank', rel: 'noopener' }, x.author || x.url) : h('b', {}, x.author || x.source), h('em', {}, x.date), h('span', {}, `拿走了：${x.took}`))))) : null;
    const exam = b.exam.length ? sec('考题', '该醒的醒、不该醒的不醒', h('div', { class: 'kt-exam' }, b.exam.map((x) => h('span', { class: x.wake ? 'y' : '' }, `${x.wake ? '该醒' : '不该醒'}：${x.text}`)))) : null;
    const hist = b.history.length ? sec('生长记录', null, clamp(b.history.map((x) => h('p', { class: 'kt-hist' }, h('em', {}, ago(x.at)), x.subject)), 3, 'kt-list')) : null;
    $('panel').replaceChildren(head,
      row(2, col(sec('主干', '底层原理，细节都挂在这上面', trunks), hist), col(qs, srcs, exam)),
      map, pits, stds);
    scrollHot();
  }

  function drawPanel(hotId) {
    const sel = state.sel || {};
    const f = state.data.forest;
    if (sel.type === 'foundation') return panelFoundation(hotId);
    if (sel.type === 'tree') { const t = f.trees.find((x) => x.key === sel.key); if (t) return panelTree(t, hotId); }
    if (sel.type === 'branch') { const b = byName().get(sel.key); if (b) return panelBranch(b); }
    $('panel').replaceChildren();
  }

  function pick(sel, hot = -1, hotId = '') {
    state.sel = sel; state.hot = hot;
    drawForest(); drawPanel(hotId);
  }
  function select(name, scroll) {  // 内化回执里「长在 X」点进来
    pick({ type: 'branch', key: name });
    if (scroll) $('stage').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function load() {
    clearTimeout(state.timer);
    let d;
    try { d = await api('/api/tree'); } catch (err) { $('msg').textContent = err.message; return; }
    const prev = state.data;
    state.data = d;
    drawJobs(d.jobs || []);
    if (!d.ok) {
      $('stage').replaceChildren(h('p', { class: 'kt-empty' }, d.why || '没找到知识树', h('br'), '知识树在 ', h('code', {}, '~/work/park-knowledge'), '；装好之后刷新这页。'));
    } else if (!d.forest) {
      d.forest = { foundation: { name: '地基', principles: [] }, trees: [{ key: 'all', name: '知识树', principles: [], predictions: [], limbs: [{ key: 'all', name: '全部', branches: d.branches.map((b) => b.name) }] }], worldview: [], unplaced: [], why: '' };
    }
    if (d.ok) {
      const un = d.forest.unplaced || [];
      if (un.length) d.forest.trees.push({ key: '_unplaced', name: '还没挂上', principles: [], predictions: [], limbs: [{ key: 'u', name: '新收的', branches: un }] });
      if (!state.sel) {
        const fresh = freshNames(d);
        const b = d.branches.find((x) => fresh.has(x.name));
        state.sel = b ? { type: 'branch', key: b.name } : { type: 'tree', key: d.forest.trees[0].key };
      }
      $('why').textContent = d.forest.why || '';
      const changed = !prev || prev.head !== d.head || prev.branches.length !== d.branches.length;
      if (changed) { if (prev) state.grown = false; drawForest(); drawPanel(); }
    }
    if ((d.jobs || []).some((j) => j.status === 'running')) state.timer = setTimeout(load, 5000);
  }

  $('theme').addEventListener('click', () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('cs-theme', root.dataset.theme); } catch (_) { /* ignore */ }
  });

  load();
})();
