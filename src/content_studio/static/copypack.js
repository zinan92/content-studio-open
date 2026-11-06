'use strict';
/* 03 打包 · 文字信息：一个标题 + 简介（短）+ 文案描述（长）+ 话题。
   9/29 作者：简介和描述是两样。描述给抖音、视频号、小红书（刷到时看的那一段），简介给 B 站、YouTube、小宇宙
   （点进去才看的说明）。存的时候按平台 key 分开写，一键发布读的就是各自那一份。 */

const CP = { data: {}, dirty: false };
// 哪些平台读「文案描述」，哪些读「简介」。标题和话题所有平台共用。
const DESC_KEYS = ['douyin', 'channels', 'xiaohongshu'];
const INTRO_KEYS = ['bilibili', 'youtube', 'xiaoyuzhou'];
const LEN_KEYS = ['douyin', 'channels', 'xiaohongshu', 'bilibili', 'youtube'];
// 9/29 作者：每个平台有自己的流量话题（抖音的「青年创作者成长计划」这类），每条都带、排在前面。
// 存在设置里（traffic_tags），填一次以后每条都用；内容话题每条自己写。
const TRAFFIC_KEYS = LEN_KEYS;
const trafficTags = () => ((S.state && S.state.settings && S.state.settings.traffic_tags) || {});

/** 这个平台最后发出去的话题：流量话题在前，内容话题在后，去重，按平台上限截。 */
function platformTags(key, content, traffic, specs) {
  const all = [...new Set([...(traffic[key] || []), ...content])];
  const cap = specs && specs[key] ? specs[key].tags : all.length;
  return { tags: all.slice(0, cap), dropped: all.slice(cap), cap };
}
window.platformTags = platformTags;

async function loadCopy(topicId, force) {
  if (!force && CP.data[topicId] && Date.now() - CP.data[topicId]._at < 30000) return CP.data[topicId];
  CP.data[topicId] = { ...(await api(`/api/topics/${topicId}/copy`)), _at: Date.now() };
  return CP.data[topicId];
}

const filled = (e) => e && (e.title || e.body);

/** 读出四样：标题、话题取第一个写过的平台；描述、简介各取自己那组里第一个写过的，没有就用共用的那段。
 *  存下的话题里混着流量话题，读回来时拿掉，只剩这条自己的内容话题。 */
function copyFields(copy, traffic = {}) {
  const platforms = (copy && copy.platforms) || {};
  const first = (keys) => keys.map((k) => platforms[k]).find(filled);
  const shared = first([...DESC_KEYS, ...INTRO_KEYS, ...Object.keys(platforms)]) || { title: '', body: '', tags: [] };
  const desc = first(DESC_KEYS);
  const intro = first(INTRO_KEYS);
  return {
    title: shared.title || '',
    desc: (desc || shared).body || '',
    intro: (intro || shared).body || '',
    tags: (shared.tags || []).filter((t) => !Object.values(traffic).some((list) => (list || []).includes(t))),
  };
}
window.copyFields = copyFields;

// 按平台的算法数字数：小红书两个英文字母算一个字
const titleUnits = (text, spec) => (spec && spec.count === 'half_ascii' ? [...text].reduce((n, ch) => n + (ch.charCodeAt(0) < 128 ? 0.5 : 1), 0) : text.length);

function lengthChips(title, specs) {
  const keys = LEN_KEYS.filter((k) => specs[k]);
  const chips = keys.map((k) => {
    const cap = specs[k].title;
    const n = titleUnits(title, specs[k]);
    return `<span class="len-chip ${n > cap ? 'bad' : ''}" title="${esc(specs[k].label)}标题最多 ${cap} 字">${esc(specs[k].label)} ${n}/${cap}</span>`;
  }).join('');
  // 10/20 走查：「超了自动裁」裁成什么样没人看得到。超了的平台直接写出发出去那一行（和 publish_desk.fill_for 同一个裁法）
  const cut = keys.filter((k) => specs[k].title && titleUnits(title, specs[k]) > specs[k].title).map((k) => specs[k].no_trim
    ? `<span class="len-cut">${esc(specs[k].label)}超了，不替你截，发之前自己删几个字</span>`
    : `<span class="len-cut">${esc(specs[k].label)}发出去是：「${esc(title.slice(0, specs[k].title))}」</span>`).join('');
  return chips + cut;
}

function thesisFromOutline(markdown) {
  const m = /^##\s*主线\s*\n([\s\S]+?)(?=^##\s|$(?![\s\S]))/m.exec(markdown || '');
  return m ? m[1].replace(/\s+/g, ' ').trim() : '';
}

/* 手机上大概长这样：抖音刷到时，标题 + 描述 + 话题叠在画面下面。 */
function dyPreview(title, desc, tags, cover) {
  const text = [title, desc].filter(Boolean).join('\n');
  const tagLine = tags.map((t) => `<span class="dy-tag">#${esc(t)}</span>`).join(' ');
  return `<div class="dy-phone"><div class="dy-screen">
      <div class="dy-cover">${cover ? `<img src="${esc(cover)}" alt="竖版封面">` : '封面'}</div>
      <div class="dy-cap">${text ? esc(text).replace(/\n/g, '<br>') : '<span class="dy-ph">描述会显示在这里</span>'}${tagLine ? `<div class="dy-tags">${tagLine}</div>` : ''}</div>
    </div><small>刷到时大概长这样</small></div>`;
}

const tagsOf = (raw) => raw.split(/[，,\s]+/).map((t) => t.replace(/^#/, '').trim()).filter(Boolean);

/** 打包页里的文字信息表单。release 是成片交付包（有 Codex 写好的「发布文案」就能一键填）。 */
async function renderCopyForm(topic, el, { release, onSaved } = {}) {
  let d;
  try { d = await loadCopy(topic.id, false); } catch (err) { el.innerHTML = `<div class="bad">${esc(err.message)}</div>`; return; }
  const specs = d.platforms_spec;
  const traffic = { ...trafficTags() };
  const f = copyFields(d.copy, traffic);
  const cover = release && release.cover_urls && (release.cover_urls.portrait || release.cover_urls.landscape);
  // 设置里关掉的平台（9/29 研习室、小宇宙）不列出来
  const enabled = (k) => { const m = (S.platforms || []).find((x) => x.key === k); return !m || m.on !== false; };
  const label = (keys) => keys.filter((k) => specs[k] && enabled(k)).map((k) => specs[k].label).join(' / ');
  el.innerHTML = `<div class="cf">
    <div class="cf-form">
      <div class="cf-tools">
        <button class="btn small" type="button" id="cbTitles">出标题</button>
        ${topic.outline_path ? '<button class="btn small ghost" type="button" id="cbFill">用提纲填</button>' : ''}
        ${release && release.copy ? `<button class="btn small ghost" type="button" id="cbRelease" title="${esc(release.copy.title || '')}">用成片包里的发布文案填</button>` : ''}
      </div>
      <label class="dy-field"><span>标题<i class="dy-hint">所有平台共用，超了的平台发的时候自动裁</i></span><input id="cbTitle" value="${esc(f.title)}" placeholder="${esc(topic.title)}" autocomplete="off" maxlength="100"></label>
      <div class="len-row" id="cbLens"></div>
      <div class="tc" id="cbTitleList" hidden></div>
      <label class="dy-field"><span>文案描述<i class="dy-hint">${esc(label(DESC_KEYS))} · <b id="cbDescN">0</b>/1000</i></span><textarea id="cbDesc" rows="5" placeholder="刷到时看的那一段。第一句就要留住人。">${esc(f.desc)}</textarea></label>
      <label class="dy-field"><span>简介<i class="dy-hint">${esc(label(INTRO_KEYS))} · 点进去才看的说明 · <b id="cbIntroN">0</b> 字</i></span><textarea id="cbIntro" rows="3" placeholder="这期讲了什么、适合谁看。可以和描述一样。">${esc(f.intro)}</textarea>
        <button class="linklike cf-same" type="button" id="cbSame">和描述一样</button></label>
      <label class="dy-field"><span>内容话题<i class="dy-hint">这条讲什么 · 逗号分隔 · 所有平台都带</i></span><input id="cbTags" value="${esc(f.tags.join('，'))}" placeholder="自媒体，变现，AI" autocomplete="off"></label>
      <div class="tt"><div class="tt-h">各平台常用话题<small>每条都自动带上，排在内容话题前面 · <button type="button" class="linklike" onclick="goTagSettings()">去设置改</button></small></div>
        ${TRAFFIC_KEYS.filter((k) => specs[k]).map((k) => `<div class="tt-row"><b>${esc(specs[k].label)}</b>
          <span class="tt-tags">${(traffic[k] || []).length ? esc(traffic[k].map((t) => '#' + t).join(' ')) : '还没填'}</span>
          <span class="tt-out" id="tt-${k}"></span></div>`).join('')}
      </div>
      <div class="dy-foot">
        <button class="btn primary" type="button" id="cbSave">保存并定稿</button>
        <button class="btn ghost" type="button" id="cbCopy">复制抖音用的标题 + 描述 + 话题</button>
        <span class="cf-saved" id="cbSaved"></span>
      </div>
    </div>
    <div class="dy-side" id="cbPreview"></div>
  </div>`;
  const title = $('#cbTitle', el);
  const read = () => ({ title: title.value.trim(), desc: $('#cbDesc', el).value.trim(), intro: $('#cbIntro', el).value.trim(), tags: tagsOf($('#cbTags', el).value) });
  // 常用话题 10/8 起只在设置里改，这里照设置算「发的时候带几个」
  const readTraffic = () => traffic;
  const repaint = () => {
    const v = read();
    $('#cbLens', el).innerHTML = lengthChips(v.title, specs);
    $('#cbDescN', el).textContent = v.desc.length;
    $('#cbIntroN', el).textContent = v.intro.length;
    const tr = readTraffic();
    TRAFFIC_KEYS.filter((k) => specs[k]).forEach((k) => {
      const r = platformTags(k, v.tags, tr, specs);
      $(`#tt-${k}`, el).innerHTML = `发的时候 ${r.tags.length}/${r.cap}${r.dropped.length ? ` · <b class="bad">超了，${esc(r.dropped.map((t) => '#' + t).join(' '))} 不带</b>` : ''}`;
    });
    $('#cbPreview', el).innerHTML = dyPreview(v.title, v.desc, platformTags('douyin', v.tags, tr, specs).tags, cover);
  };
  const touched = () => { CP.dirty = true; $('#cbSaved', el).textContent = '有改动，还没保存'; repaint(); };
  $$('input, textarea', el).forEach((input) => (input.oninput = touched));
  repaint();
  $('#cbSame', el).onclick = () => { $('#cbIntro', el).value = $('#cbDesc', el).value; touched(); };

  const fill = $('#cbFill', el);
  if (fill) fill.onclick = async () => {
    try {
      const o = await api(`/api/topics/${topic.id}/outline`);
      const heading = /^#\s+(.+)$/m.exec(o.markdown || '');
      title.value = heading ? heading[1].trim() : topic.title;
      const thesis = thesisFromOutline(o.markdown);
      if (thesis) { $('#cbDesc', el).value = thesis; if (!$('#cbIntro', el).value.trim()) $('#cbIntro', el).value = thesis; }
      touched();
    } catch (err) { toast(err.message); }
  };
  const rel = $('#cbRelease', el);
  if (rel) rel.onclick = () => {
    const c = release.copy;
    if ((title.value || $('#cbDesc', el).value) && !confirm(`用成片包里的发布文案覆盖现在填的？\n\n标题：${c.title}`)) return;
    title.value = c.title || '';
    $('#cbDesc', el).value = c.body || '';
    $('#cbIntro', el).value = c.body || '';
    $('#cbTags', el).value = (c.tags || []).join('，');
    touched();
  };

  /* 标题候选：按 Anna 的「标题」工作流出，点一条填进标题框。不替 作者 选。 */
  const list = $('#cbTitleList', el);
  const showTitles = (t) => {
    list.hidden = false;
    if (t.running) { list.innerHTML = '<p class="tc-note">正在按「标题」工作流出候选，半分钟到一分钟…</p>'; return; }
    if (t.error) { list.innerHTML = `<p class="tc-note bad">${esc(t.error)}</p>`; return; }
    const r = t.result;
    if (!r) { list.hidden = true; return; }
    list.innerHTML = `<p class="tc-note">点一条填进标题${r.had_transcript ? '' : ' · 没找到转写，只看了选题和骨架'}${r.people.length ? ` · 视频里点名了 ${esc(r.people.join('、'))}` : ''}</p>
      ${r.candidates.map((c, i) => `<button type="button" class="tc-row" data-tc="${i}"><b>${esc(c.title)}${c.over ? ` <i class="tc-over" title="抖音标题最多 30 字，发之前删几个字">${c.title.length} 字</i>` : ''}</b><span class="tc-pat ${c.pattern.includes('借力') ? 'borrow' : ''}">${esc(c.pattern)}</span><small>${esc(c.basis)}</small></button>`).join('')}`;
    $$('[data-tc]', list).forEach((b) => (b.onclick = () => { title.value = r.candidates[Number(b.dataset.tc)].title; touched(); title.focus(); }));
  };
  const pollTitles = async () => {
    let t;
    try { t = await api(`/api/topics/${topic.id}/titles`); } catch (err) { return; }
    if (!document.body.contains(list)) return;
    showTitles(t);
    if (t.running) setTimeout(pollTitles, 3000);
  };
  const tb = $('#cbTitles', el);
  api(`/api/topics/${topic.id}/titles`).then((t) => { if (t.result || t.running) { tb.textContent = '再出一批标题'; showTitles(t); if (t.running) setTimeout(pollTitles, 3000); } }).catch(() => {});
  tb.onclick = async () => {
    try { await api(`/api/topics/${topic.id}/titles`, { method: 'POST' }); tb.textContent = '再出一批标题'; showTitles({ running: true }); setTimeout(pollTitles, 3000); }
    catch (err) { toast(err.message); }
  };

  $('#cbSave', el).onclick = async () => {
    const v = read();
    if (!v.title) { toast('先写标题'); title.focus(); return; }
    const intro = v.intro || v.desc;
    const tr = readTraffic();
    const tagsFor = (k) => platformTags(k, v.tags, tr, specs).tags;
    const platforms = {
      ...Object.fromEntries(DESC_KEYS.filter((k) => specs[k]).map((k) => [k, { title: v.title, body: v.desc, tags: tagsFor(k) }])),
      ...Object.fromEntries(INTRO_KEYS.filter((k) => specs[k]).map((k) => [k, { title: v.title, body: intro, tags: tagsFor(k) }])),
    };
    try {
      await api(`/api/topics/${topic.id}/copy`, { method: 'PUT', body: { platforms } });
      CP.dirty = false; delete CP.data[topic.id];
      toast('文字信息已保存');
      if (onSaved) onSaved();
    } catch (err) { toast(err.message); }
  };
  $('#cbCopy', el).onclick = () => {
    const v = read();
    const text = [v.title, v.desc, platformTags('douyin', v.tags, readTraffic(), specs).tags.map((t) => '#' + t).join(' ')].filter(Boolean).join('\n\n');
    navigator.clipboard.writeText(text).then(() => toast('已复制'), () => toast('复制失败'));
  };
}
window.renderCopyForm = renderCopyForm;
