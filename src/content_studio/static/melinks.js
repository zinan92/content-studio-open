/* 在哪找到我（10/6 作者）：GitHub 和个人网站。正本是 profile.yaml 的 me.github / me.site，和抖音主页放一起；
 * 设置 · 通用里改。左栏「门户」两页（portal.js）截的就是这两个链接。 */
const ME = { links: null, readVersion: 0, loaded: false };

async function loadMeLinks() {
  const version = ++ME.readVersion;
  try { const links = await api('/api/me/links'); if (version === ME.readVersion) ME.links = links; } catch (_) { /* preserve known links */ }
  return ME.links;
}

// app.js 最后才加载（$、api 都在那里），所以表单在设置页第一次画的时候才接上
window.fillMeLinksForm = async () => {
  const form = $('#meLinksForm');
  if (form) form.onsubmit = submitMeLinks;
  const gh = $('#setGithub'), site = $('#setSite');
  if (!gh || document.activeElement === gh || document.activeElement === site) return;
  if (!FormState.get('links')) FormState.load('links', { github: gh.value, site: site.value });
  bindFormDraft('links', form, () => ({ github: gh.value, site: site.value }));
  form.dataset.awaitingRead = ME.loaded ? '0' : '1';
  paintFormState('links', form);
  const l = ME.links || await loadMeLinks();
  if (!l) {
    $('#meLinksErr').textContent = '暂时读不到已保存的链接，输入已保留。请重新读取后保存。';
    if (!form.querySelector('[data-links-retry]')) { const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'btn'; retry.dataset.linksRetry = ''; retry.textContent = '重新读取链接'; retry.onclick = () => window.fillMeLinksForm(); form.append(retry); }
    return;
  }
  const firstRead = !ME.loaded;
  ME.loaded = true; form.dataset.awaitingRead = '0';
  $('#meLinksErr').textContent = '';
  form.querySelector('[data-links-retry]')?.remove();
  const draft = FormState.load('links', { github: l.github_user || '', site: l.site || '' }, { mergeUntouched: firstRead });
  if (document.activeElement !== gh) gh.value = draft.values.github;
  if (document.activeElement !== site) site.value = draft.values.site;
  bindFormDraft('links', form, () => ({ github: gh.value, site: site.value }));
};

async function submitMeLinks(e) {
  e.preventDefault();
  const form = $('#meLinksForm');
  if (!ME.loaded) { $('#meLinksErr').textContent = '正在读取已有链接，请读完后保存；输入会保留。'; return; }
  $('#meLinksErr').textContent = '';
  const saved = await submitFormDraft('links', form, () => ({ github: $('#setGithub').value, site: $('#setSite').value }), async (values) => {
    const saved = await api('/api/me/links', { method: 'PUT', body: values });
    ++ME.readVersion; ME.links = saved;
    return { savedValues: { github: saved.github_user || '', site: saved.site || '' } };
  });
  if (saved) toast('门户链接已保存');
}
