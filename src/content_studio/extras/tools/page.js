/* 单点功能 · 先看结果（10/10 作者：用户得先看到做出来长什么样，才知道这是干啥的）。
   每个功能一节：左边「你给的」、右边「拿到的」，都是真跑出来的样例（examples/manifest.json）。
   「用我的内容试」打开右边的侧栏，填表交给后台队列；跑完的结果用同一套展示。 */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const md = (s) => DOMPurify.sanitize(marked.parse(String(s || '')));
  const plain = (s) => String(s || '').replace(/\*\*|__|`|^>\s?/gm, '').trim();
  const num = (n) => Number(n).toLocaleString('zh-CN');
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const STATE = { waiting: '排队中', running: '在跑', done: '好了', failed: '没成' };
  const S = { tools: [], styles: {}, ex: {}, runs: [], open: null, timer: null, account: null, pick: null };
  // 风格画廊里点「用这个风格画」带过来的风格（/tools?style=<id>，10/11）
  const sampleUrl = (id) => (STATIC ? `/tools/styles/${encodeURIComponent(id)}.webp` : `/tools/styles/sample/${encodeURIComponent(id)}.webp`);
  // 公开站（example.com/tools/）是纯静态页：没有后端，不替陌生人跑 Codex，只放样例。
  // 导出脚本 scripts/export-tools-site.py 在 HTML 里写 window.CS_STATIC = true。
  const STATIC = window.CS_STATIC === true;
  // 公开站上有邀请码服务（window.CS_API）：输入码就能用自己的内容真跑；没有这个地址就只放样例。
  const API = String(window.CS_API || '').replace(/\/$/, '');
  const LIVE = STATIC && !!API;
  // 10/20 作者：工作台里这一页只留文字功能；封面、配图、风格、小红书图文四个出图的搬到素材页（/sucai#make）。
  // 公开站（STATIC）照旧十个都放。
  const LOCAL = !STATIC;
  const IMAGE_KEYS = new Set(['cover', 'illustrate', 'style', 'xhs']);
  const makeUrl = (key) => `/sucai?tool=${encodeURIComponent(key)}#make`;
  const CODE_KEY = 'cs-tools-code';
  const code = {
    get() { try { return localStorage.getItem(CODE_KEY) || ''; } catch (_) { return ''; } },
    set(v) { try { localStorage.setItem(CODE_KEY, v); } catch (_) { /* ignore */ } },
    clear() { try { localStorage.removeItem(CODE_KEY); } catch (_) { /* ignore */ } },
  };
  const money = (cents) => `$${(Number(cents || 0) / 100).toFixed(2)}`;

  async function api(path, body, withCode) {
    // 工作台的写接口要带 x-content-studio；邀请码服务是跨站调用，只认 x-access-code（多一个头就过不了预检）
    const headers = LIVE ? { 'x-access-code': withCode || code.get() } : { 'x-content-studio': '1' };
    if (body) headers['content-type'] = 'application/json';
    const opt = { headers, ...(body ? { method: 'POST', body: JSON.stringify(body) } : {}) };
    let res;
    try { res = await fetch((LIVE ? API : '') + path, opt); } catch (_) { throw new Error('现在连不上这个服务（可能放它的那台电脑没开），晚点再试'); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || `出错了（${res.status}）`);
    return data;
  }
  const exSrc = (name) => `/tools/examples/${encodeURIComponent(name)}`;
  const runSrc = (run) => (rel) => `${LIVE ? API : ''}/api/tools/runs/${encodeURIComponent(run.id)}/file/${rel.split('/').map(encodeURIComponent).join('/')}${LIVE ? `?t=${encodeURIComponent(run.token || '')}` : ''}`;
  const when = (iso) => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }); };

  function toast(text) {
    const t = $('#toast');
    t.textContent = text;
    t.classList.add('in');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => t.classList.remove('in'), 1600);
  }

  /* ---------- 拆 Markdown ---------- */
  function sections(text) {
    const out = [];
    let cur = null;
    for (const line of String(text || '').split('\n')) {
      const h = line.match(/^##\s+(.+)/);
      if (h) { cur = { title: h[1].trim(), body: '' }; out.push(cur); } else if (cur) cur.body += line + '\n';
      else if (line.trim()) { cur = { title: '', body: line + '\n' }; out.push(cur); }
    }
    return out;
  }
  function splitTitle(text) {
    const m = String(text || '').match(/^\s*#\s+(.+)\n/);
    return m ? [m[1].trim(), text.slice(m[0].length).trim()] : ['', String(text || '').trim()];
  }
  const chars = (s) => String(s || '').replace(/\s/g, '').length;

  /* ---------- 「你给的」 ---------- */
  function give(label, parts) {
    return `<div class="sf-give" data-reveal><p class="sf-lab">你给的 · ${esc(label)}</p>${parts}</div>`;
  }
  const src = (text, max = 900) => `<div class="sf-src">${esc(String(text || '').replace(/^>\s?|^#+\s*|\*\*/gm, '').slice(0, max))}</div>`;
  // 长报告先露一截，点「展开」看全；短的不折
  const fold = (inner) => `<div class="sf-fold">${inner}</div><button type="button" class="btn sf-more" hidden>展开完整结果</button>`;
  const count = (text, n) => `<span class="sf-count">全文 ${num(n || chars(text))} 字</span>`;
  const field = (label, value) => `<div class="sf-field"><small>${esc(label)}</small><div>${esc(value)}</div></div>`;
  const get = (label, inner) => `<div class="sf-get" data-reveal><p class="sf-lab">拿到的 · ${esc(label)}</p>${inner}</div>`;
  const pair = (g, r) => `<div class="sf-pair">${g}<div class="sf-arrow" aria-hidden="true">→</div>${r}</div>`;

  /* ---------- 每个功能怎么展示结果 ---------- */
  const R = {
    review(s) {
      const [title, body] = splitTitle(s.input.text);
      const report = sections(s.result.markdown).map((x) => `<div class="sf-sec"><b>${esc(x.title)}</b><div class="md">${md(x.body)}</div></div>`).join('');
      return pair(give('一篇写好的文章', `<h3>${esc(title)}</h3>${src(body)}${count(s.input.text, s.chars?.text)}`), get('点评', fold(`<div class="sf-report">${report}</div>`)));
    },
    topic(s) {
      const d = s.result.data;
      const g = give('一句选题 + 手上的素材', `${field('选题', s.input.title)}${src(s.input.material, 600)}`);
      if (!d) return pair(g, get('三点评分', `<div class="md">${md(s.result.markdown)}</div>`));
      const VERDICT = { go: '能拍', patch: '补一补再拍', thin: '素材太薄，先别拍' };
      const pts = [['pain', '痛点具象度'], ['contrast', '认知反差度'], ['delivery', '交付可行性']];
      const meters = pts.map(([k, label]) => `<div class="sf-meter"><span>${label}</span><div class="sf-pips">${[1, 2, 3, 4, 5].map((i) => `<i class="${i <= d[k].score ? 'on' : ''}"></i>`).join('')}</div><em>${d[k].score} / 5</em></div>`).join('');
      const why = pts.map(([k, label], i) => `<details ${i === 0 ? 'open' : ''}><summary>${label} · ${d[k].score} 分，为什么</summary><p>${esc(d[k].reason)}</p>${d[k].evidence ? `<div class="md"><blockquote>${esc(d[k].evidence)}</blockquote></div>` : ''}</details>`).join('');
      return pair(g, get('三点评分', `<div class="sf-score">
        <div class="sf-total"><b><span data-count="${d.total}">${d.total}</span><small> / 15</small></b><span class="sf-verdict ${esc(d.verdict)}">${esc(VERDICT[d.verdict] || d.verdict)}</span></div>
        <div class="sf-meters">${meters}</div>
        <div class="sf-why">${why}</div>
        <div class="sf-fix"><b>最小改法</b>${esc(d.fix)}</div></div>`));
    },
    titles(s) {
      const rows = [...String(s.result.markdown).matchAll(/^\d+\.\s+\*\*(.+?)\*\*(（超过抖音字数）)?\s*\n\s+(.+?)\s·\s(.+)$/gm)];
      const list = rows.map((m, i) => `<li data-copy="${esc(m[1])}" data-cursor="复制"><i>${String(i + 1).padStart(2, '0')}</i><b>${esc(m[1])}</b><span class="sf-pat">${esc(m[3])}</span><small>${esc(m[4])}${m[2] ? ' · 超过抖音标题字数' : ''}</small></li>`).join('');
      const tags = (String(s.result.markdown).split('## 话题')[1] || '').trim();
      return pair(give('一句主题 + 文字稿', `${field('这条讲什么', s.input.topic)}${src(s.input.text, 600)}${count(s.input.text, s.chars?.text)}`),
        get(`${rows.length} 个标题候选（点一下就复制）`, `<ol class="sf-titles">${list}</ol>${tags ? `<div class="sf-tags">${tags.split('、').map((t) => `<span>#${esc(t)}</span>`).join('')}</div>` : ''}`));
    },
    clean(s) {
      const diff = s.result.diff || [['keep', s.result.copy || '']];
      const text = diff.map(([op, t]) => (op === 'drop' && t.trim() ? `<del>${esc(t)}</del>` : esc(t))).join('');
      const n = s.result.dropped ?? diff.filter(([op, t]) => op === 'drop' && t.trim()).length;
      return pair(give('一段语音输入的口述', `${src(s.input.text, 700)}${count(s.input.text, s.chars?.text)}`),
        get('只删口水词的稿子', `<div class="sf-diff-h"><small>删掉了 <b>${n}</b> 个口水词，其余一个字没改</small>${seg([['diff', '对比'], ['after', '整理后'], ['before', '原话']])}</div><div class="sf-diff" data-mode="diff">${text}</div>`));
    },
    teardown(s) {
      const likes = Number(String(s.input.likes || '').replace(/[wW万]$/, '')) || 0;
      const median = Number(s.input.median) || 0;
      const secs = sections(s.result.markdown);
      const main = secs.find((x) => x.title === '主线');
      const rest = secs.filter((x) => x !== main).map((x) => `<div class="sf-sec"><b>${esc(x.title)}</b><div class="md">${md(x.body)}</div></div>`).join('');
      const stats = likes ? `<div class="sf-stats">
        <div class="sf-stat"><b data-count="${likes}">${num(likes)}</b><small>这条的点赞</small></div>
        ${median ? `<div class="sf-stat"><b data-count="${Math.round(median)}">${num(Math.round(median))}</b><small>账号平时一条</small></div>
        <div class="sf-stat hot"><b><span data-count="${(likes / median).toFixed(1)}" data-dec="1">${(likes / median).toFixed(1)}</span>×</b><small>是平时的几倍</small></div>` : ''}</div>` : '';
      return pair(give('别人一条视频的文字稿 + 点赞数', `${src(s.input.text, 800)}${count(s.input.text, s.chars?.text)}<span class="sf-count">节选自一条公开视频，只用来演示拆解</span>`),
        get('拆解', `${stats}${main ? `<p class="sf-pull">${esc(plain(main.body))}</p>` : ''}${fold(`<div class="sf-report">${rest}</div>`)}`));
    },
    humanize(s) {
      // AI 腔常见的套话：在原文里划出来，读的人一眼看到改掉了什么
      const AI = /(在当今[^，。]*?时代|首先|其次|最后|值得注意的是|总而言之|综上所述|不仅[^，。]{0,12}更是|必由之路|方方面面|显著|高度匹配|深刻地)/g;
      const before = esc(s.input.text).replace(AI, '<del>$1</del>');
      const n = (String(s.input.text).match(AI) || []).length;
      return `<div class="sf-get" data-reveal><div class="sf-diff-h"><p class="sf-lab">你给的 → 拿到的</p><small>左边划掉的 <b>${n}</b> 处是典型的 AI 腔</small></div>
        <div class="sf-vs"><div class="sf-before"><span class="sf-tag">AI 写的</span><div class="sf-diff">${before}</div></div>
        <div class="sf-after"><span class="sf-tag">去掉 AI 味以后</span>${esc(s.result.copy || s.result.markdown)}</div></div></div>`;
    },
    cover(s, at) {
      const img = s.result.images[0];
      return `<div class="sf-media" data-reveal>
        <div><p class="sf-lab">你给的 · 一个标题</p><p class="sf-big-q">${esc(s.input.title)}</p>
          <p class="sf-note">逐字上封面，一个字不改。米白底、橙红斜角、超粗标题；3:4 竖版，抖音、视频号、小红书都能直接用。${s.seconds ? `这一张用了 ${Math.round(s.seconds / 60)} 分钟。` : ''}</p></div>
        <div class="sf-tilt"><div data-zoom="${esc(at(img))}" data-cursor="放大"><img src="${esc(at(img))}" alt="${esc(s.input.title)}" loading="lazy"></div></div>
      </div>`;
    },
    illustrate(s, at) {
      const [title, body] = splitTitle(s.input.text);
      const paras = String(s.result.markdown || '').split(/\n\s*\n/);
      const figs = [];
      paras.forEach((p, i) => {
        const m = p.trim().match(/^!\[([^\]]*)\]\(([^)\s]+)\)$/);
        if (!m) return;
        const before = paras.slice(0, i).reverse().find((x) => x.trim() && !x.trim().startsWith('!['));
        figs.push(`<figure><img src="${esc(at(m[2]))}" alt="${esc(m[1])}" data-zoom="${esc(at(m[2]))}" loading="lazy"><figcaption><b>${esc(m[1])}</b>${before ? `放在「${esc(plain(before).replace(/^#+\s*/, '').slice(0, 28))}…」这段后面` : ''}</figcaption></figure>`);
      });
      return pair(give('一篇文章', `<h3>${esc(title)}</h3>${src(body, 700)}${count(s.input.text, s.chars?.text)}`),
        get(`${figs.length} 张配图，插在各自讲的那一段后面（横着拖）`, `<div class="sf-strip" data-drag data-cursor="拖着看">${figs.join('')}</div>`));
    },
    xhs(s, at) {
      const imgs = s.result.images.map((p) => `<img src="${esc(at(p))}" alt="" loading="lazy">`).join('');
      return pair(give('一篇文章', `<h3>${esc(s.input.title)}</h3>${src(s.input.text, 700)}${count(s.input.text, s.chars?.text)}`),
        get(`${s.result.images.length} 张 3:4 图文，文章一字不改地排进去`, `<div class="sf-xhs"><div class="sf-phone"><div class="sf-swipe" data-drag data-cursor="左右滑">${imgs}</div><div class="sf-dots">${s.result.images.map((_, i) => `<i class="${i ? '' : 'on'}"></i>`).join('')}</div></div>
          <div class="sf-thumbs">${s.result.images.map((p, i) => `<button type="button" class="${i ? '' : 'on'}" data-i="${i}" aria-label="第 ${i + 1} 张"><img src="${esc(at(p))}" alt="" loading="lazy"></button>`).join('')}</div></div>`));
    },
    style(list, at) {
      const imgs = list.map((s, i) => `<img src="${esc(at(s.result.images[0]))}" alt="${esc(s.input.style)}" class="${i ? '' : 'on'}" data-i="${i}">`).join('');
      const sw = list.map((s, i) => `<button type="button" class="sf-swatch${i ? '' : ' on'}" data-i="${i}" data-cursor="换风格"><span><img src="${esc(at(s.result.images[0]))}" alt="" loading="lazy"></span><small>${esc(s.input.style)}</small></button>`).join('');
      return `<div class="sf-styles" data-reveal>
        <div class="sf-stage" data-cursor="放大">${imgs}</div>
        <div><p class="sf-lab">你给的 · 一句主题，挑一个风格</p><p class="sf-big-q">${esc(list[0].input.topic)}</p>
          <div class="sf-swatches">${sw}</div><p class="sf-style-desc">${esc(S.styles[list[0].input.style] || '')}</p>
          <a class="sf-gallery-link" href="/tools/styles">还有几百种画风，每种都有样图 →</a></div>
      </div>`;
    },
  };

  function seg(opts) {
    return `<div class="sf-seg" role="tablist">${opts.map(([k, l], i) => `<button type="button" data-k="${k}" class="${i ? '' : 'on'}">${l}</button>`).join('')}<i></i></div>`;
  }

  /* ---------- 一节一节铺出来 ---------- */
  function render() {
    const tools = S.tools;
    $('#indexIn').insertAdjacentHTML('beforeend', tools.map((t, i) => `<a href="#case-${t.key}" data-key="${t.key}"><i>${String(i + 1).padStart(2, '0')}</i>${esc(t.name)}</a>`).join(''));
    $('#cases').innerHTML = tools.map((t, i) => {
      const ex = S.ex[t.key];
      const body = !ex || !ex.length ? `<div class="sf-get"><p class="muted">这个功能还没有样例。点右上角，用你自己的内容先跑一次。</p></div>`
        : t.key === 'style' ? R.style(ex, exSrc) : R[t.key](ex[0], exSrc);
      return `<section class="sf-case" id="case-${t.key}" data-key="${t.key}">
        <header class="sf-case-h" data-reveal>
          <span class="sf-num">${String(i + 1).padStart(2, '0')} / ${String(tools.length).padStart(2, '0')}</span>
          <h2>${esc(t.name)}<span class="sf-kind">${t.kind === 'image' ? '出图 · 几分钟' : '文字 · 一两分钟'}</span></h2>
          <p>${esc(t.give)} → ${esc(t.get)}</p>
          <button type="button" class="btn primary sf-try" data-try="${t.key}">用我的内容试 <span>→</span></button>
        </header>${body}</section>`;
    }).join('');
    wire($('#cases'));
    hero();
    spy();
    reveal();
    const n = Object.values(S.ex).reduce((a, x) => a + x.reduce((b, s) => b + (s.result.images || []).length, 0), 0);
    $('#heroMeta').textContent = LOCAL ? `${tools.length} 份真结果` : n ? `10 份真结果 · ${n} 张真出的图` : '';
  }

  /* ---------- 交互 ---------- */
  function wire(root) {
    $$('[data-try]', root).forEach((b) => (b.onclick = () => drawer(b.dataset.try)));
    $$('[data-copy]', root).forEach((li) => (li.onclick = async () => {
      try { await navigator.clipboard.writeText(li.dataset.copy); toast('复制好了'); } catch (_) { toast('复制不了，手动选一下'); }
    }));
    $$('.sf-seg', root).forEach(segWire);
    $$('.sf-tilt>div', root).forEach(tilt);
    $$('[data-drag]', root).forEach(dragScroll);
    $$('.sf-swipe', root).forEach(dots);
    $$('.sf-styles', root).forEach(styles);
    $$('[data-zoom]', root).forEach((el) => (el.onclick = () => zoom(el.dataset.zoom)));
    $$('.sf-stage', root).forEach((el) => (el.onclick = () => zoom($('img.on', el).src)));
    $$('.sf-fold', root).forEach((f) => {
      const more = f.nextElementSibling;
      requestAnimationFrame(() => {
        if (f.scrollHeight <= f.clientHeight + 24) { f.classList.add('open'); return; }
        more.hidden = false;
        more.onclick = () => { const open = f.classList.toggle('open'); more.textContent = open ? '收起' : '展开完整结果'; if (!open) f.closest('.sf-case')?.scrollIntoView({ behavior: still ? 'auto' : 'smooth' }); };
      });
    });
  }

  function segWire(segEl) {
    const thumb = $('i', segEl);
    const place = (b) => { thumb.style.width = `${b.offsetWidth}px`; thumb.style.transform = `translateX(${b.offsetLeft - 4}px)`; };
    const btns = $$('button', segEl);
    requestAnimationFrame(() => place(btns[0]));
    btns.forEach((b) => (b.onclick = () => {
      btns.forEach((x) => x.classList.toggle('on', x === b));
      place(b);
      const diff = segEl.closest('.sf-get') && $('.sf-diff', segEl.closest('.sf-get'));
      if (diff) diff.dataset.mode = b.dataset.k;
    }));
  }

  function tilt(el) {
    if (still || matchMedia('(hover: none)').matches) return;
    el.addEventListener('pointermove', (e) => {
      const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      el.classList.add('live');
      el.style.transform = `rotateY(${x * 10}deg) rotateX(${-y * 10}deg) scale(1.02)`;
      el.style.setProperty('--gx', `${(x + 0.5) * 100}%`);
      el.style.setProperty('--gy', `${(y + 0.5) * 100}%`);
    });
    el.addEventListener('pointerleave', () => { el.classList.remove('live'); el.style.transform = ''; });
  }

  function dragScroll(el) {
    let x0 = 0;
    let s0 = 0;
    let moved = false;
    el.addEventListener('pointerdown', (e) => {
      if (e.pointerType !== 'mouse') return;
      x0 = e.clientX; s0 = el.scrollLeft; moved = false;
      el.classList.add('drag');
      const move = (ev) => { if (Math.abs(ev.clientX - x0) > 4) moved = true; el.scrollLeft = s0 - (ev.clientX - x0); };
      const up = () => {
        el.classList.remove('drag');
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        const kids = [...el.children];
        const near = kids.reduce((a, k) => (Math.abs(k.offsetLeft - el.scrollLeft) < Math.abs(a.offsetLeft - el.scrollLeft) ? k : a), kids[0]);
        if (near) el.scrollTo({ left: near.offsetLeft - (el.classList.contains('sf-swipe') ? 0 : 4), behavior: still ? 'auto' : 'smooth' });
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
    // 拖完松手别当成点了一下（不然会顺手打开大图）
    el.addEventListener('click', (e) => { if (moved) { e.stopPropagation(); e.preventDefault(); moved = false; } }, true);
  }

  function dots(el) {
    const ds = $$('.sf-dots i', el.parentElement);
    const th = $$('.sf-thumbs button', el.closest('.sf-xhs') || el.parentElement);
    el.addEventListener('scroll', () => {
      const i = Math.round(el.scrollLeft / el.clientWidth);
      ds.forEach((d, k) => d.classList.toggle('on', k === i));
      th.forEach((d, k) => d.classList.toggle('on', k === i));
    }, { passive: true });
    th.forEach((b) => (b.onclick = () => el.scrollTo({ left: Number(b.dataset.i) * el.clientWidth, behavior: still ? 'auto' : 'smooth' })));
    el.addEventListener('click', () => zoom($$('img', el)[Math.round(el.scrollLeft / el.clientWidth)].src));
  }

  function styles(el) {
    const list = S.ex.style || [];
    const show = (i) => {
      $$('.sf-stage img', el).forEach((im) => im.classList.toggle('on', Number(im.dataset.i) === i));
      $$('.sf-swatch', el).forEach((b) => b.classList.toggle('on', Number(b.dataset.i) === i));
      $('.sf-style-desc', el).textContent = S.styles[list[i]?.input.style] || '';
      el.dataset.i = i;
    };
    $$('.sf-swatch', el).forEach((b) => {
      b.onclick = () => show(Number(b.dataset.i));
      b.onmouseenter = () => show(Number(b.dataset.i));
    });
    el.tabIndex = 0;
    el.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      const n = list.length;
      show((Number(el.dataset.i || 0) + (e.key === 'ArrowRight' ? 1 : n - 1)) % n);
    });
  }

  function zoom(url) {
    const lb = $('#lightbox');
    $('img', lb).src = url;
    lb.hidden = false;
    void lb.offsetWidth;
    lb.classList.add('in');
    const close = () => { lb.classList.remove('in'); setTimeout(() => (lb.hidden = true), 300); document.removeEventListener('keydown', esc2); };
    const esc2 = (e) => { if (e.key === 'Escape') close(); };
    lb.onclick = close;
    document.addEventListener('keydown', esc2);
  }

  /* 视频样片（videos.json）：按仓库分组；滚到才静音循环播放，点开放大、有声音 */
  function videos(data) {
    const groups = (data && data.groups) || [];
    if (!groups.length) return;
    const src = (id, kind) => `/tools/videos/${encodeURIComponent(id)}.${kind}`;
    const secs = (s) => `${s} 秒`;
    $('#vidsBody').innerHTML = groups.map((g) => `<div class="sf-vg" data-reveal>
        <div class="sf-vg-h"><h3>${esc(g.name)}</h3><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.repo)} ↗</a><p>${esc(g.note)}</p></div>
        <div class="sf-vg-grid">${g.items.map((v) => `<figure class="sf-vc">
          <button type="button" class="sf-vc-m" data-vid="${esc(v.id)}" aria-label="放大看：${esc(v.title)}">
            <video muted loop playsinline preload="none" poster="${src(v.id, 'webp')}" src="${src(v.id, 'mp4')}"></video>
            <span class="sf-vc-t">${secs(v.secs)}${v.sound ? ' · 有声' : ''}</span>
          </button>
          <figcaption><b>${esc(v.title)}</b><p>你给的 · ${esc(v.give)}</p>${v.credit ? `<a href="${esc(v.credit_url)}" target="_blank" rel="noopener">提示词 ${esc(v.credit)} ↗</a>` : ''}</figcaption>
        </figure>`).join('')}</div></div>`).join('');
    $('#vids').hidden = false;
    const all = groups.flatMap((g) => g.items);
    $$('[data-vid]').forEach((b) => (b.onclick = () => vbox(all.find((v) => v.id === b.dataset.vid), src)));
    reveal($('#vids'));
    if (still) return;
    const io = new IntersectionObserver((ens) => ens.forEach((en) => {
      const vid = $('video', en.target);
      if (en.isIntersecting) vid.play().catch(() => {});
      else vid.pause();
    }), { threshold: 0.6 });
    $$('.sf-vc-m').forEach((m) => io.observe(m));
  }

  function vbox(v, src) {
    const box = $('#vbox');
    const vid = $('video', box);
    $$('.sf-vc-m video').forEach((x) => x.pause());
    vid.poster = src(v.id, 'webp');
    vid.src = src(v.id, 'mp4');
    $('figcaption', box).textContent = `${v.title} · ${v.secs} 秒${v.sound ? ' · 有声' : ''}`;
    box.hidden = false;
    void box.offsetWidth;
    box.classList.add('in');
    vid.play().catch(() => {});
    const close = () => { vid.pause(); box.classList.remove('in'); setTimeout(() => { box.hidden = true; vid.removeAttribute('src'); vid.load(); }, 300); document.removeEventListener('keydown', esc3); };
    const esc3 = (e) => { if (e.key === 'Escape') close(); };
    box.onclick = (e) => { if (e.target === box || e.target.classList.contains('sf-lb-x')) close(); };
    document.addEventListener('keydown', esc3);
  }

  /* 首屏：真出的图叠成一摞。鼠标一动它们按远近错开；按住能拖走 */
  function hero() {
    const box = $('#stack');
    if (LOCAL) {
      box.hidden = true;
      $('.sf-hero').classList.add('sf-hero-solo');
      // 10/20：顶上说的是下面能直接试的那几个真跑过的例子；目录里是全部功能，两个数分开说
      $('.sf-hero .sf-eyebrow').textContent = `${S.tools.length} 个能直接试的文字功能，下面目录里还有更多`;
      $('.sf-hero-cta').insertAdjacentHTML('beforeend', '<a class="sf-moved" href="/sucai#make">出图（封面、配图、风格、小红书图文）在素材页 →</a>');
      return;
    }
    const pick = [];
    const first = (k) => (S.ex[k] || [])[0];
    const add = (k, img, label) => img && pick.push({ src: exSrc(img), label });
    add('cover', first('cover')?.result.images[0], '封面');
    (S.ex.style || []).slice(0, 3).forEach((s) => add('style', s.result.images[0], `生图 · ${s.input.style}`));
    add('xhs', first('xhs')?.result.images[0], '小红书图文');
    add('illustrate', first('illustrate')?.result.images[0], '正文配图');
    (S.ex.style || []).slice(3).forEach((s) => pick.length < 6 && add('style', s.result.images[0], `生图 · ${s.input.style}`));
    if (!pick.length) { box.hidden = true; return; }
    // 位置是相对这一摞的百分比：x, y, 宽, 角度, 远近
    const SPOT = [[30, 6, 40, -4, 0.9], [2, 26, 30, -9, 0.5], [64, 0, 32, 7, 0.65], [58, 46, 34, -3, 1], [12, 60, 28, 6, 0.75], [34, 52, 46, 2, 0.35]];
    const chips = pick.slice(0, SPOT.length).map((p, i) => {
      const [x, y, w, rot, depth] = SPOT[i];
      const el = document.createElement('div');
      el.className = 'sf-chip';
      el.innerHTML = `<img src="${esc(p.src)}" alt=""><b>${esc(p.label)}</b>`;
      el.style.left = `${x}%`; el.style.top = `${y}%`; el.style.width = `${w}%`;
      el.style.zIndex = String(10 + Math.round(depth * 10));
      box.appendChild(el);
      return { el, rot, depth, dx: 0, dy: 0, px: 0, py: 0, tx: 0, ty: 0, in: 0 };
    });
    let mx = 0;
    let my = 0;
    let z = 40;
    box.parentElement.addEventListener('pointermove', (e) => {
      const r = box.getBoundingClientRect();
      mx = (e.clientX - (r.left + r.width / 2)) / r.width;
      my = (e.clientY - (r.top + r.height / 2)) / r.height;
    });
    chips.forEach((c) => {
      c.el.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        c.el.setPointerCapture(e.pointerId);
        c.el.classList.add('drag');
        c.el.style.zIndex = String(++z);
        const sx = e.clientX - c.dx;
        const sy = e.clientY - c.dy;
        const move = (ev) => { c.dx = ev.clientX - sx; c.dy = ev.clientY - sy; };
        const up = () => { c.el.classList.remove('drag'); c.el.removeEventListener('pointermove', move); c.el.removeEventListener('pointerup', up); };
        c.el.addEventListener('pointermove', move);
        c.el.addEventListener('pointerup', up);
      });
    });
    const t0 = performance.now();
    const loop = (t) => {
      chips.forEach((c, i) => {
        const appear = still ? 1 : Math.min(1, Math.max(0, (t - t0 - 250 - i * 110) / 700));
        c.in = 1 - (1 - appear) ** 3;
        c.tx = still ? 0 : -mx * 40 * c.depth;
        c.ty = still ? 0 : -my * 28 * c.depth;
        c.px += (c.tx - c.px) * 0.08;
        c.py += (c.ty - c.py) * 0.08;
        const lift = (1 - c.in) * 60;
        c.el.style.opacity = String(c.in);
        c.el.style.transform = `translate3d(${c.dx + c.px}px, ${c.dy + c.py + lift}px, 0) rotate(${c.rot * c.in}deg)`;
      });
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  /* 目录：滚到哪一节，哪一个亮，白色滑块跟过去 */
  function spy() {
    const bar = $('#indexBar');
    const links = $$('#indexIn a');
    const set = (key) => {
      const a = links.find((l) => l.dataset.key === key);
      if (!a) return;
      links.forEach((l) => l.classList.toggle('on', l === a));
      bar.style.width = `${a.offsetWidth}px`;
      bar.style.transform = `translateX(${a.offsetLeft}px)`;
      const box = $('#indexIn');
      if (a.offsetLeft < box.scrollLeft || a.offsetLeft + a.offsetWidth > box.scrollLeft + box.clientWidth) {
        box.scrollTo({ left: a.offsetLeft - 16, behavior: still ? 'auto' : 'smooth' });
      }
    };
    const io = new IntersectionObserver((ens) => ens.forEach((en) => en.isIntersecting && set(en.target.dataset.key)), { rootMargin: '-45% 0px -50% 0px' });
    $$('.sf-case').forEach((s) => io.observe(s));
    requestAnimationFrame(() => set(links[0]?.dataset.key));
  }

  /* 滚到才出现；大数字从 0 数上去 */
  function reveal(root) {
    const io = new IntersectionObserver((ens) => ens.forEach((en) => {
      if (!en.isIntersecting) return;
      en.target.classList.add('in');
      io.unobserve(en.target);
      $$('[data-count]', en.target).forEach(countUp);
    }), { threshold: 0.12 });
    $$('[data-reveal]:not(.in)', root).forEach((el) => io.observe(el));
  }
  function countUp(el) {
    const to = Number(el.dataset.count);
    const dec = Number(el.dataset.dec || 0);
    if (still || !to) return;
    const t0 = performance.now();
    const step = (t) => {
      const p = Math.min(1, (t - t0) / 1100);
      const v = to * (1 - (1 - p) ** 4);
      el.textContent = dec ? v.toFixed(dec) : num(Math.round(v));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  /* 跟着鼠标的小标签：只在能拖、能点的东西上出现 */
  function cursor() {
    const c = $('#cursor');
    if (matchMedia('(hover: none)').matches) return;
    document.addEventListener('pointermove', (e) => {
      const t = e.target.closest?.('[data-cursor]');
      c.classList.toggle('on', !!t);
      if (t) c.textContent = t.dataset.cursor;
      c.style.left = `${e.clientX}px`;
      c.style.top = `${e.clientY}px`;
    }, { passive: true });
    document.addEventListener('pointerleave', () => c.classList.remove('on'));
  }

  /* ---------- 侧栏：用我的内容试 ---------- */
  function fieldHtml(f) {
    const id = `f-${f.name}`;
    const opt = f.required ? '' : ' <span class="muted">可不填</span>';
    let input;
    if (f.kind === 'long') input = `<textarea id="${id}" name="${esc(f.name)}" placeholder="${esc(f.hint)}"></textarea>`;
    else if (f.kind === 'select' && f.name === 'style' && S.pick) {
      return `<div class="sf-pick"><span>${esc(f.label)}</span><div class="sf-pick-b"><img src="${esc(sampleUrl(S.pick.id))}" alt=""><div><b>${esc(S.pick.name)}</b><a href="/tools/styles">换一个</a></div></div><input type="hidden" name="style" value="${esc(S.pick.id)}"></div>`;
    } else if (f.kind === 'select') {
      const more = f.name === 'style' ? '<a class="sf-gallery-link" href="/tools/styles">从画风画廊里挑，几百种 →</a>' : '';
      return `<label for="${id}"><span>${esc(f.label)}${opt}</span><select id="${id}" name="${esc(f.name)}">${f.options.map((o) => `<option>${esc(o)}</option>`).join('')}</select>${more}</label>`;
    }
    else input = `<input id="${id}" name="${esc(f.name)}" placeholder="${esc(f.hint)}"${f.kind === 'number' ? ' inputmode="decimal"' : ''}>`;
    return `<label for="${id}"><span>${esc(f.label)}${opt}</span>${input}</label>`;
  }

  function drawer(key) {
    S.open = key || 'all';
    const t = S.tools.find((x) => x.key === key);
    const d = $('#drawer');
    if (LIVE && !S.account) {
      d.innerHTML = `<div class="sf-dr-h"><div><h2>${t ? esc(t.name) : '输入邀请码'}</h2><p>${t ? `${esc(t.give)} → ${esc(t.get)}` : '有码就能用自己的内容真跑一遍'}</p></div><button type="button" class="sf-x" aria-label="关闭">×</button></div>
        <div class="sf-dr-b"><form class="sf-form" id="codeForm"><label for="codeIn"><span>邀请码</span><input id="codeIn" name="code" placeholder="CS-XXXX-XXXX" autocomplete="off" autocapitalize="characters" spellcheck="false"></label>
          <div class="sf-row"><button type="submit" class="btn primary sf-try">进去 <span>→</span></button><span class="sf-err" id="err"></span></div></form>
          <p class="sf-note-line">没有邀请码？<a href="/consultation">预约一对一咨询</a>，告诉我你想试哪个功能。</p></div>`;
    } else if (STATIC && !LIVE) {
      d.innerHTML = `<div class="sf-dr-h"><div><h2>${t ? esc(t.name) : '用我的内容试'}</h2><p>${t ? `${esc(t.give)} → ${esc(t.get)}` : ''}</p></div><button type="button" class="sf-x" aria-label="关闭">×</button></div>
        <div class="sf-dr-b"><div class="sf-static"><p>这一页放的都是真跑出来的结果，在线试用还没开放。</p><p>想用你自己的内容跑一遍，可以先预约一次一对一咨询，告诉我你想试哪个功能。</p><a class="btn primary sf-try" href="/consultation">预约一对一咨询 <span>→</span></a></div></div>`;
    } else d.innerHTML = `<div class="sf-dr-h"><div><h2>${t ? esc(t.name) : '我的记录'}</h2><p>${t ? `${esc(t.give)} → ${esc(t.get)}` : '最近跑过的，点一条看结果'}</p></div><button type="button" class="sf-x" aria-label="关闭">×</button></div>
      <div class="sf-dr-b">${t ? `<form class="sf-form" id="form">${LIVE && S.account ? `<p class="sf-note-line">这一次 <b>${money(t.price)}</b> · 余额 <b data-bal>${money(S.account.balance)}</b>，没做成会退回</p>` : ''}${t.fields.map(fieldHtml).join('')}<div class="sf-row"><button type="submit" class="btn primary sf-try">开始 <span>→</span></button><span class="sf-err" id="err"></span></div></form>` : ''}<div id="runs"></div></div>`;
    $('.sf-x', d).onclick = close;
    if (t && $('#form')) $('#form').onsubmit = submit;
    if ($('#codeForm')) $('#codeForm').onsubmit = (ev) => enterCode(ev, key);
    const scrim = $('#scrim');
    scrim.hidden = false;
    void d.offsetWidth; // 先落位再加 .in，过渡才会走（不靠 requestAnimationFrame：后台标签页里它不跑）
    scrim.classList.add('in');
    d.classList.add('in');
    d.setAttribute('aria-hidden', 'false');
    scrim.onclick = close;
    document.addEventListener('keydown', escClose);
    document.body.style.overflow = 'hidden';
    if (!STATIC || S.account) runs();
    if (!STATIC || LIVE) setTimeout(() => $('input,textarea', d)?.focus(), 450);
  }
  function escClose(e) { if (e.key === 'Escape' && $('#lightbox').hidden) close(); }
  function close() {
    S.open = null;
    $('#drawer').classList.remove('in');
    $('#drawer').setAttribute('aria-hidden', 'true');
    $('#scrim').classList.remove('in');
    setTimeout(() => { $('#scrim').hidden = true; }, 300);
    document.removeEventListener('keydown', escClose);
    document.body.style.overflow = '';
  }

  async function submit(ev) {
    ev.preventDefault();
    const btn = $('button[type=submit]', ev.target);
    $('#err').textContent = '';
    btn.disabled = true;
    try {
      const run = await api(`/api/tools/${encodeURIComponent(S.open)}/run`, Object.fromEntries(new FormData(ev.target).entries()));
      if (LIVE && run.balance != null) setBalance(run.balance);
      S.runs.unshift(run);
      runs();
      poll();
      toast(run.kind === 'image' ? '交上去了，出图要几分钟' : '交上去了，一两分钟');
    } catch (e) {
      $('#err').textContent = e.message;
    } finally {
      btn.disabled = false;
    }
  }

  function setBalance(cents) {
    if (!S.account) return;
    S.account.balance = cents;
    $$('[data-bal]').forEach((el) => (el.textContent = money(cents)));
    topbar();
  }

  function topbar() {
    if (!LIVE) return;
    const a = $('#acct');
    a.hidden = false;
    a.textContent = S.account ? `${S.account.name} · ${money(S.account.balance)}` : '有邀请码？';
    $('#openHistory').hidden = !S.account;
  }

  async function enterCode(ev, key) {
    ev.preventDefault();
    const input = $('#codeIn');
    const typed = input.value.trim();
    const err = $('#err');
    err.textContent = '';
    if (!typed) { err.textContent = '先填邀请码'; return; }
    try {
      const data = await api('/api/tools', null, typed);
      code.set(typed);
      S.account = { name: data.name, balance: data.balance };
      S.runs = data.runs || [];
      topbar();
      toast(`欢迎，${data.name}`);
      drawer(key);
      poll();
    } catch (e) {
      err.textContent = e.message;
    }
  }

  async function pickFromUrl() {
    const want = new URLSearchParams(location.search).get('style');
    if (!want) return;
    if (LOCAL) { location.replace(`/sucai?style=${encodeURIComponent(want)}#make`); return; } // 生图风格搬到素材页了
    try {
      const s = (await (await fetch('/tools/styles.json')).json()).styles.find((x) => x.id === want && x.fn === 'image' && x.sample);
      if (!s) { toast('这个画风还没上架，先看看别的'); return; }
      S.pick = { id: s.id, name: s.name };
      drawer('style');
    } catch (_) { /* 清单读不到就照常看页面 */ }
  }

  async function restore() {
    if (!LIVE || !code.get()) { topbar(); return; }
    try {
      const data = await api('/api/tools');
      S.account = { name: data.name, balance: data.balance };
      S.runs = data.runs || [];
    } catch (e) {
      if (/邀请码/.test(e.message)) code.clear(); // 码被停用了
    }
    topbar();
  }

  function liveResult(run) {
    if (run.state === 'failed') return `<p class="sf-err">${esc(run.error)}</p>`;
    if (run.state !== 'done' || !run.result) return `<div class="sf-wait">${run.state === 'waiting' ? '前面还有别的在跑，轮到它就开始' : run.kind === 'image' ? '在画，几分钟' : '在写，一两分钟'}</div>`;
    const at = runSrc(run);
    const s = { input: run.input, result: run.result };
    try {
      if (R[run.tool] && run.tool !== 'style') return R[run.tool](s, at);
    } catch (_) { /* 结果长得和样例不一样：退回通用的 */ }
    const imgs = (run.result.images || []).map((p) => `<img src="${esc(at(p))}" alt="" data-zoom="${esc(at(p))}">`).join('');
    return `${imgs ? `<div class="sf-imgs">${imgs}</div>` : ''}${run.result.markdown ? `<div class="md">${md(run.result.markdown)}</div>` : ''}`;
  }

  function runs() {
    const box = $('#runs');
    if (!box) return;
    const mine = S.runs.filter((r) => S.open === 'all' || r.tool === S.open).slice(0, S.open === 'all' ? 30 : 6);
    if (S.open === 'all') {
      box.innerHTML = mine.length ? `<div class="sf-hist">${mine.map((r) => `<button type="button" data-key="${esc(r.tool)}"><span class="sf-state ${esc(r.state)}">${STATE[r.state] || esc(r.state)}</span><span>${esc(r.name)}</span><time>${when(r.created)}</time></button>`).join('')}</div>` : '<p class="muted">还没跑过。挑一个功能，点「用我的内容试」。</p>';
      $$('button', box).forEach((b) => (b.onclick = () => drawer(b.dataset.key)));
      return;
    }
    box.innerHTML = mine.map((r) => `<article class="sf-run in"><div class="sf-meta"><span class="sf-state ${esc(r.state)}">${STATE[r.state] || esc(r.state)}</span><time>${when(r.created)}</time></div>${liveResult(r)}</article>`).join('');
    $$('[data-reveal]', box).forEach((el) => el.classList.add('in'));
    wire(box);
  }

  function poll() {
    clearTimeout(S.timer);
    if (!S.runs.some((r) => r.state === 'waiting' || r.state === 'running')) return;
    S.timer = setTimeout(async () => {
      try {
        const before = JSON.stringify(S.runs.map((r) => r.state));
        const data = await api('/api/tools');
        S.runs = data.runs.filter((r) => !LOCAL || !IMAGE_KEYS.has(r.tool));
        if (LIVE && data.balance != null) setBalance(data.balance);
        if (JSON.stringify(S.runs.map((r) => r.state)) !== before) runs();
      } catch (_) { /* 下一轮再问 */ }
      poll();
    }, 3000);
  }

  /* ---------- 按场景找功能：独立加载，失败不影响样例和试用 ---------- */
  async function directory() {
    const dir = $('#dir');
    try {
      const res = await fetch('/tools/usecases.json');
      if (!res.ok) return;
      const { scenes, cards } = await res.json();
      const groupScene = new Map(scenes.flatMap((s) => s.groups.map((g) => [g.id, s.id])));
      const rank = (c) => c.tool ? 0 : c.link ? 1 : 2;
      const visible = cards.filter((c) => c.status !== '想法').sort((a, b) => rank(a) - rank(b));
      const belongs = (c, id) => !id || c.alsoScenes.includes(id) || [c.group, ...c.alsoGroups].some((g) => groupScene.get(g) === id);
      const inGroup = (c, id) => !id || c.group === id || c.alsoGroups.includes(id);
      let scene = '', platform = '', group = '';
      const media = new Set();
      try { scene = localStorage.getItem('cs-tools-scene') || ''; } catch (_) { /* 全部 */ }
      if (!scenes.some((s) => s.id === scene)) scene = '';

      const tab = (id, name) => `<button type="button" class="sf-tab" data-scene="${esc(id)}">${esc(name)}<em>${visible.filter((c) => belongs(c, id)).length}</em></button>`;
      $('#dirTabs').innerHTML = tab('', '全部') + scenes.map((s) => tab(s.id, s.name)).join('');
      const pick = (key, id, name) => `<button type="button" class="sf-pick" data-${key}="${esc(id)}">${esc(name)}</button>`;
      const groupRow = (label, groups, kind) => `<div class="sf-row" data-kind="${kind}"><span class="sf-lab">${label}</span>${pick('group', '', '全部')}${groups.map((g) => pick('group', g.id, g.name)).join('')}</div>`;

      function results() {
        const q = $('#dirQ').value.trim().toLowerCase();
        const matches = visible.filter((c) => belongs(c, scene) && inGroup(c, platform) && inGroup(c, group)
          && (!media.size || c.media.some((m) => media.has(m))) && `${c.name} ${c.note}`.toLowerCase().includes(q));
        $('#dirGrid').innerHTML = matches.length ? matches.map((c) => {
          const level = rank(c), label = ['能用', '去看', '即将上线'][level];
          const contact = !c.tool && c.buy.includes('联系我');
          const tag = c.tool || c.link ? 'a' : 'article';
          const href = c.tool ? (LOCAL && IMAGE_KEYS.has(c.tool) ? makeUrl(c.tool) : `#case-${c.tool}`) : c.link;
          return `<div class="sf-uc-wrap"><${tag} class="sf-uc${contact ? ' sf-uc-contact' : ''}"${href ? ` href="${esc(href)}"` : ''}${c.tool ? ` data-tool="${esc(c.tool)}"` : ''}>
            <b>${esc(c.name)}</b><p>${esc(c.note)}</p><div class="sf-uc-tags"><span class="sf-uc-state sf-uc-state-${level}">${label}</span>${c.media.map((m) => `<span>${esc(m)}</span>`).join('')}</div>
          </${tag}>${contact ? '<a class="sf-uc-consult" href="/consultation">联系我</a>' : ''}</div>`;
        }).join('') : '<p class="sf-dir-empty">这里还没有能用的，换一个看看</p>';
        $$('.sf-pick', dir).forEach((b) => {
          const on = b.dataset.media !== undefined ? media.has(b.dataset.media)
            : b.dataset.group === (b.closest('.sf-row').dataset.kind === 'platform' ? platform : group);
          b.classList.toggle('on', on);
          b.setAttribute('aria-pressed', String(on));
        });
      }

      function filters() {
        $$('.sf-tab', dir).forEach((b) => {
          b.classList.toggle('on', b.dataset.scene === scene);
          b.setAttribute('aria-pressed', String(b.dataset.scene === scene));
        });
        const current = scenes.find((s) => s.id === scene), rows = $('#dirRows');
        rows.hidden = !current;
        rows.innerHTML = '';
        if (current) {
          const platforms = current.groups.filter((g) => g.kind === 'platform');
          rows.innerHTML = (platforms.length ? groupRow('你在做：', platforms, 'platform') : '')
            + groupRow('要做什么：', current.groups.filter((g) => g.kind !== 'platform'), 'task')
            + `<div class="sf-row"><span class="sf-lab">出来的是：</span>${['文字', '图片', '视频', '声音', '数据', '抓取'].map((m) => pick('media', m, m)).join('')}</div>`;
        }
        results();
      }

      dir.addEventListener('click', (e) => {
        const b = e.target.closest('button');
        if (b?.dataset.scene !== undefined) {
          scene = b.dataset.scene;
          platform = group = '';
          media.clear();
          try { localStorage.setItem('cs-tools-scene', scene); } catch (_) { /* ignore */ }
          filters();
        } else if (b?.dataset.group !== undefined) {
          if (b.closest('.sf-row').dataset.kind === 'platform') platform = b.dataset.group;
          else group = b.dataset.group;
          results();
        } else if (b?.dataset.media !== undefined) {
          const value = b.dataset.media;
          if (media.has(value)) media.delete(value); else media.add(value);
          results();
        }
        const link = e.target.closest('[data-tool]');
        if (link && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) {
          const target = document.getElementById(`case-${link.dataset.tool}`);
          if (target) {
            e.preventDefault();
            target.scrollIntoView({ behavior: still ? 'instant' : 'smooth' });
          }
        }
      });
      $('#dirQ').addEventListener('input', results);
      filters();
      dir.hidden = false;
    } catch (_) { dir.hidden = true; /* 目录不可用时，样例照常展示 */ }
  }

  /* ---------- 开机 ---------- */
  directory();
  $('#theme').onclick = () => {
    const r = document.documentElement;
    const dark = r.dataset.theme ? r.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    r.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('cs-theme', r.dataset.theme); } catch (_) { /* ignore */ }
  };
  if (STATIC && !LIVE) $('#openHistory').hidden = true;
  else {
    $('#openHistory').onclick = () => drawer(null);
    if (LIVE) $('#openHistory').hidden = true; // 有账号以后才显示
  }
  if (LIVE) $('#acct').onclick = () => drawer(null);
  cursor();
  // 大标题一行一行升上来（数据还没回来就先动，不等）
  const h1 = $('.sf-hero h1');
  h1.innerHTML = h1.innerHTML.split('<br>').map((l) => `<span class="sf-ln"><span>${l}</span></span>`).join('');
  Promise.all([STATIC ? fetch('/tools/catalog.json').then((r) => r.json()) : api('/api/tools'), fetch('/tools/examples/manifest.json').then((r) => (r.ok ? r.json() : {})).catch(() => ({})),
    fetch('/tools/videos.json').then((r) => (r.ok ? r.json() : {})).catch(() => ({}))])
    .then(([data, ex, vids]) => {
      S.tools = LOCAL ? data.tools.filter((t) => !IMAGE_KEYS.has(t.key)) : data.tools;
      S.styles = data.styles || {};
      S.runs = LIVE ? [] : (data.runs || []).filter((r) => !LOCAL || !IMAGE_KEYS.has(r.tool));
      S.ex = ex;
      render();
      if (!LOCAL) videos(vids); // 工作台里视频样片在素材页
      restore().then(poll).then(pickFromUrl);
    })
    .catch((e) => { $('#cases').textContent = e.message; });
})();
