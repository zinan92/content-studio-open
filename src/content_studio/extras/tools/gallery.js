/* 风格画廊 / 打磨台（10/10）：几百种风格，每种一张样图。工作台里（不是公开静态页）每张能点「通过 / 重做」。 */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const STATIC = window.CS_STATIC === true;
  const REVIEW = !STATIC; // 打磨台只在本机工作台里
  if (!STATIC) { const back = document.querySelector('.gl-back'); if (back) { back.href = '/sucai#styles'; back.textContent = '← 素材'; } } // 工作台里风格归素材页（10/20）
  const FNS = [['image', '生图'], ['video', '特效视频'], ['motion', '动效']];
  const VERDICT = { approve: '通过', redo: '重做' };
  const PAGE = 60;
  const S = { all: [], fn: 'image', cat: '', q: '', only: true, rev: '', shown: PAGE, open: null };
  try { const v = JSON.parse(localStorage.getItem('cs-gallery') || '{}'); Object.assign(S, { fn: v.fn || 'image', only: v.only !== false }); } catch (_) { /* ignore */ }
  const save = () => { try { localStorage.setItem('cs-gallery', JSON.stringify({ fn: S.fn, only: S.only })); } catch (_) { /* ignore */ } };
  // 带着风格去出图，填一句主题就能画（10/11）；工作台里出图在素材页（10/20），公开站照旧回功能页
  const useUrl = (id) => (STATIC ? `/tools?style=${encodeURIComponent(id)}` : `/sucai?style=${encodeURIComponent(id)}#make`);
  const imgUrl = (id) => STATIC ? `/tools/styles/${encodeURIComponent(id)}.webp` : `/tools/styles/sample/${encodeURIComponent(id)}.webp`;

  function toast(text) {
    const t = $('#toast');
    t.textContent = text;
    t.classList.add('in');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => t.classList.remove('in'), 1800);
  }

  const inFn = () => S.all.filter((s) => s.fn === S.fn);
  function visible() {
    let list = inFn();
    if (S.only) list = list.filter((s) => s.sample);
    if (S.cat) list = list.filter((s) => s.cat === S.cat);
    if (REVIEW && S.rev) list = list.filter((s) => (S.rev === 'todo' ? !s.review && s.sample : s.review && s.review.verdict === S.rev));
    if (S.q) { const q = S.q.toLowerCase(); list = list.filter((s) => `${s.name} ${s.en} ${s.sum} ${s.cat}`.toLowerCase().includes(q)); }
    return list;
  }

  function bar() {
    const fns = REVIEW ? FNS : FNS.filter(([k]) => S.all.some((s) => s.fn === k)); // 公开站只放通过的，没有的那一类不显示
    if (!fns.some(([k]) => k === S.fn) && fns.length) S.fn = fns[0][0];
    $('#fns').hidden = fns.length < 2;
    $('#fns').innerHTML = fns.map(([k, n]) => {
      const list = S.all.filter((s) => s.fn === k);
      const have = list.filter((s) => s.sample).length;
      return `<button type="button" class="gl-fn${S.fn === k ? ' on' : ''}" data-fn="${k}" role="tab" aria-selected="${S.fn === k}">${n}<em>${have ? `${have} / ${list.length}` : list.length}</em></button>`;
    }).join('');
    const pool = inFn().filter((s) => !S.only || s.sample);
    const cats = [...pool.reduce((m, s) => m.set(s.cat, (m.get(s.cat) || 0) + 1), new Map())].sort((a, b) => b[1] - a[1]);
    if (S.cat && !cats.some(([c]) => c === S.cat)) S.cat = '';
    $('#cats').innerHTML = `<button type="button" class="gl-chip${!S.cat ? ' on' : ''}" data-cat="">全部<em>${pool.length}</em></button>`
      + cats.map(([c, n]) => `<button type="button" class="gl-chip${S.cat === c ? ' on' : ''}" data-cat="${esc(c)}">${esc(c)}<em>${n}</em></button>`).join('');
    if (REVIEW) {
      const withSample = inFn().filter((s) => s.sample);
      const n = (v) => withSample.filter((s) => (v === 'todo' ? !s.review : s.review && s.review.verdict === v)).length;
      $('#rev').hidden = false;
      $('#rev').innerHTML = `<span class="gl-lab">打磨台：</span>` + [['', '全部'], ['todo', '待看'], ['approve', '通过'], ['redo', '重做']]
        .map(([k, l]) => `<button type="button" class="gl-chip${S.rev === k ? ' on' : ''}" data-rev="${k}">${l}${k ? `<em>${n(k)}</em>` : ''}</button>`).join('');
    }
    const fnName = FNS.find(([k]) => k === S.fn)[1];
    const have = inFn().filter((s) => s.sample).length;
    $('#eyebrow').textContent = `风格画廊 · ${fnName} · ${inFn().length} 种${have ? `，已出样 ${have} 张` : '，样图在路上'}`;
    $('#onlyWrap').hidden = STATIC || !inFn().some((s) => s.sample); // 公开站上每一张都有样图
    $$('[data-fn]').forEach((b) => (b.onclick = () => { S.fn = b.dataset.fn; S.cat = ''; S.shown = PAGE; S.only = inFn().some((s) => s.sample) ? S.only : false; save(); draw(); }));
    $$('[data-cat]').forEach((b) => (b.onclick = () => { S.cat = b.dataset.cat; S.shown = PAGE; draw(); }));
    $$('[data-rev]').forEach((b) => (b.onclick = () => { S.rev = b.dataset.rev; S.shown = PAGE; draw(); }));
  }

  function card(s) {
    const mark = s.review ? s.review.verdict : '';
    const pic = s.sample ? `<img src="${imgUrl(s.id)}" alt="${esc(s.name)}" loading="lazy" decoding="async">` : '<div class="ph">样图在路上</div>';
    const use = s.fn === 'image' && s.sample && (STATIC || mark === 'approve') ? `<div class="gl-acts"><a class="go" href="${useUrl(s.id)}">用这个风格画</a></div>` : '';
    const acts = REVIEW && s.sample ? `<div class="gl-acts"><button type="button" class="ok${mark === 'approve' ? ' on' : ''}" data-ok="${s.id}">通过</button><button type="button" class="no${mark === 'redo' ? ' on' : ''}" data-no="${s.id}">重做</button></div>` : '';
    return `<article class="gl-card${mark ? ` ${mark}` : ''}" tabindex="0" data-id="${s.id}">${pic}<div class="bd"><b>${esc(s.name)}</b><p>${esc(s.sum)}</p><small>${esc(s.cat)}</small></div>${STATIC ? use : acts}</article>`;
  }

  function draw() {
    bar();
    const list = visible();
    $('#grid').innerHTML = list.length ? list.slice(0, S.shown).map(card).join('')
      : `<p class="gl-empty">${S.fn !== 'image' && !inFn().some((s) => s.sample) ? '这一类的样片还在做，先看生图。' : '没有对得上的，换个词或分类试试。'}</p>`;
    $('#more').hidden = list.length <= S.shown;
    $('#moreBtn').textContent = `再看 ${Math.min(PAGE, list.length - S.shown)} 个（还有 ${list.length - S.shown}）`;
    $$('.gl-card').forEach((c) => {
      c.onclick = (e) => { if (!e.target.closest('button')) open(c.dataset.id); };
      c.onkeydown = (e) => { if (e.key === 'Enter') open(c.dataset.id); };
    });
    $$('[data-ok]').forEach((b) => (b.onclick = () => mark(b.dataset.ok, 'approve')));
    $$('[data-no]').forEach((b) => (b.onclick = () => open(b.dataset.no, true)));
  }

  async function mark(id, verdict, note = '') {
    const s = S.all.find((x) => x.id === id);
    const next = s.review && s.review.verdict === verdict && !note ? '' : verdict; // 再点一次 = 撤回
    try {
      const res = await fetch(`/api/tools/styles/${encodeURIComponent(id)}/review`, { method: 'POST', headers: { 'content-type': 'application/json', 'x-content-studio': '1' }, body: JSON.stringify({ verdict: next, note }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '没存上');
      s.review = data.review;
      toast(next ? `「${s.name}」${VERDICT[next]}` : `「${s.name}」撤回了`);
      draw();
    } catch (e) {
      toast(e.message || '没存上，再点一次');
    }
  }

  function open(id, redo) {
    const s = S.all.find((x) => x.id === id);
    if (!s) return;
    S.open = id;
    const box = $('#box');
    const note = s.review && s.review.note ? s.review.note : '';
    box.innerHTML = `<div class="gl-box-in">
      <div class="gl-box-img">${s.sample ? `<img src="${imgUrl(s.id)}" alt="${esc(s.name)}">` : '<div class="ph">样图在路上</div>'}</div>
      <div class="gl-box-info">
        <h2>${esc(s.name)}</h2>${s.en ? `<div class="en">${esc(s.en)}</div>` : ''}
        <p>${esc(s.sum)}</p>
        <div class="gl-meta"><span>${esc(s.cat)}</span><span>${esc(s.src.repo)}</span><span>${esc(s.src.license)}</span>${s.src.by ? `<span>${esc(s.src.by)}</span>` : ''}</div>
        ${s.fn === 'image' && s.sample && (STATIC || (s.review && s.review.verdict === 'approve')) ? `<a class="btn primary gl-use" href="${useUrl(s.id)}">用这个风格画我的主题 →</a>` : ''}
        ${s.prompt ? `<details><summary>提示词</summary><pre>${esc(s.prompt)}</pre></details>` : ''}
        ${REVIEW && s.sample ? `<label for="note" class="gl-lab">哪里不行（点重做时写一句，比如「字太小」「人物太幼」）</label>
          <textarea class="gl-note" id="note" placeholder="可以不写">${esc(note)}</textarea>
          <div class="gl-box-acts"><button type="button" class="btn" id="bxNo">重做</button><button type="button" class="btn primary" id="bxOk">通过</button><span class="grow"></span>
            <button type="button" class="btn ghost" id="bxPrev">← 上一张</button><button type="button" class="btn ghost" id="bxNext">下一张 →</button></div>` : ''}
      </div></div>
      <button type="button" class="gl-x" id="bxX" aria-label="关闭">×</button>`;
    box.showModal();
    $('#bxX').onclick = () => box.close();
    box.onclick = (e) => { if (e.target === box) box.close(); };
    if (REVIEW && s.sample) {
      const step = (d) => { const list = visible(); const i = list.findIndex((x) => x.id === id); const n = list[i + d]; if (n) open(n.id); };
      $('#bxOk').onclick = async () => { await mark(id, 'approve', $('#note').value.trim()); step(1); };
      $('#bxNo').onclick = async () => { await mark(id, 'redo', $('#note').value.trim()); step(1); };
      $('#bxPrev').onclick = () => step(-1);
      $('#bxNext').onclick = () => step(1);
      if (redo) setTimeout(() => $('#note').focus(), 50);
    }
  }

  // 键盘：详情里 ← → 翻页，Y 通过，N 重做
  document.addEventListener('keydown', (e) => {
    const box = $('#box');
    if (!box.open || e.target.closest('textarea')) return;
    if (e.key === 'ArrowRight') $('#bxNext')?.click();
    if (e.key === 'ArrowLeft') $('#bxPrev')?.click();
    if (e.key.toLowerCase() === 'y') $('#bxOk')?.click();
    if (e.key.toLowerCase() === 'n') $('#bxNo')?.click();
  });

  async function load(first) {
    const data = await (await fetch(STATIC ? '/tools/styles.json' : '/tools/styles.json', { cache: 'no-store' })).json();
    const before = S.all.filter((s) => s.sample).length;
    S.all = data.styles;
    $('#topic').textContent = data.topic;
    const now = S.all.filter((s) => s.sample).length;
    if (!first && now > before) { toast(`又出了 ${now - before} 张`); }
    const live = $('#live');
    const todo = S.all.filter((s) => s.fn === 'image').length - S.all.filter((s) => s.fn === 'image' && s.sample).length;
    live.hidden = STATIC || !todo;
    live.textContent = `样图在出：还差 ${todo} 张`;
    if (first || !$('#box').open) draw();
  }

  $('#q').oninput = (e) => { S.q = e.target.value.trim(); S.shown = PAGE; draw(); };
  $('#only').onchange = (e) => { S.only = e.target.checked; S.shown = PAGE; save(); draw(); };
  $('#moreBtn').onclick = () => { S.shown += PAGE; draw(); };
  $('#theme').onclick = () => {
    const r = document.documentElement;
    const dark = r.dataset.theme ? r.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    r.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('cs-theme', r.dataset.theme); } catch (_) { /* ignore */ }
  };
  $('#only').checked = S.only;
  load(true).catch(() => { $('#grid').innerHTML = '<p class="gl-empty">风格清单没读到，刷新试试。</p>'; });
  if (!STATIC) setInterval(() => load(false).catch(() => {}), 60000); // 样图还在出：每分钟看一次
})();
