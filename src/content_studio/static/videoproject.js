'use strict';
/* 视频 · 剪辑进度：关联口播 workflow（ask-park-video）项目目录，按产物读出 14 步进度 */
window.VIDEO_TABS = window.VIDEO_TABS || [];

const VP = { cache: {}, list: null, listAt: 0, media: {}, wt: false, plan: {}, draft: {} };

async function loadProjectList(force) {
  if (!force && VP.list && Date.now() - VP.listAt < 30000) return VP.list;
  VP.list = await api('/api/video-projects');
  VP.listAt = Date.now();
  return VP.list;
}

const fileUrl = (name, rel) => `/api/video-projects/${encodeURIComponent(name)}/file?path=${encodeURIComponent(rel)}`;


/* 把剪映导出放进项目：拖文件夹进来，或者点一下自己选文件夹。
   浏览器只给得到文件名和大小、拿不到路径，所以只把这两样发给后台，由后台去剪映导出目录里找回原文件（不往本机再传一遍）。
   还没关联项目时顺手建好、关联上——以前要先「新建并关联」再等它自己认，10/7 那条就没认出来。 */
async function droppedFiles(dt) {
  const entries = [...dt.items].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (!entries.length) return [...dt.files];
  const out = [];
  const walk = async (entry, depth) => {
    if (entry.isFile) out.push(await new Promise((ok, no) => entry.file(ok, no)));
    else if (entry.isDirectory && depth < 4) {
      const reader = entry.createReader();
      for (;;) {
        const batch = await new Promise((ok, no) => reader.readEntries(ok, no));
        if (!batch.length) break;
        for (const e of batch) await walk(e, depth + 1);
      }
    }
  };
  for (const e of entries) await walk(e, 0);
  return out;
}

const minSec = (n) => (n ? `${Math.floor(n / 60)} 分 ${String(Math.round(n % 60)).padStart(2, '0')} 秒` : '—');

async function renderImport(topic, box, after, note = '') {
  let ex = {};
  try { ex = await api(`/api/topics/${topic.id}/video-project/latest-export`); } catch (err) { /* 目录不在就当没有 */ }
  const e = ex.latest;
  box.innerHTML = `<label class="vp-drop"><b>把剪映导出的文件夹拖到这里</b>
      <span>视频和字幕（.srt）一起放进项目。也可以点这里，自己选文件夹。</span>
      <input type="file" webkitdirectory multiple></label>
    ${e
      // 名字全是日期，认不出内容，所以摆出时长和大小给他核对一眼。
      ? `<div class="vp-media"><span class="muted">或者：剪映最新导出的是</span>
          <b>${esc(e.name)}</b><span class="num">${minSec(e.seconds)}</span><span class="num">${e.mb} MB</span>
          <small class="muted">${day(e.modified_at)}</small>${e.srt ? '<span class="pill hot">带字幕</span>' : ''}
          <button class="btn small" type="button" data-latest>就是它，放进项目</button></div>`
      : ''}
    ${note}`;
  const zone = $('.vp-drop', box);
  const send = async (files) => {
    const picked = files.filter((f) => /\.(mp4|mov|m4v|srt)$/i.test(f.name)).map((f) => ({ name: f.name, size: f.size }));
    if (!picked.length) { toast('里面没有视频或字幕：拖剪映导出的那个文件夹进来'); return; }
    zone.classList.add('busy');
    $('b', zone).textContent = '正在放进项目…';
    try {
      toast((await api(`/api/topics/${topic.id}/video-project/drop`, { method: 'POST', body: { files: picked } })).message);
      await after();
    } catch (err) {
      toast(err.message);
      zone.classList.remove('busy');
      $('b', zone).textContent = '把剪映导出的文件夹拖到这里';
    }
  };
  zone.ondragover = (ev) => { ev.preventDefault(); zone.classList.add('over'); };
  zone.ondragleave = () => zone.classList.remove('over');
  zone.ondrop = async (ev) => { ev.preventDefault(); zone.classList.remove('over'); send(await droppedFiles(ev.dataTransfer)); };
  const input = $('input', zone);
  input.onchange = () => send([...input.files]);
  const b = $('[data-latest]', box);
  if (b) b.onclick = async () => { b.disabled = true; await send([{ name: e.name, size: e.bytes }]); b.disabled = false; };
}

// 没落在拖放区上的文件，浏览器会直接打开它、把工作台换掉。
window.addEventListener('dragover', (ev) => { if (ev.dataTransfer && [...ev.dataTransfer.types].includes('Files')) ev.preventDefault(); });
window.addEventListener('drop', (ev) => { if (ev.dataTransfer && [...ev.dataTransfer.types].includes('Files')) ev.preventDefault(); });

/* Step 3–4：成片 → 字幕 → 可以标 Hook 的工作台。以前这三步要开终端，
   标完还要把导出的 JSON 从下载文件夹拷回项目。 */
async function renderMedia(topic, box, opts = {}) {
  if (!box) return;
  let m;
  try { m = await api(`/api/topics/${topic.id}/video-project/media`); } catch (err) { box.innerHTML = ''; return; }
  const busy = (await api(`/api/topics/${topic.id}/video-project/transcribe`).catch(() => ({}))).running;
  VP.media[topic.id] = m;
  if (!m.video) {
    await renderImport(topic, box, () => (opts.v2 ? refreshVideoTab() : renderMedia(topic, box)));
    return;
  }
  const head = `<span class="pill mid">${esc(m.video.name)} · ${m.video.mb} MB</span>`;
  if (opts.v2) {
    box.innerHTML = `<div class="vp-media"><span class="muted">项目里的粗剪</span>${head}${m.srt ? `<span class="pill mid">${esc(m.srt.name)}</span>` : '<span class="muted">没有字幕文件</span>'}</div>`;
    return;
  }
  if (busy) {
    box.innerHTML = `<div class="vp-media">${head}<span><span class="spin"></span> 正在本机转写，15 分钟的片子大概 2–3 分钟</span></div>`;
    setTimeout(() => { if (S.view === 'work' && VD.tab === 'edit' && document.body.contains(box)) renderMedia(topic, box); }, 15000);
    return;
  }
  if (!m.srt) {
    box.innerHTML = `<div class="vp-media">${head}<span class="muted">没找到字幕</span>
      <button class="btn small primary" type="button" id="vpTranscribe">用本机 whisper 跑一遍</button></div>`;
  } else if (!m.worktable) {
    box.innerHTML = `<div class="vp-media">${head}<span class="pill mid">${esc(m.srt.name)}</span>
      <button class="btn small primary" type="button" id="vpBuild">生成标 Hook 的工作台</button></div>`;
  } else {
    box.innerHTML = `<div class="vp-media">${head}<span class="pill mid">${esc(m.srt.name)}</span>
        ${m.exported ? '<span class="pill hot">已标完并存回项目</span>' : ''}
        <button class="btn small ${VP.wt ? '' : 'primary'}" type="button" id="vpToggleWt">${VP.wt ? '收起工作台' : '在这里标 Hook'}</button>
        <button class="btn small ghost" type="button" id="vpBuild" title="字幕改过之后重建">重建</button></div>
      ${VP.wt ? `<iframe class="vp-wt" src="/api/topics/${topic.id}/video-project/worktable.html" title="标 Hook 的工作台"></iframe>
        <p class="muted vp-wt-note">标完点表里的「保存到项目」，直接写回 analysis/worktable.json，不用再下载再拷回来。上面是空白？<a href="/api/topics/${topic.id}/video-project/worktable.html" target="_blank" rel="noopener">在新标签页打开 ↗</a>（一样能保存到项目）</p>` : ''}`;
  }
  const t = $('#vpTranscribe', box);
  if (t) t.onclick = async () => {
    if (!confirm(`项目里没有字幕。现在用本机 whisper 转写《${m.video.name}》？大概要 2–3 分钟，期间机器会比较忙。`)) return;
    t.disabled = true;
    try { toast((await api(`/api/topics/${topic.id}/video-project/transcribe`, { method: 'POST' })).message); renderMedia(topic, box); }
    catch (err) { toast(err.message); t.disabled = false; }
  };
  const b = $('#vpBuild', box);
  if (b) b.onclick = async () => {
    b.disabled = true;
    try { toast((await api(`/api/topics/${topic.id}/video-project/build-worktable`, { method: 'POST' })).message); renderMedia(topic, box); }
    catch (err) { toast(err.message); b.disabled = false; }
  };
  const tw = $('#vpToggleWt', box);
  if (tw) tw.onclick = () => { VP.wt = !VP.wt; renderMedia(topic, box); };
}

async function refreshVideoTab() {
  VP.cache = {};
  VP.list = null;
  if (window.refreshTopics) await window.refreshTopics();
  const body = $('#videoBody');
  if (body) body.dataset.sig = '';
  renderView();
}

window.VIDEO_TABS.push({
  key: 'edit',
  label: '剪辑进度',
  badge: (t) => (t.video_project ? '已关联' : ''),
  async render(topic, el) {
    if (!topic.video_project) {
      let list;
      try { list = await loadProjectList(false); } catch (err) { el.innerHTML = `<div class="empty"><b>${esc(err.message)}</b></div>`; return; }
      if (list.error) {
        el.innerHTML = `<div class="empty"><b>${esc(list.error)}</b><span>视频项目放在外接硬盘上时，接上硬盘后刷新；也可以在设置里改成别的目录。</span><button class="btn" type="button" onclick="go('settings')">去设置</button></div>`;
        return;
      }
      const free = list.projects.filter((p) => !p.topic_id);
      el.innerHTML = '<div class="vp-start" id="vpImport"></div>';
      const more = `<p>拖进来就会在 <code>${esc(list.root)}</code> 下建好这一条的项目文件夹${topic.outline_path ? '（附拍摄提纲）' : ''}，并把视频和字幕拷进去。</p>
        <details class="vp-more"><summary>还没导出，或者项目文件夹已经有了</summary><div class="acts">
          <button class="btn small" type="button" id="vpCreate">先建一个空的项目文件夹</button>
          ${free.length ? `<select id="vpPick">${free.map((p) => `<option value="${esc(p.name)}">${esc(p.name)} · ${esc(p.summary)}</option>`).join('')}</select><button class="btn small" type="button" id="vpLink">关联这个</button>` : ''}
        </div></details>`;
      await renderImport(topic, $('#vpImport'), refreshVideoTab, more);
      $('#vpCreate').onclick = async () => {
        try { const info = await api(`/api/topics/${topic.id}/video-project`, { method: 'POST' }); toast(`已新建 ${info.name}`); await refreshVideoTab(); } catch (err) { toast(err.message); }
      };
      const link = $('#vpLink');
      if (link) link.onclick = async () => {
        try { await api(`/api/topics/${topic.id}/video-project`, { method: 'PUT', body: { name: $('#vpPick').value } }); toast('已关联'); await refreshVideoTab(); } catch (err) { toast(err.message); }
      };
      return;
    }
    let info = VP.cache[topic.id];
    if (!info || Date.now() - info._at > 20000) {
      try { info = { ...(await api(`/api/topics/${topic.id}/video-project`)), _at: Date.now() }; VP.cache[topic.id] = info; } catch (err) {
        el.innerHTML = `<div class="empty"><b>${esc(err.message)}</b><button class="btn small ghost" type="button" id="vpUnlink">取消关联</button></div>`;
        $('#vpUnlink').onclick = async () => { await api(`/api/topics/${topic.id}/video-project`, { method: 'PUT', body: { name: null } }); await refreshVideoTab(); };
        return;
      }
    }
    let plan = null;
    try { plan = await api(`/api/topics/${topic.id}/video-project/plan`); } catch (err) { /* 读不到就不画那张卡 */ }
    VP.plan[topic.id] = plan;
    el.innerHTML = '<div id="vpPlan"></div><div id="vpMain"></div>';
    renderPlan(topic, plan, $('#vpPlan', el));
    const main = $('#vpMain', el);
    if (info.layout === 'v2') { renderV2(topic, info, main); return; }
    const a = info.artifacts;
    const finalVideo = info.final_video;
    const done = info.steps.filter((x) => x.done).length;
    // 10/19 作者「简单一点」：上面一张卡（现在做什么、一个主按钮），其余全收进一个「更多」
    const sub = (label, inner) => `<div class="vp-more-sec"><b>${label}</b>${inner}</div>`;
    const made = [a['analysis/worktable.html'] && ['analysis/worktable.html', 'worktable'], a['part-a-hook/video.mp4'] && ['part-a-hook/video.mp4', '成品 A（Hook）'],
      a['part-b-body/video.mp4'] && ['part-b-body/video.mp4', '成品 B（正文）'], a['process-log.md'] && ['process-log.md', '过程日志']].filter(Boolean);
    main.innerHTML = `<div class="vp">
      <div id="vpNow"><div class="vp-now"><span class="spin"></span> 正在看这一步…</div></div>

      ${info.blocked_reason ? `<div class="banner warn"><div><b>卡住了：</b>${esc(info.blocked_reason)}</div></div>` : ''}
      <div id="vpMotionSlot"></div>

      <details class="vp-fold vp-more"><summary>更多<span class="spacer"></span><small>素材 · 产物 · 机器明细 · 在外面做完了</small></summary><div>
        ${sub('素材', '<div id="vpMedia"></div><div id="vpOpening"></div>')}
        ${made.length || finalVideo || info.log.length ? sub('产物', `${made.length ? `<div class="vp-artifacts">${made.map(([rel, label]) => `<a class="btn small" href="${fileUrl(info.name, rel)}" target="_blank" rel="noopener">${label} ↗</a>`).join('')}</div>` : ''}
          ${finalVideo ? `<video class="vp-video" controls preload="metadata" src="${fileUrl(info.name, finalVideo)}"></video>` : ''}
          ${info.log.length ? `<ul class="vp-log-list">${info.log.map((l) => `<li><span class="pill ${['pass', 'approved'].includes(l.status) ? 'hot' : 'low'}">${esc(l.status || '—')}</span>${esc(l.title)}</li>`).join('')}</ul>` : ''}`) : ''}
        ${info.steps.length ? sub(`机器明细 <small>ask-park-video ${done} / 14 步</small>`, `<ol class="vp-steps-list">${info.steps.map((x) => `<li class="${x.done ? 'done' : x.step === info.current_step ? 'now' : ''}"><b>Step ${x.step} ${esc(x.name)}</b><span>${esc(x.evidence)}</span></li>`).join('')}</ol>`) : ''}
        ${info.delivered ? '' : sub('在外面做完了', `<div class="vp-skip"><span class="muted">整条已经在外面（剪映、Codex）做完了？成片放进项目，直接去发。</span>
          <button class="btn small" type="button" id="vpExtAll">整条在外面做完了</button></div>`)}
        ${sub('项目文件夹', `<p class="vp-path">${esc(info.path)}</p><div class="vp-cmd"><span>在 Claude 或 Codex 里继续：</span><button class="invoke" type="button" id="vpCmd">${esc(info.continue_command)}</button></div>
          <div class="acts"><button class="btn small" type="button" id="vpRefresh">刷新</button><button class="btn small ghost" type="button" id="vpUnlink">取消关联</button></div>`)}
      </div></details>
    </div>`;
    renderNow(topic, info);
    renderOpening(topic);
    const extAll = $('#vpExtAll', el);
    if (extAll) extAll.onclick = () => markExternal(topic, info, 'all');
    $('#vpRefresh').onclick = async () => { delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); };
    $('#vpUnlink').onclick = async () => { try { await api(`/api/topics/${topic.id}/video-project`, { method: 'PUT', body: { name: null } }); toast('已取消关联'); await refreshVideoTab(); } catch (err) { toast(err.message); } };
    $('#vpCmd').onclick = () => navigator.clipboard.writeText(info.continue_command).then(() => toast('已复制，贴到 Claude 或 Codex'), () => toast(info.continue_command));
  },
});


const mins = (iso) => Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));

/* 口播动效 v2：四步（准备 → 方案 → 渲染 → 终审），进度是 pv2.py 写的真实百分比。
   按钮点两下才生效（第一下变「再点一次确认」），结果留在按钮下面，服务器没收到就明说。 */
function twoStep(btn, out, run) {
  if (!btn) return;
  const label = btn.textContent;
  let armed = 0;
  btn.onclick = async () => {
    if (!armed) {
      armed = setTimeout(() => { armed = 0; btn.textContent = label; }, 6000);
      btn.textContent = '再点一次确认';
      return;
    }
    clearTimeout(armed); armed = 0;
    btn.disabled = true; btn.textContent = '提交中…';
    out.className = 'vp-v2-out'; out.textContent = '';
    try {
      const msg = await run();
      out.className = 'vp-v2-out ok'; out.textContent = msg || '服务器已收到';
      toast(msg || '服务器已收到');
      setTimeout(() => { delete VP.cache[topic_id_of(btn)]; $('#videoBody').dataset.sig = ''; renderView(); }, 900);
    } catch (err) {
      out.className = 'vp-v2-out bad'; out.textContent = `没成功：${err.message}。可以再点一次。`;
      btn.disabled = false; btn.textContent = label;
    }
  };
}
const topic_id_of = (el) => Number(el.closest('[data-topic]').dataset.topic);

function renderV2(topic, info, el) {
  const st = info.v2 || {};
  const w = st.waiting_for;
  const pct = st.percent;
  const running = !w && !st.failed && st.step !== '已交付' && pct !== null && pct !== undefined;
  const video = (rel) => (rel ? `<video class="vp-video" controls preload="metadata" src="${fileUrl(info.name, rel)}"></video>` : '');
  const approveBox = (gate, label, hint) => `<textarea id="v2Msg" rows="2" placeholder="${esc(hint)}"></textarea>
    <div class="acts"><button class="btn primary" type="button" id="v2Approve" data-gate="${gate}">${label}</button></div><div class="vp-v2-out" id="v2Out"></div>`;
  const startBox = (job, label, say) => `<p class="vp-now-say">${say}</p>
    <div class="acts"><button class="btn primary" type="button" id="v2Start" data-job="${job}">${label}</button></div><div class="vp-v2-out" id="v2Out"></div>`;
  let now;
  if (st.failed) {
    now = `<div class="vp-now todo"><div class="vp-now-h"><span class="chip warn">出错了</span><b>${esc(st.step)}</b></div>
      <p class="vp-now-say">${esc(st.detail)}</p>
      ${st.step === '渲染' ? startBox('render', '重新渲染整条', '修好之后从这里重来。') : st.step === '方案' ? startBox('sample', '重新出样片', '修好之后从这里重来。') : ''}</div>`;
  } else if (running) {
    now = `<div class="vp-now busy"><div class="vp-now-h"><span class="chip busy"><span class="spin"></span>在渲染</span><b>${esc(st.step)} · ${pct}%</b></div>
      <div class="vp-bar"><i style="flex:${pct || 0.001}"></i><b style="flex:${100 - pct}"></b></div>
      <p class="vp-now-say">这是 pv2 写的真实进度，几秒刷新一次。</p></div>`;
    clearTimeout(VP.poll);
    VP.poll = setTimeout(() => { if (S.view === 'work' && VD.tab === 'edit' && VD.topicId === topic.id) { delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); } }, 4000);
  } else if (w === '作者 看样片') {
    now = `<div class="vp-now gate"><div class="vp-now-h"><span class="chip warn">等你看</span><b>10 秒样片</b></div>
      <p class="vp-now-say">这段和整条用的是同一个渲染。质量、位置没问题就批准，然后一次渲染整条。</p>
      ${video(st.sample)}${approveBox('sample', '批准样片', '写一句你的话，比如「可以，全部渲染」')}</div>`;
  } else if (w === '跑 sample') {
    now = `<div class="vp-now todo">${startBox('sample', '出 10 秒样片', '方案已经过了程序检查。先出一段 10 秒的最终样子给你看。')}</div>`;
  } else if (w === '跑 render') {
    now = `<div class="vp-now todo">${startBox('render', '开始渲染整条', '样片批过了。渲染全部镜头、合成整条、跑终检，页面上看真实进度。')}</div>`;
  } else if (w === '作者 看成片') {
    now = `<div class="vp-now gate"><div class="vp-now-h"><span class="chip warn">等你终审</span><b>整条成片</b>
        <span class="spacer"></span><a class="btn small" href="${fileUrl(info.name, 'v2/contact.jpg')}" target="_blank" rel="noopener">抽帧总览 ↗</a></div>
      ${video(st.final)}${approveBox('final', '批准成片', '写一句你的话，比如「就这样了」')}</div>`;
  } else if (st.step === '已交付') {
    now = `<div class="vp-now ok"><div class="vp-now-h"><span class="chip ok">交付了</span><b>成片好了，去打包</b>
      <span class="spacer"></span><button class="btn small primary" type="button" onclick="S.packId = ${topic.id}; go('pack')">去标题和封面 →</button></div>${video(st.final)}</div>`;
  } else {
    const say = { '作者 确认 brief': '在下面「动效设置」里定好这条的视频类型、动效放哪、哪些时间段不加、字幕是否已经烧进去，再调密度和动效努力。人脸位置和字幕带要从画面里量：设好后在 Claude 或 Codex 里继续，它会量好、写方案、出样片。', '跑 prep': '对齐字幕时间（约 30 秒）。', 'AI 写 plan.json': '在 Claude/Codex 里让它写动效方案。' }[w] || '';
    now = `<div class="vp-now todo"><div class="vp-now-h">${w === '作者 确认 brief' ? '<span class="chip warn">要你定</span>' : '<span class="chip busy">在对话里做</span>'}<b>${esc(st.step)} · ${esc(w || '')}</b></div>
      <p class="vp-now-say">${esc(say)}</p>
      <div class="vp-cmd"><span>在 Claude 或 Codex 里继续：</span><button class="invoke" type="button" id="vpCmd">${esc(info.continue_command)}</button></div></div>`;
  }
  // 等 作者 定 brief 时，设置面板直接展开：要填的就在这里
  const setState = VP.set[topic.id] || (VP.set[topic.id] = { draft: {}, open: w === '作者 确认 brief' });
  // 10/19：项目路径、刷新、取消关联这些收进最底下的「更多」，上面只留现在要做的那张卡
  el.innerHTML = `<div class="vp" data-topic="${topic.id}">
    ${now}
    <div class="v2-ev" id="v2Ev"></div>
    <div id="vpMotionSlot"></div>
    <details class="v2s" id="v2Set"${setState.open ? ' open' : ''}><summary><b>动效设置</b><small>预设、样式偏好和高级设置</small></summary><div id="v2SetBody"></div></details>
    <details class="vp-fold vp-more"><summary>更多<span class="spacer"></span><small>动效图鉴 · 项目文件夹</small></summary><div>
      <div class="vp-more-sec"><b>项目文件夹</b><p class="vp-path">${esc(info.path)}</p>
        <div class="acts"><button class="btn small" type="button" id="v2Gallery">动效图鉴</button><button class="btn small" type="button" id="vpRefresh">刷新</button>${running ? '' : '<button class="btn small ghost" type="button" data-back="v2">退回：不做动效</button>'}<button class="btn small ghost" type="button" id="vpUnlink">取消关联</button></div></div>
    </div></details>
  </div>`;
  const out = $('#v2Out', el);
  twoStep($('#v2Approve', el), out, async () => {
    const gate = $('#v2Approve', el).dataset.gate;
    const message = ($('#v2Msg', el).value || '').trim();
    if (!message) throw new Error('先写一句你的话');
    await api(`/api/topics/${topic.id}/video-project/v2/approve`, { method: 'POST', body: { gate, message } });
    return gate === 'sample' ? '样片已批准，记进了 v2/approvals.json' : '成片已批准，交付了';
  });
  twoStep($('#v2Start', el), out, async () => {
    const r = await api(`/api/topics/${topic.id}/video-project/v2/start`, { method: 'POST', body: { job: $('#v2Start', el).dataset.job } });
    return r.message || '已在后台启动';
  });
  $('#vpRefresh', el).onclick = () => { delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); };
  bindBack(topic, el);
  $('#vpUnlink', el).onclick = async () => { try { await api(`/api/topics/${topic.id}/video-project`, { method: 'PUT', body: { name: null } }); toast('已取消关联'); await refreshVideoTab(); } catch (err) { toast(err.message); } };
  $('#v2Gallery', el).onclick = () => openMotionGallery();
  loadV2Evidence(topic, $('#v2Ev', el));
  const setBox = $('#v2Set', el);
  if (setState.open) loadV2Settings(topic, $('#v2SetBody', el));
  setBox.ontoggle = () => { setState.open = setBox.open; if (setBox.open) loadV2Settings(topic, $('#v2SetBody', el)); };
  const cmd = $('#vpCmd', el);
  if (cmd) cmd.onclick = () => navigator.clipboard.writeText(info.continue_command).then(() => toast('已复制，贴到 Claude 或 Codex'), () => toast(info.continue_command));
}

/* 证据截图（10/5 作者）：骨架页点过「要」的真截图（新闻、数据、原推、你的后台）放进这条视频，
   写方案时放在你讲到那个论点的地方（park-video-v2 的 Proof 卡，只能用这些、来源照抄）。 */
async function loadV2Evidence(topic, box) {
  if (!box) return;
  let st;
  try { st = await api(`/api/topics/${topic.id}/video-project/v2/evidence`); } catch (err) { box.innerHTML = ''; return; }
  const head = '<b>证据截图</b>';
  if (!st.picked && !st.in_video) {
    box.innerHTML = `${head}<span>骨架页还没点「要」的证据。拍之前在「骨架」页点「按论点找证据」，挑好的会放到视频里你讲到那个论点的地方。</span>`;
    return;
  }
  if (st.synced) {
    box.innerHTML = `${head}<span>视频里放着你在骨架页要的 ${st.in_video} 张，写方案时放在你讲到那个论点的地方。</span>`;
    return;
  }
  box.innerHTML = `${head}<span>骨架页要了 ${st.picked} 张${st.in_video ? `，视频里现在是 ${st.in_video} 张（你后来又改过）` : '，还没放进这条视频'}。</span>
    <button class="btn small primary" type="button" id="v2EvPut">${st.in_video ? '换成骨架页现在要的' : '放进这条视频'}</button>`;
  $('#v2EvPut', box).onclick = async (e) => {
    e.target.disabled = true;
    try { await api(`/api/topics/${topic.id}/video-project/v2/evidence`, { method: 'POST' }); toast('放进去了：写方案时会用'); } catch (err) { toast(err.message); }
    loadV2Evidence(topic, box);
  };
}

/* 动效设置的值和可用档位仍由 pv2.py 提供；VP.set 保存各视频独立的未保存草稿。 */
VP.set = VP.set || {};
const V2_SRC = { project: '这条视频', user: '你的默认', repo: '仓库默认' };
const V2_FORM = { text: '文字', number: '数字', chart: '图表', diagram: '示意图', icon: '图标', image: '图片' };
const V2_NAMES = { density: '动效密度', effort: '表现方式', evidence: '证据素材', exit: '退场时机',
  overshoot: '数字回弹', max_items: '每卡要点上限', min_gap: '卡片间隔（秒）', no_motion: '不加动效的时段',
  captions_burned_in: '已有画面字幕', banned_words: '禁用词', prefer: '偏爱样式', avoid: '不用样式' };
const V2_LABELS = { effort: { b: '图表与示意图', c: '重点定制' }, evidence: { own: '自己的素材', search: '外部证据' } };
const v2SetUrl = (topic) => (topic.id === 'default' ? '/api/video-v2/settings' : `/api/topics/${topic.id}/video-project/v2/settings`);
const v2Value = (st, key) => key in st.draft ? st.draft[key] : st.data.values[key];
function v2Draft(st, key, value) {
  if (JSON.stringify(value) === JSON.stringify(st.data.values[key])) delete st.draft[key];
  else st.draft[key] = value;
}
let MOTION_REQUEST = null;
async function loadMotionCatalog() {
  if (MOTION_CATALOG) return MOTION_CATALOG;
  if (!MOTION_REQUEST) MOTION_REQUEST = api('/api/video-v2/catalog').then((data) => {
    MOTION_CATALOG = data; return data;
  }).finally(() => { MOTION_REQUEST = null; });
  return MOTION_REQUEST;
}
// 10/8 作者：不用一张张点开——每张直接露出画面（封面图），鼠标放上去就在原地播放
function shotcraftLibraryHtml(cards, components = []) {
  const names = Object.fromEntries(components.map((component) => [component.key, component.name]));
  const groups = {};
  cards.forEach((card) => { (groups[card.category_zh || '其他'] ||= []).push(card); });
  const tile = (card) => {
    const adapted = (card.adapted_as || []).map((key) => names[key] || key);
    const thumb = card.poster_url ? `<img src="${esc(card.poster_url)}" alt="" loading="lazy" decoding="async">` : '<span class="sc-none">暂无预览</span>';
    return `<article class="sc-tile" data-shotcraft-card="${esc(card.name)}">
      <button type="button" class="sc-thumb" data-shotcraft-play aria-label="播放 ${esc(card.name)} 演示"${card.video_url ? '' : ' disabled'}>${thumb}</button>
      <div class="sc-tile-t"><b>${esc(card.name)}</b>${adapted.length ? `<span class="sc-adapted" title="已改编成组件：${esc(adapted.join('、'))}">可直接用</span>` : ''}</div>
      <p title="${esc(card.use || '')}">${esc(card.summary || '')}</p>
      <div class="sc-tile-acts"><button type="button" class="btn small ghost" data-copy="${esc(card.name)}">复制样式名</button>${card.video_url ? `<a href="${esc(card.video_url)}" target="_blank" rel="noopener">大图 ↗</a>` : ''}</div>
    </article>`;
  };
  return Object.entries(groups).map(([name, items]) => `<section class="sc-reference-category"><h4>${esc(name)} · ${items.length}</h4><div class="sc-reference-grid">${items.map(tile).join('')}</div></section>`).join('') || '<p class="ms-help">没有找到符合条件的样式卡。</p>';
}
function bindShotcraftLibrary(root) {
  const cardOf = (name) => (MOTION_CATALOG?.shotcraft || []).find((item) => item.name === name);
  const play = (thumb) => {
    const card = cardOf(thumb.closest('[data-shotcraft-card]').dataset.shotcraftCard);
    if (!card?.video_url) return;
    let video = $('video', thumb);
    if (!video) {
      video = document.createElement('video');
      Object.assign(video, { src: card.video_url, muted: true, loop: true, playsInline: true, preload: 'auto' });
      thumb.appendChild(video);
    }
    thumb.classList.add('playing'); video.play().catch(() => {});
  };
  const stop = (thumb) => { thumb.classList.remove('playing'); $('video', thumb)?.pause(); };
  $$('[data-shotcraft-play]', root).forEach((thumb) => {
    thumb.onmouseenter = () => play(thumb);
    thumb.onmouseleave = () => stop(thumb);
    thumb.onfocus = () => play(thumb);
    thumb.onblur = () => stop(thumb);
    thumb.onclick = () => (thumb.classList.contains('playing') ? stop(thumb) : play(thumb));
  });
  $$('[data-copy]', root).forEach((button) => { button.onclick = () => {
    const text = `参考 video-shotcraft 镜头卡 ${button.dataset.copy}，读取原配方及 demo 后适配到当前视频`;
    navigator.clipboard.writeText(text).then(() => toast('已复制样式名与适配要求'), () => toast(text));
  }; });
}
function updateV2Catalog(topic) {
  const state = VP.set[topic.id], box = state.box;
  if (!box?.isConnected) return;
  const body = $('[data-shotcraft-body]', box), count = $('[data-shotcraft-count]', box);
  if (!body) return;
  if (count) count.textContent = MOTION_CATALOG ? `${(MOTION_CATALOG.shotcraft || []).length} 张原始镜头卡` : '点开读取完整图鉴';
  body.innerHTML = state.catalogError ? `<p class="ms-error" role="alert">图鉴读取失败：${esc(state.catalogError)} <button type="button" class="btn small" data-gallery-retry>重试图鉴</button></p>` : MOTION_CATALOG ? shotcraftLibraryHtml(MOTION_CATALOG.shotcraft || [], MOTION_CATALOG.components || []) : '<p class="ms-help" role="status">正在读取 video-shotcraft 图鉴…</p>';
  bindShotcraftLibrary(body);
  const retry = $('[data-gallery-retry]', body);
  if (retry) retry.onclick = () => refreshV2Catalog(topic);
}
async function refreshV2Catalog(topic) {
  const state = VP.set[topic.id];
  if (state.catalogLoading) return;
  state.catalogLoading = true; state.catalogError = ''; updateV2Catalog(topic);
  try { await loadMotionCatalog(); } catch (err) { state.catalogError = err.message; }
  finally { state.catalogLoading = false; }
  // Only update the library: partial edits elsewhere in the form must keep their DOM and focus.
  updateV2Catalog(topic);
}
async function loadV2Settings(topic, box, force) {
  const st = VP.set[topic.id] || (VP.set[topic.id] = { draft: {} });
  if (!box) return;
  st.box = box;
  if (!st.data || force) {
    box.innerHTML = '<p class="v2s-now" role="status">读取设置…</p>';
    try { st.data = await api(v2SetUrl(topic)); } catch (err) {
      box.innerHTML = /找不到/.test(err.message) ? '<p class="vp-v2-out">视频动效工具还没安装，可先完成其他步骤。</p>' : `<p class="vp-v2-out bad" role="alert">读不到设置：${esc(err.message)}</p>`;
      return;
    }
  }
  drawV2Settings(topic, box);
  if (st.galleryOpen && !MOTION_CATALOG && !st.catalogLoading && !st.catalogError) await refreshV2Catalog(topic);
}

function drawV2Settings(topic, box) {
  const st = VP.set[topic.id], d = st.data, sc = d.schema;
  const val = (key) => v2Value(st, key);
  const name = (item) => V2_NAMES[item.key] || item.name;
  const src = (key) => `<span class="v2s-src${key in st.draft ? ' edit' : ''}">${key in st.draft ? '未保存' : esc(V2_SRC[d.source[key]] || '')}</span>`;
  const label = (key, level) => V2_LABELS[key]?.[level.value] || level.label;
  const available = (item) => item.levels.filter((level) => level.available !== false);
  const segmented = (item) => {
    const levels = available(item), current = item.levels.find((level) => level.value === val(item.key));
    if (levels.length <= 1) return `<div class="ms-fixed"><b>${esc(name(item))}</b><span>${esc(current?.label || levels[0]?.label || '暂无可用选项')}</span><small>${esc(current?.detail || '')}</small></div>`;
    return `<section class="ms-control"><div class="v2s-h"><b>${esc(name(item))}</b>${src(item.key)}</div>
      <p class="ms-help">${esc(item.help || '')}</p><div class="ms-segments" role="group" aria-label="${esc(name(item))}">
      ${levels.map((level) => `<button type="button" data-level="${esc(item.key)}" data-value="${esc(level.value)}" aria-pressed="${level.value === val(item.key)}" title="${esc(level.detail || '')}">${esc(label(item.key, level))}</button>`).join('')}</div>
      <p class="ms-detail">${esc(current?.detail || '')}${current?.cost ? ` · ${esc(current.cost)}` : ''}</p></section>`;
  };
  const choice = (item) => {
    const value = val(item.key);
    let input;
    if (item.type === 'components') return '';
    if (item.options) input = `<select data-choice="${esc(item.key)}">${item.options.filter((o) => o.available !== false).map((o) => `<option value="${esc(o.value)}"${o.value === value ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
    else if (item.type === 'color') input = `<input type="color" data-choice="${esc(item.key)}" value="${esc(value || '')}">`;
    else if (item.type === 'bool') input = `<input type="checkbox" data-choice="${esc(item.key)}"${value ? ' checked' : ''}>`;
    else if (item.type === 'int' || item.type === 'number') input = `<input type="number" data-choice="${esc(item.key)}" data-type="${item.type}" min="${item.min ?? ''}" max="${item.max ?? ''}" step="${item.type === 'int' ? 1 : 0.5}" value="${esc(value ?? '')}">`;
    else return '';
    return `<label class="v2s-choice"><span><b>${esc(name(item))}</b>${src(item.key)}</span>${input}</label>`;
  };
  const isDefault = topic.id === 'default';
  const perDirty = (sc.per_video || []).some((item) => item.key in st.draft);
  const perInput = (item) => {
    const value = val(item.key), attr = `data-per="${esc(item.key)}"`;
    if (item.options) return `<select ${attr}><option value="">还没定</option>${item.options.map((o) => `<option value="${esc(o.value)}"${o.value === value ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
    if (item.key === 'captions_burned_in') return `<select ${attr}><option value="">还没定</option><option value="true"${value === true ? ' selected' : ''}>已烧进画面</option><option value="false"${value === false ? ' selected' : ''}>没有</option></select>`;
    if (item.key === 'no_motion') return `<input ${attr} value="${esc(Array.isArray(value) ? value.map((v) => Array.isArray(v) ? v.join('-') : v).join(', ') : '')}" placeholder="如 312.9-565.4, 600-620（秒）">`;
    return `<input ${attr} value="${esc(Array.isArray(value) ? value.join('，') : value || '')}" placeholder="${item.key === 'video_type' ? '如 横屏口播' : '用逗号隔开'}">`;
  };
  const per = isDefault ? '' : `<section class="ms-per"><h3>这条视频</h3><p class="ms-help">以下信息只用于当前视频，不会成为默认。</p><div class="ms-choices">
    ${(sc.per_video || []).map((item) => `<label class="v2s-choice"><span><b>${esc(name(item))}</b>${item.key in st.draft ? src(item.key) : ''}</span>${perInput(item)}</label>`).join('')}</div>
    <p class="ms-help">${['canvas', 'face_box', 'caption_band'].some((k) => k in d.values) ? '已读取画面、人脸和字幕区域。' : '画面、人脸和字幕区域将在制作时从原片测量。'}</p></section>`;
  const fields = [...(sc.sliders || []), ...(sc.choices || []), ...(sc.per_video || [])];
  const dirty = Object.keys(st.draft), changes = dirty.map((key) => name(fields.find((item) => item.key === key) || { key, name: key })).join('、');
  const common = ['density', 'effort', 'evidence'];
  box.innerHTML = `<div class="motion-settings"><fieldset class="ms-fields"${st.saving ? ' disabled' : ''}><legend class="ms-legend">动效设置</legend>
    <div class="ms-presets" role="group" aria-label="动效预设">${(sc.presets || []).filter((p) => p.available !== false).map((preset) => {
      const index = sc.presets.indexOf(preset);
      const description = Object.entries(preset.values).map(([key, value]) => {
        const item = (sc.sliders || []).find((s) => s.key === key), level = item?.levels.find((l) => l.value === value);
        return level ? `${name(item)}：${label(key, level)}` : '';
      }).filter(Boolean).join(' · ');
      return `<button type="button" class="ms-preset" data-preset="${index}" aria-pressed="${Object.entries(preset.values).every(([key, value]) => JSON.stringify(val(key)) === JSON.stringify(value))}"><b>${esc(preset.name)}</b><span>${esc(description)}</span></button>`;
    }).join('')}</div><p class="ms-help">预设只调整上面列出的项目；保存后生效。</p>
    <div class="ms-common">${(sc.sliders || []).filter((item) => common.includes(item.key)).map(segmented).join('')}</div>
    <details class="ms-shotcraft" data-shotcraft-library${st.galleryOpen ? ' open' : ''}><summary><b>video-shotcraft 完整样式图鉴</b><span data-shotcraft-count>${MOTION_CATALOG ? `${(MOTION_CATALOG.shotcraft || []).length} 张原始镜头卡` : '点开读取完整图鉴'}</span></summary><p class="ms-help">鼠标放到画面上就播放。标「可直接用」的已接进引擎，其余是参考，要适配。</p><div data-shotcraft-body>${MOTION_CATALOG ? shotcraftLibraryHtml(MOTION_CATALOG.shotcraft || [], MOTION_CATALOG.components || []) : ''}</div></details>
    <details class="ms-advanced"${st.advanced ? ' open' : ''}><summary>高级设置 · 卡片、节奏与文字</summary>
      <div class="ms-choices">${(sc.choices || []).map(choice).join('')}</div>
      <div class="ms-fixed-list">${(sc.sliders || []).filter((item) => !common.includes(item.key)).map(segmented).join('')}</div>${per}</details></fieldset>
    <div class="ms-savebar${dirty.length || st.saving || st.noteClass === 'bad' ? ' is-dirty' : ''}"><div class="ms-save-status" role="status" aria-live="polite"><b>${st.saving ? '正在保存…' : dirty.length ? `${dirty.length} 项未保存` : st.noteClass === 'ok' ? '已保存' : '当前设置已生效'}</b>${dirty.length ? `<span>${esc(changes)}</span>` : ''}</div>
      <div class="ms-actions">${isDefault ? '' : `<button class="btn primary" type="button" id="vsSave"${dirty.length && !st.saving ? '' : ' disabled'}>保存到这条视频</button>`}
      <button class="btn${isDefault ? ' primary' : ''}" type="button" id="vsDefault"${dirty.length && !perDirty && !st.saving ? '' : ' disabled'}>设为以后默认</button>
      <button class="btn ghost" type="button" id="vsUndo"${dirty.length && !st.saving ? '' : ' disabled'}>撤销</button></div>
      ${perDirty ? '<p class="ms-help">含当前视频专属信息，请保存到这条视频。</p>' : ''}
      <p class="ms-feedback${st.noteClass === 'bad' ? ' ms-error' : ''}" id="vsOut" role="${st.noteClass === 'bad' ? 'alert' : 'status'}">${esc(st.note || '')}</p></div></div>`;
  const redraw = (control) => {
    const dataset = control ? { ...control.dataset } : null;
    drawV2Settings(topic, box);
    if (dataset) $$('button, input, select', box).find((node) => Object.entries(dataset).every(([key, value]) => node.dataset[key] === value))?.focus();
  };
  const put = (key, value, control) => {
    if (st.saving) return;
    v2Draft(st, key, value); st.note = ''; st.noteClass = ''; redraw(control);
  };
  $$('[data-level]', box).forEach((button) => { button.onclick = () => {
    const item = sc.sliders.find((s) => s.key === button.dataset.level);
    const level = available(item).find((l) => String(l.value) === button.dataset.value);
    if (level) put(item.key, level.value, button);
  }; });
  $$('[data-choice]', box).forEach((input) => { input.onchange = () => {
    if (input.type === 'number' && (input.value === '' || !input.checkValidity())) return;
    const value = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.type === 'color' ? input.value.toUpperCase() : input.value;
    put(input.dataset.choice, value, input);
  }; });
  $$('[data-per]', box).forEach((input) => { input.onchange = () => {
    const key = input.dataset.per, raw = input.value.trim();
    if (key === 'captions_burned_in') { if (raw) put(key, raw === 'true', input); return; }
    if (key === 'no_motion') {
      const spans = (raw ? raw.split(/[,，、\s]+/).filter(Boolean) : []).map((part) => part.split(/[-–~]/).map(Number));
      if (spans.some((span) => span.length !== 2 || span.some((n) => !Number.isFinite(n)) || span[0] >= span[1])) {
        st.note = '时段请填写「开始-结束」（秒），如 312.9-565.4；多段用逗号隔开。'; st.noteClass = 'bad'; redraw(input); return;
      }
      put(key, spans, input); return;
    }
    if (key === 'banned_words') { put(key, raw ? raw.split(/[,，、]+/).map((part) => part.trim()).filter(Boolean) : [], input); return; }
    if (raw) put(key, raw, input);
  }; });
  $$('[data-preset]', box).forEach((button) => { button.onclick = () => {
    if (st.saving) return;
    const preset = sc.presets[Number(button.dataset.preset)];
    Object.entries(preset.values).forEach(([key, value]) => v2Draft(st, key, value));
    st.note = `已套用「${preset.name}」，保存后生效。`; st.noteClass = ''; redraw(button);
  }; });
  $('.ms-advanced', box).ontoggle = (event) => { st.advanced = event.target.open; };
  const library = $('[data-shotcraft-library]', box);
  if (library) library.ontoggle = () => {
    st.galleryOpen = library.open;
    if (library.open && !MOTION_CATALOG && !st.catalogLoading) refreshV2Catalog(topic);
  };
  bindShotcraftLibrary(box);
  const save = (scope) => async () => {
    if (st.saving || !Object.keys(st.draft).length || (scope === 'default' && perDirty)) return;
    const values = JSON.parse(JSON.stringify(st.draft));
    st.saving = true; st.note = ''; st.noteClass = ''; drawV2Settings(topic, box);
    try {
      const result = await api(v2SetUrl(topic), { method: 'POST', body: { values, scope } });
      st.data = result.settings; st.draft = {};
      st.note = scope === 'default' ? `已设为以后默认${isDefault ? '。' : '；这条视频单独设置过的项目不受影响。'}` : '已保存到这条视频。';
      st.noteClass = 'ok'; toast(st.note);
      if (scope === 'project') {
        delete VP.cache[topic.id];
        const videoBody = $('#videoBody'); if (videoBody) videoBody.dataset.sig = '';
      }
    } catch (err) { st.note = `保存失败：${err.message}。改动仍保留，可以重试。`; st.noteClass = 'bad'; }
    finally { st.saving = false; }
    if (st.box?.isConnected) drawV2Settings(topic, st.box); else drawV2Settings(topic, box);
    if (scope === 'project' && st.noteClass === 'ok') renderView();
  };
  if ($('#vsSave', box)) $('#vsSave', box).onclick = save('project');
  $('#vsDefault', box).onclick = save('default');
  $('#vsUndo', box).onclick = () => { if (!st.saving) { st.draft = {}; st.note = '已撤销未保存的改动。'; st.noteClass = ''; drawV2Settings(topic, box); } };
}

/* 动效图鉴：能直接用的组件（带 3 秒演示）+ ShotCraft 全部样式卡（叫不出名字时翻这里挑，可以让 AI 改编）。 */
let MOTION_CATALOG = null;
async function openMotionGallery() {
  const dlg = $('#motionDlg');
  const body = $('#motionBody');
  dlg.showModal();
  $('#motionClose').onclick = () => dlg.close();
  if (!MOTION_CATALOG) {
    body.innerHTML = '<p class="v2s-now">读取图鉴…</p>';
    try { await loadMotionCatalog(); } catch (err) {
      body.innerHTML = `<p class="vp-v2-out bad">读不到图鉴：${esc(err.message)}</p>`;
      return;
    }
  }
  drawMotionGallery('');
  $('#motionQ').value = '';
  $('#motionQ').oninput = (e) => drawMotionGallery(e.target.value.trim().toLowerCase());
  $('#motionClose').onclick = () => dlg.close();
}

function drawMotionGallery(q) {
  const { components = [], shotcraft = [] } = MOTION_CATALOG;
  const hit = (...values) => !q || values.flat().some((value) => String(value || '').toLowerCase().includes(q));
  const cards = shotcraft.filter((card) => hit(card.name, card.summary, card.use, card.category_zh));
  const body = $('#motionBody');
  body.innerHTML = `<details class="ms-shotcraft" open><summary><b>video-shotcraft 完整样式图鉴</b><span>${cards.length} / ${shotcraft.length} 张原始镜头卡</span></summary><p class="ms-help">鼠标放到画面上就播放。标「可直接用」的已接进引擎，其余是参考，要适配。</p>${shotcraftLibraryHtml(cards, components)}</details>
    <details class="sc-engine"><summary>当前引擎组件 · ${components.length} 种</summary><p class="ms-help">这里是已接入引擎的组件，与上面的完整参考图鉴分开列出。</p><div class="sc-engine-list">${components.map((component) => `<span>${esc(component.name)} · ${esc(V2_FORM[component.form] || component.form || '')}</span>`).join('')}</div></details>`;
  bindShotcraftLibrary(body);
}

/* 这次怎么剪（10/19 作者）：视频进来以后他自己选这一条走哪几块——Hook 剪不剪、动效加不加。
   以前这件事散在四处（Hook 下拉、「这条不剪 Hook」、「做动效 / 不加动效」、版式），现在只在这张卡里。
   开始以后卡锁住，变成进度：只列勾上的块。上一次的选择存进设置，下一条默认照它。 */
const CUT_SAY = {
  plain: '粗剪就是成片，直接去定标题和封面。',
  motion: '不剪 Hook，正文加动效（park-video-v2）：先定动效设置，出 10 秒样片给你看。',
  full: '剪 Hook、加动效（park-video-v2）：先在这里标 Hook、切 h1–h5，你在剪映里拼到开头，放回来再做动效。',
  hook: '只剪 Hook：在这里标 Hook，导出 h1–h5 片段，你拖进剪映自己拼。',
};
const cutRoute = (p) => (p.hook ? (p.motion ? 'full' : 'hook') : (p.motion ? 'motion' : 'plain'));
// 文件夹名是建项目那天的标题，标题后来改过就对不上：只提醒，不拦
const cutNorm = (t) => String(t || '').replace(/^\d{4}-\d{2}-\d{2}_/, '').replace(/[\s\p{P}\p{S}]/gu, '');
function cutMismatch(topic, plan) {
  if (!plan || !plan.project) return false;
  try { if (localStorage.getItem(`vp-same-${topic.id}`) === plan.project) return false; } catch (err) { /* 存不了就每次提醒 */ }
  const a = cutNorm(plan.project), b = cutNorm(topic.title);
  return !!a && !!b && !a.includes(b.slice(0, 6)) && !b.includes(a.slice(0, 6));
}

function renderPlan(topic, plan, box) {
  if (!box) return;
  // 10/19：文件夹名一行小字跟在卡片标题旁边；对不上只在这行里问一句，不再是一条粉色大横幅
  // 10/20：一条内容一个名字。文件夹名平时不露（在「更多 · 项目文件夹」里），只在对不上时问一句
  const folder = plan && plan.project && cutMismatch(topic, plan) ? `<span class="cut-proj">项目文件夹「${esc(plan.project)}」和这条的名字对不上，是同一条吗？<button class="linklike" type="button" id="cutSame">是这条</button><button class="linklike" type="button" id="cutRelink">换一个</button></span>` : '';
  const warn = folder ? `<p class="cut-proj-row">${folder}</p>` : '';
  if (!plan || (!plan.has_video && !plan.locked)) { box.innerHTML = warn; bindMismatch(topic, plan, box); return; }
  if (plan.locked) {
    const p = plan.plan;
    box.innerHTML = `<section class="cut-plan locked" aria-label="这次怎么剪">
      <div class="cut-plan-h"><b>这次怎么剪</b><span class="cut-pick">Hook ${p.hook ? '剪' : '不剪'} · 动效 ${p.motion ? '加' : '不加'}</span>${folder}</div>
      <ol class="vp-v2-steps cut-blocks">${plan.blocks.map((b) => `<li class="${b.state}">${esc(b.label)}</li>`).join('')}</ol></section>`;
    bindMismatch(topic, plan, box);
    return;
  }
  const d = VP.draft[topic.id] || (VP.draft[topic.id] = { ...plan.plan });
  const seg = (key, label, opts) => `<div class="cut-seg" role="group" aria-label="${label}"><span>${label}</span>${opts.map(([v, t]) => `<button type="button" class="${d[key] === v ? 'on' : ''}" aria-pressed="${d[key] === v}" data-cut="${key}" data-val="${v}">${t}</button>`).join('')}</div>`;
  const route = cutRoute(d);
  box.innerHTML = `<section class="cut-plan" aria-label="这次怎么剪">
    <div class="cut-plan-h"><b>这次怎么剪</b><small>${plan.chosen ? '' : '默认照上一次'}</small>${folder}</div>
    <div class="cut-row">${seg('hook', 'Hook', [[true, '剪'], [false, '不剪']])}${seg('motion', '动效', [[true, '加'], [false, '不加']])}</div>
    <p class="cut-say">${CUT_SAY[route]}</p>
    <div class="acts"><button class="btn primary" type="button" id="cutStart">开始</button></div></section>`;
  const save = () => api(`/api/topics/${topic.id}/video-project/plan`, { method: 'PUT', body: d }).catch((err) => toast(err.message));
  $$('[data-cut]', box).forEach((b) => (b.onclick = () => {
    d[b.dataset.cut] = b.dataset.val === 'true'; save(); renderPlan(topic, plan, box);
    if (typeof mountMotionPlan === 'function' && box.parentElement) mountMotionPlan(topic, box.parentElement);
  }));
  const start = $('#cutStart', box);
  start.onclick = async () => {
    start.disabled = true;
    try {
      const r = await api(`/api/topics/${topic.id}/video-project/plan/start`, { method: 'POST', body: d });
      toast(r.message);
      delete VP.draft[topic.id]; delete VP.cache[topic.id];
      if (r.route === 'motion') VP.set[topic.id] = { draft: {}, open: true };
      await refreshVideoTab();
    } catch (err) { toast(err.message); start.disabled = false; }
  };
  bindMismatch(topic, plan, box);
}
function bindMismatch(topic, plan, box) {
  const same = $('#cutSame', box);
  if (same) same.onclick = () => { try { localStorage.setItem(`vp-same-${topic.id}`, plan.project); } catch (err) { /* 存不了下次再问 */ } renderPlan(topic, plan, box); };
  const relink = $('#cutRelink', box);
  if (relink) relink.onclick = async () => {
    if (!confirm(`取消关联「${plan.project}」？文件夹里的东西不动，取消后重新放这一条的视频。`)) return;
    try { await api(`/api/topics/${topic.id}/video-project`, { method: 'PUT', body: { name: null } }); toast('已取消关联'); await refreshVideoTab(); } catch (err) { toast(err.message); }
  };
}

/* 这一页只回答一个问题：现在轮到谁、要做什么。
   状态由 14 步的 current_step / gate / 后台任务决定，不靠一颗颗手加的按钮堆出来。 */
async function renderNow(topic, info) {
  const box = $('#vpNow');
  if (!box) return;
  let data = {};
  try { data = await api(`/api/topics/${topic.id}/video-project/run`); } catch (err) { /* 没跑过就当没有 */ }
  const run = data.run;
  const running = run && run.state === 'running';
  const plan = VP.plan[topic.id];
  const route = plan && plan.locked ? plan.route : null;
  const blockOf = (n) => (n <= 4 ? '准备' : [5, 7, 8, 9].includes(n) ? 'Hook' : n === 14 ? '成片' : '动效');
  const last = run && !running
    ? `<details class="vp-last"><summary>${{ done: '上次运行结束', failed: '上次运行失败', cancelled: '上次运行已中止' }[run.state] || '上次运行'} · ${day(run.started_at)}</summary><pre class="vp-log-tail">${esc(run.log_tail || '（没有输出）')}</pre></details>`
    : '';

  if (running) {
    box.innerHTML = `<div class="vp-now busy"><div class="vp-now-h"><span class="chip busy"><span class="spin"></span>机器在跑</span>
        <b>${blockOf(info.current_step || 1)} · ${esc((info.steps[(info.current_step || 1) - 1] || {}).name || '')}</b>
        <span class="spacer"></span><button class="btn small ghost" type="button" id="runCancel">中止</button></div>
      <p class="vp-now-say">已跑 ${mins(run.started_at)} 分钟。跑到下一个要你拍板的地方就停。</p></div>${last}`;
    clearTimeout(VP.poll);
    VP.poll = setTimeout(() => { if (S.view === 'work' && VD.tab === 'edit' && VD.topicId === topic.id) { delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); } }, 8000);
  } else if (info.layout === 'v2.6' && !info.delivered && info.final_video) {
    // 10/20 作者 走查：成片已经在项目里（多半在外面剪完放进来的），机器 14 步没走完也不该再让人「开始跑」重剪一遍
    box.innerHTML = `<div class="vp-now ok"><div class="vp-now-h"><span class="chip ok">有成片了</span><b>成片好了，去定标题和封面</b>
        <span class="spacer"></span>${data.busy_elsewhere ? '' : '<button class="btn small ghost" type="button" id="runStart">让机器接着剪</button>'}<button class="btn small primary" type="button" onclick="S.packId = ${topic.id}; go('pack')">去标题和封面 →</button></div>
      <p class="vp-now-say">机器那 14 步不用接着跑了：成片已经在项目里。</p></div>${last}`;
  } else if (info.gate && info.layout === 'v2.6') {
    box.innerHTML = '<div class="vp-now gate" id="gateBox"><span class="spin"></span> 正在读取审批材料…</div>';
  } else if (info.layout !== 'v2.6' && !info.delivered && (route === 'hook' || route === 'full')) {
    // 只剪 Hook（10/19）：标 Hook 在这里；点「切 Hook 片段」后台切 h1–hN；拼成片在剪映里。
    // 10/21 剪 Hook + 加动效也走这里：拼好的粗剪放回项目，再点「做动效」转成 park-video-v2 项目
    const picked = plan.blocks.some((b) => b.key === 'pick' && b.state === 'done');
    const clips = plan.blocks.some((b) => b.key === 'clips' && b.state === 'done');
    let cut = {};
    if (picked) { try { cut = await api(`/api/topics/${topic.id}/video-project/hook-clips`); } catch (err) { /* 读不到就当没切过 */ } }
    const flags = (cut.flags || []).flatMap((f) => f.notes.map((n) => `<p class="vp-now-need">${esc(f.id)} · ${esc(n)}</p>`)).join('');
    const say = !picked ? '在表里标好这条的 Hook，点表里的「保存到项目」。'
      : cut.running ? `在切：${esc(cut.stage || '准备')}。照你标的原话对词级时间、切在停顿上，切完再听一遍首尾字，几十秒。`
      : !clips ? '照你在表里标的 Hook，从粗剪原画面切出 h1、h2…，放进 part-a-hook/individual。正文不动、不加动效。'
      : route === 'full' ? 'h1、h2… 在 part-a-hook/individual 里，拖进剪映拼到开头、导出新的粗剪放进项目文件夹，再点「做动效」。'
      : 'h1、h2… 在 part-a-hook/individual 里，拖进剪映拼好、导出，再把成片放进来。';
    box.innerHTML = `<div class="vp-now ${cut.running ? 'busy' : 'todo'}"><div class="vp-now-h">${cut.running ? '<span class="chip busy"><span class="spin"></span>机器在切</span>' : ''}
        <b>${!picked ? '标 Hook' : !clips || cut.running ? '剪 Hook 片段' : route === 'full' ? '在剪映里拼好，再做动效' : '在剪映里拼成片'}</b>
        ${picked && clips && !cut.running ? '<span class="spacer"></span><button class="btn small ghost" type="button" id="vpHookCut">重新切</button>' : ''}</div>
      <div id="vpNowMedia"></div>
      <p class="vp-now-say">${say}</p>${cut.error ? `<p class="vp-now-need">上次没切成：${esc(cut.error)}</p>` : ''}${cut.running ? '' : flags}
      <div class="acts">${picked && !clips && !cut.running ? '<button class="btn primary" type="button" id="vpHookCut">切 Hook 片段</button>' : ''}
        ${clips && !cut.running ? (route === 'full' ? '<button class="btn primary" type="button" id="vpV2Init">拼好了，做动效</button>' : '<button class="btn primary" type="button" id="vpHookDone">剪映里拼好了，放成片</button>') : ''}</div></div>${last}`;
    if (cut.running) {
      clearTimeout(VP.poll);
      VP.poll = setTimeout(() => { if (S.view === 'work' && VD.tab === 'edit' && VD.topicId === topic.id) { delete VP.cache[topic.id]; delete VP.plan[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); } }, 3000);
    }
  } else if (info.layout !== 'v2.6' && !info.delivered && plan && plan.has_video && !plan.locked) {
    // 视频进来了，还没选这次怎么剪：动作在上面那张卡里
    box.innerHTML = last;
  } else if (info.layout !== 'v2.6' && !info.delivered) {
    const fresh = info.layout === 'fresh';
    box.innerHTML = `<div class="vp-now todo"><div class="vp-now-h">
        <b>${fresh ? '把剪映导出的粗剪放进项目' : featureOn('motion') ? '粗剪放好了：加不加动效？' : '粗剪放好了：这就是成片'}</b></div>
      ${fresh ? `<p class="vp-now-say">把剪映导出的文件夹拖到下面（字幕一起拷进来）；或者看一眼剪映最新导出的那条，时长、时间对得上就点「就是它」。</p><div id="vpNowMedia"></div>`
        : !featureOn('motion') ? `<div id="vpNowMedia"></div><p class="vp-now-say">看一眼下面的粗剪对不对，对就点一下，去定标题和封面。</p>
          <div class="acts"><button class="btn primary" type="button" id="vpNoMotion">这就是成片，去打包</button></div>`
        : `<div id="vpNowMedia"></div><p class="vp-now-say">要加动效就点「做动效」：密度、动效努力、卡片样子这些设置马上出现在这里，在页面上调。不加动效，粗剪就是成片，直接去打包。</p>
          <div class="acts"><button class="btn primary" type="button" id="vpV2Init">做动效</button>
            <button class="btn" type="button" id="vpNoMotion">不加动效，直接去打包</button></div>`}</div>${last}`;
  } else if (info.layout !== 'v2.6') {
    // 没走 14 步的目录、final/ 里已经有成片：多半是点了「不加动效」，粗剪就是成片。以前这里错报「还没按 14 步初始化」。
    box.innerHTML = `<div class="vp-now ok"><div class="vp-now-h"><span class="chip ok">${route === 'hook' ? '只剪 Hook' : '不加动效'}</span><b>${route === 'hook' ? '剪映里拼好的成片在 final/，去打包' : '粗剪就是成片，去打包'}</b>
        <span class="spacer"></span><button class="btn small ghost" type="button" data-back="final">改主意：退回去选</button>
        <button class="btn small primary" type="button" onclick="S.packId = ${topic.id}; go('pack')">去标题和封面 →</button></div></div>${last}`;
  } else if (info.delivered) {
    box.innerHTML = `<div class="vp-now ok"><div class="vp-now-h"><span class="chip ok">交付了</span><b>成片好了，去打包</b>
        <span class="spacer"></span><button class="btn small primary" type="button" onclick="S.packId = ${topic.id}; go('pack')">去标题和封面 →</button></div></div>${last}`;
  } else {
    // 10/21：旧的 14 步（ask-park-video）归档了，机器不再接着跑。没走完的旧项目在剪映里剪完、把成片放进来就行
    box.innerHTML = `<div class="vp-now todo"><div class="vp-now-h"><b>旧流程的项目：在剪映里剪完</b></div>
      <p class="vp-now-say">这条是用旧的 14 步流程建的，那套流程 10/21 归档了（剪 Hook、动效都并进了 park-video-v2），机器不再接着跑。在剪映里剪完，把成片放进来，接着定标题和封面。</p>
      <div class="acts"><button class="btn primary" type="button" id="vpHookDone">剪映里剪完了，放成片</button></div></div>${last}`;
  }

  const upTop = $('#vpNowMedia');
  const fold = $('#vpMedia');
  const v2Start = info.layout !== 'v2.6' && !info.delivered && route !== 'hook';
  if (upTop) { if (fold) fold.innerHTML = '<p class="muted">在最上面那张卡片里。</p>'; renderMedia(topic, upTop, { v2: v2Start }); }
  else if (fold && !(info.gate && info.gate.key === 'H1' && !running)) renderMedia(topic, fold);  // H1 时由审批卡片放上面
  box.insertAdjacentHTML('beforeend', '<div class="vp-act" id="vpAct" hidden></div>');
  renderActivity(topic);
  // 10/19：成片好了才出手机预览；final/ 里放的粗剪不算
  if (info.delivered) { box.insertAdjacentHTML('beforeend', '<div class="vp-phone" id="vpPhone"></div>'); renderPhone(topic); }
  const v2Init = $('#vpV2Init');
  if (v2Init) v2Init.onclick = async () => {
    v2Init.disabled = true;
    try {
      await api(`/api/topics/${topic.id}/video-project/v2/init`, { method: 'POST' });
      (VP.set[topic.id] = { draft: {}, open: true });
      toast('转成动效项目了：在下面「动效设置」里定这条怎么做');
      await refreshVideoTab();
    } catch (err) { toast(err.message); v2Init.disabled = false; }
  };
  const noMotion = $('#vpNoMotion');
  if (noMotion) noMotion.onclick = () => markExternal(topic, info, 'all');
  const start = $('#runStart');
  if (start) start.onclick = async () => {
    if (!confirm('让机器在后台继续跑这个口播项目？它会处理视频文件，停在下一个审批门。')) return;
    try { const r = await api(`/api/topics/${topic.id}/video-project/run`, { method: 'POST' }); toast(r.message); delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); } catch (err) { toast(err.message); }
  };
  const cancel = $('#runCancel');
  if (cancel) cancel.onclick = async () => {
    if (!confirm('中止后台运行？已经生成的产物会保留。')) return;
    try { await api(`/api/topics/${topic.id}/video-project/run`, { method: 'DELETE' }); toast('已中止'); delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); } catch (err) { toast(err.message); }
  };
  const hookCut = $('#vpHookCut');
  if (hookCut) hookCut.onclick = async () => {
    if (hookCut.textContent === '重新切' && !confirm('照表里现在标的 Hook 重新切？part-a-hook/individual 里的 h1、h2… 会换成新切的。')) return;
    hookCut.disabled = true;
    try { toast((await api(`/api/topics/${topic.id}/video-project/hook-clips`, { method: 'POST' })).message); delete VP.cache[topic.id]; delete VP.plan[topic.id]; $('#videoBody').dataset.sig = ''; renderView(); }
    catch (err) { toast(err.message); hookCut.disabled = false; }
  };
  const hookDone = $('#vpHookDone');
  if (hookDone) hookDone.onclick = () => markExternal(topic, info, 'final');
  bindBack(topic, box);
  const gateBox = $('#gateBox');
  if (gateBox) renderGate(topic, info, gateBox);
}

/* 选了「做动效」或「不加动效」后反悔：退回到「加不加动效」。后台只挪不删。 */
function bindBack(topic, root) {
  const b = $('[data-back]', root);
  if (!b) return;
  b.onclick = async () => {
    const ask = b.dataset.back === 'v2'
      ? '退回到「加不加动效」？\n动效设置和已经做出来的东西会收进项目里一个「.v2-撤回」文件夹，不删；粗剪和字幕不动。'
      : '退回到「加不加动效」？\n拷进 final/ 的成片会收进项目里一个「.final-撤回」文件夹，不删；粗剪和字幕不动。';
    if (!confirm(ask)) return;
    b.disabled = true;
    try { toast((await api(`/api/topics/${topic.id}/video-project/back`, { method: 'POST' })).message); delete VP.set[topic.id]; await refreshVideoTab(); }
    catch (err) { toast(err.message); b.disabled = false; }
  };
}

/* 在外面做完的：Hook 给出剪好的视频；整条要 final/ 里有成片（没有就给路径拷进来）。 */
async function markExternal(topic, info, what) {
  let path = '';
  const askPath = what === 'final';  // 只剪 Hook：成片是剪映里另外拼好导出的，要问在哪
  if (askPath) what = 'all';
  if (what === 'all' && !askPath && !info.final_video && info.layout !== 'v2.6') {
    // 没走 14 步的新目录：项目里的剪映粗剪就是成片，不用再问路径。
    if (!confirm('记下「整条在外面做完了」？\n项目里的剪映粗剪就当成片，拷进 final/，这一条去打包。')) return;
  } else if (what === 'hook' || askPath || !info.final_video) {
    let hint = '';
    try { hint = ((await api(`/api/topics/${topic.id}/video-project/latest-export`)).latest || {}).path || ''; } catch (err) { /* 没有就空着 */ }
    const ask = what === 'hook' ? '剪好的 Hook 视频在哪？（完整路径，默认是剪映最新导出的那条）' : '成片在哪？（完整路径，会拷进项目的 final/）';
    const typed = prompt(ask, hint);
    if (typed === null) return;
    path = typed.trim();
    if (!path) { toast('没给路径'); return; }
  } else if (!confirm(`记下「整条在外面做完了」？\n成片用 ${info.final_video}，14 步都记成在外面做完，这一条进待发。`)) return;
  try { toast((await api(`/api/topics/${topic.id}/video-project/external`, { method: 'POST', body: { what, path: path || null } })).message); await refreshVideoTab(); }
  catch (err) { toast(err.message); }
}

/* 手机预览：成片一百多 MB 发不到手机上。压成 540p，放得下就一个文件，放不下再切。
   只在本机出文件（final/手机预览/），不上传。 */
async function renderPhone(topic) {
  const el = $('#vpPhone');
  if (!el) return;
  let st;
  try { st = await api(`/api/topics/${topic.id}/phone-preview`); } catch (err) { el.innerHTML = ''; return; }
  const list = st.parts.map((p) => `<a class="vp-phone-part" href="${p.url}" target="_blank" rel="noopener">${esc(p.name)} <small>${p.mb} MB</small></a>`).join('');
  el.innerHTML = `<div class="vp-phone-h"><b>手机预览</b>
      <small>${st.running ? '正在压…' : st.parts.length ? `${st.parts.length} 个文件，每个不超过 ${st.cap_mb} MB` : `压成 540p，每个文件不超过 ${st.cap_mb} MB，好发到手机上`}</small>
      <span class="spacer"></span>
      ${st.running ? '<span class="spin"></span>' : `<button class="btn small" type="button" id="vpPhoneGo">${st.parts.length ? '重做' : '做手机预览'}</button>`}</div>
    ${st.error ? `<p class="bad">${esc(st.error)}</p>` : ''}${list ? `<div class="vp-phone-list">${list}</div>` : ''}`;
  const go = $('#vpPhoneGo', el);
  if (go) go.onclick = async () => {
    try { toast((await api(`/api/topics/${topic.id}/phone-preview`, { method: 'POST' })).message); renderPhone(topic); } catch (err) { toast(err.message); }
  };
  clearTimeout(VP.phonePoll);
  if (st.running) VP.phonePoll = setTimeout(() => { if (document.body.contains(el)) renderPhone(topic); }, 4000);
}

/* 实时动静：不管是工作台、Codex 还是 Claude 在跑，只看项目目录本身。
   9/22 那条视频前后被问了大约 14 次「怎么样了」——答案应该一直摆在这里。 */
const agoText = (s) => (s < 60 ? '刚刚' : s < 3600 ? `${Math.floor(s / 60)} 分钟前` : `${Math.floor(s / 3600)} 小时 ${Math.floor((s % 3600) / 60)} 分钟前`);
const spanText = (m) => (m < 60 ? `${m} 分钟` : `${Math.floor(m / 60)} 小时 ${m % 60} 分钟`);

async function renderActivity(topic) {
  const el = $('#vpAct');
  if (!el) return;
  let a;
  try { a = await api(`/api/topics/${topic.id}/video-project/activity`); } catch (err) { el.innerHTML = ''; return; }
  // 10/19 作者：没东西在跑时这行只是噪音（「33 分钟没有写入——可能卡住了」）；有进程在跑才出来
  clearTimeout(VP.actPoll);
  VP.actPoll = setTimeout(() => { if (S.view === 'work' && VD.tab === 'edit' && VD.topicId === topic.id) renderActivity(topic); }, 15000);
  el.hidden = !(a.state === 'working' || a.workers.length);
  if (el.hidden) { el.innerHTML = ''; return; }
  const bits = [];
  if (a.step && a.step_minutes !== null) bits.push(`Step ${a.step} 已进行 ${spanText(a.step_minutes)}`);
  if (a.last_write) bits.push(`最后写入 ${agoText(a.last_write.seconds_ago)}`);
  el.innerHTML = `<div class="vp-act-h"><i class="dot ${a.state}"></i><b>${esc(a.say)}</b></div>
    ${bits.length ? `<p>${bits.join(' · ')}</p>` : ''}
    ${a.workers.length ? `<details><summary>${a.workers.length} 个进程</summary><ul>${a.workers.map((w) => `<li><span class="pill mid">${esc(w.kind)}</span> 已跑 ${esc(w.elapsed)} <code>${esc(w.command)}</code></li>`).join('')}</ul></details>` : ''}`;
}

async function renderGate(topic, info, el) {
  let data;
  try { data = await api(`/api/topics/${topic.id}/video-project/gate`); } catch (err) { el.innerHTML = `<span class="bad">${esc(err.message)}</span>`; return; }
  const r = data.review;
  const url = (rel) => fileUrl(info.name, rel);
  let body = '';
  if (r.gate === 'H1') {
    body = (r.hooks.length ? `<ol class="gate-hooks">${r.hooks.map((h) => `<li>${esc(h.text || '')}${h.status && h.status !== 'ok' ? ` <span class="bad">（${esc(h.status)}，需要核对）</span>` : ''}</li>`).join('')}</ol><small class="muted">来自 ${esc(r.from)}</small>`
      : '<p class="muted">还没有 Hook。在下面的表里选句子（可以几段拼一条），点「保存到项目」。</p>')
      + `<div id="vpNowMedia"></div>
      <div class="acts vp-hook-alt"><span class="muted">或者：</span><button class="btn small" type="button" id="gateSkipHook">这条不剪 Hook</button><button class="btn small" type="button" id="gateExtHook">Hook 在外面剪好了</button></div>`;
  } else if (r.gate === 'H2' && info.h2_review) {
    // 审批页原样嵌进来：原画面 / 合成画面并排，样片能播。沙箱不给 same-origin，
    // 页面里的脚本碰不到工作台的接口；批准按钮在沙箱外面。
    const src = `/api/video-projects/${encodeURIComponent(info.name)}/raw/${info.h2_review.split('/').map(encodeURIComponent).join('/')}`;
    body = `<iframe class="vp-h2" src="${src}" sandbox="allow-scripts allow-popups" title="H2 视觉审批页"></iframe>
      <p class="muted vp-wt-note">${esc(info.h2_review)} · <a href="${src}" target="_blank" rel="noopener">新窗口打开 ↗</a></p>`;
  } else if (r.gate === 'H2') {
    body = `<p>视觉覆盖 ${r.coverage === null || r.coverage === undefined ? '—' : pct(r.coverage, 0)} · ${r.shots.length} 个镜头</p>
      <div class="tbl-wrap"><table class="gate-table"><thead><tr><th class="l">镜头</th><th>时间</th><th>类型</th><th class="l">目的</th><th>对你备注的处理</th></tr></thead><tbody>
      ${r.shots.map((s) => `<tr><td class="l">${esc(s.id || '')}</td><td>${s.start === undefined ? '—' : mmss(s.start)}–${s.end === undefined ? '—' : mmss(s.end)}</td><td>${esc(s.visual_type || '')}</td><td class="l">${esc(s.purpose || '')}</td><td>${esc(s.disposition || '—')}</td></tr>`).join('')}</tbody></table></div>`;
  } else if (r.gate === 'H3') {
    body = `<video class="vp-video" controls preload="metadata" src="${url('final/video.mp4')}"></video><p class="muted">QA Final：${esc(JSON.stringify(r.qa || {}).slice(0, 200))}</p>`;
  }
  const canApprove = r.gate !== 'H1' || r.hooks.length;
  el.className = 'vp-now gate';
  el.innerHTML = `<div class="vp-now-h"><span class="chip warn">等你拍板</span><b>${esc(data.gate.key)} · ${esc(data.gate.title)}</b></div>
    <p class="vp-now-say">${esc(data.gate.action || '')}</p>${body}
    ${canApprove ? `<textarea id="gateNote" rows="2" placeholder="备注（可选），比如「第 2 句放到最后」"></textarea>
    <div class="acts"><button class="btn primary" type="button" id="gateApprove">批准 ${esc(data.gate.key)}</button><span class="muted">批准后可以让 Claude 继续跑</span></div>` : ''}`;
  const importWorktable = async (body) => {
    try {
      const res = await api(`/api/topics/${topic.id}/video-project/worktable`, { method: 'POST', body });
      toast(`已导入 ${res.hooks} 个 Hook、${res.visual_notes} 条画面备注${res.needs_review ? `，${res.needs_review} 条需要核对位置` : ''}`);
      delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView();
    } catch (err) { toast(err.message); }
  };
  const wtf = $('#wtFile', el);
  if (wtf) wtf.onchange = async () => { const f = wtf.files && wtf.files[0]; if (f) importWorktable({ text: await f.text(), filename: f.name }); };
  const wtp = $('#wtPaste', el);
  if (wtp) wtp.onclick = () => { const t = prompt('在 worktable 里点「复制 JSON」，粘贴到这里'); if (t && t.trim()) importWorktable({ text: t }); };
  const gm = $('#vpNowMedia', el);
  if (gm) { VP.wt = VP.wt || !r.hooks.length; renderMedia(topic, gm); const fold = $('#vpMedia'); if (fold) fold.innerHTML = '<p class="muted">在最上面那张卡片里。</p>'; }
  const gs = $('#gateSkipHook', el);
  if (gs) gs.onclick = async () => {
    if (!confirm('记下「这条不剪 Hook」？Step 5/7/8/9 会标成跳过，直接进正文和动效。')) return;
    try { toast((await api(`/api/topics/${topic.id}/video-project/skip-hook`, { method: 'POST' })).message); await refreshVideoTab(); } catch (err) { toast(err.message); }
  };
  const ge = $('#gateExtHook', el);
  if (ge) ge.onclick = () => markExternal(topic, info, 'hook');
  const approveBtn = $('#gateApprove');
  if (approveBtn) approveBtn.onclick = async () => {
    if (!confirm(`确认批准 ${data.gate.key}？会写进项目的 project.json 和过程日志。`)) return;
    try {
      await api(`/api/topics/${topic.id}/video-project/approve`, { method: 'POST', body: { gate: data.gate.key, note: $('#gateNote').value || null } });
      toast(`已批准 ${data.gate.key}`);
      delete VP.cache[topic.id]; $('#videoBody').dataset.sig = ''; renderView();
    } catch (err) { toast(err.message); }
  };
}

/* 开头 15 秒：主线有没有在前 15 秒说出来（读项目里已有的字幕） */
async function renderOpening(topic) {
  const el = $('#vpOpening');
  if (!el) return;
  let d;
  try { d = await api(`/api/topics/${topic.id}/opening`); } catch (err) { el.innerHTML = ''; return; }
  if (!d.subtitles && !d.result) { el.innerHTML = '<div class="op op-idle"><b>开头 15 秒</b><span>录完把粗剪和字幕放进项目文件夹，这里会检查主线有没有在前 15 秒说出来。</span></div>'; return; }
  const r = d.result;
  const btn = `<button class="btn small ${r ? '' : 'primary'}" type="button" id="opRun" ${d.state === 'running' ? 'disabled' : ''}>${d.state === 'running' ? '检查中…' : r ? '重新检查' : '检查开头 15 秒'}</button>`;
  if (d.state === 'running') setTimeout(() => { if (S.view === 'work') renderOpening(topic); }, 4000);
  el.innerHTML = `<div class="op ${r ? (r.passed ? 'op-pass' : 'op-fail') : ''}">
    <div class="op-h"><b>开头 15 秒</b>${r ? `<span class="pill ${r.passed ? 'hot' : 'low'}">${r.passed ? `过了 · ${r.stated_at.toFixed(1)} 秒说出主线` : r.stated_at === null ? '没过 · 前 60 秒没说出主线' : `没过 · 第 ${r.stated_at.toFixed(1)} 秒才说出主线`}</span>` : ''}<span class="spacer"></span>${btn}</div>
    ${d.state === 'failed' ? `<p class="bad">${esc(d.error || '检查失败')}</p>` : ''}
    ${r ? `<p class="op-line"><span>主线</span>${esc(r.thesis)}</p>
      <p class="op-line"><span>前 15 秒</span>${esc(r.first_15s)}</p>
      ${r.quote ? `<p class="op-line"><span>主线出现</span>「${esc(r.quote)}」</p>` : ''}
      ${r.before ? `<p class="op-line"><span>之前在讲</span>${esc(r.before)}</p>` : ''}
      <ol class="op-fixes">${r.fixes.map((f) => `<li>${esc(f)}</li>`).join('')}</ol>
      <small class="muted">依据：${esc(r.source_label)}字幕 ${esc(r.source)} · ${day(r.generated_at)}</small>` : `<p class="muted">会读${esc(d.subtitles.label)}字幕（${esc(d.subtitles.path)}）的前 60 秒。</p>`}
  </div>`;
  $('#opRun').onclick = async () => {
    try { const res = await api(`/api/topics/${topic.id}/opening`, { method: 'POST' }); toast(res.message); renderOpening(topic); } catch (err) { toast(err.message); }
  };
}
