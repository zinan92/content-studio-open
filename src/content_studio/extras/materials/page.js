// 素材 Agent（10/17）：丢链接或文件夹 → 后台学 → 卡片墙。卡里的字全来自外部原文，只用 textContent，不拼 HTML。
// 10/20 并进素材页的「学一个新的」：元素 id 都带 ma 前缀，深浅色按钮用素材页那个，只在这一栏打开时轮询。
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { sid: null, deck: null, filter: 'all', cat: '', jobs: [], sources: [] };
  const STATUS = { queued: '排队中', running: '', done: '', error: '' };

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

  const media = (sid, name) => `/materials/media/${encodeURIComponent(sid)}/${encodeURIComponent(name)}`;

  // ---------- 丢进来 ----------
  $('maPasteToggle').addEventListener('click', () => { $('maPaste').hidden = !$('maPaste').hidden; if (!$('maPaste').hidden) $('maPaste').focus(); });
  $('maForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('maMsg').textContent = '';
    const input = $('maInput').value.trim();
    const text = $('maPaste').hidden ? '' : $('maPaste').value.trim();
    if (!input && !text) { $('maMsg').textContent = '贴一个链接或文件夹路径'; return; }
    $('maGo').disabled = true;
    try {
      await api('/api/material-agent/learn', { input, text });
      $('maInput').value = ''; $('maPaste').value = '';
      await refresh();
    } catch (err) { $('maMsg').textContent = err.message; }
    $('maGo').disabled = false;
  });

  function renderJobs() {
    const live = state.jobs.filter((j) => j.status !== 'done' || Date.now() - Date.parse(j.updated_at) < 10 * 60e3).slice(0, 6);
    $('maJobs').replaceChildren(...live.map((j) => {
      const cls = { queued: '', running: 'run', done: 'done', error: 'err' }[j.status];
      const note = j.status === 'error' ? j.error : (STATUS[j.status] || j.step);
      return h('li', { class: `ma-job ${cls}` }, h('i'), h('b', { title: j.input }, j.input), h('span', {}, note),
        j.status === 'error' ? h('button', { type: 'button', class: 'btn ghost', onclick: () => api(`/api/material-agent/jobs/${encodeURIComponent(j.id)}/retry`, {}).then(refresh) }, '重试') : null);
    }));
  }

  // ---------- 学过的 ----------
  function renderSources() {
    $('maShelf').hidden = !state.sources.length;
    $('maSources').replaceChildren(...state.sources.map((s) => h('button', {
      type: 'button', class: `ma-src${s.source.id === state.sid ? ' on' : ''}`, onclick: () => open(s.source.id),
    }, s.cover ? h('img', { src: media(...s.cover.split('/')), alt: '' }) : h('i', { class: 'ma-src-ph' }), s.source.title, h('em', {}, `${s.count} 张`))));
  }

  async function open(sid) {
    state.sid = sid; state.filter = 'all'; state.cat = '';
    try { localStorage.setItem('ma-sid', sid); } catch (_) { /* ignore */ }
    state.deck = await api(`/api/material-agent/sources/${encodeURIComponent(sid)}`);
    renderSources(); renderDeck();
  }

  function renderDeck() {
    const { source, cards } = state.deck;
    const kept = cards.filter((c) => c.status === 'kept').length;
    const publicSource = ['github', 'x', 'web'].includes(source.kind);
    const tree = source.tree || {};
    const link = source.url ? h('a', { href: source.url, target: '_blank', rel: 'noopener' }, source.url.replace(/^https?:\/\//, '')) : source.path;
    $('maHead').replaceChildren(...[
      h('div', {}, h('h2', {}, source.title), source.what ? h('p', {}, source.what) : null,
        h('small', {}, link, source.author ? ` · ${source.author}` : '', ` · 许可 ${source.license || '未声明'} · ${cards.length} 张`)),
      h('div', { class: 'ma-acts' },
        h('button', { type: 'button', class: 'btn primary', disabled: !publicSource || !kept, title: publicSource ? '留下的卡进选题工作台的素材库，半小时内上线' : '本机文件夹和粘进来的正文不推到线上', onclick: push },
          publicSource ? `推到工作台（${kept}）` : '本机来源不推'),
        h('button', { type: 'button', class: 'btn ghost', disabled: tree.status === 'running', title: '照 internalize 的规矩收进知识树分支：做之前该懂什么、该问什么', onclick: internalize },
          tree.status === 'running' ? '正在收进知识树…' : tree.status === 'done' ? '再收一次' : '进知识树')),
      tree.status === 'done' ? h('p', { class: 'ma-receipt' }, tree.receipt) : null,
      tree.status === 'error' ? h('p', { class: 'ma-receipt err' }, `没收成：${tree.error}`) : null,
    ].filter(Boolean));
    const counts = { all: cards.length, new: 0, kept: 0, dropped: 0 };
    const cats = new Map();
    for (const c of cards) { counts[c.status] += 1; if (c.category) cats.set(c.category, (cats.get(c.category) || 0) + 1); }
    const chip = (key, label, n, on, fn) => h('button', { type: 'button', class: `ma-chip${on ? ' on' : ''}`, onclick: fn }, label, h('em', {}, n));
    $('maFilters').replaceChildren(
      ...[['all', '全部'], ['new', '没看'], ['kept', '留下'], ['dropped', '不要']].map(([k, label]) =>
        chip(k, label, counts[k], state.filter === k, () => { state.filter = k; renderDeck(); })),
      ...(cats.size > 1 ? [...cats].map(([cat, n]) => chip(cat, cat, n, state.cat === cat, () => { state.cat = state.cat === cat ? '' : cat; renderDeck(); })) : []),
    );
    const shown = cards.filter((c) => (state.filter === 'all' || c.status === state.filter) && (!state.cat || c.category === state.cat));
    $('maGrid').replaceChildren(...(shown.length ? shown.map(card) : [h('p', { class: 'ma-empty' }, '这一栏没有卡')]));
  }

  function mediaBox(c, sid) {
    const box = h('button', { type: 'button', class: 'ma-media', 'aria-label': `看「${c.title}」的提示词原文`, onclick: () => detail(c) });
    if (c.poster) box.append(h('img', { src: media(sid, c.poster), alt: '', loading: 'lazy' }));
    else box.append(h('span', { class: 'ma-noimg' }, c.title));
    if (c.sample) {
      const v = h('video', { src: media(sid, c.sample), muted: true, loop: true, playsinline: true, preload: 'none' });
      v.muted = true;
      box.append(v);
      box.addEventListener('mouseenter', () => { box.classList.add('play'); v.play().catch(() => {}); });
      box.addEventListener('mouseleave', () => { box.classList.remove('play'); v.pause(); });
      box.append(h('span', { class: 'ma-tag' }, '▶ 样片'));
    }
    return box;
  }

  function card(c) {
    const sid = state.sid;
    const set = (status) => api(`/api/material-agent/sources/${encodeURIComponent(sid)}/cards/${encodeURIComponent(c.name)}`, { status })
      .then((got) => { Object.assign(c, got); renderDeck(); }).catch((err) => { $('maMsg').textContent = err.message; });
    return h('article', { class: `ma-card ${c.status}` },
      mediaBox(c, sid),
      h('div', { class: 'ma-body-c' },
        h('div', { class: 't ma-t' }, h('b', {}, c.title), c.title_en ? h('small', {}, c.title_en) : null),
        c.category ? h('span', { class: 'ma-cat' }, c.category) : null,
        c.what ? h('p', {}, c.what) : null,
        c.when ? h('p', { class: 'when' }, c.when) : null,
        h('div', { class: 'ma-card-acts' },
          h('button', { type: 'button', class: `btn ghost${c.status === 'kept' ? ' on' : ''}`, onclick: () => set(c.status === 'kept' ? 'new' : 'kept') }, c.status === 'kept' ? '已留下' : '留下'),
          h('button', { type: 'button', class: 'btn ghost', onclick: () => set(c.status === 'dropped' ? 'new' : 'dropped') }, c.status === 'dropped' ? '撤回' : '不要'),
          h('button', { type: 'button', class: 'btn ghost', onclick: () => detail(c) }, '提示词'))));
  }

  function detail(c) {
    const sid = state.sid;
    $('maDlgTitle').textContent = c.title;
    $('maDlgSub').textContent = [c.title_en, c.category].filter(Boolean).join(' · ');
    $('maDlgMedia').replaceChildren(c.sample ? h('video', { src: media(sid, c.sample), controls: true, autoplay: true, muted: true, loop: true, playsinline: true })
      : c.poster ? h('img', { src: media(sid, c.poster), alt: '' }) : '');
    const row = (k, v) => (v ? [h('dt', {}, k), h('dd', {}, v)] : []);
    $('maDlgMeta').replaceChildren(...row('这是什么', c.what), ...row('什么时候用', c.when), ...row('作者写的用途', c.use),
      ...row('出处', c.source_url ? h('a', { href: c.source_url, target: '_blank', rel: 'noopener' }, c.prompt_file || c.source_url) : null));
    $('maDlgPrompt').textContent = c.prompt || c.prompt_note || '这张卡没有提示词原文';
    $('maDlg').showModal();
  }
  $('maCopy').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('maDlgPrompt').textContent); $('maCopy').textContent = '已复制'; setTimeout(() => { $('maCopy').textContent = '复制'; }, 1500); } catch (_) { /* ignore */ }
  });
  $('maDlg').addEventListener('close', () => { const v = $('maDlgMedia').querySelector('video'); if (v) v.pause(); });

  async function push() {
    try {
      const r = await api(`/api/material-agent/sources/${encodeURIComponent(state.sid)}/push`, {});
      $('maMsg').textContent = '';
      await open(state.sid);
      $('maHead').querySelector('.btn.primary').textContent = `已排进推送（${r.queued} 张），半小时内上线`;
    } catch (err) { $('maMsg').textContent = err.message; }
  }

  async function internalize() {
    try { await api(`/api/material-agent/sources/${encodeURIComponent(state.sid)}/internalize`, {}); await open(state.sid); } catch (err) { $('maMsg').textContent = err.message; }
  }

  // ---------- 轮询 ----------
  let lastDone = '';
  async function refresh() {
    const data = await api('/api/material-agent');
    state.jobs = data.jobs; state.sources = data.sources;
    renderJobs(); renderSources();
    const done = state.jobs.filter((j) => j.status === 'done').map((j) => j.id).join();
    let saved = null;
    try { saved = localStorage.getItem('ma-sid'); } catch (_) { /* ignore */ }
    if (!state.sid && state.sources.length) await open(state.sources.some((s) => s.source.id === saved) ? saved : state.sources[0].source.id);
    else if (state.sid && (done !== lastDone || (state.deck && state.deck.source.tree && state.deck.source.tree.status === 'running'))) await open(state.sid);
    lastDone = done;
  }
  setInterval(() => { if (!document.hidden && !$('learnPanel').hidden) refresh().catch(() => {}); }, 4000);
  refresh().catch((err) => { $('maMsg').textContent = err.message; });

})();
