const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/content_studio/static/reviewtab.js', 'utf8');

function load(extra = {}) {
  const tabs = [], calls = [], els = {};
  const ctx = vm.createContext({
    window: { VIDEO_TABS: tabs }, featureOn: () => true,
    esc: (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])),
    $: (sel) => els[sel] || { onclick: null }, toast() {}, VD: { topicId: 1, tab: 'review', forceRender: false }, S: { view: 'work' }, renderView() {},
    clearTimeout() {}, setTimeout: () => 0,
    api: async (url, opts) => { calls.push({ url, opts }); return (extra.api || (async () => ({})))(url, opts); }, ...extra.ctx });
  vm.runInContext(source, ctx);
  return { tab: tabs[0], calls, els, ctx };
}
const el = () => ({ isConnected: true, innerHTML: '' });
const base = { available: true, running: false, has_transcript: true, can_auto: false, stale: false, error: null, review: null };
const review = { items: [{ id: 'retain', title: '留人' }, { id: 'typo', title: '错字通顺和导语' }], next: ['开头先说结果', '证据放前面'],
  scores: { 留人: { id: 'retain', score: 7, why: '开头给了数字', quote: '三天三单' } } };

test('the tab shows for anything that has a video and only with the xline block', () => {
  const { tab } = load();
  assert.equal(tab.key, 'review'); assert.equal(tab.label, '拍后');
  assert.equal(tab.show({ video_project: 'p' }), true);
  assert.equal(tab.show({ published_video_id: '1' }), true);
  assert.equal(tab.show({}), false);
  assert.equal(load({ ctx: { featureOn: () => false } }).tab.show({ video_project: 'p' }), false);
});

test('without the review sections or without subtitles it says what to do and calls nothing', async () => {
  let { tab, calls } = load({ api: async () => ({ ...base, available: false }) });
  let e = el(); await tab.render({ id: 1 }, e);
  assert.match(e.innerHTML, /还没有评判清单/); assert.equal(calls.length, 1);
  ({ tab, calls } = load({ api: async () => ({ ...base, has_transcript: false }) }));
  e = el(); await tab.render({ id: 1 }, e);
  assert.match(e.innerHTML, /还没有字幕/); assert.equal(calls.length, 1);
});

test('a transcript with no review yet starts one automatically, once per opening', async () => {
  const { tab, calls } = load({ api: async (url, opts) => (opts && opts.method === 'POST' ? { started: true } : { ...base, can_auto: true }) });
  await tab.render({ id: 1 }, el());
  assert.deepEqual(calls.map((c) => c.opts && c.opts.method), [undefined, 'POST']);
  assert.equal(calls[1].opts.body.force, false);
  await tab.render({ id: 1 }, el());  // 再画一次不会再起
  assert.equal(calls.filter((c) => c.opts && c.opts.method === 'POST').length, 1);
});

test('while it runs the page says so and the badge follows', async () => {
  const { tab } = load({ api: async () => ({ ...base, running: true }) });
  const e = el(); await tab.render({ id: 1 }, e);
  assert.match(e.innerHTML, /在做拍后批注/); assert.equal(tab.badge({ id: 1 }), '在做');
});

test('a finished review lists the nine items with score, reason and the quoted sentence, plus what to watch next time', async () => {
  const { tab, els } = load({ api: async () => ({ ...base, review }) });
  const e = el(); els['#rvAgain'] = { onclick: null };
  await tab.render({ id: 1 }, e);
  assert.match(e.innerHTML, /下一条要注意的/); assert.match(e.innerHTML, /开头先说结果/);
  assert.match(e.innerHTML, /留人<\/b><span class="rv-score">7<small>\/10/);
  assert.match(e.innerHTML, /字幕里：「三天三单」/);
  assert.match(e.innerHTML, /rv-item na"><b>错字通顺和导语/);  // 没打分的那项：虚线，说为什么
  assert.match(e.innerHTML, /拍视频没有导语/);
  assert.equal(tab.badge({ id: 1 }), '2 条');
  assert.match(e.innerHTML, /id="rvAgain">重新批注/);
});

test('stale subtitles are called out and the button asks for a fresh run', async () => {
  const { tab, els, calls } = load({ api: async () => ({ ...base, review, stale: true }) });
  const e = el(); els['#rvAgain'] = { onclick: null };
  await tab.render({ id: 1 }, e);
  assert.match(e.innerHTML, /字幕换过了/); assert.match(e.innerHTML, /按新字幕重来/);
  assert.equal(typeof els['#rvAgain'].onclick, 'function');
});
