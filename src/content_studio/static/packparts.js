'use strict';
/* 「标题和封面」页（pack.js）用的几块：插图、证据图、公众号排版、小红书图文，还有「包缺什么」。
   10/6 作者：发的事搬进了各平台页，原来的 04 发布台（每个平台一张上传页的弹窗）整页删了，只留这几块。 */
const PD = { data: null, at: 0 };
window.invalidatePublish = () => { PD.data = null; PD.at = 0; };

function packMissing(d) {
  // 9/29 起按「定稿」算：做出来了但 作者 还没定稿的，也算没打包好
  if (d.approvals) {
    return [['copy', '标题和描述'], ['cover', '封面']].filter(([k]) => !(d.approvals[k] && d.approvals[k].approved && d.approvals[k].valid)).map(([, l]) => l);
  }
  const c = (d.release && d.release.covers) || {};
  const miss = [];
  if (!(c.landscape || c.portrait)) miss.push('封面');
  if (!d.has_copy) miss.push('标题和描述');
  return miss;
}

async function renderFigs(dlg, topicId) {
  const box = $('#pdlFigs', dlg);
  if (!box) return;
  let st;
  try { st = await api(`/api/topics/${topicId}/illustrate`); } catch (err) { box.innerHTML = `<p class="pdl-note bad">${esc(err.message)}</p>`; return; }
  if (window.prepTick) window.prepTick('figs', st);
  const thumbs = st.images.length ? `<div class="pdl-fig-grid">${st.images.map((i) => `<a href="${i.url}" target="_blank" rel="noopener" title="${esc(i.caption)}"><img src="${i.url}" alt="${esc(i.caption)}" loading="lazy"></a>`).join('')}</div>` : '';
  if (st.running) {
    box.innerHTML = `<p class="pdl-note"><span class="spin"></span> 正在配图（小黑手绘，一张一张画），一般 5–10 分钟。</p>${thumbs}`;
    setTimeout(() => { if (document.body.contains(box)) renderFigs(dlg, topicId); }, 8000);
    return;
  }
  box.innerHTML = `${st.error ? `<p class="pdl-note bad">配图失败：${esc(st.error)}</p>` : ''}
    <p class="pdl-note">${st.images.length ? `配图 ${st.images.length} 张，已经插在文章里` : '还没配图'}
    <button class="linklike" type="button" data-fig-go>${st.images.length ? '重新配图' : '配图（5–10 分钟）'}</button></p>${thumbs}`;
  box.querySelector('[data-fig-go]').onclick = async (e) => {
    if (st.images.length && !confirm('重新配图会换掉现在这几张，排好的公众号版式和小红书图也要重出。继续？')) return;
    e.target.disabled = true;
    try { await api(`/api/topics/${topicId}/illustrate`, { method: 'POST' }); } catch (err) { toast(err.message); }
    renderFigs(dlg, topicId);
  };
}

/* 证据图（10/2 作者）：要不要找由他点；找完一张张挑「要 / 不要」，放进文章或者整篇不要。
   没挑之前补发工作台里这篇的 X、公众号不让发——10/2 那篇找了 5 张没人看，发出去一张没有。 */
const EV_KIND = { frame: '视频里的截图', tweet: '原推', news: '新闻', data: '数据', post: '公开帖子', mine: '你的截图' };
async function renderEvidence(dlg, topicId) {
  const box = $('#pdlEvid', dlg);
  if (!box) return;
  let st;
  try { st = await api(`/api/topics/${topicId}/evidence`); } catch (err) { box.innerHTML = `<p class="pdl-note bad">${esc(err.message)}</p>`; return; }
  const head = `<h4 class="ev-h">证据图 <span>真东西：骨架页你要过的${st.picked ? ` ${st.picked} 张` : ''}证据、你视频里的笔记截图、名人说过的原推</span></h4>`;
  const again = (ms) => setTimeout(() => { if (document.body.contains(box)) renderEvidence(dlg, topicId); }, ms);
  const post = async (path, body, btn) => {
    if (btn) btn.disabled = true;
    try {
      await api(`/api/topics/${topicId}/evidence${path}`, { method: 'POST', body: body || {} });
      if (window.rerenderPackRow) window.rerenderPackRow('wx');
    } catch (err) { toast(err.message); }
    renderEvidence(dlg, topicId);
  };
  if (st.running) {
    box.innerHTML = `${head}<p class="pdl-note"><span class="spin"></span> 正在找：看视频画面、核对推文原话，一般 2–4 分钟。可以先做别的。</p>`;
    again(8000);
    return;
  }
  const err = st.error ? `<p class="pdl-note bad">上次没找成：${esc(st.error)}</p>` : '';
  if (st.state === 'none' || st.state === 'empty') {
    const why = st.skip ? `<p class="pdl-note">${esc(st.skip)}，找不了。</p>` : '';
    box.innerHTML = `${head}${err}${st.state === 'empty' ? `<p class="pdl-note">找过一遍，没有能用的${st.rejected ? `（${st.rejected} 张没过检查：糊、有隐私、原话对不上）` : ''}。</p>` : ''}${why}
      ${st.skip ? '' : `<p class="pdl-note">这篇要不要配证据图？<button class="btn small" type="button" data-ev-go>${st.state === 'empty' ? '再找一遍' : '找证据图'}</button> 只出提案，你挑完才放进文章。</p>`}`;
    const go = $('[data-ev-go]', box);
    if (go) go.onclick = () => post('', null, go);
    return;
  }
  const card = (i, on) => `<label class="ev-card${on ? ' on' : ''}">
      <input type="checkbox" data-ev-file="${esc(i.file)}" ${on ? 'checked' : ''}${st.state === 'pending' ? '' : ' disabled'}>
      <a href="${i.src}" target="_blank" rel="noopener"><img src="${i.src}" alt="${esc(i.caption)}" loading="lazy"></a>
      <span class="ev-kind">${EV_KIND[i.kind] || ''}${i.from === 'skeleton' ? ' · 骨架页要过的' : ''}${i.url ? ` · <a href="${esc(i.url)}" target="_blank" rel="noopener">${i.kind === 'tweet' ? '原推' : '原文'}</a>` : ''}</span>
      <b>${esc(i.caption)}</b>
      <span class="ev-where">放在「${esc(String(i.after || '').slice(0, 22))}…」后面${i.replaces ? `，顶掉 AI 图 ${esc(i.replaces)}` : ''}</span>
    </label>`;
  if (st.state === 'pending') {
    box.innerHTML = `${head}${err}<p class="pdl-note">找到 ${st.items.length} 张${st.rejected ? `（另有 ${st.rejected} 张没过检查，已扔掉）` : ''}。不要的取消勾选，再点「放进文章」。<b>挑完之前，补发工作台里这篇的 X、公众号先不发。</b></p>
      <div class="ev-grid">${st.items.map((i) => card(i, true)).join('')}</div>
      <p class="ev-act"><button class="btn primary small" type="button" data-ev-apply>放进文章</button> <button class="btn small" type="button" data-ev-skip>这篇都不要</button></p>`;
    const picked = () => [...box.querySelectorAll('[data-ev-file]:checked')].map((x) => x.dataset.evFile);
    const btn = $('[data-ev-apply]', box);
    const paint = () => { const n = picked().length; btn.textContent = n ? `放进文章（${n} 张）` : '一张都没勾'; btn.disabled = !n; box.querySelectorAll('.ev-card').forEach((c) => c.classList.toggle('on', c.querySelector('input').checked)); };
    box.querySelectorAll('[data-ev-file]').forEach((x) => { x.onchange = paint; });
    paint();
    btn.onclick = () => post('/apply', { files: picked() }, btn);
    $('[data-ev-skip]', box).onclick = (e) => post('/apply', { files: [] }, e.target);
    return;
  }
  const used = new Set(st.used || []);
  const shown = st.items.filter((i) => used.has(i.file));
  box.innerHTML = st.state === 'applied'
    ? `${head}<p class="pdl-note">放进文章 ${used.size} 张。公众号排版要重排一次（下面「公众号排版」那一步）。${st.can_undo ? ' <button class="linklike" type="button" data-ev-undo>撤回，重新挑</button>' : ''}</p>
       ${shown.length ? `<div class="ev-grid">${shown.map((i) => card(i, true)).join('')}</div>` : ''}`
    : `${head}<p class="pdl-note">这篇说了不要证据图。<button class="linklike" type="button" data-ev-undo>改主意，重新挑</button></p>`;
  const undo = $('[data-ev-undo]', box);
  if (undo) undo.onclick = () => post('/undo', null, undo);
}

/* 公众号：先排版（gzh，5–10 分钟）→ 看公众号里的样子 → 存进草稿箱。状态就地显示，不靠 toast（弹窗会挡住它）。 */
function openWxPreview(topicId) {
  const box = document.createElement('dialog');
  box.className = 'wx-prev';
  box.innerHTML = `<div class="wx-prev-h"><b>公众号里的样子</b><button class="btn small" type="button">关掉</button></div><iframe src="/api/topics/${topicId}/wechat-preview.html?t=${Date.now()}" title="公众号预览"></iframe>`;
  document.body.appendChild(box);
  box.querySelector('button').onclick = () => box.close();
  box.onclose = () => box.remove();
  box.showModal();
}

async function renderWx(dlg, topicId) {
  const box = $('#pdlWx', dlg);
  if (!box) return;
  let st;
  try { st = await api(`/api/topics/${topicId}/layout`); } catch (err) { box.innerHTML = `<p class="bad">${esc(err.message)}</p>`; return; }
  if (window.prepTick) window.prepTick('wx', st);
  const fresh = st.has_layout && !st.stale;
  const preview = `<button class="btn ${fresh ? 'primary' : ''}" type="button" data-wx-preview>看公众号里的样子</button>`;
  if (st.running) {
    box.innerHTML = `<p class="pdl-note"><span class="spin"></span> 正在用 gzh 排版（橄榄手记），一般 5–10 分钟，排好这里会变。可以先关掉弹窗做别的。</p>`;
    const save = $('[data-pj-prepare="draft"]', dlg);
    if (save) { save.disabled = true; save.textContent = '排版中，排好再存'; }
    setTimeout(() => { if (document.body.contains(box)) renderWx(dlg, topicId); }, 5000);
    return;
  }
  box.innerHTML = fresh
    ? `<p class="pdl-note">✓ 已用 gzh 排好版（${esc(st.theme || '橄榄手记')}）。先看一眼，没问题再存草稿箱。</p><div class="pdl-acts">${preview}<button class="btn ghost" type="button" data-wx-layout>重新排版</button></div>`
    : `${st.error ? `<p class="pdl-note bad">上次排版失败：${esc(st.error)}</p>` : ''}
       <p class="pdl-note">${st.stale ? '文章改过了，之前的排版作废了。' : '还没排版。'}先用 gzh 排一下（5–10 分钟），排好能预览；不排也能发，用的是基础排版。</p>
       <div class="pdl-acts"><button class="btn primary" type="button" data-wx-layout>用 gzh 排版</button>${preview.replace('看公众号里的样子', '看基础排版的样子')}</div>`;
  // 存草稿按钮跟着排版走：排版中先别存（存进去就是基础排版）；没排就写明是基础排版
  const save = $('[data-pj-prepare="draft"]', dlg);
  if (save) {
    save.disabled = false;
    save.textContent = fresh ? '存进公众号草稿箱（gzh 排版）' : '存进公众号草稿箱（基础排版）';
  }
  box.querySelector('[data-wx-preview]').onclick = () => openWxPreview(topicId);
  box.querySelector('[data-wx-layout]').onclick = async (e) => {
    e.target.disabled = true;
    try { await api(`/api/topics/${topicId}/layout`, { method: 'POST' }); } catch (err) { box.insertAdjacentHTML('afterbegin', `<p class="pdl-note bad">${esc(err.message)}</p>`); }
    renderWx(dlg, topicId);
  };
}

/* 小红书图文：文章原文排成 3:4 图。01 是封面；打包下载的文件名就是顺序。 */
async function renderXhs(dlg, topicId) {
  const box = $('#pdlXhs', dlg);
  if (!box) return;
  let st;
  try { st = await api(`/api/topics/${topicId}/xhs`); } catch (err) { box.innerHTML = `<p class="bad">${esc(err.message)}</p>`; return; }
  if (window.prepTick) window.prepTick('xhs', st);
  const has = st.images.length && !st.stale;
  const note = st.running ? '<span class="spin"></span> 正在出图，十几秒'
    : st.error ? `<span class="bad">${esc(st.error)}</span>`
      : st.stale ? '<span class="bad">文章改过了，这组图是旧的：重新出一次</span>'
        : has ? `${st.images.length} 张 · ${st.chars} 字一字不改${st.font_scale && st.font_scale < 1 ? ` · 字号缩到 ${Math.round(st.font_scale * 100)}% 才放进 ${st.max} 张` : ''}${st.over_limit ? ` · <b class="bad">超过小红书 ${st.max} 张上限，得拆成上下两篇</b>` : ''}`
          : '还没出图';
  box.innerHTML = `<div class="xhs-h"><button class="btn ${has ? '' : 'primary'}" type="button" id="xhsGo" ${st.running ? 'disabled' : ''}>${has || st.stale ? '重新出图文' : '出图文'}</button>
      ${has ? `<a class="btn" href="/api/topics/${topicId}/xhs.zip" download>打包下载</a>` : ''}<small>${note}</small></div>
    ${st.images.length ? `<div class="xhs-grid ${st.stale ? 'dim' : ''}">${st.urls.map((u, i) => `<a href="${u}" target="_blank" rel="noopener" title="第 ${i + 1} 张"><img src="${u}?t=${encodeURIComponent(st.generated_at || '')}" alt="第 ${i + 1} 张" loading="lazy"><small>${i + 1}</small></a>`).join('')}</div>` : ''}`;
  $('#xhsGo', box).onclick = async () => {
    try { toast((await api(`/api/topics/${topicId}/xhs`, { method: 'POST' })).message); renderXhs(dlg, topicId); } catch (err) { toast(err.message); }
  };
  if (st.running) setTimeout(() => { if (document.body.contains(box)) renderXhs(dlg, topicId); }, 2500);
}
