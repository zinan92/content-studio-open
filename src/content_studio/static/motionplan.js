'use strict';
/* AI 排动效（10/18 作者：选题工作台「视频动效」那一页很有用，Studio 也要）。
   放在「剪辑进度」最上面：照这条的口播稿，AI 每句从 ShotCraft 157 个动效里挑一个、说为什么 →
   时间线 + 逐句对照（稿子里这一句 → 拿到的动效）+ 连播预览 + 换一个 → 交给 park-video-v2 写方案、渲染。
   卡和预览来自 /api/video-v2/catalog（videoproject.js 的 loadMotionCatalog）。 */

const MP = { busy: {}, err: {}, open: {} };
const MP_STEPS = ['读稿', '切成镜头', '从 157 个动效里挑', '排时间线', '写每个镜头的理由'];
const mpNorm = (s) => String(s || '').replace(/\s+/g, '');

(function wrapEditTab() {
  const tab = (window.VIDEO_TABS || []).find((x) => x.key === 'edit');
  if (!tab || tab._mp) return;
  const render = tab.render;
  tab._mp = true;
  tab.render = async function (topic, el) {
    await render.call(this, topic, el);
    mountMotionPlan(topic, el);
  };
})();

function mountMotionPlan(topic, el) {
  if (typeof featureOn === 'function' && !featureOn('motion')) return;
  // 10/19：「这次怎么剪」没勾动效就不出这张卡
  const cut = typeof VP !== 'undefined' ? VP.plan[topic.id] : null;
  const pick = cut && (cut.locked ? cut.plan : (VP.draft[topic.id] || cut.plan));
  // 10/19 作者「简单一点」：逐字稿出来了（口播稿才有）才出现，默认收着，点开才读、才画
  const words = cut && (cut.blocks || []).some((b) => b.key === 'words' && b.state === 'done');
  let host = el.querySelector('.mp-host');
  if (cut && !(cut.has_video && pick.motion && words)) { if (host) host.remove(); return; }
  if (!host) {
    host = document.createElement('details');
    host.className = 'mp-host vp-fold';
    host.open = !!MP.open[topic.id];
    host.innerHTML = '<summary>AI 排动效<span class="spacer"></span><small>照口播稿每句挑一个动效</small></summary><section class="mp-body" aria-label="AI 排动效"></section>';
    const slot = el.querySelector('#vpMotionSlot');
    const after = el.querySelector(':scope > #vpPlan');
    if (slot) slot.replaceWith(host); else if (after) after.after(host); else el.prepend(host);
    host.ontoggle = () => { MP.open[topic.id] = host.open; if (host.open) drawMotionPlan(topic, host.querySelector('.mp-body')); };
  }
  if (host.open) drawMotionPlan(topic, host.querySelector('.mp-body'));
}

async function drawMotionPlan(topic, host) {
  let script = '', planData = { plan: null, project: false }, lib;
  try {
    const [s, p, c] = await Promise.all([
      api(`/api/topics/${topic.id}/script`).catch(() => null),
      api(`/api/topics/${topic.id}/motion-plan`),
      loadMotionCatalog(),
    ]);
    script = (s && s.script && s.script.text) || '';
    planData = p; lib = c;
  } catch (err) {
    host.innerHTML = `<div class="mp-card mp-empty"><b>排动效读不到：${esc(err.message)}</b></div>`;
    return;
  }
  const cards = Object.fromEntries((lib.shotcraft || []).map((c) => [c.name, c]));
  const ready = new Set((lib.components || []).flatMap((c) => c.shotcraft || []));
  const plan = planData.plan;
  if (MP.busy[topic.id]) { host.innerHTML = mpThinking(script); return; }
  if (!plan || !plan.beats || !plan.beats.length) {
    host.innerHTML = `<div class="mp-card mp-ask">
        <div class="mp-ask-t"><p>照这条的口播稿，每句从 ${(lib.shotcraft || []).length} 个动效里挑一个、说为什么。排好能连播预览，再交给 park-video-v2 渲染。</p></div>
        ${script ? '<button class="btn primary" type="button" data-mp-go>让 AI 排动效</button>' : '<span class="mp-muted">视频放进来后口播稿会照逐字稿自动出，好了这里就能排。</span>'}
      </div>${MP.err[topic.id] ? `<p class="mp-err" role="alert">${esc(MP.err[topic.id])}</p>` : ''}`;
    const go = host.querySelector('[data-mp-go]');
    if (go) go.onclick = () => mpMake(topic, host, script);
    return;
  }
  const stale = script && mpNorm(script) !== mpNorm(plan.body);
  const cardOf = (b) => cards[b.card] || { name: b.card, summary: '', category: 'effects', category_zh: '动效' };
  const cat = (c) => String(c.category || 'effects').replace(/[^a-z-]/g, '');
  const catName = (c) => String(c.category_zh || c.category || '').replace(/与.*$/, '');
  const strip = plan.beats.map((b, i) => {
    const c = cardOf(b);
    return `<button type="button" class="mp-seg mp-cat-${cat(c)}" data-mp-jump="${i}" title="${esc(b.line)}"><b>${i + 1}</b><span>${esc(catName(c))}</span></button>`;
  }).join('');
  const rows = plan.beats.map((b, i) => {
    const c = cardOf(b);
    const media = c.video_url
      ? `<video src="${esc(c.video_url)}" ${c.poster_url ? `poster="${esc(c.poster_url)}"` : ''} muted loop playsinline preload="none"></video>`
      : '<span class="mp-novideo">暂无预览</span>';
    return `<div class="mp-beat" id="mp-beat-${topic.id}-${i}">
        <div class="mp-card mp-give"><small>镜头 ${i + 1} · 稿子里这一句</small><p>${esc(b.line)}</p></div>
        <span class="mp-arrow" aria-hidden="true">→</span>
        <div class="mp-card mp-get"><small>拿到的 · 动效</small>
          <div class="mp-pick"><div class="mp-clip">${media}</div>
            <div class="mp-meta"><div class="mp-name"><b>${esc(c.name)}</b><span class="mp-pill">${esc(catName(c))}</span>${ready.has(c.name) ? '<span class="mp-pill ok">能直接渲染</span>' : ''}${b.swapped ? '<span class="mp-pill">你换的</span>' : ''}</div>
              <p class="mp-sum">${esc(c.summary || '')}</p>
              ${b.why ? `<div class="mp-why"><b>为什么用它</b>${esc(b.why)}</div>` : ''}
              <button class="btn small" type="button" data-mp-swap="${i}">换一个</button></div></div></div>
      </div>`;
  }).join('');
  host.innerHTML = `<div class="mp">
      <div class="mp-card mp-head">
        ${plan.idea ? `<p class="mp-idea">“${esc(plan.idea)}”</p>` : ''}
        <div class="mp-acts"><button class="btn primary" type="button" data-mp-play>▶ 连播预览</button>
          ${planData.project ? '<button class="btn" type="button" data-mp-hand>交给 park-video-v2</button>' : `<a class="btn" href="/api/topics/${topic.id}/motion-plan.json" download="motion-picks-${topic.id}.json">导出方案</a>`}
          <span class="mp-muted">${plan.beats.length} 个镜头 · ${planData.project ? (plan.handed_at ? '已交给 park-video-v2，写方案时照着挑' : '交过去后 park-video-v2 写方案时照着挑') : '这条做动效（下面拖进剪映导出、点「做动效」）之后能直接交过去'}</span>
          <span class="mp-grow"></span><button class="btn small ghost" type="button" data-mp-redo>重新排</button></div>
        ${stale ? '<p class="mp-stale">口播稿改过了，下面是照改之前那版排的。点「重新排」照新稿子再排一遍。</p>' : ''}
        <div class="mp-strip">${strip}</div>
      </div>
      ${rows}
      <p class="mp-muted mp-credit">动效来自开源仓库 video-shotcraft（Apache-2.0）</p>
    </div>`;
  mpAutoplay(host);
  host.querySelectorAll('[data-mp-jump]').forEach((btn) => { btn.onclick = () => document.getElementById(`mp-beat-${topic.id}-${btn.dataset.mpJump}`).scrollIntoView({ behavior: 'smooth', block: 'center' }); });
  host.querySelector('[data-mp-play]').onclick = () => mpPlayer(plan.beats.map((b) => ({ line: b.line, card: cardOf(b) })));
  host.querySelector('[data-mp-redo]').onclick = () => mpMake(topic, host, script);
  const hand = host.querySelector('[data-mp-hand]');
  if (hand) hand.onclick = async () => {
    hand.disabled = true;
    try { const r = await api(`/api/topics/${topic.id}/motion-plan/hand-off`, { method: 'POST' }); toast(`交过去了：${r.beats} 个镜头写进 v2/motion-picks.json`); drawMotionPlan(topic, host); }
    catch (err) { toast(err.message); hand.disabled = false; }
  };
  host.querySelectorAll('[data-mp-swap]').forEach((btn) => {
    btn.onclick = () => mpSwap(lib, plan.beats[Number(btn.dataset.mpSwap)], async (name) => {
      try { await api(`/api/topics/${topic.id}/motion-plan/beats/${btn.dataset.mpSwap}`, { method: 'PUT', body: { card: name } }); toast('换好了'); drawMotionPlan(topic, host); }
      catch (err) { toast(err.message); }
    });
  });
}

function mpThinking(script) {
  return `<div class="mp-card mp-think" role="status"><b>AI 在排动效</b><ol>${MP_STEPS.map((x, i) => `<li data-mp-step="${i}">${esc(x)}${i === 0 ? ` · ${mpNorm(script).length} 字` : ''}</li>`).join('')}</ol><small>20–60 秒，不用守着</small></div>`;
}

async function mpMake(topic, host, script) {
  if (!script) { toast('先在「口播稿」写好稿子'); return; }
  MP.busy[topic.id] = true; MP.err[topic.id] = '';
  host.innerHTML = mpThinking(script);
  let k = 0;
  const tick = () => host.querySelectorAll('[data-mp-step]').forEach((li) => {
    const i = Number(li.dataset.mpStep);
    li.className = i < k ? 'ok' : i === k ? 'on' : '';
  });
  tick();
  const timer = setInterval(() => { if (k < MP_STEPS.length - 1) { k += 1; tick(); } }, 6000);
  try {
    const r = await api(`/api/topics/${topic.id}/motion-plan`, { method: 'POST', body: { text: script } });
    toast(`排好了：${r.plan.beats.length} 个镜头`);
  } catch (err) {
    MP.err[topic.id] = err.message;
  } finally {
    clearInterval(timer);
    MP.busy[topic.id] = false;
    if (host.isConnected) drawMotionPlan(topic, host);
  }
}

/* 滚到眼前的预览自己播，滚走就停（十来段视频一起播太费） */
function mpAutoplay(root) {
  const vids = [...root.querySelectorAll('.mp-clip video')];
  if (!('IntersectionObserver' in window)) { vids.forEach((v) => v.play().catch(() => {})); return; }
  const io = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (e.isIntersecting) { e.target.preload = 'auto'; e.target.play().catch(() => {}); } else e.target.pause();
  }), { threshold: 0.4 });
  vids.forEach((v) => io.observe(v));
}

function mpDialog(title, inner) {
  const dlg = $('#mpDlg');
  $('#mpTitle').textContent = title;
  $('#mpBody').innerHTML = inner;
  $('#mpClose').onclick = () => dlg.close();
  dlg.onclose = () => { if (!dlg.open) $('#mpBody').innerHTML = ''; };  // 上一个弹层的 close 事件会晚到：已经又打开了就别清
  dlg.showModal();
  return $('#mpBody');
}

/* 连播：一段一段播，下面是这一句当字幕；播完自动下一段，最后一段播完从头来 */
function mpPlayer(seq) {
  const body = mpDialog('连播预览', '<div class="mp-player"><video muted playsinline autoplay></video><p class="mp-sub"></p><div class="mp-dots"></div></div>');
  const v = $('video', body), sub = $('.mp-sub', body), dots = $('.mp-dots', body);
  let i = 0;
  const go = () => {
    if (!v.isConnected) return;
    if (i >= seq.length) i = 0;
    const x = seq[i];
    if (x.card.video_url) { v.src = x.card.video_url; v.play().catch(() => {}); } else { i += 1; setTimeout(go, 400); return; }
    sub.textContent = x.line;
    dots.innerHTML = seq.map((_, j) => `<i class="${j === i ? 'on' : j < i ? 'done' : ''}"></i>`).join('');
  };
  v.onended = () => { i += 1; go(); };
  go();
}

/* 换一个：同一类的排前面，鼠标放上去就播 */
function mpSwap(lib, beat, done) {
  const all = lib.shotcraft || [];
  const cur = all.find((c) => c.name === beat.card) || {};
  const list = [...all.filter((c) => c.category === cur.category && c.name !== cur.name), ...all.filter((c) => c.category !== cur.category)];
  const body = mpDialog('换一个动效', `<p class="mp-muted">这一句：${esc(beat.line)}</p><div class="mp-grid">${list.map((c) => `<button type="button" class="mp-tile" data-mp-card="${esc(c.name)}">
      <span class="mp-clip">${c.poster_url ? `<img src="${esc(c.poster_url)}" alt="" loading="lazy">` : '<span class="mp-novideo">暂无预览</span>'}</span>
      <b>${esc(c.name)}</b><small>${esc(c.summary || '')}</small></button>`).join('')}</div>`);
  body.querySelectorAll('[data-mp-card]').forEach((tile) => {
    const c = all.find((x) => x.name === tile.dataset.mpCard);
    tile.onmouseenter = () => {
      if (!c || !c.video_url || $('video', tile)) return;
      const v = document.createElement('video');
      Object.assign(v, { src: c.video_url, muted: true, loop: true, playsInline: true, autoplay: true });
      $('.mp-clip', tile).append(v);
    };
    tile.onclick = () => { $('#mpDlg').close(); done(tile.dataset.mpCard); };
  });
}
