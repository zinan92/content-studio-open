'use strict';
/* Skills：作者 做内容在用的 skill，按生产阶段分组；放在「设置与 Skills」里 */
window.VIEWS = window.VIEWS || {};

const SK = { data: null };

/* 「每轮读的文件」一格；when 是 Wendy 那种只在某一页才读的，写在路径下面。 */
function soulRow(f, who) {
  const missing = f.exists === false ? '（读不到这个文件，现在用的是默认）' : '';
  return `<button class="soul-row" type="button" data-soul="${f.i}" data-soul-who="${who}" ${f.exists === false ? 'disabled' : ''}><b>${esc(f.name.replace(/\.(md|txt)$/, ''))}</b><small>${esc(f.path)}</small>${f.when || missing ? `<small class="soul-when">${esc(f.when || '')}${esc(missing)}</small>` : ''}</button>`;
}

/* 每轮除了文件还带上的：规则、这一页的资料、屏幕、聊过的。不列出来，这一页就只说了一半。 */
function soulAlso(also) {
  return also && also.length ? `<p class="sync-note soul-also-h">每轮除了这些文件，还带上：</p><ul class="soul-also">${also.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
}

async function loadSkills() {
  if (!SK.data) SK.data = await api('/api/skills');
  return SK.data;
}

function copyText(text) {
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => toast('已复制调用方式'), () => toast(text));
  else toast(text);
}

/* Anna 的标准：拆解里学到的方法写进 content-qa，以后每条内容都按它评分。 */
window.reloadStandard = async function reloadStandard() {
  try { S.standard = await api('/api/standard'); } catch (_) { S.standard = null; }
  const box = $('#standardBox');
  if (box) renderStandard(box);
};

function standardRow(r) {
  return `<div class="std-row"><div><b>${esc(r.text)}</b><div class="by">${esc(r.at)}${r.source ? ' · ' + esc(r.source) : ''}</div></div>
    <button class="btn small ghost" type="button" data-std-rm="${esc(r.id)}">删掉</button></div>`;
}

function renderStandard(box) {
  const d = S.standard;
  if (!d) { box.innerHTML = ''; return; }
  box.innerHTML = `<section class="panel std">
    <div class="panel-h"><h2>从拆解里学来的 <span class="num">${d.rules.length || ''}</span></h2><small>写进三点评分标准，Anna 每轮都读它 · ${esc(d.path)}</small></div>
    ${d.rules.length ? d.rules.map(standardRow).join('')
      : '<div class="std-empty">还没有。拆一条对标的视频，问 Anna 学到什么，她会给一个「记进标准」的按钮。</div>'}
  </section>`;
  $$('[data-std-rm]', box).forEach((b) => (b.onclick = async () => {
    const r = d.rules.find((x) => x.id === b.dataset.stdRm);
    if (!confirm(`把这条从标准里删掉？\n\n${r.text}`)) return;
    try { await api(`/api/standard/${encodeURIComponent(b.dataset.stdRm)}`, { method: 'DELETE' }); toast('已删掉'); await window.reloadStandard(); } catch (err) { toast(err.message); }
  }));
}

const SKILL_FIELDS = [
  ['name', '名字', '英文，比如 khazix-writer'],
  ['title', '叫什么', '中文名，比如 卡兹克写作'],
  ['use', '用来做什么', '一句话'],
  ['repo', 'GitHub 链接', 'https://github.com/…（别人写的 skill 只放链接）'],
  ['dir', '本机 skill 目录', '装在 ~/.claude/skills 下的文件夹名，没有就空着'],
  ['path', '本机 Markdown', '~/ 开头的 .md，比如一份写作框架'],
  ['author', '作者', ''],
  ['invoke', '怎么叫它', '在 Codex / Claude 中调用…'],
];

function skillForm(stages, s, fresh) {
  s = s || {};
  return `<form class="dlg skill-form" id="skillForm">
    <h2>${s.name && !fresh ? '改这个 skill' : '加一个 skill'}</h2>
    ${SKILL_FIELDS.map(([k, l, ph]) => `<label><span>${l}</span><input id="sk-${k}" value="${esc(s[k] || '')}" placeholder="${esc(ph)}" autocomplete="off"></label>`).join('')}
    <label><span>用在哪一步</span><select id="sk-stage">${stages.map((st) => `<option value="${st.key}" ${s.stage === st.key ? 'selected' : ''}>${esc(st.label)}</option>`).join('')}</select></label>
    <label class="chk"><input type="checkbox" id="sk-own" ${s.own ? 'checked' : ''}> 我自己写的</label>
    <div class="dlg-actions"><button type="button" class="btn" id="skCancel">取消</button><button class="btn primary" type="submit">保存</button></div>
  </form>`;
}

function openSkillDialog(html, bind) {
  let dlg = $('#skillDlg');
  if (!dlg) { dlg = document.createElement('dialog'); dlg.id = 'skillDlg'; dlg.className = 'skill-dlg'; document.body.appendChild(dlg); }
  dlg.innerHTML = html;
  dlg.showModal();
  bind(dlg);
  return dlg;
}

function openSkillEditor(data, s, fresh) {
  openSkillDialog(skillForm(data.stages, s, fresh), (dlg) => {
    $('#skCancel', dlg).onclick = () => dlg.close();
    $('#skillForm', dlg).onsubmit = async (e) => {
      e.preventDefault();
      const body = { previous: s && !fresh ? s.name : null, stage: $('#sk-stage', dlg).value, own: $('#sk-own', dlg).checked };
      SKILL_FIELDS.forEach(([k]) => { body[k] = $(`#sk-${k}`, dlg).value.trim() || null; });
      try { await api('/api/skills', { method: 'PUT', body }); dlg.close(); toast('已保存'); await reloadSkills(); } catch (err) { toast(err.message); }
    };
  });
}

async function openDoc(url, fallbackTitle) {
  const dlg = openSkillDialog('<div class="dlg doc-dlg"><div class="empty"><span class="spin"></span></div></div>', () => {});
  try {
    const d = await api(url);
    dlg.innerHTML = `<div class="dlg doc-dlg"><div class="doc-h"><div><h2>${esc(d.name || fallbackTitle)}</h2><small>${esc(d.path)}</small></div><button class="btn small" type="button" id="docClose">关掉</button></div><article class="md">${renderMarkdown(d.body || '')}</article></div>`;
  } catch (err) { dlg.innerHTML = `<div class="dlg"><b>${esc(err.message)}</b><div class="dlg-actions"><button class="btn" type="button" id="docClose">关掉</button></div></div>`; }
  const c = $('#docClose', dlg); if (c) c.onclick = () => dlg.close();
}

async function reloadSkills() {
  SK.data = null;
  const body = $('#skillsBody'); if (body) body.dataset.done = '';
  await window.renderSkills.render();
}

function usedText(u) {
  if (!u) return '';
  if (u.missing) return u.missing;
  return u.count ? `近两周 ${u.count} 次 · ${u.last}` : '近两周没跑过';
}

function skillCard(s, usedBy) {
  const acts = s.listed
    ? `${s.installed ? `<button class="btn small" type="button" data-sk-doc="${esc(s.name)}">看文件</button>` : ''}<button class="btn small ghost" type="button" data-sk-edit="${esc(s.name)}">改</button><button class="btn small ghost" type="button" data-sk-rm="${esc(s.name)}">删</button>`
    : `<button class="btn small" type="button" data-sk-add="${esc(s.name)}">加进清单</button>`;
  const where = s.in_flow
    ? `<div class="skill-steps">${s.steps.map((t) => `<span class="pill">${esc(t)}</span>`).join('')}${usedBy ? `<small>${esc(usedBy)}</small>` : ''}</div>`
    : (s.was ? `<div class="skill-by">原来放在「${esc(s.was)}」</div>` : '');
  return `<article class="panel skill ${s.in_flow ? 'in-flow' : 'off-flow'}" id="skill-${esc(s.name)}">
    <div class="skill-h"><b>${esc(s.title || s.name)}</b>${s.own ? '<span class="pill hot">我的</span>' : ''}${s.listed ? `<span class="skill-state ${s.installed ? 'ok' : ''}">${s.installed ? '本机有' : '本机未装'}</span>` : '<span class="skill-state unlisted">清单里没列</span>'}</div>
    <code class="skill-name">${esc(s.name)}</code>
    ${where}
    <p>${esc(s.use || '')}</p>
    ${s.listed ? `<div class="skill-by">${s.author ? `作者：${esc(s.author)}` : '作者：来源待补'}${s.repo ? ` · <a href="${esc(s.repo)}" target="_blank" rel="noopener">GitHub ↗</a>` : ''}</div>
    <button class="invoke" type="button" data-copy="${esc(s.invoke)}" title="点击复制">${esc(s.invoke)}</button>` : ''}
    <div class="skill-acts">${acts}</div>
  </article>`;
}

/* 流程图：五段照左栏，skill 挂在调用它的那一步；相邻同组的步骤是同时进行的几条路，框在一起 */
function flowStep(step, cards) {
  const chips = step.skills.map((n) => {
    const c = cards.find((x) => x.name === n) || { name: n, title: n, listed: true };
    return `<button type="button" class="sk-chip ${c.listed ? '' : 'unlisted'}" data-sk-jump="${esc(n)}" title="${c.listed ? '' : '清单里没列'}">${esc(c.title || n)}</button>`;
  }).join('');
  const used = usedText(step.used);
  return `<div class="fl-step ${step.skills.length ? 'has' : ''}"><b>${esc(step.label)}</b>${step.note ? `<small>${esc(step.note)}</small>` : ''}${chips ? `<div class="fl-chips">${chips}</div>` : ''}${used ? `<small class="fl-used">${esc(used)}</small>` : ''}</div>`;
}

function flowStage(stage, cards) {
  const parts = [];
  let i = 0;
  while (i < stage.steps.length) {
    const g = stage.steps[i].group;
    let j = i + 1;
    while (g && j < stage.steps.length && stage.steps[j].group === g) j++;
    const run = stage.steps.slice(i, j);
    if (parts.length) parts.push('<div class="fl-arrow">↓</div>');
    parts.push(g && run.length > 1
      ? `<div class="fl-par"><span>${esc(g)}</span>${run.map((s) => flowStep(s, cards)).join('')}</div>`
      : run.map((s) => flowStep(s, cards)).join(''));
    i = j;
  }
  return `<section class="fl-stage fl-${stage.key}"><header><b>${esc(stage.label)}</b><small>${esc(stage.sub)}</small></header>${parts.join('')}</section>`;
}

function stepUsage(flow, name) {
  for (const st of flow) for (const s of st.steps) if (s.skills.includes(name) && s.used && s.used.count) return usedText(s.used);
  return '';
}

window.renderSkills = {
  async render() {
    const body = $('#skillsBody');
    await window.reloadStandard();  // its own panel in 设置, not inside the collapsed Skills block
    if (body.dataset.done) return;
    let data, soul, wsoul;
    try { [data, soul, wsoul] = await Promise.all([loadSkills(), ...(featureOn('team') ? [api('/api/anna/soul'), api('/api/wendy/soul')] : [])]); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    body.dataset.done = '1';
    const cards = data.cards || data.skills.map((x) => ({ ...x, listed: true, in_flow: false, steps: [] }));
    const inFlow = cards.filter((c) => c.in_flow);
    const offFlow = cards.filter((c) => !c.in_flow);
    const unlisted = inFlow.filter((c) => !c.listed).length;
    body.innerHTML = `<div class="skill-top"><p class="sync-note"><b>${inFlow.length - unlisted}</b> 个在流程中${unlisted ? `（另有 ${unlisted} 个流程在用、清单里没列）` : ''} · <b>${offFlow.length}</b> 个不在流程中。「在不在」看工作台哪一步真的调用它，不用你填；次数是近 ${data.usage_days || 14} 天这一步留下的东西。清单存在 <code>${esc(data.file || '')}</code>。</p><button class="btn small primary" type="button" id="skAdd">加一个 skill</button></div>
      ${data.flow ? `<div class="fl-scroll"><div class="fl">${data.flow.map((st) => flowStage(st, cards)).join('')}</div></div>` : ''}
      <section class="skill-stage"><h2>在流程中 <small>${inFlow.length - unlisted}${unlisted ? ` + ${unlisted} 个清单没列` : ''}</small></h2><div class="skill-grid">${inFlow.map((c) => skillCard(c, stepUsage(data.flow || [], c.name))).join('')}</div></section>
      <section class="skill-stage"><h2>不在流程中 <small>${offFlow.length}</small></h2><p class="sync-note">清单里有，但工作台哪一步都没调用。仍可在支持该 Skill 的工具中调用；不用了可以删（只删清单，不动本机文件）。</p><div class="skill-grid">${offFlow.map((c) => skillCard(c, '')).join('')}</div></section>
`;
    // 试用版没有 AI 团队，也就没有她们每轮读的文件
    const soulHtml = !soul ? '' : `      <section class="skill-stage"><h2>${esc(((S.state || {}).brand || {}).editor || 'Anna')} 每轮读的文件 <small>${soul.files.length}</small></h2><p class="sync-note">角色、knowledge、原则、定位、三点评分。改这些 Markdown 就是改 Anna；这里只读。</p>
        <div class="soul-list">${soul.files.map((f) => soulRow(f, 'anna')).join('')}</div>${soulAlso(soul.also)}</section>
      <section class="skill-stage"><h2>${esc(((S.state || {}).brand || {}).boss || 'Wendy')} 每轮读的文件 <small>${wsoul.files.length}</small></h2><p class="sync-note">她的角色文件，工作台和微信读的是同一份；在「我是谁」页再加上定位。改这些 Markdown 就是改 Wendy；这里只读。</p>
        <div class="soul-list">${wsoul.files.map((f) => soulRow(f, 'wendy')).join('')}</div>${soulAlso(wsoul.also)}</section>`;
    const soulBox = $('#soulBody');
    if (soulBox) soulBox.innerHTML = soulHtml; else body.insertAdjacentHTML('beforeend', soulHtml);
    const scope = $('#v-settings') || body;
    $$('[data-sk-jump]', body).forEach((b) => (b.onclick = () => {
      const el = document.getElementById(`skill-${b.dataset.skJump}`);
      if (!el) return;
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1600);
    }));
    $$('[data-sk-add]', body).forEach((b) => (b.onclick = () => {
      const c = cards.find((x) => x.name === b.dataset.skAdd);
      openSkillEditor(data, { name: c.name, title: c.title, use: c.use, dir: c.dir, path: c.path, own: c.own, stage: c.path ? 'plan' : 'video' }, true);
    }));
    $$('[data-copy]', body).forEach((b) => (b.onclick = () => copyText(b.dataset.copy)));
    $('#skAdd').onclick = () => openSkillEditor(data, null);
    $$('[data-sk-edit]', body).forEach((b) => (b.onclick = () => openSkillEditor(data, data.skills.find((s) => s.name === b.dataset.skEdit))));
    $$('[data-sk-doc]', body).forEach((b) => (b.onclick = () => openDoc(`/api/skills/${encodeURIComponent(b.dataset.skDoc)}/doc`, b.dataset.skDoc)));
    $$('[data-soul]', scope).forEach((b) => (b.onclick = () => openDoc(`/api/${b.dataset.soulWho}/soul/${b.dataset.soul}`, '')));
    $$('[data-sk-rm]', body).forEach((b) => (b.onclick = async () => {
      if (!confirm(`把「${b.dataset.skRm}」从清单里删掉？只删清单，不动本机的 skill 文件。`)) return;
      try { await api(`/api/skills/${encodeURIComponent(b.dataset.skRm)}`, { method: 'DELETE' }); toast('已删掉'); await reloadSkills(); } catch (err) { toast(err.message); }
    }));
  },
};
