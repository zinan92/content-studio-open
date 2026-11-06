// 素材页 · 出图（10/20 作者：「素材主要是生图和生视频」）：封面、正文配图、生图风格、小红书图文四个出图的功能从单点功能搬过来。
// 后台还是单点功能那条队列（/api/tools），一次跑一个；这里只放这四个、只看这四个的记录。
// 结果里的字来自用户自己贴的东西，只用 textContent / setAttribute，不拼 HTML。
window.SucaiMake = (() => {
  const KEYS = ['cover', 'illustrate', 'style', 'xhs'];
  const STATE = { waiting: '排队中', running: '在画', done: '好了', failed: '没成' };
  const S = { tools: [], ex: {}, runs: [], open: null, pick: null, timer: null, box: null };

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
  const exSrc = (name) => `/tools/examples/${encodeURIComponent(name)}`;
  const runSrc = (run, rel) => `/api/tools/runs/${encodeURIComponent(run.id)}/file/${rel.split('/').map(encodeURIComponent).join('/')}`;
  const sample = (id) => `/tools/styles/sample/${encodeURIComponent(id)}.webp`;
  const when = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }); };
  const mine = (runs) => (runs || []).filter((r) => KEYS.includes(r.tool));

  function field(f) {
    const label = h('span', {}, f.label, f.required ? null : h('em', {}, '可不填'));
    if (f.name === 'style' && S.pick) {
      return h('div', { class: 'mk-field' }, label,
        h('div', { class: 'mk-pick' }, h('img', { src: sample(S.pick.id), alt: '' }), h('b', {}, S.pick.name),
          h('button', { type: 'button', class: 'btn ghost small', onclick: () => { S.pick = null; draw(); } }, '换回常用的'),
          h('a', { href: '#styles', onclick: (e) => { e.preventDefault(); window.SucaiGo('styles'); } }, '去风格里挑')),
        h('input', { type: 'hidden', name: 'style', value: S.pick.id }));
    }
    let input;
    if (f.kind === 'long') input = h('textarea', { name: f.name, rows: 8, placeholder: f.hint || '' });
    else if (f.kind === 'select') input = h('select', { name: f.name }, (f.options || []).map((o) => h('option', {}, o)));
    else input = h('input', { name: f.name, placeholder: f.hint || '', autocomplete: 'off' });
    const extra = f.name === 'style' ? h('a', { class: 'mk-more', href: '#styles', onclick: (e) => { e.preventDefault(); window.SucaiGo('styles'); } }, '从风格里挑，几百种 →') : null;
    return h('label', { class: 'mk-field' }, label, input, extra);
  }

  function toolCard(t) {
    const ex = (S.ex[t.key] || [])[0];
    const img = ex && ex.result && (ex.result.images || [])[0];
    return h('button', { type: 'button', class: `mk-tool${S.open === t.key ? ' on' : ''}`, 'aria-pressed': String(S.open === t.key), onclick: () => { S.open = t.key; draw(); S.box.querySelector('.mk-form')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } },
      h('span', { class: 'mk-thumb' }, img ? h('img', { src: exSrc(img), alt: '', loading: 'lazy' }) : null),
      h('b', {}, t.name), h('span', {}, `给${t.give} → ${t.get}`));
  }

  function form(t) {
    const err = h('span', { class: 'mk-err', role: 'status' });
    const go = h('button', { type: 'submit', class: 'btn primary' }, '开始出图');
    const el = h('form', { class: 'mk-form' }, h('h2', {}, t.name), h('p', { class: 'mk-sub' }, `${t.give} → ${t.get} · 出图要几分钟，一次跑一个`),
      t.fields.map(field), h('div', { class: 'mk-row' }, go, err));
    el.addEventListener('submit', async (e) => {
      e.preventDefault();
      err.textContent = '';
      go.disabled = true;
      try {
        const run = await api(`/api/tools/${encodeURIComponent(t.key)}/run`, Object.fromEntries(new FormData(el).entries()));
        S.runs.unshift(run);
        drawRuns();
        poll();
        err.textContent = '交上去了，下面「最近出的图」里看进度';
      } catch (ex) { err.textContent = ex.message; }
      go.disabled = false;
    });
    return el;
  }

  function runCard(r) {
    const imgs = r.state === 'done' && r.result ? (r.result.images || []) : [];
    return h('article', { class: `mk-run ${r.state}` },
      h('div', { class: 'mk-meta' }, h('span', { class: `mk-state ${r.state}` }, STATE[r.state] || r.state), h('b', {}, r.name), h('time', {}, when(r.created))),
      r.state === 'failed' ? h('p', { class: 'mk-err' }, r.error || '没成') : null,
      r.state === 'waiting' || r.state === 'running' ? h('p', { class: 'mk-wait' }, r.state === 'waiting' ? '前面还有别的在跑，轮到它就开始' : '在画，几分钟') : null,
      imgs.length ? h('div', { class: 'mk-imgs' }, imgs.map((p) => h('a', { href: runSrc(r, p), target: '_blank', rel: 'noopener' }, h('img', { src: runSrc(r, p), alt: '', loading: 'lazy' })))) : null);
  }

  function drawRuns() {
    const box = S.box && S.box.querySelector('.mk-runs');
    if (!box) return;
    const list = S.runs.slice(0, 12);
    box.replaceChildren(...(list.length ? list.map(runCard) : [h('p', { class: 'lib-empty' }, '还没出过图。挑上面一个，填好点「开始出图」。')]));
  }

  function draw() {
    const t = S.tools.find((x) => x.key === S.open) || S.tools[0];
    if (t) S.open = t.key;
    S.box.replaceChildren(
      h('div', { class: 'mk-tools' }, S.tools.map(toolCard)),
      t ? form(t) : null,
      h('h2', { class: 'mk-h' }, '最近出的图'),
      h('div', { class: 'mk-runs', 'aria-live': 'polite' }));
    drawRuns();
  }

  function poll() {
    clearTimeout(S.timer);
    if (!S.box || !S.runs.some((r) => r.state === 'waiting' || r.state === 'running')) return;
    S.timer = setTimeout(async () => {
      try {
        const before = S.runs.map((r) => r.state).join();
        S.runs = mine((await api('/api/tools')).runs);
        if (S.runs.map((r) => r.state).join() !== before) drawRuns();
      } catch (_) { /* 下一轮再问 */ }
      poll();
    }, 3000);
  }

  async function pickStyle(id) {
    try {
      const s = ((await api('/tools/styles.json')).styles || []).find((x) => x.id === id && x.fn === 'image' && x.sample);
      if (s) S.pick = { id: s.id, name: s.name };
    } catch (_) { /* 风格清单读不到就用常用的 */ }
  }

  return {
    // 风格页点一张：带着这个风格去「生图风格」
    pick(style) { S.pick = style; S.open = 'style'; },
    async show(box, params) {
      S.box = box;
      if (params.get('tool') && KEYS.includes(params.get('tool'))) S.open = params.get('tool');
      if (params.get('style')) { await pickStyle(params.get('style')); S.open = 'style'; }
      const [data, ex] = await Promise.all([api('/api/tools'), fetch('/tools/examples/manifest.json').then((r) => (r.ok ? r.json() : {})).catch(() => ({}))]);
      S.tools = (data.tools || []).filter((t) => KEYS.includes(t.key));
      S.runs = mine(data.runs);
      S.ex = ex;
      draw();
      poll();
    },
    hide() { clearTimeout(S.timer); S.box = null; },
  };
})();
