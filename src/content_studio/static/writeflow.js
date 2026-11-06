'use strict';

/* 写作流程（10/12 作者）：流程在 park-writing 的 module.yaml 里定，工作台只读它、只开关其中的步骤。
   这个文件管两件事：卡片上要用的清单（window.writeModule），和「设置 · 流程」里的写作流程面板。 */
(() => {
  const S = { info: null, loading: null, editing: null, ids: new Set(), msg: '' };
  const GROUPS = ['写', '风格', '查'];

  window.writeModule = () => S.info;
  window.loadWriteModule = (force = false) => {
    if (S.loading && !force) return S.loading;
    S.loading = api('/api/xline/write/module').then((info) => {
      S.info = info;
      if (info.ok && !S.editing) { S.editing = info.default; S.ids = new Set(flowIds(info, info.default)); }
      return info;
    }).catch((err) => (S.info = { ok: false, error: err.message }));
    return S.loading;
  };

  const flowIds = (info, name) => (info.flows[name] || info.custom[name] || []);
  const flowNames = (info) => [...Object.keys(info.flows), ...Object.keys(info.custom)];
  const same = (a, b) => a.length === b.size && a.every((i) => b.has(i));

  function paint() {
    const box = $('#wfBody');
    if (!box) return;
    const info = S.info;
    if (!info) { box.innerHTML = '<p class="sync-note">读取中…</p>'; return; }
    if (!info.ok) { box.innerHTML = `<p class="sync-note wf-bad">${esc(info.error).replace(/\n/g, '<br>')}</p>`; return; }
    const names = flowNames(info);
    const isCustom = Object.prototype.hasOwnProperty.call(info.custom, S.editing);
    const changed = !same(flowIds(info, S.editing), S.ids);
    const steps = (g) => info.steps.filter((s) => s.group === g).map((s) => {
      const planned = s.status === 'planned';
      return `<label class="wf-step${planned ? ' off' : ''}"><input type="checkbox" data-wf-step="${esc(s.id)}"${S.ids.has(s.id) && !planned ? ' checked' : ''}${planned ? ' disabled' : ''}>
        <b>${esc(s.title)}</b><span>${planned ? '还没做出来' : esc(s.does)}</span></label>`;
    }).join('');
    box.innerHTML = `
      <div class="wf-pick"><label>默认走 <select id="wfFlow">${names.map((n) => `<option value="${esc(n)}"${n === S.editing ? ' selected' : ''}>${esc(n)}${n === info.default ? '（默认）' : ''}</option>`).join('')}</select></label>
        ${S.editing !== info.default ? '<button class="btn small" type="button" id="wfDefault">设为默认</button>' : ''}
        ${isCustom ? '<button class="btn small ghost" type="button" id="wfDelete">删掉这个流程</button>' : ''}</div>
      ${GROUPS.map((g) => `<div class="wf-group"><h3>${g}</h3>${steps(g)}</div>`).join('')}
      <div class="wf-save"><input type="text" id="wfName" maxlength="20" placeholder="${isCustom ? S.editing : '给改过的流程起个名字'}" value="${isCustom ? esc(S.editing) : ''}" aria-label="流程名字">
        <button class="btn primary small" type="button" id="wfSave"${changed || !isCustom ? '' : ' disabled'}>${isCustom ? '保存这个流程' : '另存为我的流程'}</button>
        <small>顺序是固定的，只能开关；最多存 2 个。</small><small id="wfMsg" aria-live="polite">${esc(S.msg)}</small></div>
      <p class="sync-note">现在读的 park-writing：${esc(info.skill.path)}${info.skill.commit ? `，最后一次提交 ${esc(info.skill.commit)}` : ''}。这是本机的一份，GitHub 上合并的改动要拉到本机才生效。</p>
      <div class="wf-save"><label>默认改动预算 <input type="number" id="wfPct" min="1" max="${info.max_change_pct_limit || 50}" value="${info.max_change_pct}" aria-label="默认改动预算百分比"> %</label>
        <button class="btn small" type="button" id="wfPctSave">存</button><small>对你的原文；每一篇在批注视图顶上还能单独改。最多 ${info.max_change_pct_limit || 50}%。</small></div>
      <p class="sync-note">顺序不动、只用原词、不加数字和人名，由代码逐条检查，关不掉。痛点、利他、高密度只能加不能删；能删的只有口癖、重复的句子、读者看不到的指代。</p>`;
    $('#wfFlow').onchange = (e) => { S.editing = e.target.value; S.ids = new Set(flowIds(info, S.editing)); S.msg = ''; paint(); };
    $$('[data-wf-step]', box).forEach((c) => (c.onchange = () => { c.checked ? S.ids.add(c.dataset.wfStep) : S.ids.delete(c.dataset.wfStep); S.msg = ''; paint(); }));
    const put = async (body, done) => {
      try { await api('/api/xline/write/flow', { method: 'PUT', body }); await window.loadWriteModule(true); S.msg = done; } catch (err) { S.msg = err.message; }
      paint();
    };
    if ($('#wfDefault')) $('#wfDefault').onclick = () => put({ default: S.editing }, '已设为默认，之后做的长文按它走');
    if ($('#wfDelete')) $('#wfDelete').onclick = () => { const gone = S.editing; S.editing = info.default; S.ids = new Set(flowIds(info, info.default)); put({ delete: gone, default: info.default }, '删掉了'); };
    $('#wfPctSave').onclick = () => {
      const pct = Number($('#wfPct').value);
      if (!Number.isFinite(pct) || pct < 1 || pct > (info.max_change_pct_limit || 50)) { S.msg = '预算要在 1% 到 50% 之间'; paint(); return; }
      put({ max_change_pct: pct }, `默认改动预算改成 ${pct}%，之后做的文章按它走`);
    };
    $('#wfSave').onclick = () => {
      const name = ($('#wfName').value || '').trim() || (isCustom ? S.editing : '');
      if (!name) { S.msg = '起个名字'; paint(); return; }
      const ids = info.steps.filter((s) => S.ids.has(s.id) && s.status !== 'planned').map((s) => s.id);
      S.editing = name;
      put({ save: { name, steps: ids }, default: name }, '存好了，已设为默认');
    };
  }

  window.loadWriteFlow = async function () {
    paint();
    if (!S.info) await window.loadWriteModule();
    paint();
  };
})();
