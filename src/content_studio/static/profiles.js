'use strict';
/* 对外简介：一个文件、两段——国内版和 X 版（profiles.py），正本是 Obsidian 里的 park profile.md。
 * 放在「定位」页最下面：在这里改就写回 Obsidian，在 Obsidian 里改这里也跟着变。
 * 每个平台只记「哪天改成了它那一版」。改到平台上是 作者自己做：复制过去贴，贴完点「我贴好了」。 */
const PFX = { data: null, live: null, editing: {}, tab: null };  // tab：看的是哪一版（10/6 照 Codex 稿：一次看一版）  // editing：哪一版点了「改这一版」；存过的默认锁着（10/1 作者：存好了还是开着，lock in）
const PF_STATE = { synced: ['已同步', 'hot'], stale: ['这一版改过了，要更新', 'mid'], never: ['还没改过', 'low'] };

function profilePlatform(p) {
  const [word, tone] = PF_STATE[p.state];
  const acts = p.state === 'synced' || p.empty ? '' : `<button class="btn small" type="button" data-pf-applied="${p.key}">我贴好了</button>${p.can_push ? `<button class="btn small ghost" type="button" data-pf-push="${p.key}" title="不想手动贴的话，点两次直接改到 X 上">直接改上去</button>` : ''}`;
  return `<div class="pf-row"><b>${esc(p.label)}</b><span class="pf-state ${tone}">${word}${p.state !== 'never' && p.applied_at ? ' · ' + day(p.applied_at) : ''}</span>
    <small>${esc(p.where)}</small>
    <span class="acts">${p.edit_url ? `<a class="pos-text-btn" href="${esc(p.edit_url)}" target="_blank" rel="noopener">打开 ↗</a>` : ''}${acts}</span></div>`;
}

function profileVariant(v, d) {
  const cur = d.profile.variants[v.key];
  const count = (f) => `<i class="${v.limits[f] && cur[f].length > v.limits[f] ? 'over' : ''}"><b data-pf-count="${v.key}-${f}">${cur[f].length}</b>${v.limits[f] ? ' / ' + v.limits[f] : ''}</i>`;
  const plats = d.platforms.filter((p) => p.variant === v.key);
  const live = v.key === 'x' && PFX.live ? `<div class="pf-live"><small>X 上现在是</small><b>${esc(PFX.live.name || '')}</b><span>${esc(PFX.live.description || '（没有简介）')}</span></div>` : '';
  const sync = `${live}<div class="pos-sh"><div><h3>平台同步</h3><p>${plats.map((p) => esc(p.label)).join('、') || '这一版对应的平台都没开'}</p></div></div>
    <div class="pf-sync">${plats.map(profilePlatform).join('')}</div>`;
  const avatar = esc(((cur.name || '').match(/[A-Za-z]+/) || [(cur.name || '我').slice(0, 1)])[0]);
  if ((cur.name || cur.bio) && !PFX.editing[v.key]) {
    // 锁定：只读显示，复制照常；要改先点「改这一版」
    return `<div class="pf-var locked" data-pf-var="${v.key}">
    <div class="pf-sheet">
      <div class="pf-sheet-head"><span class="pf-avatar">${avatar}</span><div><h3>${esc(cur.name)}</h3><span class="pos-pill">已定稿</span></div>
        <button class="btn small" type="button" data-pf-copy="${v.key}" data-f="name">复制名字</button></div>
      <p class="pf-bio">${esc(cur.bio)}</p>
      <div class="pf-acts">
        <button class="btn small primary" type="button" data-pf-copy="${v.key}" data-f="bio">复制简介</button>
        <button class="btn small" type="button" data-pf-unlock="${v.key}">改这一版</button>
      </div>
    </div>
    ${sync}
  </div>`;
  }
  return `<div class="pf-var" data-pf-var="${v.key}">
    <div class="pf-sheet pf-edit">
      <label><span class="pf-lab">名字 ${count('name')}</span>
        <input data-pf-f="name" value="${esc(cur.name)}" placeholder="主页上显示的名字" autocomplete="off"></label>
      <label><span class="pf-lab">简介 ${count('bio')}</span>
        <textarea data-pf-f="bio" rows="${v.key === 'x' ? 5 : 7}" placeholder="${v.key === 'x' ? '身份｜带数字的证据｜关注我能看到什么｜怎么找我' : '我是谁、帮谁、做成什么、怎么找我'}">${esc(cur.bio)}</textarea></label>
      <div class="pf-acts">
        <button class="btn small primary" type="button" data-pf-save="${v.key}">存进 Obsidian</button>
        <button class="btn small" type="button" data-pf-copy="${v.key}" data-f="bio">复制简介</button>
        <button class="btn small" type="button" data-pf-copy="${v.key}" data-f="name">复制名字</button>
        ${cur.name || cur.bio ? `<button class="btn small ghost" type="button" data-pf-cancel="${v.key}">不改了，锁回去</button>` : ''}
      </div>
    </div>
    ${sync}
  </div>`;
}

window.renderProfiles = async () => {
  const box = $('#profilesBody');
  if (!box) return;
  try { PFX.data = await api('/api/profile'); } catch (err) { box.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
  if (document.activeElement && box.contains(document.activeElement) && document.activeElement.matches('input, textarea')) return;
  const d = PFX.data, p = d.profile;
  if (!d.variants.some((v) => v.key === PFX.tab)) PFX.tab = (d.variants[0] || {}).key;
  const shown = d.variants.find((v) => v.key === PFX.tab);
  box.innerHTML = `<section class="pf-sec">
      <div class="pos-seg" role="tablist">${d.variants.map((v) => `<button type="button" role="tab" class="${v.key === PFX.tab ? 'on' : ''}" data-pf-tab="${v.key}">${esc(v.label)}</button>`).join('')}</div>
      ${shown ? profileVariant(shown, d) : ''}
      <p class="pos-foot">内容来源：${p.exists ? `<code>${esc(p.path.replace(/^.*\/(000_我\/)/, '$1'))}</code>${p.embeds ? `（里面还有 ${p.embeds} 张图，原样留着）` : ''}` : '文件还不存在，存一次就会建出来'}
        ${p.obsidian ? ` · <a href="${esc(p.obsidian)}">在 Obsidian 里打开</a>` : ''} · <button class="linklike" type="button" id="pfReload">重新读</button></p>
    </section>`;
  $$('[data-pf-tab]', box).forEach((b) => (b.onclick = () => { PFX.tab = b.dataset.pfTab; window.renderProfiles(); }));
  const again = () => window.renderProfiles();
  $('#pfReload').onclick = () => { document.activeElement.blur(); again(); };
  $$('.pf-var', box).forEach((card) => {
    const key = card.dataset.pfVar;
    const limits = d.variants.find((v) => v.key === key).limits;
    const unlock = $(`[data-pf-unlock="${key}"]`, card);
    if (unlock) unlock.onclick = () => { PFX.editing[key] = true; again(); };
    const cancel = $(`[data-pf-cancel="${key}"]`, card);
    if (cancel) cancel.onclick = () => { delete PFX.editing[key]; again(); };
    $$('[data-pf-f]', card).forEach((el) => (el.oninput = () => {
      const c = $(`[data-pf-count="${key}-${el.dataset.pfF}"]`, card);
      c.textContent = el.value.length;
      c.parentElement.classList.toggle('over', Boolean(limits[el.dataset.pfF]) && el.value.length > limits[el.dataset.pfF]);
    }));
    const save = $(`[data-pf-save="${key}"]`, card);
    if (save) save.onclick = async () => {
      const body = { ...Object.fromEntries($$('[data-pf-f]', card).map((el) => [el.dataset.pfF, el.value])), mtime: p.mtime };
      try { await api(`/api/profile/${key}`, { method: 'PUT', body }); delete PFX.editing[key]; toast('存进 Obsidian 了，锁上了'); } catch (err) { toast(err.message); }
      document.activeElement.blur();
      again();
    };
    $$(`[data-pf-copy="${key}"]`, card).forEach((b) => (b.onclick = async () => {
      const field = $(`[data-pf-f="${b.dataset.f}"]`, card);
      const text = field ? field.value : (p.variants[key] || {})[b.dataset.f] || '';
      try { await navigator.clipboard.writeText(text); toast(b.dataset.f === 'bio' ? '简介复制好了' : '名字复制好了'); } catch (_) { toast('没复制上，手动选中复制'); }
    }));
  });
  $$('[data-pf-applied]', box).forEach((b) => (b.onclick = async () => { try { await api(`/api/profile/applied/${b.dataset.pfApplied}`, { method: 'POST' }); toast('记下了'); } catch (err) { toast(err.message); } again(); }));
  $$('[data-pf-push]', box).forEach((b) => (b.onclick = async () => {
    if (!b.dataset.armed) { b.dataset.armed = '1'; b.textContent = '再点一次：真的改到 X 上'; setTimeout(() => { if (document.body.contains(b)) { delete b.dataset.armed; b.textContent = '直接改上去'; } }, 4000); return; }
    b.disabled = true;
    try { const r = await api('/api/profile/x/push', { method: 'POST' }); PFX.live = r.live; toast('X 主页改好了'); } catch (err) { toast(err.message); }
    again();
  }));
  // X 上现在是什么：读一次，读不到就不显示
  if (PFX.live === null && d.platforms.some((x) => x.key === 'x')) {
    PFX.live = false;
    api('/api/profile/x/live').then((r) => { PFX.live = r.live; again(); }).catch(() => {});
  }
};
