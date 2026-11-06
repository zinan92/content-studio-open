// 朋友圈（10/18）：他 X 上最新发的，点「复刻到其他平台」原样搬到小红书小号、抖音小号、公众号贴图。
// 帖子是他自己的字，但照样只用 textContent / setAttribute，不拼 HTML。
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { posts: [], packs: {}, open: new Set() };

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

  function say(text, err) {
    $('msg').textContent = text || '';
    $('msg').classList.toggle('err', !!err);
  }

  const ago = (iso) => {
    const t = Date.parse(iso);
    if (!t) return '';
    const min = Math.round((Date.now() - t) / 60000);
    if (min < 60) return `${Math.max(min, 1)} 分钟前`;
    if (min < 1440) return `${Math.round(min / 60)} 小时前`;
    const d = new Date(t);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  };

  async function copy(text, btn) {
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = '复制好了';
    } catch (_) {
      btn.textContent = '复制不了，手动选';
    }
    setTimeout(() => { btn.textContent = '复制'; }, 1600);
  }

  function field(name, text) {
    const btn = h('button', { type: 'button' }, '复制');
    btn.addEventListener('click', () => copy(text, btn));
    return h('div', { class: 'mo-field' }, h('div', { class: 'mo-field-h' }, h('span', {}, name), btn), h('p', {}, text));
  }

  function wechatBox(pack, part) {
    const box = h('div', { class: 'mo-pack-wx' });
    const done = pack.wechat;
    const status = h('p', { class: 'mo-done', role: 'status' }, done ? `草稿箱里有一份（${ago(done.at)}存的）：去公众号后台点发布` : '');
    if (!part.images) return box;
    const btn = h('button', { type: 'button', class: 'btn primary' }, done ? '更新草稿箱那份' : '存进公众号草稿箱');
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      btn.textContent = '在传图…';
      try {
        const r = await api(`/api/moments/${pack.id}/wechat`, {});
        pack.wechat = r;
        status.textContent = r.message;
        status.className = 'mo-done';
        btn.textContent = '更新草稿箱那份';
      } catch (e) {
        status.textContent = e.message;
        status.className = 'mo-note';
        btn.textContent = done ? '更新草稿箱那份' : '存进公众号草稿箱';
      }
      btn.disabled = false;
    });
    box.append(btn, status);
    return box;
  }

  function packView(pack) {
    const cols = ['xhs', 'douyin', 'wechat'].map((key) => {
      const part = pack.packs[key];
      const imgs = pack.images.slice(0, part.images);
      return h('div', { class: 'mo-pack' },
        h('h3', {}, part.label),
        part.title ? field('标题', part.title) : null,
        field('正文', part.body),
        imgs.length ? h('div', { class: 'mo-thumbs' }, imgs.map((name) => {
          const src = `/api/moments/${pack.id}/img/${encodeURIComponent(name)}`;
          return h('a', { href: src, download: name, title: '下载这张' }, h('img', { src, alt: name, loading: 'lazy' }));
        })) : null,
        part.notes.map((n) => h('p', { class: 'mo-note' }, n)),
        key === 'wechat' ? wechatBox(pack, part) : null);
    });
    return h('div', { class: 'mo-packs' }, cols);
  }

  function card(post) {
    const pack = state.packs[post.id];
    const text = h('p', { class: 'mo-text' }, post.text);
    const more = h('button', { type: 'button', class: 'mo-more', hidden: true }, '展开');
    more.addEventListener('click', () => {
      const open = text.classList.toggle('open');
      more.textContent = open ? '收起' : '展开';
    });
    requestAnimationFrame(() => { if (text.scrollHeight > text.clientHeight + 2) more.hidden = false; });
    const go = h('button', { type: 'button', class: post.done ? 'btn' : 'btn primary' }, post.done ? (state.open.has(post.id) ? '收起' : '看复刻好的') : '复刻到其他平台');
    go.addEventListener('click', async () => {
      if (post.done && state.open.has(post.id)) { state.open.delete(post.id); render(); return; }
      go.disabled = true;
      go.textContent = post.photos.length ? '在下载原图…' : '在复刻…';
      try {
        state.packs[post.id] = post.done ? await api(`/api/moments/${post.id}/pack`) : await api(`/api/moments/${post.id}/replicate`, {});
        post.done = post.done || { at: new Date().toISOString() };
        post.new = false;
        state.open.add(post.id);
        say('');
      } catch (e) {
        say(e.message, true);
      }
      render();
      // 复刻好的三份在长帖子下面，常常在屏幕外：滚过去，不然看着像没反应；出错就滚回顶上那句提示
      const packs = document.querySelector(`[data-pid="${post.id}"] .mo-packs`);
      (packs || $('msg')).scrollIntoView({ behavior: 'smooth', block: packs ? 'start' : 'center' });
    });
    const tag = post.new ? h('span', { class: 'mo-tag' }, '刚发的') : post.done ? h('span', { class: 'mo-tag' }, '已复刻') : null;
    return h('li', { class: `mo-post${post.new ? ' new' : ''}`, 'data-pid': post.id },
      h('div', { class: 'mo-meta' }, tag, h('a', { href: post.url, target: '_blank', rel: 'noopener' }, ago(post.at)),
        post.kind === 'quote' ? h('span', {}, '· 引用帖') : null, post.video ? h('span', {}, '· 有视频') : null),
      text, more,
      post.photos.length ? h('div', { class: 'mo-thumbs' }, post.photos.map((src) => h('img', { src, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer' }))) : null,
      h('div', { class: 'mo-actions' }, go),
      pack && state.open.has(post.id) ? packView(pack) : null);
  }

  function render() {
    const list = $('list');
    list.replaceChildren(...state.posts.map(card));
    if (!state.posts.length) list.append(h('li', { class: 'mo-msg' }, '还没读到帖子：点上面的按钮看看 X。'));
  }

  function take(data) {
    state.posts = data.posts || [];
    render();
  }

  async function check() {
    const btn = $('check');
    btn.disabled = true;
    say('在读 X…');
    try {
      const data = await api('/api/moments/check', {});
      take(data);
      const fresh = state.posts.filter((p) => p.new).length;
      if (data.error) say(`${data.error}。下面是上次读到的；急的话把链接贴进来。`, true);
      else say(fresh ? `有 ${fresh} 条刚发的还没复刻` : '没有新的，刚发的都复刻过了');
    } catch (e) {
      say(e.message, true);
    }
    btn.disabled = false;
  }

  $('check').addEventListener('click', check);
  $('form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const url = $('link').value.trim();
    if (!url) return;
    say('在读这条…');
    try {
      await api('/api/moments/add', { url });
      $('link').value = '';
      take(await api('/api/moments'));
      say('读到了');
    } catch (e) {
      say(e.message, true);
    }
  });
  $('theme').addEventListener('click', () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('cs-theme', root.dataset.theme); } catch (_) { /* ignore */ }
  });

  // 一打开就去 X 看一眼：「小王刚刚发了」就排在最上面，标着「刚发的」
  api('/api/moments').then(take).catch(() => {}).finally(check);
})();
