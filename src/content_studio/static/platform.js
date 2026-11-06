'use strict';
/* 平台页（10/6 作者：左边按平台排，抖音、视频号、小红书、X 各一页，B 站 · YouTube · 公众号合成「其他三个」）。

   一页三段：
     待发   加工中做完「标题和封面」的那条在这个平台要做的事：发哪几种（默认按这个平台的设置，这条上改只影响这条）、
            每一种一行——机器能发的一个按钮；要他自己传的，文件夹和文案备好、他传完点「发了」（能贴链接）。
     这个平台  默认发什么、常用话题（只显示，10/8 起在设置里改）、顺序、账号、开关。
     数据   今天触达、近 7 天、发过的每条和它的数；被删、被限流的记录。
   X 那一页和别的平台一模一样（10/19 作者：长文、短帖、每天发多少、今天的都从页面上拿掉）。
   「其他三个」不是这三段，是一张汇总表（10/8，见 ppOthers）。 */
window.VIEWS = window.VIEWS || {};

const PP = { key: null, data: null, at: 0, poll: null, busy: {}, linkFor: null, noteOpen: false, match: null, request: 0, renderRequest: 0 };
const PP_STATE = { linked: '已连接', ready: '凭据就绪', stale: '要重新登录', blocked: '平台不让机器发', setup: '差一步配置', manual: '你来传' };
const PP_LABEL = { douyin: '抖音', channels: '视频号', xiaohongshu: '小红书', x: 'X', bilibili: 'B 站', youtube: 'YouTube', wechat_mp: '公众号', others: '其他三个' };
const PP_FOLDER = ['douyin', 'channels', 'xiaohongshu'];  // 这几个有上传文件夹（视频 + 封面 + 文案.txt）

// Shared publication display helpers consume backend facts; they never authorize a send.
function publicationUrl(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : ''; } catch (_) { return ''; }
}
function publicationWarnings(warnings = []) {
  if (!warnings.length) return '';
  return `<aside class="publication-warning" role="note"><b>发布关联需要核对</b><ul>${warnings.map((w) => `<li>${esc(w.message || `${w.platform} 同一帖子关联了多条内容`)}${w.publications?.length ? ` · ${esc(PP_LABEL[w.platform] || w.platform)}：${w.publications.map((p) => `《${esc(p.title || '未命名内容')}》`).join('、')}` : ''}</li>`).join('')}</ul></aside>`;
}
function publicationFact(p) {
  if (!p) return '';
  const url = publicationUrl(p.state === 'published' ? p.url : p.draft_link);
  return `<div class="publication-fact"><span class="publication-status state-${esc(p.state)}">${esc(p.label)}</span>${p.published_at ? `<small>${esc(ppWhen(p.published_at))}</small>` : ''}${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${p.state === 'published' ? '回执' : '草稿'} ↗</a>` : ''}${p.reason ? `<span>${esc(p.reason)}</span>` : ''}</div>`;
}
async function ppLoad(force) {
  const key = S.platformKey;
  if (!force && PP.data && PP.key === key && Date.now() - PP.at < 8000) return PP.data;
  const request = ++PP.request;
  const data = await api(`/api/platform/${key}`);
  if (request === PP.request && key === S.platformKey) { PP.key = key; PP.data = data; PP.at = Date.now(); }
  return data;
}

window.invalidatePlatform = () => { PP.data = null; PP.at = 0; const b = $('#platformBody'); if (b) b.dataset.sig = ''; };

/* 左栏每个平台右边的数：几条待发。10/19 作者：六个平台一个格式，X 不再另挂「等你勾」 */
window.refreshPlatformNav = async () => {
  let c;
  try { c = await api('/api/platform/counts'); } catch (_) { return; }
  for (const k of ['douyin', 'channels', 'xiaohongshu', 'x', 'youtube', 'bilibili']) {
    const el = $(`#navP-${k}`);
    if (!el) continue;
    el.textContent = c[k] ? `${c[k]} 待发` : '';
    el.classList.toggle('hot', Boolean(c[k]));
  }
};

const ppCopyText = (c) => `${c.title || ''}\n\n${c.body || ''}\n\n${(c.tags || []).map((t) => `#${t}`).join(' ')}`.trim();
const ppWhen = (iso) => (iso ? new Date(iso).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) : '');
const ppPlat = (d) => `<i class="plat tier-core" style="--plat:${esc(d.hue || '#444')}">${esc(d.mark || d.label[0])}</i>`;

/* ---------- 顶部：这个平台是谁、连没连上、今天的数 ---------- */
function ppHeader(d) {
  const how = d.how ? d.how[0] === 'auto' ? '机器发' : d.how[0] === 'draft' ? '进草稿箱' : '你来传' : '';
  const bits = [d.handle ? `@${d.handle}` : '', d.state === 'manual' ? '' : PP_STATE[d.state] || d.state, how, d.today.manual ? '数据手填' : '自动读数'].filter(Boolean);
  const today = d.today.manual
    ? `<label class="pp-today-in">今天触达 <input class="num" type="number" min="0" inputmode="numeric" id="ppTodayIn" value="${d.today.views ?? ''}" placeholder="待填">${d.today.stats_url ? `<a href="${esc(d.today.stats_url)}" target="_blank" rel="noopener">去后台看 ↗</a>` : ''}</label>`
    : `<div class="pp-today"><small>今天触达</small><b class="num">${d.today.views === null || d.today.views === undefined ? '—' : fmt(d.today.views)}</b><small>${d.today.share ? `全网的 ${d.today.share}%` : d.today.read === 'not_read' ? '今天还没读' : d.today.read === 'baseline' ? '今天第一次读' : ''}</small></div>`;
  return `<header class="page-h pp-h">
    <div class="pp-id">${ppPlat(d)}<div><button class="linklike stage-eyebrow" type="button" onclick="go('plats')">盘 · 各平台 ‹</button><h1>${esc(d.label)}</h1><p>${bits.map(esc).join(' · ')}${d.note && d.state !== 'linked' && d.state !== 'manual' ? ` · <span class="bad">${esc(d.note)}</span>` : ''}</p></div></div>
    ${today}
  </header>`;
}

/* ---------- 待发 ---------- */
function ppFormRow(item, r, d) {
  return `<div class="publication-row">${publicationFact(r.presentation)}${ppFormActions(item, r, d)}</div>`;
}
function ppFormActions(item, r, d) {
  const key = d.key;
  const tid = item.topic_id;
  const sent = r.sent;
  const linkKey = `${tid}|${r.form}|${key}`;  // 带上平台：「发」页一张表里几个平台同一条同一种形式，链接框只开点的那一行
  if (sent) {
    return `<div class="pp-frow s-sent"><span class="fk">${esc(r.label)}</span>
      <span class="fv"><b class="ok">✓ 发了</b>${sent.at ? ` · ${ppWhen(sent.at)}` : ''}${sent.url ? ` · <a href="${esc(sent.url)}" target="_blank" rel="noopener">看这条 ↗</a>` : ''}${sent.how === 'mark' ? ' · 你标的' : ''}</span>
      <span class="act">${sent.how === 'douyin' ? '' : `<button class="btn small ghost" type="button" data-pp-undo="${linkKey}">撤回</button>`}</span></div>`;
  }
  const job = r.job;
  const linkForm = PP.linkFor === linkKey ? `<span class="pp-link"><input type="url" id="ppLinkIn" placeholder="贴上这条的链接（可以不贴）" autocomplete="off"><label class="pp-day">哪天发的<input type="date" id="ppDayIn" value="${new Date().toLocaleDateString('sv-SE')}" max="${new Date().toLocaleDateString('sv-SE')}"></label><button class="btn small primary" type="button" data-pp-sent-go="${linkKey}">记下</button><button class="btn small ghost" type="button" data-pp-sent-no="1">算了</button></span>` : '';
  const sentBtn = linkForm || `<button class="btn small ghost" type="button" data-pp-sent="${linkKey}">${job?.draft ? '已发布，登记链接' : ['unknown', 'awaiting_confirm'].includes(job?.state) ? '已核实发布，登记链接' : '已上传，登记链接'}</button>`;
  if (job && job.state === 'running') return `<div class="pp-frow s-run"><span class="fk">${esc(r.label)}</span><span class="fv"><span class="spin"></span> 机器在发…</span><span class="act"></span></div>`;
  if (job && ['unknown', 'awaiting_confirm'].includes(job.state)) {
    const admin = publicationUrl(d.admin || r.upload_url);
    return `<div class="pp-frow s-wait"><span class="fk">${esc(r.label)}</span><span class="fv">先去后台核对这次发布结果，核实后登记。</span><span class="act">${admin ? `<a class="btn small" href="${esc(admin)}" target="_blank" rel="noopener">去后台核对 ↗</a>` : ''}${sentBtn}</span></div>`;
  }
  if (job?.draft) {
    const draft = publicationUrl(job.draft_link || d.admin || r.upload_url);
    return `<div class="pp-frow s-wait"><span class="fk">${esc(r.label)}</span><span class="fv">已有草稿，去后台核对并发布${!r.ready ? '；当前素材的改动尚未准备好，不影响登记已有草稿' : ''}。</span><span class="act">${draft ? `<a class="btn small primary" href="${esc(draft)}" target="_blank" rel="noopener">去后台查看草稿 ↗</a>` : ''}${sentBtn}</span></div>`;
  }
  if (!r.ready) {
    const fix = /标题|封面|文章|排版|图文卡/.test(r.why) ? `<button class="btn small" type="button" onclick="S.packId=${tid};go('pack')">去定标题和封面 →</button>` : '';
    return `<div class="pp-frow s-wait"><span class="fk">${esc(r.label)}</span><span class="fv">${esc(r.why)}</span><span class="act">${fix}</span></div>`;
  }
  const failed = job && job.state === 'failed';
  const note = failed ? `${ppFailLine(job.message, d.label, d.key)} ` : '';
  let fv = '', act = '';
  if (r.action === 'auto' || r.action === 'draft') {
    fv = note || (r.action === 'auto' ? `机器直接发（${esc(d.label)}${r.form === 'text' ? '图文文章' : ''}）` : '存进草稿箱，群发你点');
    // 机器没发成：除了「再发一次」，也给自己传的路（去后台 + 传完登记），不用干等机器
    const admin = failed ? publicationUrl(d.admin || r.upload_url) : '';
    act = job && job.draft ? sentBtn : `${admin ? `<a class="btn small" href="${esc(admin)}" target="_blank" rel="noopener">去后台自己传 ↗</a>` : ''}<button class="btn small primary" type="button" data-pp-send="${linkKey}" ${PP.busy[linkKey] ? 'disabled' : ''}>${failed ? '再发一次' : r.action === 'auto' ? `发到 ${esc(d.label)}` : '存进草稿箱'}</button>${failed ? sentBtn : ''}`;
  } else {
    const folder = r.form === 'video' && PP_FOLDER.includes(key) ? `<button class="btn small" type="button" data-pp-folder="${tid}">打开上传文件夹</button>` : '';
    const cards = r.form === 'cards' && key === 'xiaohongshu' ? `<a class="btn small" href="/api/topics/${tid}/xhs.zip">下载图文卡</a>` : '';
    const upload = r.upload_url ? `<a class="btn small primary" href="${esc(r.upload_url)}" target="_blank" rel="noopener">${key === 'x' ? '去 X 发' : '去上传'} ↗</a>` : '';
    const what = r.form === 'video' ? (folder ? '视频、封面、文案.txt 在上传文件夹里' : '视频在成片里，文案复制去发') : r.form === 'cards' ? (cards ? '图文卡出好了，文案复制去发' : '图文你自己配，文案复制去发') : '文案复制去发';
    fv = note + what;
    act = `${folder}${cards}<button class="btn small" type="button" data-pp-copy="${tid}">复制文案</button>${upload}${key === 'douyin' && r.form === 'video' ? `<button class="btn small ghost" type="button" data-pp-dy="${tid}">已上传，去抖音核对</button>${PP.linkFor === linkKey ? sentBtn : `<button class="linklike" type="button" data-pp-sent="${linkKey}" title="抖音读不到作品时（核对一直找不到），直接登记">核对不了？直接登记</button>`}` : sentBtn}`;
  }
  return `<div class="pp-frow s-ready"><span class="fk">${esc(r.label)}</span><span class="fv">${fv}</span><span class="act">${act}</span></div>
    ${key === 'douyin' && r.form === 'video' && PP.match === tid ? `<div class="pp-match" id="ppMatch-${tid}"></div>` : ''}`;
}

/* 10/20 走查：B 站失败时页面上直接是「Page.wait_for_selector: Timeout 120000ms … locator(…)」。
   先说人话、说该做什么，原文收进「详情」 */
function ppFailLine(message, label, key) {
  const raw = String(message || '');
  const loginish = /timeout|locator|selector|wait_for|超时|login|登录|cookie|401|403/i.test(raw);
  const why = /timeout|locator|selector|wait_for|超时/i.test(raw) ? `机器在${label}的投稿页没走到填表那一步，多半是登录失效了`
    : loginish ? `${label}要重新登录`
    : `机器没发成`;
  const p = ((typeof S !== 'undefined' && S.platforms) || []).find((x) => x.key === key) || {};
  const relogin = loginish && p.can_login ? ` <button class="btn small primary" type="button" data-reconnect="${esc(key)}">重新登录${esc(label)}</button>` : '';
  return `<span class="bad">${esc(why)}。${relogin ? '先重新登录，登好了会自己再发一次；' : '可以再发一次，'}也可以去后台自己传，传完点「已上传，登记链接」。</span>${relogin}${raw ? `<details class="pp-fail-raw"><summary>详情</summary><small>${esc(raw)}</small></details>` : ''}`;
}

function ppItem(item, d) {
  const meta = [item.video ? `成片${item.video_mb ? ` ${item.video_mb >= 1024 ? `${(item.video_mb / 1024).toFixed(1)} GB` : `${item.video_mb} MB`}` : ''}` : '还没有成片', item.video_id ? '抖音已发' : (d.key === 'douyin' ? '' : '抖音还没发')].filter(Boolean).join(' · ');
  const c = item.copy || {};
  return `<article class="pp-item ${S.platformTopic === item.topic_id ? 'focus' : ''}" id="ppItem-${item.topic_id}">
    <div class="pp-item-h">${item.cover ? `<img class="pp-cover" src="${esc(item.cover)}" alt="">` : '<span class="pp-cover none"></span>'}<div><b>${esc(item.title)}</b><small>${esc(meta)}</small></div><button class="linklike" type="button" onclick="S.workId=${item.topic_id};go('work')">看这条</button></div>
    <div class="pp-forms"><span>这条在${esc(d.label)}发：<b>${item.forms.map((f) => (item.choices.find((x) => x.key === f) || {}).label || f).join(' + ')}</b></span><button class="linklike" type="button" onclick="S.packId=${item.topic_id};go('pack')">在「标题和封面」里改</button></div>
    <div class="pp-frows">${item.rows.map((r) => ppFormRow(item, r, d)).join('')}</div>
    <details class="pp-copyfold"><summary>文案<small>${esc((c.title || '').slice(0, 40))}${c.tags && c.tags.length ? ` · #${c.tags.slice(0, 3).join(' #')}` : ''}</small></summary><pre>${esc(ppCopyText(c))}</pre><button class="btn small" type="button" data-pp-copy="${item.topic_id}">复制文案</button><button class="linklike" type="button" onclick="S.packId=${item.topic_id};go('pack')">改标题、描述、话题</button></details>
  </article>`;
}

function ppPending(d) {
  const n = d.pending.length;
  return `<section class="panel pp-pend"><div class="panel-h"><h2>待发 <span class="num">${n || ''}</span></h2><small>在「发」里点「开始发」后，这条在这里也能发</small></div>
    ${n ? d.pending.map((it) => ppItem(it, d)).join('') : '<div class="empty me-moment"><b>手上没有要发的</b><span>一条内容定了标题，在「发」里点「开始发」，它就会出现在这里。</span></div>'}
  </section>`;
}

/* ---------- 这个平台：默认 ---------- */
function ppDefaults(d) {
  const df = d.defaults;
  const ticks = df.choices.map((c) => `<button type="button" class="tk ${df.forms.includes(c.key) ? 'on' : ''}" data-pp-def-form="${c.key}" ${df.forms.includes(c.key) && df.forms.length === 1 ? 'disabled title="至少留一种"' : ''}><i>${df.forms.includes(c.key) ? '✓' : ''}</i>${esc(c.label)}</button>`).join('');
  const order = df.order ? `第 ${df.order} 个发` : '—';
  const state = `<span class="chip-state ${d.state === 'linked' ? 'shipped' : ''}">${PP_STATE[d.state] || d.state}</span>`;
  return `<section class="panel pp-def"><div class="panel-h"><h2>这个平台</h2><small>默认发什么、账号、开关在这里改；常用话题在设置里改</small></div>
    <div class="pp-defs">
      <div class="def"><label>新内容默认发什么</label><div class="pp-ticks">${ticks}</div><small>只管以后新建的；已经在做的那条，在它的「标题和封面」里改</small></div>
      <div class="def"><label>常用话题</label><div class="v">${df.traffic_tags.length ? esc(df.traffic_tags.map((t) => '#' + t).join(' ')) : '还没填'}</div><small>每条都自动带上，排在内容话题前面 · <button type="button" class="linklike" onclick="goTagSettings()">去设置改</button></small></div>
      <div class="def"><label>顺序</label><div class="v">${order}</div><small>X 先发，抖音、小红书、视频号同时传，其余在后</small></div>
      <div class="def"><label>账号</label><div class="pp-acct"><input id="ppHandle" value="${esc(df.handle)}" placeholder="账号名" ${d.key === 'douyin' ? 'disabled' : ''}>${state}${d.admin ? `<a href="${esc(d.admin)}" target="_blank" rel="noopener">后台 ↗</a>` : ''}</div>${d.login_hint && d.state !== 'linked' ? `<small>${esc(d.login_hint)}</small>` : ''}</div>
      <div class="def"><label>开关</label><label class="pp-on"><input type="checkbox" id="ppOn" ${df.on ? 'checked' : ''} ${d.key === 'douyin' ? 'disabled' : ''}> ${df.on ? '开着：待发、汇总都算它' : '关着：不发、不算'}</label></div>
    </div>
  </section>`;
}

/* ---------- 数据 ---------- */
function ppBars(days) {
  const vals = days.map((x) => x.views);
  const top = Math.max(1, ...vals.filter((v) => v !== null && v !== undefined));
  return `<div class="pp-bars">${days.map((x, i) => `<i class="${i === days.length - 1 ? 'now' : ''} ${x.views === null || x.views === undefined ? 'none' : ''}" style="height:${x.views ? Math.max(4, Math.round((x.views / top) * 100)) : 2}%" title="${x.day.slice(5)} · ${x.views === null || x.views === undefined ? '没读' : fmt(x.views)}"></i>`).join('')}</div>
    <div class="pp-bars-x"><span>${days[0] ? days[0].day.slice(5) : ''}</span><span>今天</span></div>`;
}

function ppData(d) {
  const read = d.days.filter((x) => x.views !== null && x.views !== undefined && x.day !== d.days[d.days.length - 1].day);
  const avg = read.length ? Math.round(read.reduce((a, x) => a + x.views, 0) / read.length) : null;
  const t = d.today.views;
  const posts = d.posts.length ? `<div class="pp-rows">${d.posts.slice(0, 12).map((p) => `<div class="pp-row"><span class="t" title="${esc(p.title)}">${esc(cleanTitle(p.title))}<small>${day(p.published_at)}</small></span><span class="f">${(p.forms || []).map((f) => `<i>${({ video: '视频', text: '文字', cards: '图文', audio: '音频' })[f] || f}</i>`).join('')}</span><span class="n num">${p.views === null || p.views === undefined ? '—' : fmt(p.views)}</span>${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">↗</a>` : '<span></span>'}</div>`).join('')}</div>`
    : '<div class="empty small"><span>还没有发过的记录。</span></div>';
  const notes = d.notes.length ? `<ul class="pp-notes">${d.notes.map((n) => `<li><span class="when">${ppWhen(n.at)}</span><span>${n.title ? `<b>${esc(n.title)}</b>${n.form ? ` · ${esc(n.form)}` : ''}：` : ''}${esc(n.text)}</span><button class="linklike" type="button" data-pp-note-del="${n.id}">删</button></li>`).join('')}</ul>`
    : '<p class="pp-muted">还没记。哪条被删、哪条没流量，记下是哪条、哪种形式、平台说了什么。以后看哪些话在这里不能说。</p>';
  const add = PP.noteOpen ? `<div class="pp-note-add"><input id="ppNoteTitle" placeholder="哪条（可不填）" autocomplete="off"><textarea id="ppNoteText" rows="2" placeholder="发生了什么：被删 / 限流 / 审核不过，平台怎么说"></textarea><div><button class="btn small primary" type="button" id="ppNoteGo">记下</button><button class="btn small ghost" type="button" id="ppNoteNo">算了</button></div></div>` : '';
  return `<section class="panel pp-data"><div class="panel-h"><h2>${esc(d.label)}的数据</h2><small>${d.today.manual ? '这个平台读不到，每天去后台看一眼填在上面' : '每天早上读一次'}</small></div>
    <div class="pp-dgrid">
      <div class="pp-dleft"><div class="big"><b class="num">${t === null || t === undefined ? '—' : fmt(t)}</b><small>今天 · 尚未结束${avg !== null ? ` · 已读取完整日日均 ${fmt(avg)}` : ''}</small></div>${ppBars(d.days)}</div>
      <div class="pp-dright"><small class="pp-k">发过的 · 最近 ${Math.min(12, d.posts.length)} 条</small>${posts}</div>
    </div>
    <div class="pp-notes-h"><b>被删 · 被限流</b><button class="btn small" type="button" id="ppNoteOpen">${PP.noteOpen ? '收起' : '+ 记一条'}</button></div>
    ${add}${notes}
  </section>`;
}

/* ---------- 其他三个：B 站、YouTube、公众号（10/8 作者：主线下来的全部自动处理，这一页是一张汇总表） ----------
   B 站、YouTube 做好了机器自己发；公众号做好了自己存进草稿箱，他只去后台扫码群发，群发后草稿箱里没了，这里自己打 ✓。
   一行一条内容，三列三个平台；每格说清是发了、在发、等他群发、还差什么。要他动手的只剩：扫码登录、群发、没发成的「再发一次」。 */
const PP_TIME = (iso) => (iso ? new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }) : '');

function ppCell(c, g, row) {
  const published = c.state === 'sent' && c.presentation?.state === 'published';
  const form = published && c.label && row.cells[g.key].length > 1 ? `<span>${esc(c.label)}</span>` : '';
  const presentation = c.state === 'draft' && c.presentation ? { ...c.presentation, draft_link: null } : c.presentation;
  return `<div class="publication-others-cell">${form}${publicationFact(presentation)}${published ? '' : ppCellActions(c, g, row)}</div>`;
}
function ppCellActions(c, g, row) {
  const k = `${row.topic_id}|${c.form}|${g.key}`;
  const form = c.label && row.cells[g.key].length > 1 ? `<i>${esc(c.label)}</i> ` : '';
  const sentBtn = (label) => `<button class="btn small ghost" type="button" data-pp-sent3="${k}">${label}</button>`;
  const again = `<button class="btn small" type="button" data-pp-send3="${k}" ${PP.busy[k] ? 'disabled' : ''}>再发一次</button>`;
  switch (c.state) {
    case 'sent':
      return `<div class="pp-c s-sent">${form}<b>✓ 发了</b>${c.at ? ` <small>${ppWhen(c.at)}</small>` : ''}${c.url && !/mp\.weixin\.qq\.com\/?$/.test(c.url) ? ` <a href="${esc(c.url)}" target="_blank" rel="noopener">↗</a>` : ''}</div>`;
    case 'running':
      return `<div class="pp-c s-run">${form}<span class="spin"></span> ${g.key === 'wechat_mp' ? '在存草稿箱' : '在发'}</div>`;
    case 'draft':
      return `<div class="pp-c s-draft">${form}${c.presentation ? '' : '<b>在草稿箱</b>'}<div class="pp-draft-actions"><a class="btn small primary" href="${esc(publicationUrl(c.draft_link) || 'https://mp.weixin.qq.com/')}" target="_blank" rel="noopener">去群发 ↗</a>${sentBtn('登记已群发')}</div></div>`;
    case 'due':
      return `<div class="pp-c s-due">${form}${g.login ? '<b class="bad">等你扫码登录</b>' : `做好了，${g.key === 'wechat_mp' ? '马上自动存草稿箱' : '马上自动发'}`}</div>`;
    case 'retry':
      return `<div class="pp-c s-bad">${form}<b class="bad">没发成</b><small title="${esc(c.message || '')}">${esc((c.message || '').slice(0, 60))}</small><small>${PP_TIME(c.note)} 自动再试</small><span class="acts">${again}</span></div>`;
    case 'failed':
      return `<div class="pp-c s-bad">${form}<b class="bad">没发成，不再自动试了</b><small title="${esc(c.message || '')}">${esc((c.message || '').slice(0, 60))}</small><span class="acts">${again}</span></div>`;
    case 'unknown':
      return `<div class="pp-c s-bad">${form}<b class="bad">发的时候服务重启了，不知道发没发</b><small>去后台看一眼</small><span class="acts">${publicationUrl(g.admin) ? `<a class="btn small" href="${esc(publicationUrl(g.admin))}" target="_blank" rel="noopener">去后台核对 ↗</a>` : ''}${sentBtn('已核实发布，登记链接')}</span></div>`;
    case 'hand':
      return `<div class="pp-c">${form}要你自己传<span class="acts">${sentBtn('发了')}</span></div>`;
    default:
      return `<div class="pp-c s-wait">${form}等：${esc(c.note || '还没做好')}</div>`;
  }
}

function ppOthersHead(g, auto) {
  const login = g.login
    ? (g.login_action ? `<button class="btn small primary" type="button" data-pp-login="${g.key}">扫码登录${esc(g.label)}</button>` : '<span class="bad">要重新登录</span>')
    : g.state === 'manual' ? '' : `<small>${esc(PP_STATE[g.state] || g.state)}</small>`;
  const how = !auto ? '你来传' : g.key === 'wechat_mp' ? '自动存草稿箱 · 群发你扫码' : '做好了自动发';
  const off = g.defaults.on ? '' : ' · <span class="bad">关着，不发</span>';
  return `<div class="pp-oh">${ppPlat(g)}<div><b>${esc(g.label)}${g.admin ? ` <a href="${esc(g.admin)}" target="_blank" rel="noopener" title="打开${esc(g.label)}后台">后台 ↗</a>` : ''}</b><small>${how}${off}</small></div>${login && !/<small>/.test(login) ? `<span class="acts">${login}</span>` : ''}</div>`;
}

function ppOthers(d) {
  const rows = d.table.map((row) => `<tr><th><b>${esc(cleanTitle(row.title))}</b><small>${day(row.at)}</small></th>${d.groups.map((g) => `<td>${(row.cells[g.key] || []).map((c) => ppCell(c, g, row)).join('') || '<span class="pp-none">—</span>'}</td>`).join('')}</tr>`).join('');
  const table = d.table.length
    ? `<div class="pp-sum-wrap"><table class="pp-sum"><thead><tr><th>内容</th>${d.groups.map((g) => `<th>${ppOthersHead(g, d.auto)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`
    : '<div class="empty small"><span>最近没有要发、也没有发过的。一条内容定了标题，在「发」里点「开始发」，这里就会出现。</span></div>';
  const lead = d.auto
    ? 'B 站、YouTube 做好了自动发；公众号自动存草稿，你扫码群发。'
    : 'B 站、YouTube、公众号：文案和文件备好，你去传，传完点「发了」。';
  return `<header class="page-h pp-h"><div class="pp-id"><div><button class="linklike stage-eyebrow" type="button" onclick="go('plats')">盘 · 各平台 ‹</button><h1>其他三个</h1><p>${lead}</p></div></div></header>
    <section class="panel pp-others">${table}</section>`;
}

/* 10/19 作者：左栏 B 站、YouTube 各一行，「其他三个」不在左栏了；它的总表（扫码登录、公众号群发）从这两页进 */
const ppOthersLink = (d) => (['bilibili', 'youtube'].includes(d.key) && featureOn('others')
  ? '<p class="pp-others-link"><a href="#platform/others">B 站 · YouTube · 公众号自动发总表（扫码登录、群发在这里）→</a></p>' : '');

/* ---------- 抖音：发完对上是哪条作品（数据、评论、补发表都靠它） ---------- */
async function ppDouyinMatch(box, tid) {
  if (!box) return;
  box.innerHTML = '<p class="pp-muted"><span class="spin"></span> 正在找你刚发的那条…</p>';
  let d;
  try { d = await api(`/api/topics/${tid}/publish`); } catch (err) { box.innerHTML = `<p class="pp-muted bad">${esc(err.message)}</p>`; return; }
  if (!d.account) { box.innerHTML = '<p class="pp-muted">还没设置自己的抖音号，先去设置里加。</p>'; return; }
  if (!d.suggestions.length && (d.account.syncing || !box.dataset.synced)) {
    if (!d.account.syncing) {
      box.dataset.synced = '1';
      try { await api(`/api/accounts/${d.account.id}/sync`, { method: 'POST' }); } catch (err) { toast(err.message); }
    }
    box.innerHTML = '<p class="pp-muted"><span class="spin"></span> 去抖音上找你刚发的那条，半分钟左右…</p>';
    setTimeout(() => { if (box.isConnected) ppDouyinMatch(box, tid); }, 5000);
    return;
  }
  const row = (v, primary) => `<div class="pp-dyv"><div><b>${esc(cleanTitle(v.title))}</b><small>${day(v.published_at)} · ${fmt(v.likes)} 赞</small></div><button class="btn small ${primary ? 'primary' : ''}" type="button" data-pp-dyv="${esc(v.video_id)}">就是这条</button></div>`;
  const list = d.suggestions.length ? d.suggestions.map((v) => row(v, true)).join('') : d.recent.slice(0, 5).map((v) => row(v, false)).join('');
  box.innerHTML = `<p class="pp-muted">${d.suggestions.length ? '是这条吗？' : `刚去抖音看过，还没找到标题相近的新作品。刚发的有时要等几分钟才出现，<button class="linklike" type="button" id="ppDySync">再找一次</button>${d.recent.length ? '；标题改过的话，在下面这几条里点。' : '。'}`}</p>${list}`;
  $$('[data-pp-dyv]', box).forEach((b) => (b.onclick = async () => {
    try { await api(`/api/topics/${tid}/publish`, { method: 'PUT', body: { video_id: b.dataset.ppDyv } }); } catch (err) { toast(err.message); return; }
    PP.match = null; toast('对上了');
    if (window.invalidatePublish) window.invalidatePublish();
    if (window.refreshTodayBadge) window.refreshTodayBadge();
    ppReload();
  }));
  const sync = $('#ppDySync', box);
  if (sync) sync.onclick = () => { delete box.dataset.synced; ppDouyinMatch(box, tid); };
}

/* ---------- 绑定 ---------- */
async function ppReload() {
  // 「发」页（标题和封面下面那张表）也用这套按钮：在那边点的，重画那边
  if (S.view === 'pack' && window.invalidateFa) { window.invalidateFa(); if (window.paintFa) window.paintFa(); if (window.refreshPlatformNav) window.refreshPlatformNav(); return; }
  try { await ppLoad(true); } catch (err) { toast(err.message); }
  const b = $('#platformBody'); if (b) b.dataset.sig = '';
  renderView();
  if (window.refreshPlatformNav) window.refreshPlatformNav();
}

function ppBind(root, d) {
  const key = d.key;
  const put = async (path, body, msg) => { try { await api(path, { method: 'PUT', body }); if (msg) toast(msg); } catch (err) { toast(err.message); } ppReload(); };
  const post = async (path, body, msg) => { try { const r = await api(path, { method: 'POST', body }); if (msg) toast(msg); return r; } catch (err) { toast(err.message); return null; } };
  $$('[data-pp-def-form]', root).forEach((b) => (b.onclick = () => {
    const forms = d.defaults.forms.includes(b.dataset.ppDefForm) ? d.defaults.forms.filter((f) => f !== b.dataset.ppDefForm) : [...d.defaults.forms, b.dataset.ppDefForm];
    if (!forms.length) return;
    put(`/api/platform/${key}/settings`, { forms }, '以后新建的按这个来');
  }));
  const handle = $('#ppHandle', root);
  if (handle) handle.onchange = () => put(`/api/platform/${key}/settings`, { handle: handle.value }, '记下了');
  const on = $('#ppOn', root);
  if (on) on.onchange = () => put(`/api/platform/${key}/settings`, { on: on.checked });
  const tin = $('#ppTodayIn', root);
  if (tin) tin.onchange = () => put('/api/reach', { day: new Date().toLocaleDateString('sv-SE'), platform: key, views: tin.value === '' ? null : Number(tin.value) }, '记下了');
  $$('[data-pp-copy]', root).forEach((b) => (b.onclick = () => {
    const item = d.pending.find((it) => String(it.topic_id) === b.dataset.ppCopy) || (d.groups || []).flatMap((g) => g.pending).find((it) => String(it.topic_id) === b.dataset.ppCopy);
    const text = ppCopyText((item || {}).copy || {});
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => toast('复制了：标题、描述、话题'), () => toast('复制不了，手动选中复制')); else toast('这个浏览器不让复制，手动选中');
  }));
  $$('[data-pp-folder]', root).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    const r = await post(`/api/topics/${b.dataset.ppFolder}/upload-folder`, { platform: key, open: true });
    if (r) toast(r.missing && r.missing.length ? `文件夹开了，缺：${r.missing.join('、')}` : '文件夹打开了：视频、封面、文案.txt 都在里面');
    b.disabled = false;
  }));
  $$('[data-pp-sent]', root).forEach((b) => (b.onclick = () => { PP.linkFor = b.dataset.ppSent; root.dataset.sig = ''; renderView(); setTimeout(() => { const i = $('#ppLinkIn'); if (i) i.focus(); }, 50); }));
  $$('[data-pp-sent-no]', root).forEach((b) => (b.onclick = () => { PP.linkFor = null; root.dataset.sig = ''; renderView(); }));
  $$('[data-pp-sent-go]', root).forEach((b) => (b.onclick = async () => {
    const [tid, form] = b.dataset.ppSentGo.split('|');
    const url = ($('#ppLinkIn', root) || {}).value || '';
    const day = ($('#ppDayIn', root) || {}).value || '';
    const r = await post(`/api/topics/${tid}/platform/${key}/sent`, { form, url, ...(day ? { day } : {}) }, '记下了：发了');
    if (r) { PP.linkFor = null; ppReload(); if (window.refreshTodayBadge) window.refreshTodayBadge(); }
  }));
  $$('[data-pp-undo]', root).forEach((b) => (b.onclick = async () => {
    const [tid, form] = b.dataset.ppUndo.split('|');
    if (await post(`/api/topics/${tid}/platform/${key}/sent`, { form, undo: true }, '撤回了')) ppReload();
  }));
  $$('[data-pp-send]', root).forEach((b) => (b.onclick = async () => {
    const [tid, form] = b.dataset.ppSend.split('|');
    PP.busy[b.dataset.ppSend] = true; b.disabled = true;
    const r = await post(`/api/topics/${tid}/platform/${key}/send`, { form });
    PP.busy[b.dataset.ppSend] = false;
    if (r && r.state === 'login') toast(r.message || '要先登录');
    else if (r) toast('机器在发，发完这里会打 ✓');
    ppReload();
  }));
  // 10/9 作者：改了立刻变——格子先变成「已发布 · 刚刚」，接口回来按真实结果重画；失败了重画就变回去
  const optimistic = (b, html) => { const cell = b.closest('.publication-others-cell'); if (!cell) return; cell.innerHTML = html; cell.classList.remove('just-changed'); void cell.offsetWidth; cell.classList.add('just-changed'); };
  $$('[data-pp-sent3]', root).forEach((b) => (b.onclick = async () => {
    const [tid, form, pk] = b.dataset.ppSent3.split('|');
    optimistic(b, '<div class="publication-fact"><span class="publication-status state-published">已发布</span><small>刚刚</small></div>');
    await post(`/api/topics/${tid}/platform/${pk}/sent`, { form }, '记下了：发了');
    ppReload();
  }));
  $$('[data-pp-send3]', root).forEach((b) => (b.onclick = async () => {
    const [tid, form, pk] = b.dataset.ppSend3.split('|');
    PP.busy[b.dataset.ppSend3] = true; b.disabled = true;
    optimistic(b, '<div class="publication-fact"><span class="publication-status state-running">发布中</span><small>刚刚点的</small></div>');
    const r = await post(`/api/topics/${tid}/platform/${pk}/send`, { form });
    PP.busy[b.dataset.ppSend3] = false;
    if (r && r.state === 'login') toast(r.message || '要先登录');
    else if (r) toast('机器在发，发完这里会打 ✓');
    ppReload();
  }));
  $$('[data-pp-login]', root).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    if (await post(`/api/platforms/${b.dataset.ppLogin}/login`, {}, '登录窗口开了：扫码登好，这里会自己接着发')) setTimeout(ppReload, 20000);
  }));
  $$('[data-pp-dy]', root).forEach((b) => (b.onclick = async () => {
    const tid = Number(b.dataset.ppDy);
    PP.match = tid;
    await post('/api/today/check-shipped', {}, null);
    root.dataset.sig = ''; renderView();  // 画完那一下由 render 去填核对框；这里画还没完，框还不在
  }));
  const nopen = $('#ppNoteOpen', root); if (nopen) nopen.onclick = () => { PP.noteOpen = !PP.noteOpen; root.dataset.sig = ''; renderView(); if (PP.noteOpen) setTimeout(() => { const t = $('#ppNoteText'); if (t) t.focus(); }, 50); };
  const nno = $('#ppNoteNo', root); if (nno) nno.onclick = () => { PP.noteOpen = false; root.dataset.sig = ''; renderView(); };
  const ngo = $('#ppNoteGo', root); if (ngo) ngo.onclick = async () => {
    const r = await post(`/api/platform/${key}/notes`, { text: ($('#ppNoteText', root) || {}).value || '', title: ($('#ppNoteTitle', root) || {}).value || '' }, '记下了');
    if (r) { PP.noteOpen = false; ppReload(); }
  };
  $$('[data-pp-note-del]', root).forEach((b) => (b.onclick = async () => {
    try { await api(`/api/platform/${key}/notes/${b.dataset.ppNoteDel}`, { method: 'DELETE' }); } catch (err) { toast(err.message); }
    ppReload();
  }));
}

window.VIEWS.platform = {
  async render() {
    const root = $('#platformBody');
    if (!root || S.view !== 'platform') return;
    const key = S.platformKey, request = ++PP.renderRequest;
    const valid = () => S.view === 'platform' && S.platformKey === key && request === PP.renderRequest;
    if (PP.key !== S.platformKey) { PP.data = null; PP.linkFor = null; PP.match = null; PP.noteOpen = false; }
    if (!PP.data) root.innerHTML = window.skeletonPage ? window.skeletonPage({ cards: 0, rows: 4 }) : '';
    let d;
    try { d = await ppLoad(false); } catch (err) { if (valid()) { root.innerHTML = `<div class="panel empty" role="alert"><b>${esc(err.message)}</b><button class="btn" type="button" data-pp-retry>重试</button></div>`; $('[data-pp-retry]', root).onclick = () => renderView(); } return; }
    if (!valid()) return;
    if (root.contains(document.activeElement) && document.activeElement.matches('input, textarea')) return;
    const sig = JSON.stringify([d.key, PP.at, PP.linkFor, PP.match, PP.noteOpen, S.platformTopic]);
    if (root.dataset.sig === sig) return;
    root.dataset.sig = sig;
    if (d.key === 'others') {
      root.innerHTML = publicationWarnings(d.publication_warnings) + ppOthers(d);
    } else {
      // 10/19 作者：「X 的页面跟小红书、抖音、视频号长得一模一样」——页头、待发、数据、这个平台；
      // X 自己的那段（每天发多少、今天的短帖 · 引用 · 回复、长帖长文）从页面上拿掉了。X 热榜 10/9 起在选题页的 tab 里
      root.innerHTML = `${ppHeader(d)}${ppOthersLink(d)}${publicationWarnings(d.publication_warnings)}<div class="publication-sections">${ppPending(d)}${ppData(d)}${ppDefaults(d)}</div>`;
    }
    ppBind(root, d);
    if (PP.match) ppDouyinMatch($(`#ppMatch-${PP.match}`), PP.match);  // 每次重画核对框都是空的，重新填
    if (S.platformTopic) { const el = $(`#ppItem-${S.platformTopic}`); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    clearTimeout(PP.poll);
    const running = (d.pending || []).concat((d.groups || []).flatMap((g) => g.pending)).some((it) => it.rows.some((r) => r.job && r.job.state === 'running'));
    // 其他三个：做好了等机器自己发的，后台两分钟一轮，这里半分钟看一次
    const queued = (d.table || []).some((row) => Object.values(row.cells).some((cs) => cs.some((c) => c.state === 'due')));
    if (running || queued) PP.poll = setTimeout(() => { if (S.view === 'platform') ppReload(); }, running ? 3000 : 30000);
  },
};

/* 10/20「盘 · 各平台」：平台不再在左栏各占一行。这里一个平台一行：连没连上、还有几格没发，点进去是那个平台的页（数据、账号、默认发什么）。 */
window.VIEWS.plats = {
  async render() {
    const root = $('#platsBody');
    let counts = {};
    try { counts = await api('/api/platform/counts'); } catch (_) { /* 数不到就不写 */ }
    if (S.view !== 'plats') return;
    const keys = ['douyin', 'channels', 'xiaohongshu', 'x', 'youtube', 'bilibili'].filter((k) => !(window.platformOff && window.platformOff(k)) && (!['youtube', 'bilibili'].includes(k) || featureOn('others')));
    const meta = Object.fromEntries((S.platforms || []).map((p) => [p.key, p]));
    root.innerHTML = `<section class="panel plats-list">${keys.map((k) => {
      const p = meta[k] || { label: PP_LABEL[k] || k, mark: (PP_LABEL[k] || k)[0] };
      const st = p.alert ? `<span class="bad">${esc(p.alert)}</span>` : p.state === 'stale' || p.state === 'setup' ? `<span class="bad">${esc(p.note || PP_STATE[p.state])}</span>` : esc(PP_STATE[p.state] || '');
      if (p.can_login && p.state === 'stale') return `<div class="plats-row">${ppPlat({ ...p, label: p.label || PP_LABEL[k] })}<b>${esc(p.label || PP_LABEL[k])}</b><small>${st}</small><span class="spacer"></span><button class="btn small primary" type="button" data-reconnect="${k}">重新登录</button><button class="linklike" type="button" data-plats="${k}">打开 ›</button></div>`;
      return `<button type="button" class="plats-row" data-plats="${k}">${ppPlat({ ...p, label: p.label || PP_LABEL[k] })}<b>${esc(p.label || PP_LABEL[k])}</b><small>${st}</small><span class="spacer"></span><small>${counts[k] ? `${counts[k]} 格没发` : ''}</small><span aria-hidden="true">›</span></button>`;
    }).join('')}</section>`;
    $$('[data-plats]', root).forEach((b) => (b.onclick = () => window.goPlatform(b.dataset.plats)));
  },
};
