'use strict';
/* 今天：最上面是月历（10/1 起，原来是周历）（9/30 作者：「plan not just for one day, I can plan for the whole week」「每天扣了多少分，
 * I'm not even keeping count」），下面是 ABC 几件事（逻辑在 driver.py）。
 * 周历：过去的日子看算分的几项做没做到、减几分、发了哪条；今天和以后排哪天拍哪条、加不算分的事。排哪条只由他定。
 * 做完的行收成一行；每行原来那串 7 天小圆点拿掉了，周历里有。
 * A 读日报（9/30）；B 出摊：抖音、视频号、小红书发视频，X、公众号发文字；C 回私信；D X 互动，回 20 条。
 * E「整条补发」10/1 拿掉了：补发全走补发工作台（backfilldesk.js），他看当天的情绪自己挑格子。
 * 没做到当天各减 1 分，左边栏一直显示。触达是结果，不在这一页看（在「已发出」）。
 * 9/29 作者：「你只需要告诉我，我今天要做的 ABC 三件事就好了……感觉今天这个页面太散了。」
 * 拍什么他定：「接下来要拍的」收在 A 里面；只有他点「我今天不知道拍什么」才建议。
 * 10/5 作者 收窄：「今天我要做的只有一件事儿，就是出摊儿。」页面从上到下：两条结果线（全网粉丝、每天触达）和两个预期数
 * →月历（只看出摊了没有：昨天到底做没做）→出摊。读日报留一行链接、不算分；回私信、X 互动、页面里的 Wendy 卡片拿掉（她在右边）。
 * 10/19 作者 拿掉排期：月历上只在第一个空着的日子灰字写正在做的那一条（driver.queue_days 只拿到它），以后的日子空着。
 * 开始做只有一个入口：选题 →「我的选题」点「做这条」。
 * 10/5 作者：「这个第一页的出摊就没有用了……第一页就保留数据和 calendar 还有 Wendy 的对话框就好了。」
 * 这一页只剩两条结果线 + 月历（Wendy 在右边）。出摊行、先处理、读日报、补发入口、杂事都拿掉：
 * 拍哪条在 02 排，机器卡住了 Wendy 会说（wendy.py 读 /api/today 的 first），补发从「已发出」的全平台追踪进。
 * 10/9 作者（变现流程板）：Wendy 管变现。钱那一格从「本月咨询几单」长成本月收入 / 目标 / 预期月底 + 记一笔；
 * 10/11 起变现动作不再算分，「今天这一条」下面改为 Wendy 每日复盘。 */
window.VIEWS = window.VIEWS || {};

const TD = { data: null, month: null, monthStart: null, sel: null, kpi: null, home: null, review: null, poll: null };

async function loadToday() { TD.data = await api('/api/today'); return TD.data; }
window.refreshTodayBadge = async () => { try { await loadToday(); } catch (_) { /* ignore */ } paintTodayBadge(); };

function paintTodayBadge() {
  const b = $('#navToday');
  if (!b || !TD.data) return;
  const n = TD.data.week.demerits;  // 本周（周一到周日）减的分
  b.textContent = n ? `减 ${n}` : '';
  b.classList.toggle('bad', !!n);
}

const DOW = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
function dayTitle(key) {
  const d = new Date(key + 'T00:00:00');
  return `${d.getMonth() + 1}月${d.getDate()}日 ${DOW[d.getDay()]}`;
}

/* ---- Wendy：最上面那张卡片。「现在做这一件」是工作台直接算的；她说的话是微信那边定时写的，
 *      加上你在这里回她、她在这里答你的。三小时没动静她去微信找你（规则在 wendy.py）。 ---- */
function wdWhen(iso) {
  const d = new Date(iso), now = new Date();
  const day = (x) => `${x.getFullYear()}-${x.getMonth()}-${x.getDate()}`;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  const hm = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${day(d) === day(now) ? '今天' : day(d) === day(y) ? '昨天' : `${d.getMonth() + 1}/${d.getDate()}`} ${hm}`;
}

function wdMsg(m, clip) {
  const where = m.who === 'park' ? '你' : m.source === 'desk' ? 'Wendy' : `Wendy · 微信${m.label ? ' · ' + esc(m.label) : ''}`;
  return `<div class="wd-m ${m.who === 'park' ? 'me' : ''} ${clip ? 'clip' : ''}"><small>${where} · ${wdWhen(m.at)}</small><p>${esc(m.text)}</p></div>`;
}

/* ---- 最上面：两条结果线 + 两个预期数（10/5 作者：「I can see the results, I can see it happen」）----
 * 全网粉丝：每次读数一个点；预期月底粉丝 = 现在 + 最近两周日均涨粉 × 到月底还剩几天。
 * 每天触达：只画过完的日子（今天早上的半截数天天像跳水）；昨天比前一天掉了就标红。
 * 预期本月触达 = 这个月过完的日子加起来 + 最近 7 天日均 × 还剩几天。平均观看、收藏、点赞这些不放（作者：那是平台给的，不是结果）。 */
function lineChart(points, { label, ariaLabel }) {
  const W = 520, H = 120, L = 6, R = 6, T = 14, B = 20;
  if (!points.length) return '';
  const xs = points.map((p) => new Date(p.at || p.day + 'T00:00:00').getTime());
  const x0 = Math.min(...xs), x1 = Math.max(...xs, x0 + (points[0].at ? 36e5 : 864e5));
  const vals = points.map((p) => p.v);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi === lo) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.15; lo -= pad; hi += pad;
  const X = (t) => L + ((t - x0) / (x1 - x0)) * (W - L - R);
  const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const pts = points.map((p, i) => [X(xs[i]), Y(p.v)]);
  const path = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join('');
  const dots = pts.map(([x, y], i) => `<circle class="rl-dot ${i === pts.length - 1 ? 'last' : ''}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${i === pts.length - 1 ? 4 : 3}"/>
    <rect class="hit" x="${(x - 14).toFixed(1)}" y="0" width="28" height="${H}" data-tip="${esc(points[i].tip)}"/>`).join('');
  const first = points[0].day, last = points[points.length - 1].day;
  return `<svg viewBox="0 0 ${W} ${H}" class="rl-svg" role="img" aria-label="${esc(ariaLabel)}">
    <line class="rl-base" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/>
    <path class="rl-line" d="${path}"/>${dots}
    <text class="axis" x="${L}" y="${H - 5}">${points[0].axisLabel ? esc(points[0].axisLabel) : md(first)}</text><text class="axis" x="${W - R}" y="${H - 5}" text-anchor="end">${points[points.length - 1].axisLabel ? esc(points[points.length - 1].axisLabel) : md(last)}</text>
    <text class="axis" x="${L}" y="10">${esc(label)}</text></svg>`;
}

/* 钱这一层（10/5）：粉丝、触达都在上游，钱是结果。10/9 起是本月收入：一笔一笔记在账本里（先手动，以后接 Stripe） */
/* 10/11 晚 作者：「我要看 whether you are meeting your KPI」——有目标的数旁边直接写达标还是落后 */
function kpiPill(now, due) {
  if (now == null || due == null) return '';
  return now >= due ? '<i class="kpi-pill ok">达标</i>' : '<i class="kpi-pill bad">落后</i>';
}
const yuan = (n) => `¥${Number(n || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
/* 收了钱记一笔：收在「战况」本月收入那张卡里（10/13 作者：战况就是首页，钱的事都在那一张卡） */
function moneyBook(h) {
  if (!h || !h.money || !featureOn('consults')) return '';
  const m = h.money, c = h.consults || {};
  const by = m.by_source.map((x) => `${esc(x.label)} ${yuan(x.amount)}`).join(' · ');
  const opts = m.sources.map((x) => `<option value="${esc(x.key)}">${esc(x.label)}</option>`).join('');
  const rows = m.rows.map((r) => `<li><span class="num">${md(r.day)}</span> ${yuan(r.amount)} · ${esc((m.sources.find((x) => x.key === r.source) || {}).label || r.source)}${r.note ? ` · ${esc(r.note)}` : ''}
      <button type="button" class="linklike" data-mn-del="${r.id}" aria-label="删掉这一笔">删掉</button></li>`).join('');
  return `<details class="rs-manual kpi-book" id="mnBook"><summary>收了钱，记一笔 <small>${by || `${m.month} 月还没记过一笔`}${c.count != null ? ` · 本月咨询 ${c.count} 单` : ''}</small></summary>
      <form class="rs-fl" id="mnAdd"><label>金额（元）<input class="num" type="number" min="0.01" step="0.01" inputmode="decimal" name="amount" required></label>
        <label>来源 <select name="source">${opts}</select></label>
        <label>哪天 <input type="date" name="day" value="${esc(TD.data ? TD.data.day : '')}"></label>
        <label>备注 <input name="note" maxlength="200" placeholder="谁付的、买了什么"></label>
        <button class="btn small" type="submit">记下</button></form>
      ${rows ? `<ul class="mn-list">${rows}</ul>` : ''}</details>`;
}

/* 收入点：每 3 天问一次（10/12 作者：「不用每天，每 3 天来催我一次，看看我有没有新的收入点」）。写一句就算答了，没有也点一下 */
function moneyAsk(b) {
  const m = b && b.money;
  if (!m || !m.ask) return '';
  return `<div class="ks-ask"><p><b>Wendy 问你</b>这 3 天有没有新的收入点？谁可能付钱、能卖什么、谁来问过价。</p>
    <form class="td-add" id="ksAsk"><input name="note" maxlength="200" placeholder="一句话：比如「张三问了工具价格」" autocomplete="off"><button class="btn small primary" type="submit">记下</button><button class="btn small" type="button" data-ks-none>这 3 天没有</button></form></div>`;
}

/* Wendy 的复盘正文（10/13 作者：一整段读不懂。她是负责人，复盘就是早会：一句结论、昨天三个数、你错在哪、今天你做、她在等什么）。
 * 昨天三个数是代码算的（rv.facts）。旧的一段话照原样显示。 */
function verdictBody(v, rv) {
  const say = (html) => `<p class="rv-verdict" role="status">${html}</p>`;
  if (v.state === 'writing') return say('<span class="spin"></span> Wendy 在写今天的复盘…');
  if (v.state === 'waiting') return say(reviewWaiting(v));
  if (v.error) return say(`今天的复盘没写成：${esc(v.error)}`);
  const facts = (rv.facts || []).length ? `<dl class="rv-facts">${rv.facts.map(([k, t]) => `<div><dt>${esc(k)}</dt><dd>${esc(t)}</dd></div>`).join('')}</dl>` : '';
  if (!v.headline) return facts + say(v.text ? esc(v.text) : '今天的复盘还没写好。');
  const list = (title, items, tag) => (items || []).length ? `<div class="rv-sec"><h3>${title}</h3><${tag} class="rv-do">${items.map((t) => `<li>${esc(t)}</li>`).join('')}</${tag}></div>` : '';
  return `<div class="rv-top"><p class="rv-head" role="status">${esc(v.headline)}</p>${facts}
      ${v.wrong ? `<p class="rv-wrong"><b>你做错了</b>${esc(v.wrong)}</p>` : ''}</div>
    ${list('今天你做', v.today, 'ol')}${list('我在等', v.wait, 'ul')}`;
}

/* ---- Wendy 复盘（10/11 晚 作者 重做）----
 * 「这些是需要的数据吗」：昨天的几格数和最上面重复，拿掉；X 的表放 X 页，这里不放；
 * 只留 Wendy 那段结论（10/19 抖音最近几条的对账拿掉，和「抖音作品分析」重复）、
 * 在验证的猜测一行一个（点开看依据）、等他拍板的提案。 */
/* 还没开始写：每天 9:35 以后才写（等早上同步完昨天的数），一次大约 5 分钟；等不及就点「重写」 */
const reviewWaiting = (v) => `今天的复盘还没开始写：每天 ${esc(v.from || '09:35')} 以后写（等早上把昨天的数同步完），大约 5 分钟。想现在就看，点右上角「重写」。`;

function dailyReviewBlock(rv) {
  if (!rv) return '<section class="rv"><div class="fc-h"><span>Wendy 的复盘</span></div><p class="td-note">复盘暂时没读到，稍后刷新再试。</p></section>';
  const v = rv.verdict || {};
  const at = v.at ? new Date(v.at).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }) : '';
  const guesses = rv.hypotheses || [], records = rv.experiments || [];
  const matches = (e, h) => (e.hypothesis || '').split(/[、,，\s]+/).includes(h.id);
  const isDue = (e) => !e.conclusion && (rv.due || []).some((d) => d.title === e.title && d.check_on === e.check_on && d.hypothesis === e.hypothesis);
  const line = (e) => [e.sent && e.sent !== '待拍' ? e.sent : '', e.title, e.check_on ? `${e.check_on} 对账` : ''].filter(Boolean).join(' · ');
  const guessRows = guesses.map((h) => {
    const related = records.filter((e) => matches(e, h)), pending = related.filter((e) => !e.conclusion);
    const due = pending.some(isDue);
    const status = due ? '该对账了' : pending.length ? '在验证' : related.map((e) => e.conclusion).filter(Boolean).join('；') || '还没排';
    return `<li><details><summary><i class="rv-id">${esc(h.id)}</i><span>${esc(h.text)}</span><span class="pill ${due ? 'mid' : 'low'}">${esc(status)}</span></summary>
      <div class="rv-more"><p>${esc([h.confidence, h.basis].filter(Boolean).join(' · '))}</p>${related.map((e) => `<p>${esc(line(e))}</p>`).join('')}</div></details></li>`;
  }).join('');
  const dueN = guesses.filter((h) => records.some((e) => matches(e, h) && isDue(e))).length;
  const props = (rv.proposals || []).filter((p) => p.status === '待定').map((p) => `<li><div><b>${esc(p.idea)}</b><small>${esc([p.why, p.time, p.days ? `试 ${p.days} 天` : ''].filter(Boolean).join(' · '))}</small></div>
    <div class="btns"><button type="button" class="btn primary small" data-rv-proposal="${p.id}" data-rv-decision="try">试</button><button type="button" class="btn small" data-rv-proposal="${p.id}" data-rv-decision="skip">不试</button></div></li>`).join('');
  return `<section class="rv">
    <div class="fc-h"><span>Wendy 的复盘</span><small>${at ? `${esc(at)} 写好 · ` : ''}<button type="button" class="linklike" data-rv-redo>重写</button></small></div>
    ${verdictBody(v, rv)}
    ${props ? `<div class="rv-sec"><h3>等你拍板</h3><ul class="rv-props">${props}</ul></div>` : ''}
    ${guessRows ? `<details class="rv-sec rv-fold"${dueN ? ' open' : ''}><summary><h3>在验证的猜测 <small>${guesses.length} 个${dueN ? ` · ${dueN} 个该对账了` : ' · 没有该对账的'}</small></h3></summary><ul class="rv-guess">${guessRows}</ul></details>` : ''}
  </section>`;
}

function bindReview(body, again) {
  $$('[data-rv-redo]', body).forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try { await api('/api/today/review/verdict', { method: 'POST' }); again(); }
    catch (err) { toast(err.message); }
    finally { b.disabled = false; }
  }));
  $$('[data-rv-proposal]', body).forEach((b) => (b.onclick = async () => {
    const controls = $$(`[data-rv-proposal="${b.dataset.rvProposal}"]`, body);
    controls.forEach((button) => { button.disabled = true; });
    try { TD.review = await api('/api/today/review/proposal', { method: 'POST', body: { index: Number(b.dataset.rvProposal), decision: b.dataset.rvDecision } }); again(); }
    catch (err) { toast(err.message); controls.forEach((button) => { button.disabled = false; }); }
  }));
}

function bindMoneyAsk(body) {
  const ask = $('#ksAsk', body);
  const send = (note) => tdAct(async () => { await api('/api/today/money', { method: 'POST', body: { note } }); toast('记下了'); });
  if (ask) ask.onsubmit = (e) => { e.preventDefault(); const note = ask.note.value.trim(); if (!note) { toast('写一句，或者点「这 3 天没有」'); return; } send(note); };
  const none = $('[data-ks-none]', body);
  if (none) none.onclick = () => send('这 3 天没有新的收入点');
}

function bindMoney(body) {
  const add = $('#mnAdd', body);
  if (add) add.onsubmit = (e) => {
    e.preventDefault();
    const f = new FormData(add);
    TD.bookOpen = true;
    tdAct(() => api('/api/revenue', { method: 'POST', body: { amount: Number(f.get('amount')), source: f.get('source'), day: f.get('day') || null, note: f.get('note') || '' } }));
  };
  $$('[data-mn-del]', body).forEach((b) => (b.onclick = () => { TD.bookOpen = true; tdAct(() => api(`/api/revenue/${b.dataset.mnDel}`, { method: 'DELETE' })); }));
  const book = $('#mnBook', body);
  if (book && TD.bookOpen) book.open = true;

}

/* ---- 周历 ---- */
// 10/5 作者：月历只看一件事——出摊了没有。读日报、回私信、X 互动不再算分，格子里不画。10/9 加回变现动作
const KPI_MARK = [['ship', '摊', '出摊'], ['mn', '钱', '变现动作']];
const md = (key) => `${Number(key.slice(5, 7))}/${Number(key.slice(8))}`;
const dow = (key) => DOW[new Date(key + 'T00:00:00').getDay()];

function streakText(s) {
  if (!s || !s.days) return '';
  return s.kind === 'ok' ? `连续出摊 <b class="ok">${s.days}</b> 天` : `连续 <b>${s.days}</b> 天没出摊`;
}

/* 平台的名字（10/5 作者：小图标颜色太杂，这里只写字） */
function platName(key) {
  const p = ((typeof S !== 'undefined' && S.platforms) || []).find((x) => x.key === key) || {};
  return p.label || key;
}

/* 那天发出去的：同一条内容只写一次标题，后面跟发到的平台图标（10/1 作者：「不要占这么大的 space」） */
function sentByTitle(sent) {
  const groups = [];
  for (const x of sent || []) {
    let g = groups.find((y) => y.title === x.title);
    if (!g) groups.push((g = { title: x.title, keys: [] }));
    if (!g.keys.includes(x.platform)) g.keys.push(x.platform);
  }
  return groups.map((g) => `<p class="wk-sent"><span class="t" title="${esc(g.title)}">《${esc(g.title)}》</span><span class="ic">${g.keys.map((k) => esc(platName(k))).join(' · ')}</span></p>`).join('');
}
const headline = (t) => String(t || '').split(/\s+/)[0].slice(0, 28);

/* 月历的一格：过去的日子——四项做没做到、减几分、发了什么、发到了哪些平台；以后的日子——排了拍哪条 */
function monthCell(c) {
  // 右上角：今天 / ✓ 出摊了 / ✗ 没出摊。颜色只留这一种意思：绿 = 出摊了，红 = 没出摊
  const score = c.state === 'today' ? '<span class="wk-score now">今天</span>' : c.state === 'past' && c.ship === 'ok' ? '<span class="wk-score ok" title="出摊了">✓</span>'
    : c.state === 'past' && c.ship === 'miss' ? `<span class="wk-score bad" title="没出摊${featureOn('score') ? '，减 1 分' : ''}">✗</span>` : '';
  // 10/5 作者：平台小图标颜色太杂。格子里只写发到了几个平台（灰字），点开那天再看是哪几个
  const where = [...new Set(c.sent.map((x) => x.platform))];
  const lines = [
    ...c.shipped.slice(0, 1).map((t) => `<span class="wk-l out" title="${esc(c.shipped.join('；'))}">${esc(headline(t))}</span>`),
    ...(c.backfilled ? ['<span class="wk-l">补发完成</span>'] : []),
    ...(where.length ? [`<span class="mo-sent" title="${esc(c.sent.map((x) => `${x.label}：${x.title}`).join('\n'))}">发到 ${where.length} 个平台</span>`] : []),
    ...(c.state === 'past' && ['ok', 'miss'].includes(c.mn) ? [`<span class="wk-l">${c.mn === 'ok' ? '变现 ✓' : '没做变现动作'}</span>`] : []),
    ...(c.state !== 'past' && !c.shipped.length && c.planned.length ? [`<span class="wk-l next" title="${esc(c.planned[0].text)}（正在做的这一条）">拍：${esc(c.planned[0].text)}</span>`] : []),
    ...(c.items.some((it) => !it.done) ? [`<span class="wk-l item">· ${c.items.filter((it) => !it.done).length} 件别的事</span>`] : []),
  ];
  const verdict = c.state === 'past' ? (c.ship === 'miss' || c.mn === 'miss' ? 'mo-fail' : c.ship === 'ok' ? 'mo-pass' : '') : '';
  return `<button type="button" class="mo-day ${c.state} ${verdict} ${c.in_month ? '' : 'out'} ${TD.sel === c.day ? 'sel' : ''}" data-wk-day="${c.day}" aria-pressed="${TD.sel === c.day}">
    <span class="wk-d"><b>${Number(c.day.slice(8))}</b>${score}</span>${lines.join('')}</button>`;
}

/* 点开某一天：过去的日子看那天的账；今天和以后排拍哪条、加不算分的事 */
function dayPanel(c, notes) {
  const title = `<b>${dow(c.day)} ${md(c.day)}</b>`;
  const chk = (it) => `<label class="wk-item ${it.done ? 'done' : ''}"><input type="checkbox" data-wk-done="${it.id}" ${it.done ? 'checked' : ''}><span>${esc(it.text)}</span><button type="button" class="linklike" data-wk-del="${it.id}" aria-label="删掉">×</button></label>`;
  const items = `<div class="wk-col"><h4>别的事 <small>不算分</small></h4>${c.items.map(chk).join('')}
      <form class="td-add" data-wk-item="${c.day}"><input maxlength="200" placeholder="这天还要做什么，回车加上（比如：约两个博主诊断）" autocomplete="off"></form></div>`;
  if (c.state === 'past') {
    const RES = { ok: '做到', miss: featureOn('score') ? '没做到，减 1 分' : '没做到', 'n/a': '那天还不算分' };
    const det = { rd: '', ship: c.backfilled ? '：没发新的，补发的格子都发完了' : c.shipped.length ? `：${c.shipped.map((t) => `《${esc(headline(t))}》`).join('、')}` : '',
      dm: c.dm_entry ? `：收到 ${c.dm_entry.received}，回了 ${c.dm_entry.replied}` : c.dm === 'miss' ? '（没填数）' : '',
      xr: c.xr_count != null ? `：${c.xr_count} 条` : c.xr === 'miss' ? '（没填数）' : '' };
    return `<div class="wk-panel"><div class="wk-ph">${title}<span class="wk-score ${c.ship === 'miss' ? 'bad' : 'ok'}">${c.ship === 'miss' ? `这天没出摊${featureOn('score') ? '，减 1 分' : ''}` : c.ship === 'ok' ? '这天出摊了' : '那天还不算分'}</span></div>
      <div class="wk-cols"><div class="wk-col"><h4>那天的账</h4>${KPI_MARK.map(([f, , name]) => `<p class="wk-res ${c[f] === 'n/a' ? 'na' : c[f]}"><b>${name}</b>${RES[c[f]]}${det[f]}</p>`).join('')}
        ${(c.sent || []).length ? `<h4 class="wk-sub">发到了</h4>${sentByTitle(c.sent)}` : ''}
        ${c.skips.map((k) => `<p class="wk-res na"><b>跳过</b>${esc(k.what)}：${esc(k.reason || '')}</p>`).join('')}</div>${items}</div></div>`;
  }
  // 10/19 作者 拿掉排期：日历上只写正在做的那一条（今天）；以后的日子空着，发完再在「选题」里挑下一条
  const p = c.planned[0];
  const which = p ? `《${esc(p.text)}》，正在做的这一条。` : c.state === 'today' ? '现在没有正在做的：去「选题」挑一条，点「做这条」。' : '以后的不排：发完这条，再去「选题」挑下一条。';
  return `<div class="wk-panel"><div class="wk-ph">${title}<span class="td-note">${c.state === 'today' ? '今天' : '以后'}</span></div>
    <div class="wk-cols"><div class="wk-col"><h4>拍哪条</h4><p class="td-note">${which}</p>${(c.sent || []).length ? `<h4 class="wk-sub">这天已经发出去</h4>${sentByTitle(c.sent)}` : ''}</div>${items}</div></div>`;
}

/* 月历的目的（10/5 作者）：看昨天到底做没做该做的事。一句话放在月历最上面 */
function yesterdayLine(days) {
  const y = new Date(); y.setDate(y.getDate() - 1);
  const key = `${y.getFullYear()}-${String(y.getMonth() + 1).padStart(2, '0')}-${String(y.getDate()).padStart(2, '0')}`;
  const c = days.find((x) => x.day === key);
  if (!c || !['ok', 'miss'].includes(c.ship)) return '';
  const what = c.shipped.length ? `《${esc(headline(c.shipped[0]))}》` : c.backfilled ? '补发完成' : '';
  const money = c.mn === 'ok' ? '；做了变现动作' : c.mn === 'miss' ? `；没做变现动作${featureOn('score') ? '，减 1 分' : ''}` : '';
  const bad = c.ship === 'miss' || c.mn === 'miss' ? 'miss' : 'ok';
  return `<p class="mo-yday ${bad}">${c.ship === 'ok' ? `${bad === 'ok' ? '✓' : '✗'} 昨天 ${md(key)} 出摊了${what ? `：${what}` : ''}` : `✗ 昨天 ${md(key)} 没出摊${featureOn('score') ? '，减 1 分' : ''}`}${money}</p>`;
}

function monthBlock(m, w, streak, notes) {
  const days = m.weeks.flatMap((x) => x.days);
  const sel = days.find((c) => c.day === TD.sel);
  // 右上角是这一周的账（周一到周日）：出摊几天、减几分、新视频几条、连续几天
  const sum = [w.ship_days ? `本周出摊 <b class="${w.shipped === w.ship_days ? 'ok' : ''}">${w.shipped}/${w.ship_days}</b> 天` : '', !featureOn('score') ? '' : w.demerits ? `减 <b>${w.demerits}</b> 分` : w.ship_days ? '<b class="ok">没减分</b>' : '',
    w.new_target ? `新视频 <b class="${w.new_videos >= w.new_target ? 'ok' : ''}">${w.new_videos}/${w.new_target}</b> 条` : '', streakText(streak)].filter(Boolean).join(' · ');
  const [y, mo] = m.month.split('-').map(Number);
  return `<section class="wk">
    ${yesterdayLine(days)}
    <div class="wk-h"><span class="wk-nav"><button type="button" class="btn small" data-mo-go="${m.prev}" aria-label="上个月">‹</button><b>${y} 年 ${mo} 月</b><button type="button" class="btn small" data-mo-go="${m.next}" aria-label="下个月">›</button>${m.current ? '' : '<button type="button" class="btn small quiet" data-mo-go="">回到这个月</button>'}</span>
      <span class="wk-sum">${sum}</span></div>
    <div class="mo-grid">${['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map((x) => `<span class="mo-dow">${x}</span>`).join('')}${days.map(monthCell).join('')}</div>
    ${sel ? dayPanel(sel, notes) : '<p class="td-note wk-hint">绿 = 那天算分的事都做到了，红 = 有一件没做到。点某一天：过去的看那天发了哪条、发到了哪些平台；今天和以后的加别的事。</p>'}
  </section>`;
}

async function tdAct(fn) {
  try { await fn(); } catch (err) { toast(err.message); }
  $('#todayBody').dataset.sig = '';
  window.VIEWS.today.render();
}

/* 10/20 走查：抖音拒绝读作品列表时，复盘顶上照样说「连续 6 天没发」、扣分；只有作品分析页写了读取失败。
   数据没读到 ≠ 没做：哪路数据停了、上次读到是什么时候，放在所有结论上面。 */
function dataGapBlock() {
  const me = typeof S !== 'undefined' && S.mine ? S.mine.account : null;  // 自己的号在 /api/mine 里，不在 /api/accounts（那是老师和对标）
  const gaps = [];
  if (me && me.last_error) {
    const when = me.last_synced_at ? new Date(me.last_synced_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) : '';
    gaps.push(`抖音作品读不到${when ? `（上次读到是 ${when}）` : ''}：抖音上之后发的还没算进来，下面的「没出摊」、减分和播放先别信。`);
  }
  const x = ((typeof S !== 'undefined' && S.platforms) || []).find((p) => p.key === 'x' && p.alert);
  if (x) gaps.push(`X ${x.alert}：X 的曝光和涨粉停在上次读到的数。`);
  const relogin = me && me.last_error ? '<button class="btn small primary" type="button" data-reconnect="douyin">重新登录抖音</button>' : '';
  return gaps.length ? `<div class="data-gap" role="status"><b>数据有缺口</b>${gaps.map((g) => `<p>${esc(g)}</p>`).join('')}<div class="data-gap-acts">${relogin}<button class="linklike" type="button" onclick="go('mine')">去作品分析看详情</button></div></div>` : '';
}

window.VIEWS.today = {
  async render() {
    const body = $('#todayBody');
    if (window.skeletonPage && body.children && !body.children.length) body.innerHTML = window.skeletonPage({ cards: 3, rows: 4 });
    let d;
    let month;
    try { [d, TD.kpi, month, TD.home, TD.review] = await Promise.all([loadToday(), api('/api/kpi').catch(() => null), api(`/api/today/month${TD.monthStart ? `?start=${TD.monthStart}` : ''}`).catch(() => null), api('/api/today/home').catch(() => null), featureOn('team') ? api('/api/today/review').catch(() => null) : null]); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    paintTodayBadge();
    $('#todayDay').textContent = `盘 · ${dayTitle(d.day)}`;
    if (document.activeElement && document.activeElement.closest('#todayBody, #todayTargets') && document.activeElement.matches('input:not([type=checkbox])')) return;
    if (month) TD.month = month;
    const gap = dataGapBlock();
    const sig = JSON.stringify([d.week, d.streak, d.ship.notes, TD.kpi, TD.month, TD.sel, TD.home, TD.review, gap]);
    const again = () => { body.dataset.sig = ''; this.render(); };
    this.schedule();
    if (window.renderFupanTable) window.renderFupanTable();  // 每条内容 × 每个平台那张表自己记 sig
    if (body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    // 10/13 作者：「战况和今天合并，太乱了……以战况页面为主页面，calendar 保留，其他都拿掉。」
    // 10/19 作者：「战况和汇总放到一起，改名叫复盘……核心是要 simplify」。
    // 从上到下：Wendy 的复盘（结论 + 今天你做）→ 三个 KPI（钱那张卡里记一笔、每 3 天问一次）→ 月历 → 每条内容 × 每个平台（#fupanTable，output.js）→ 改目标
    const k = TD.kpi;
    body.innerHTML = `${gap}${featureOn('team') ? dailyReviewBlock(TD.review) : ''}
      ${k ? `<div class="kpi-grid">${k.kpis.map(kpiCard).join('')}${kpiMoney(k.money, moneyAsk(k) + moneyBook(TD.home))}</div>` : ''}
      ${TD.month ? monthBlock(TD.month, d.week, d.streak, d.ship.notes) : ''}`;
    const targets = $('#todayTargets');
    targets.innerHTML = k ? kpiTargets(k.targets) : '';
    bindMoneyAsk(body);
    bindMoney(body);
    bindKpiTargets(targets, again);
    if (typeof bindTips === 'function') bindTips(body);
    if (featureOn('team')) bindReview(body, again);
    $$('[data-mo-go]', body).forEach((b) => (b.onclick = () => { TD.monthStart = b.dataset.moGo || null; TD.sel = null; again(); }));
    $$('[data-wk-day]', body).forEach((b) => (b.onclick = () => { TD.sel = TD.sel === b.dataset.wkDay ? null : b.dataset.wkDay; again(); }));
    $$('[data-wk-item]', body).forEach((f) => (f.onsubmit = (e) => {
      e.preventDefault();
      const text = $('input', f).value.trim();
      if (!text) return;
      $('input', f).value = '';
      tdAct(() => api('/api/today/plan', { method: 'POST', body: { day: f.dataset.wkItem, text } }));
    }));
    $$('[data-wk-done]', body).forEach((c) => (c.onchange = () => tdAct(() => api(`/api/today/plan/${c.dataset.wkDone}`, { method: 'PATCH', body: { done: c.checked } }))));
    $$('[data-wk-del]', body).forEach((b) => (b.onclick = () => tdAct(() => api(`/api/today/plan/${b.dataset.wkDel}`, { method: 'DELETE' }))));
  },
  /* 「我发了」以后在同步抖音：隔几秒再看一眼，同步完就停 */
  schedule() {
    clearTimeout(TD.poll);
    const checking = TD.home && TD.home.check && TD.home.check.state === 'running';
    const writing = TD.review && TD.review.verdict && TD.review.verdict.state === 'writing';
    if (checking || writing) TD.poll = setTimeout(() => { if (S.view === 'today') this.render(); }, checking ? 4000 : 10000);
  },
};
