'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/content_studio/static/today.js'), 'utf8');

function harness(nodes = [], request = async () => ({})) {
  const calls = [], timers = [], notices = [];
  const context = vm.createContext({
    window: { openWendy() { calls.push('open'); } }, S: { view: 'today' }, featureOn: () => true,
    esc: (value) => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
    WORK_STEPS: [['a', '骨架'], ['b', '录制与剪辑'], ['c', '标题和封面']], q: (tip) => `<i data-tip="${tip}">?</i>`, fmt: (value) => String(value), pct: (value) => value == null ? '—' : `${(value * 100).toFixed(1)}%`,
    api: async (url, options) => { calls.push({ url, options }); return request(url, options); },
    toast: (message) => notices.push(message),
    $: (selector) => nodes.find((node) => node.selector === selector) || null,
    $$: (selector) => nodes.filter((node) => node.selector === selector || selector === `[data-rv-proposal="${node.dataset?.rvProposal}"]`),
    clearTimeout() {}, setTimeout(fn, delay) { timers.push({ fn, delay }); return timers.length; },
  });
  vm.runInContext(source, context);
  return { context, calls, timers, notices, run: (code) => vm.runInContext(code, context) };
}

const review = {
  verdict: { text: '<不要编数>', at: '2026-10-11T01:35:00Z' },
  yesterday: { ship: 'miss', streak: { days: 2, kind: 'miss' }, douyin: { value: 70, previous: 100 }, x: { value: 100, previous: 100 }, money: { yesterday: 0, month: 800 } },
  douyin: { median: 100, n: 3, rows: [
    { day: '2026-10-08', title: '高于中位数', multiple: 1.2, likes_72h: 120, bounce_rate_2s: 0.35, completion_rate_5s: 0.4, time: '20:30' },
    { day: '2026-10-07', title: '低于中位数', multiple: 0.6, likes_72h: 60 },
    { title: '新视频', multiple: null, likes_72h: null, status: '还不到 72 小时' },
  ] },
  x: { day: '2026-10-10', impressions: 91604, verified_impressions: 1200, verified_ratio: 1200 / 91604,
    source: '后台', new_follows: 120, unfollows: 20, net_follows: 100, follow_source: '后台',
    progress: { current: 2500, expected: 6288, gap: -3788, bad: true, as_of: '2026-10-10' },
    top: [{ post_id: '123', text: '<测试>', impressions: 1000, bookmarks: 20, bookmarks_per_1k: 20 }],
    kinds: [{ kind: '长文', sent: 3, median_24h: 1200, bookmarks_per_1k: null }],
  },
  stuck: { days: 2, options: ['不知道演示哪一段'] }, next_missing: [{ title: '证据', why: '骨架还没写' }],
  hypotheses: [{ id: 'A', text: '标题写结果' }],
  experiments: [{ title: '标题实验', hypothesis: 'A', check_on: '10/11', conclusion: '' }],
  due: [{ title: '标题实验', hypothesis: 'A', check_on: '10/11' }],
  proposals: [{ id: 0, idea: '试直播', why: '离钱近', time: '30 分钟', metric: '咨询数', days: 7, status: '待定' }, { id: 1, idea: '已决定', status: '不试（10/11）' }],
};

test('review: verdict and pending proposals only; the Douyin table lives in 抖音作品分析, not here (10/19 复盘合页)', () => {
  const h = harness(); h.context.review = review;
  review.douyin.rows[0] = { ...review.douyin.rows[0], views: 6503, fans: 42, avg_view_second: 14.07, duration_s: 379.5 };
  const html = h.run('dailyReviewBlock(review)');
  assert.match(html, /09:35 写好/);
  assert.match(html, /&lt;不要编数>/);
  assert.doesNotMatch(html, /<th>平均看了<\/th>|1\.2×|6503/);  // 抖音小表拿掉了：和抖音作品分析重复
  assert.match(html, /pill mid">该对账了/); assert.match(html, /rv-fold" open/);
  assert.equal((html.match(/data-rv-proposal=/g) || []).length, 2);
  assert.doesNotMatch(html, /已决定/);
  assert.doesNotMatch(html, /rv-tile|X 昨天|每千曝光收藏|data-rv-stuck|style=/);
});

test('writing review polls after ten seconds, stops when ready, and preserves shipped check polling', () => {
  const h = harness();
  h.run("TD.review = {verdict:{state:'writing'}}; window.VIEWS.today.schedule()");
  assert.equal(h.timers[0].delay, 10000);
  assert.match(h.run('dailyReviewBlock(TD.review)'), /class="spin"/);
  h.run("TD.review = {verdict:{text:'已写好'}}; window.VIEWS.today.schedule()");
  assert.equal(h.timers.length, 1);
  h.run("TD.home = {check:{state:'running'}}; window.VIEWS.today.schedule()");
  assert.equal(h.timers[1].delay, 4000);
  h.run("TD.review = {verdict:{error:'暂时失败'}}");
  assert.match(h.run('dailyReviewBlock(TD.review)'), /暂时失败/);
});

test('proposal disables both decisions while pending and retries after a failed request', async () => {
  const yes = { selector: '[data-rv-proposal]', dataset: { rvProposal: '0', rvDecision: 'try' } };
  const no = { selector: '[data-rv-proposal]', dataset: { rvProposal: '0', rvDecision: 'skip' } };
  let reject;
  const h = harness([yes, no], () => new Promise((_, fail) => { reject = fail; }));
  h.run('bindReview({}, () => {})');
  const pending = yes.onclick();
  assert.equal(yes.disabled, true); assert.equal(no.disabled, true);
  assert.equal(h.calls[0].options.body.index, 0); assert.equal(h.calls[0].options.body.decision, 'try');
  reject(new Error('账本暂时写不了')); await pending;
  assert.equal(yes.disabled, false); assert.equal(no.disabled, false);
  assert.deepEqual(h.notices, ['账本暂时写不了']);
});

test('one row per hypothesis includes its experiments; pending work takes precedence over old conclusions', () => {
  const h = harness();
  h.context.review = {
    hypotheses: [{ id: 'A', text: '开头猜测' }, { id: 'B', text: '发布时间' }],
    experiments: [
      { title: '旧开头实验', hypothesis: 'A', conclusion: '旧结论' },
      { title: '新开头实验', hypothesis: 'A', change: '第一句加数字', metric: '2 秒跳出', check_on: '10/18', conclusion: '' },
      { title: '晚间实验', hypothesis: 'B', conclusion: '晚上较好' },
    ],
  };
  const html = h.run('dailyReviewBlock(review)').split('<ul class="rv-guess">')[1];
  assert.equal((html.match(/<li>/g) || []).length, 2);
  assert.equal((html.match(/新开头实验/g) || []).length, 1);
  assert.match(html, /新开头实验 · 10\/18 对账/);
  assert.match(html, /pill low">在验证/);
  assert.doesNotMatch(html, /pill low">旧结论/);
  assert.match(html, /pill low">晚上较好/);
});

test('a writing placeholder still allows manual rewrite and only disables the request in flight', async () => {
  const redo = { selector: '[data-rv-redo]', dataset: {} };
  let resolve;
  const h = harness([redo], () => new Promise((done) => { resolve = done; }));
  assert.match(h.run("dailyReviewBlock({verdict:{state:'writing'}})"), /data-rv-redo>重写/);
  h.run('bindReview({}, () => {})');
  const pending = redo.onclick();
  assert.equal(redo.disabled, true);
  assert.equal(h.calls[0].url, '/api/today/review/verdict');
  resolve({ started: false }); await pending;
  assert.equal(redo.disabled, false);
});

test('not started yet says when it will be written, not that Wendy is writing', () => {
  const h = harness([]);
  for (const fn of ['dailyReviewBlock']) {
    const html = h.run(`${fn}({verdict:{state:'waiting', from:'09:35'}})`);
    assert.match(html, /还没开始写：每天 09:35 以后写/);
    assert.doesNotMatch(html, /在写今天的复盘|spin/);
  }
  h.run("TD.review = {verdict:{state:'waiting'}}; window.VIEWS.today.schedule()");
  assert.equal(h.run('TD.poll'), null);  // 没在写就不用每 10 秒刷一次
});

test('structured verdict (10/13): headline, facts, wrong, today list, wait', () => {
  const h = harness();
  h.context.rv = { ...review, facts: [['抖音', '没发（连续 4 天） · 播放 10,463'], ['X', '曝光 33,347 · 净涨粉 +180'], ['收入', '¥0 · 本月 ¥0']],
    verdict: { headline: '抖音差 3.2 倍，卡在你 4 天没发', wrong: '昨天又没发<视频>', today: ['把《版本答案》发到抖音'], wait: ['10/14 看曝光'], text: 'x', at: '2026-10-13T01:35:00Z' } };
  const full = h.run('dailyReviewBlock(rv)');
  assert.match(full, /class="rv-head" role="status">抖音差 3\.2 倍/);
  assert.match(full, /<dt>X<\/dt><dd>曝光 33,347 · 净涨粉 \+180<\/dd>/);
  assert.match(full, /<b>你做错了<\/b>昨天又没发&lt;视频>/);
  assert.match(full, /<h3>今天你做<\/h3><ol class="rv-do"><li>把《版本答案》发到抖音<\/li>/);
  assert.match(full, /<h3>我在等<\/h3>/);
  assert.doesNotMatch(full, /rv-verdict|style=/);
  assert.match(h.run("dailyReviewBlock({...rv, verdict:{text:'旧的一段话'}})"), /rv-facts[\s\S]*rv-verdict" role="status">旧的一段话/);
});
