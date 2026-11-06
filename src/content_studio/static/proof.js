'use strict';
/* 骨架页「证据」（10/5 作者）：拍之前按论点找真东西——新闻、数据、原推，逐条核对过原话才给；
   只有他能拿的（后台、录屏、聊天）写成待办，他截好传上来。点「要」的才进视频动效和文章，AI 画的图不再当证据。
   10/9 证据单：每个论点先定用什么证明（你的截图 / 外面的证据 / 插图 / 不要证据），他点一下就能改；
   定了「你的截图」还没传的，X、公众号发之前要补（卡发不卡拍）。进了「正在做」会自己开始出。 */

async function renderProof(topic, box) {
  if (!box) return;
  let st;
  try { st = await api(`/api/topics/${topic.id}/proof`); } catch (err) { box.innerHTML = `<section class="proof"><p class="proof-note bad">${esc(err.message)}</p></section>`; return; }
  const still = () => document.body.contains(box) && S.view === 'work' && VD.tab === 'outline' && VD.topicId === topic.id;
  const redraw = (next) => { st = next; paint(); };
  const post = async (path, body, btn) => {
    if (btn) btn.disabled = true;
    try { redraw(await api(`/api/topics/${topic.id}/proof${path}`, { method: 'POST', body: body || {} })); } catch (err) { toast(err.message); if (btn) btn.disabled = false; }
  };
  const upload = async (key, file) => {
    const body = new FormData();
    body.append('file', file);
    body.append('key', key);
    try {
      const res = await fetch(`/api/topics/${topic.id}/proof/mine`, { method: 'POST', body, headers: { 'X-Content-Studio': '1' } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || `上传失败（${res.status}）`);
      toast('收到了，放进这个论点的证据');
      redraw(data);
    } catch (err) { toast(err.message); }
  };
  const card = (i) => `<div class="ev-card${i.pick ? ' on' : ''}">
      <label class="proof-pick"><input type="checkbox" data-pf-file="${esc(i.file)}" ${i.pick ? 'checked' : ''}${st.running ? ' disabled' : ''}> 要</label>
      <a href="${i.src}" target="_blank" rel="noopener"><img src="${i.src}" alt="${esc(i.caption)}" loading="lazy"></a>
      <span class="ev-kind">${esc(i.kind_label)} · ${esc(i.source || '')}${i.date ? ` · ${esc(i.date)}` : ''}${i.url ? ` · <a href="${esc(i.url)}" target="_blank" rel="noopener">原文</a>` : ''}</span>
      <b>${esc(i.caption)}</b>
      ${i.claim && i.kind !== 'mine' ? `<span class="ev-where">证明：${esc(i.claim)}</span>` : ''}
      ${i.kind === 'mine' && !st.running ? `<button class="linklike" type="button" data-pf-del="${esc(i.file)}">删掉这张</button>` : ''}
    </div>`;
  const up = (key, label, cls) => (st.running ? '' : `<label class="${cls}">${label}<input type="file" accept="image/*" data-pf-up="${esc(key)}" hidden></label>`);
  // 待办只写一次：「你来截」就是骨架里那句「要补：……」去掉前缀；两句一样时不再把骨架原句重复一遍
  const todoOf = (p) => (p.mine || p.line || '').replace(/^\s*(要补|待补|需要补)\s*[—\-：:]*\s*/, '').trim();
  const uses = (p) => (p.gone ? '' : `<div class="proof-use"><div class="seg-toggle">${Object.entries(st.uses).map(([k, v]) =>
      `<button type="button" class="${p.use === k ? 'on' : ''}" data-pf-use="${esc(k)}" data-pf-key="${esc(p.key)}"${st.running ? ' disabled' : ''}>${esc(v)}</button>`).join('')}</div>
      ${p.why && !p.use_by ? `<small>${esc(p.why)}</small>` : ''}</div>`);
  const point = (p) => {
    const todo = st.sheet ? (p.use === 'mine' ? todoOf(p) || '截一张能证明这一条的图' : '') : (p.mine || (p.missing && !st.searched) ? todoOf(p) : '');
    const same = todo && p.line && p.line.includes(todo);
    const tag = p.use === 'mine' ? (p.short ? '你来截 · 发之前要补' : '你来截 · 已经传了') : '你来截';
    return `<div class="proof-pt${p.gone ? ' gone' : ''}">
      <h5><span class="proof-k">论点 ${esc(p.key)}</span><span>${esc(p.title)}${p.gone ? ' <small>（骨架里已经没有这个论点了）</small>' : ''}</span></h5>
      ${uses(p)}
      ${p.line && !same ? `<p class="proof-line">骨架里写的：${esc(p.line)}</p>` : ''}
      ${p.items.length ? `<div class="ev-grid">${p.items.map(card).join('')}</div>` : (st.searched && !p.gone ? '<p class="proof-line">外面没找到能核对的。</p>' : '')}
      ${todo ? `<div class="proof-todo"><span><b>${tag}</b>${esc(todo)}</span>${up(p.key, '传你截的图', 'btn small')}</div>`
        : (p.gone || st.running ? '' : `<p class="proof-more">${up(p.key, '也有你自己的截图？传上来', 'linklike')}</p>`)}
    </div>`;
  };
  function paint() {
    if (!document.body.contains(box)) return;
    const head = `<div class="proof-head"><div><h4>证据</h4><small>每个论点先定用什么证明：你的截图、外面的证据，都没有才画插图。点「要」的才进视频和文章</small></div>
      ${st.running ? '' : `<button class="btn small${st.searched ? '' : ' primary'}" type="button" data-pf-go>${st.searched ? '再找一遍' : '按论点出证据单'}</button>`}</div>`;
    const short = st.points.filter((p) => p.short && !p.gone).length;
    const notes = [
      st.running ? '<p class="proof-note"><span class="spin"></span> 正在找：搜新闻和数据、打开原网页逐字核对、截图，一般 3–8 分钟。可以先做别的；找完再挑、再传你的截图。</p>' : '',
      st.error ? `<p class="proof-note bad">上次没找成：${esc(st.error)}</p>` : '',
      st.stale && !st.running ? '<p class="proof-note">骨架的论点改过了，下面是按旧论点找的。要对上新论点，点「再找一遍」（点过「要」的和你传的都留着）。</p>' : '',
      st.own ? '<p class="proof-note">这篇讲的是你自己的东西：能用你截图证明的论点，都用你的截图。</p>' : '',
      short ? `<p class="proof-note bad">还差 ${short} 张你的截图。可以先拍；X 和公众号发之前要补上，或者把那条改成别的。</p>` : '',
      st.searched && !st.running ? `<p class="proof-note">${st.chosen ? `已经要了 ${st.chosen} 张。` : '一张都还没要。'}${st.rejected ? ` 另有 ${st.rejected} 条没过核对（打不开、要付费、原话对不上、来源重复），已扔掉。` : ''}</p>` : '',
      !st.searched && !st.running ? '<p class="proof-note">这条进了「正在做」会自己开始，也可以现在点：每个论点定用什么证明，外面的原话逐字核对过才给你；只有你能拿的（工作台、后台、录屏）写成待办，你截好传上来。</p>' : '',
    ].join('');
    box.innerHTML = `<section class="proof">${head}${notes}${st.points.map(point).join('')}</section>`;
    const go = $('[data-pf-go]', box);
    if (go) go.onclick = async () => {
      go.disabled = true;
      try { toast((await api(`/api/topics/${topic.id}/proof`, { method: 'POST' })).message); } catch (err) { toast(err.message); }
      renderProof(topic, box);
    };
    $$('[data-pf-use]', box).forEach((b) => (b.onclick = () => post('/use', { key: b.dataset.pfKey, use: b.dataset.pfUse }, b)));
    $$('[data-pf-file]', box).forEach((x) => (x.onchange = () => post('/pick', { file: x.dataset.pfFile, pick: x.checked })));
    $$('[data-pf-del]', box).forEach((b) => (b.onclick = () => { if (confirm('删掉你传的这张？')) post('/remove', { file: b.dataset.pfDel }, b); }));
    $$('[data-pf-up]', box).forEach((x) => (x.onchange = () => { if (x.files[0]) upload(x.dataset.pfUp, x.files[0]); }));
    if (st.running) setTimeout(() => { if (still()) renderProof(topic, box); }, 8000);
  }
  paint();
}
