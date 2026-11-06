/* 门户（10/6 作者）：GitHub 和网站是常驻的触达面。不用定期发，但要经常看一眼它现在长什么样、能不能当好门户。
 * 一页一个：电脑、手机第一屏截图（陌生人看到的样子）+ AI 当陌生人的五项判断 + 最该改的一处；能翻以前的样子。
 * 每天第一次打开时后台截一次，在截的时候过几秒再问一次。 */
window.VIEWS = window.VIEWS || {};

const PORTAL = { data: {}, day: {}, timer: null };
const PORTAL_KEYS = ['github', 'site'];

function portalTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function portalJudge(s, running) {
  if (s.judge) {
    const j = s.judge;
    const pass = j.checks.filter((c) => c.ok).length;
    return `<div class="panel pt-judge">
      <div class="pt-score"><b>${pass}</b><span>/ ${j.checks.length} 项过关</span></div>
      <p class="pt-verdict">${esc(j.verdict)}</p>
      <ul class="pt-checks">${j.checks.map((c) => `<li class="${c.ok ? 'ok' : 'no'}"><i>${c.ok ? '✓' : '✗'}</i><div><b>${esc(c.label)}</b><span>${esc(c.note)}</span></div></li>`).join('')}</ul>
      ${j.fix ? `<div class="pt-fix"><small>最该改的一处</small>${esc(j.fix)}</div>` : ''}
      <p class="pt-foot">AI 当一个第一次点进来的陌生人，只看这两张图判断</p>
    </div>`;
  }
  if (running) return '<div class="panel pt-judge empty"><span class="spin"></span><span>正在用陌生人的眼光看，大约一两分钟…</span></div>';
  if (s.judge_error) return `<div class="panel pt-judge empty"><b>这次没判断出来</b><span>${esc(s.judge_error)}</span></div>`;
  return '<div class="panel pt-judge empty"><span>还没有判断</span></div>';
}

function portalPage(d) {
  const s = d.shot;
  const head = `<header class="page-h">
      <div><div class="stage-eyebrow">门户 · 常驻</div><h1>${esc(d.label)}</h1>
        <p>不用定期发，但一直放在那儿。陌生人点开你简介里的链接，第一眼看到的就是下面两张。每天第一次打开这页时重截一次。</p></div>
      <div class="page-h-actions">${d.url ? `<a class="btn" href="${esc(d.url)}" target="_blank" rel="noopener">打开 ${esc(d.url.replace(/^https?:\/\//, ''))}</a>` : ''}
        ${d.url ? `<button class="btn primary" type="button" id="ptRefresh"${d.running ? ' disabled' : ''}>${d.running ? '正在截…' : '重新截'}</button>` : ''}</div>
    </header>`;
  if (!d.url) {
    return `${head}<div class="panel empty"><b>还没填${esc(d.label)}链接</b><span>在设置 · 通用 · 在哪找到我里填一次，这里就开始截。</span><button class="btn" type="button" id="ptSetup">去设置填</button></div>`;
  }
  if (!s) {
    return `${head}<div class="panel empty"><span class="spin"></span><span>第一次截图，电脑和手机各一张，十几秒…</span></div>`;
  }
  const latest = d.days[0] === s.day;
  const stale = s.url && s.url !== d.url;
  const shot = (v, label) => (s.variants.includes(v)
    ? `<figure class="pt-shot pt-${v}"><a href="/api/portal/${d.key}/shot/${s.day}/${v}.png?t=${encodeURIComponent(s.at || '')}" target="_blank" rel="noopener"><img src="/api/portal/${d.key}/shot/${s.day}/${v}.png?t=${encodeURIComponent(s.at || '')}" alt="${esc(d.label)}${label}第一屏" loading="lazy"></a><figcaption>${label}</figcaption></figure>`
    : `<figure class="pt-shot pt-${v} pt-none"><div>没截到</div><figcaption>${label}</figcaption></figure>`);
  return `${head}
    <div class="pt-meta">
      <span>${latest ? '最新一次' : '以前的样子'} · 截于 ${esc(portalTime(s.at))}${stale ? ' · 那时的链接是 ' + esc(s.url) : ''}</span>
      ${s.error ? `<span class="bad">这次没截成：${esc(s.error)}</span>` : ''}
    </div>
    <div class="pt-grid">
      <div class="pt-shots">${shot('desktop', '电脑')}${shot('mobile', '手机')}</div>
      ${portalJudge(s, d.running && latest)}
    </div>
    ${d.days.length > 1 ? `<div class="pt-days"><small>以前的样子</small>${d.days.map((day) => `<button type="button" class="${day === s.day ? 'on' : ''}" data-pt-day="${day}">${day.slice(5).replace('-', '/')}</button>`).join('')}</div>` : ''}`;
}

async function loadPortal(key) {
  const day = PORTAL.day[key];
  PORTAL.data[key] = await api(`/api/portal/${key}${day ? `?day=${day}` : ''}`);
  return PORTAL.data[key];
}

window.VIEWS.portal = {
  async render() {
    const key = PORTAL_KEYS.includes(S.portalKey) ? S.portalKey : 'github';
    const body = $('#portalBody');
    if (!PORTAL.data[key]) body.innerHTML = '<div class="panel empty"><span class="spin"></span><span>正在读…</span></div>';
    let d;
    try { d = await loadPortal(key); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    if (S.view !== 'portal' || S.portalKey !== key) return;
    body.innerHTML = portalPage(d);
    clearTimeout(PORTAL.timer);
    if (d.running) PORTAL.timer = setTimeout(() => { if (S.view === 'portal') window.VIEWS.portal.render(); }, 5000);
    const refresh = $('#ptRefresh');
    if (refresh) refresh.onclick = async () => {
      refresh.disabled = true;
      try { PORTAL.day[key] = null; await api(`/api/portal/${key}/refresh`, { method: 'POST' }); toast('开始重新截，电脑和手机各一张'); } catch (err) { toast(err.message); }
      window.VIEWS.portal.render();
    };
    const setup = $('#ptSetup');
    if (setup) setup.onclick = () => {
      SET.tab = 'general';
      try { localStorage.setItem('cs-set-tab', 'general'); } catch (_) { /* ignore */ }
      go('settings');
      setTimeout(() => $('#setGithub')?.focus(), 0);
    };
    $$('[data-pt-day]', body).forEach((b) => (b.onclick = () => {
      PORTAL.day[key] = b.dataset.ptDay === d.days[0] ? null : b.dataset.ptDay;
      window.VIEWS.portal.render();
    }));
  },
};
