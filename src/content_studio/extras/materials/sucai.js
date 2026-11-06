// 素材页（10/18，照选题工作台的「素材」）：视频样片、风格两个画廊 + 素材卡 / 爆款视频 / 好网站一条条卡。
// 10/20 作者：素材、素材 Agent 是一回事——出图（make.js）和「学一个新的」（素材 Agent，/materials/page.js）也并进这一页。
// 卡里的字来自别人的东西，只用 textContent / setAttribute，不拼 HTML。
(() => {
  const $ = (id) => document.getElementById(id);
  const TABS = [['make', '出图'], ['styles', '风格'], ['video-samples', '视频样片'], ['learn', '学一个新的'], ['card', '素材卡'], ['video', '爆款视频'], ['site', '好网站'], ['all', '全部']];
  const KIND = { card: '素材卡', video: '爆款视频', site: '好网站' };
  const state = { tab: 'make', counts: {} };

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
  async function api(path, body) {
    const opt = body === undefined ? {} : { method: 'POST', headers: { 'content-type': 'application/json', 'x-content-studio': '1' }, body: JSON.stringify(body) };
    const r = await fetch(path, opt);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `出错了（${r.status}）`);
    return data;
  }
  function toast(msg) {
    const t = $('libToast');
    t.textContent = msg; t.classList.add('show');
    clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 2600);
  }
  const ago = (iso) => {
    const t = new Date(iso).getTime();
    if (!iso || Number.isNaN(t)) return '';
    const d = Math.round((Date.now() - t) / 86400000);
    return d < 1 ? '今天' : d < 30 ? `${d} 天前` : String(iso).slice(0, 10);
  };
  const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch (_) { return ''; } };
  const wan = (n) => (n >= 10000 ? `${(n / 10000).toFixed(1).replace(/\.0$/, '')}万` : String(Math.round(n)));

  /* 滚到眼前的视频自己播（静音），滚走就停 */
  function autoplay(root) {
    const vids = [...root.querySelectorAll('video[data-auto]')];
    if (!('IntersectionObserver' in window)) return;
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.preload = 'auto'; e.target.play().catch(() => {}); } else e.target.pause(); }), { threshold: 0.35 });
    vids.forEach((v) => io.observe(v));
  }

  function drawTabs() {
    $('libTabs').replaceChildren(...TABS.map(([k, name]) => h('button', { type: 'button', class: k === state.tab ? 'on' : '', 'aria-pressed': String(k === state.tab), onclick: () => go(k) },
      name, state.counts[k] != null ? h('em', {}, String(state.counts[k])) : null)));
  }

  async function intoTopics(m, btn) {
    btn.disabled = true;
    try {
      const memo = [m.excerpt, m.note, m.url].filter(Boolean).join('\n\n');
      await api('/api/topics', { title: m.title.slice(0, 60), memo });
      btn.textContent = '已加入选题'; btn.classList.add('on');
      toast('加进选题了，在「排期 → 选题池」');
    } catch (err) { toast(err.message); btn.disabled = false; }
  }

  function card(m) {
    const media = m.image || m.video
      ? h('a', { class: 'lib-img', href: m.url || null, target: '_blank', rel: 'noopener' },
        m.video ? h('video', { src: m.video, poster: m.image || null, muted: true, loop: true, playsinline: true, preload: 'none', 'data-auto': '1' }) : h('img', { src: m.image, alt: '', loading: 'lazy' }))
      : null;
    const stats = [m.stats && m.stats.likes != null ? `${wan(m.stats.likes)} 赞` : '', m.stats && m.stats.multiple != null ? `平时的 ${m.stats.multiple} 倍` : ''].filter(Boolean).join(' · ');
    const btn = h('button', { class: 'btn small', type: 'button' }, '加入选题');
    btn.onclick = () => intoTopics(m, btn);
    return h('article', { class: 'lib-card' }, media,
      h('div', { class: 'lib-b' },
        h('div', { class: 'lib-row' }, h('span', { class: `lib-pill k-${m.kind}` }, KIND[m.kind] || m.kind), m.category ? h('span', { class: 'lib-pill' }, m.category) : null, h('span', { class: 'lib-when' }, ago(m.when))),
        m.url ? h('a', { class: 'lib-t', href: m.url, target: '_blank', rel: 'noopener' }, m.title) : h('b', { class: 'lib-t' }, m.title),
        m.excerpt ? h('p', { class: 'lib-x' }, m.excerpt) : null,
        m.note ? h('p', { class: `lib-n k-${m.kind}` }, m.note) : null,
        h('div', { class: 'lib-f' }, h('span', { class: 'lib-src' }, [m.author, host(m.url)].filter(Boolean).join(' · ') + (stats ? ` · ${stats}` : '')), btn)));
  }

  async function feed(kind) {
    const d = await api(`/api/sucai?kind=${kind}`);
    d.kinds.forEach((k) => { state.counts[k.key] = k.count; });
    state.counts.all = d.kinds.reduce((n, k) => n + k.count, 0);
    drawTabs();
    $('libWhy').textContent = d.why || '';
    if (!d.items.length) {
      $('libBody').replaceChildren(h('p', { class: 'lib-empty' }, kind === 'card' ? '还没有留下的素材卡。去「学一个新的」丢一个链接，学完点「留下」。' : kind === 'video' ? '还没有拆过的爆款视频（vault 002_对标内容）。' : '这里还没有东西。'));
      return;
    }
    const grid = h('div', { class: 'lib-grid' }, d.items.map(card));
    $('libBody').replaceChildren(grid);
    autoplay(grid);
  }

  async function samples() {
    const d = await api('/tools/videos.json');
    $('libBody').replaceChildren(...(d.groups || []).map((g) => h('section', { class: 'lib-group' },
      h('div', { class: 'lib-gh' }, h('h2', {}, g.name), g.url ? h('a', { href: g.url, target: '_blank', rel: 'noopener' }, g.repo || '仓库') : null),
      g.note ? h('p', { class: 'lib-gn' }, g.note) : null,
      h('div', { class: 'lib-vgrid' }, (g.items || []).map((it) => {
        const v = h('video', { src: `/tools/videos/${it.id}.mp4`, poster: `/tools/videos/${it.id}.webp`, muted: true, loop: true, playsinline: true, preload: 'none', 'data-auto': '1' });
        const fig = h('figure', { class: 'lib-vid' }, h('div', { class: 'lib-vbox' }, v, h('span', { class: 'lib-len' }, `${it.secs} 秒${it.sound ? ' · 点开声音' : ''}`)),
          h('figcaption', {}, h('b', {}, it.title), it.give ? h('span', {}, `给的：${it.give}`) : null));
        if (it.sound) fig.querySelector('.lib-vbox').onclick = () => {
          const on = v.muted;
          document.querySelectorAll('.lib-vid video').forEach((o) => { o.muted = true; });
          v.muted = !on; if (on) { v.currentTime = 0; v.play().catch(() => {}); }
        };
        return fig;
      })))));
    autoplay($('libBody'));
  }

  async function styles() {
    const d = await api('/tools/styles.json');
    const list = (d.styles || []).filter((s) => s.sample);
    const cats = [...new Set(list.map((s) => s.cat))];
    let cat = '';
    const draw = () => {
      const rows = list.filter((s) => !cat || s.cat === cat);
      $('libBody').replaceChildren(
        h('div', { class: 'lib-chips' }, ['', ...cats].map((c) => h('button', { type: 'button', class: c === cat ? 'on' : '', onclick: () => { cat = c; draw(); } }, c || '全部', h('em', {}, String(c ? list.filter((s) => s.cat === c).length : list.length))))),
        h('div', { class: 'lib-sgrid' }, rows.map((s) => h('button', { type: 'button', class: 'lib-style', title: s.sum || s.name, onclick: () => { window.SucaiMake.pick({ id: s.id, name: s.name }); go('make'); } },
          h('img', { src: `/tools/styles/sample/${encodeURIComponent(s.id)}.webp`, alt: '', loading: 'lazy' }), h('b', {}, s.name), h('span', {}, s.sum || '')))),
        h('p', { class: 'lib-why' }, '点一张就用它出图。', h('a', { href: '/tools/styles' }, '全部风格和打磨台 ↗')));
    };
    draw();
  }

  async function go(tab) {
    const params = new URLSearchParams(location.search);
    state.tab = tab;
    try { history.replaceState(null, '', `${location.pathname}#${tab}`); } catch (_) { /* ignore：网址里带的 ?tool / ?style 用一次就丢 */ }
    drawTabs();
    window.SucaiMake.hide();
    $('libWhy').textContent = '';
    $('learnPanel').hidden = tab !== 'learn';
    $('libBody').hidden = tab === 'learn';
    if (tab === 'learn') { $('maInput').focus(); return; }
    $('libBody').replaceChildren(h('p', { class: 'lib-empty' }, '读取中…'));
    try {
      if (tab === 'make') await window.SucaiMake.show($('libBody'), params);
      else if (tab === 'video-samples') await samples();
      else if (tab === 'styles') await styles();
      else await feed(tab);
    } catch (err) {
      $('libBody').replaceChildren(h('p', { class: 'lib-empty' }, `读不到：${err.message}`));
    }
  }

  $('theme').addEventListener('click', () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('cs-theme', root.dataset.theme); } catch (_) { /* ignore */ }
  });

  const first = location.hash.slice(1);
  api('/api/sucai?kind=all').then((d) => { d.kinds.forEach((k) => { state.counts[k.key] = k.count; }); state.counts.all = d.kinds.reduce((n, k) => n + k.count, 0); drawTabs(); }).catch(() => {});
  window.SucaiGo = go;
  go(TABS.some(([k]) => k === first) ? first : 'make');
})();
