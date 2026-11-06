'use strict';
/* 战况（10/12 作者）：「Wendy 是这个 project 的 full owner……一旦定下了 KPI，就要 make that happen，而且要确保 KPI is viable。」
 * 10/13 起战况就是首页（today.js 的 VIEWS.today 渲染，这里只放 KPI 卡和改目标）：每个 KPI 一张卡——目标、现在、今天应到、每天要涨多少、照最近 7 天的速度到哪，
 * 下面拆成撬动它的几个数（每天播放 × 每千播放涨粉；条数；最近几条的 2 秒跳出、5 秒完播、点进主页）。
 * 转化率不是目标，是算出来的。目标在最下面「改目标」改（一个地方）。 */
const pct0 = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`);

const wan = (n) => (n == null ? '—' : n >= 10000 ? `${(n / 10000).toFixed(n >= 100000 ? 0 : 1)} 万` : fmt(Math.round(n)));

/* 实际的线 + 目标的虚线（起点那天的数 → 终点那天的目标） */
function kpiChart(k) {
  const W = 520, H = 120, L = 6, R = 6, T = 14, B = 20;
  const t = (d) => new Date(d + 'T00:00:00').getTime();
  const pts = k.points || [];
  const x0 = Math.min(t(k.start_day), ...pts.map((p) => t(p.day))), x1 = t(k.end_day);
  const vals = [k.start, k.end, ...pts.map((p) => p.v)];
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.1 || 1; lo -= pad; hi += pad;
  const X = (d) => L + ((t(d) - x0) / Math.max(1, x1 - x0)) * (W - L - R);
  const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.day).toFixed(1)},${Y(p.v).toFixed(1)}`).join('');
  const last = pts[pts.length - 1];
  const hits = pts.map((p) => `<rect class="hit" x="${(X(p.day) - 8).toFixed(1)}" y="0" width="16" height="${H}" data-tip="${esc(`${p.day}\n${fmt(p.v)}`)}"/>`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" class="rl-svg" role="img" aria-label="${esc(k.label)}：实际和目标">
    <line class="rl-base" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/>
    <line class="kpi-goal" x1="${X(k.start_day).toFixed(1)}" y1="${Y(k.start).toFixed(1)}" x2="${X(k.end_day).toFixed(1)}" y2="${Y(k.end).toFixed(1)}"/>
    ${line ? `<path class="rl-line" d="${line}"/>` : ''}${last ? `<circle class="rl-dot last" cx="${X(last.day).toFixed(1)}" cy="${Y(last.v).toFixed(1)}" r="4"/>` : ''}${hits}
    <text class="axis" x="${L}" y="${H - 5}">${md(pts.length ? pts[0].day : k.start_day)}</text><text class="axis" x="${W - R}" y="${H - 5}" text-anchor="end">${md(k.end_day)} 目标 ${fmt(k.end)}</text></svg>`;
}

/* 一个数一行：名字 · 现在 · 要多少（有的话）· 一句怎么算的 */
function kpiRow(name, now, need, note, bad) {
  return `<li class="${bad ? 'bad' : ''}"><span>${esc(name)}</span><b class="num">${now}</b>${need ? `<small>要 <b class="num">${need}</b></small>` : '<small></small>'}<em>${esc(note || '')}</em></li>`;
}

function kpiCard(k) {
  const t = k.tree || {}, c = t.conv;
  const unit = k.key === 'douyin' ? '播放' : '曝光';
  const rows = [
    kpiRow(`每天${unit}`, wan(t.views_avg), t.views_need ? wan(t.views_need) : '', `最近 7 天日均；要多少 = 每天要涨的粉 ÷ 每千${unit}涨粉${k.key === 'x' && t.views_target ? `（你定的是每天 ${wan(t.views_target)}）` : ''}`, t.views_need && t.views_avg != null && t.views_avg < t.views_need),
    kpiRow(`每千${unit}涨粉`, c ? String(c.per_1k) : '—', '', c ? `${md(c.from)}–${md(c.to)} 全号：涨 ${fmt(c.fans)} ÷ ${wan(c.views)} ${unit}。靠内容提高，不是目标` : '读数还不够，先不算'),
  ];
  if (k.key === 'douyin') {
    rows.push(kpiRow('最近 7 天发了', `${t.posted_7} 条`, '7 条', `${t.posted_days_7}/7 天有新视频${t.days_since_post ? ` · 上一条是 ${t.days_since_post} 天前` : t.posted_today ? ' · 今天发了' : ''}。每天 1 条，不商量`, t.posted_days_7 < 7));
    rows.push(kpiRow(`最近 ${t.videos} 条中位`, `${wan(t.views_median)} 播放`, '', `2 秒跳出 ${pct0(t.bounce_2s)} · 5 秒完播 ${pct0(t.retain_5s)} · 点进主页 ${pct0(t.profile_rate)} · 每千播放涨粉 ${t.fans_per_1k == null ? '—' : t.fans_per_1k.toFixed(1)}`));
  }
  return `<section class="rs-card kpi-card">
    <div class="rs-h"><span>${esc(k.label)} · ${md(k.end_day)} 前到 ${fmt(k.end)} ${k.ok ? '<i class="kpi-pill ok">达标</i>' : '<i class="kpi-pill bad">落后</i>'}</span><b class="num">${k.now == null ? '—' : fmt(k.now)}</b>
      <small>今天应到 ${fmt(k.expected)}${k.gap != null ? `（${k.gap >= 0 ? '多' : '差'} ${fmt(Math.abs(k.gap))}）` : ''}</small>
      <span class="rs-proj">照这个速度 ${md(k.end_day)} 到 ${q('现在的数 + 最近 7 个过完的日子（记得不够 7 天就从第一次读数算）每天涨多少 × 剩下的天数。照现在的速度，不是保证。')} <b class="num ${k.forecast != null && k.forecast < k.end ? 'bad' : ''}">${k.forecast == null ? '—' : fmt(k.forecast)}</b></span></div>
    <p class="kpi-say">${esc(k.say)}</p>
    <p class="td-note">每天要涨 <b class="num">${k.need_per_day == null ? '—' : fmt(k.need_per_day)}</b>（还剩 ${k.days_left} 天）· 最近每天 <b class="num">${k.rate == null ? '—' : `+${fmt(Math.round(k.rate))}`}</b></p>
    ${kpiChart(k)}
    <ul class="kpi-tree">${rows.join('')}</ul>
  </section>`;
}

function kpiMoney(m, extra = '') {
  if (!m) return '';
  return `<section class="rs-card kpi-card">
    <div class="rs-h"><span>${m.month} 月收入 · 目标 ${yuan(m.target)} ${m.ok ? '<i class="kpi-pill ok">够</i>' : '<i class="kpi-pill bad">落后</i>'}</span><b class="num">${yuan(m.total)}</b>
      <span class="rs-proj">照这个速度月底 <b class="num ${m.ok ? '' : 'bad'}">${yuan(m.expected)}</b></span></div>
    <p class="td-note">还差 ${yuan(Math.max(0, m.target - m.total))}，剩 ${m.days_left} 天，每天要 ${yuan(m.need_per_day)}。每 3 天问你一次有没有新的收入点${m.last_note ? `；上次 ${md(m.last_note.day)}：${esc(m.last_note.note)}` : ''}。</p>
    ${extra}
  </section>`;
}

function kpiTargets(t) {
  return `<details class="rs-card kpi-set"><summary>改目标 <small>你和 Wendy 一起定；只改终点，起点是定下来那天的数</small></summary>
    <form class="rs-fl" id="kpiSet">
      <label>抖音粉丝 <input class="num" type="number" min="0" name="douyin_end" value="${t.douyin.end}"></label><label>到哪天 <input type="date" name="douyin_end_day" value="${esc(t.douyin.end_day)}"></label>
      <label>X 粉丝 <input class="num" type="number" min="0" name="x_end" value="${t.x.end}"></label><label>到哪天 <input type="date" name="x_end_day" value="${esc(t.x.end_day)}"></label>
      <label>X 每天曝光 <input class="num" type="number" min="0" name="x_impressions" value="${t.x_impressions}"></label>
      <label>本月收入（元） <input class="num" type="number" min="0" name="revenue" value="${t.revenue}"></label>
      <button class="btn small" type="submit">保存</button></form></details>`;
}

/* 改目标的表单（在首页最下面） */
function bindKpiTargets(body, again) {
  const form = $('#kpiSet', body);
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(form), num = (k) => (f.get(k) === '' ? null : Number(f.get(k)));
    try {
      TD.kpi = await api('/api/kpi/targets', { method: 'PUT', body: { douyin_end: num('douyin_end'), douyin_end_day: f.get('douyin_end_day'), x_end: num('x_end'),
        x_end_day: f.get('x_end_day'), x_impressions: num('x_impressions'), revenue: num('revenue') } });
      toast('目标改好了');
      if (document.activeElement) document.activeElement.blur();
      again();
    } catch (err) { toast(err.message); }
  };
}
