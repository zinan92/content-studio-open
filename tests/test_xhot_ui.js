'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = (name) => fs.readFileSync(path.join(__dirname, '../src/content_studio/static', name), 'utf8');
const flush = () => new Promise((resolve) => setImmediate(resolve));
const item = { url: 'https://x.com/a/status/1', kind: 'articles', title: '示例长文', text: '示例内容', author: '作者', reads: 100, rank: 1 };
const board = (items = [item]) => ({ items, dimensions: { articles: ['reads'], tweets: ['reads'], topics: ['heat'] }, categories: [] });

function harness(api, { startOnRising = false } = {}) {
  let now = 1000, nextTimer = 0;
  const timers = new Map(), calls = [];
  const context = vm.createContext({
    window: { VIEWS: {} }, URLSearchParams, console,
    Date: class extends Date { static now() { return now; } },
    setTimeout: (fn, delay) => { const id = ++nextTimer; timers.set(id, { fn, at: now + delay }); return id; },
    clearTimeout: (id) => timers.delete(id),
    esc: (s) => String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
    toast: () => {}, S: { state: {} }, featureOn: () => true,
    $: (selector, box) => (box.controls[selector] || [])[0] || null,
    $$: (selector, box) => box.controls[selector] || [],
    api: (url, opts) => { calls.push({ url, opts }); return api(url, opts); },
  });
  vm.runInContext(source('input.js') + '\n' + source('xhot.js'), context);
  if (!startOnRising) vm.runInContext("XH.kind = 'articles'", context);  // 下面的老测试都是按长文榜写的；默认是「持续在涨」
  return {
    calls, context, run: (code) => vm.runInContext(code, context),
    box: () => ({ isConnected: true, innerHTML: '', controls: {} }),
    render(box) { context.box = box; vm.runInContext('xhRender(box)', context); },
    advance(ms, fire = false) {
      now += ms;
      if (fire) for (const [id, timer] of [...timers]) if (timer.at <= now) { timers.delete(id); timer.fn(); }
    },
  };
}

test('loading moves to the current page and shares one request across mounts', async () => {
  let resolve;
  const h = harness(() => new Promise((r) => { resolve = r; }));
  const old = h.box(), current = h.box();
  h.render(old); await flush();
  old.isConnected = false; h.render(current); h.render(current);
  assert.equal(h.calls.length, 1);
  resolve(board()); await flush();
  assert.match(current.innerHTML, /示例长文/);
  assert.doesNotMatch(current.innerHTML, /在读 X 指数榜/);
});

test('fresh filters and manual refresh each issue one request', async () => {
  const h = harness(async () => board());
  const box = h.box();
  box.controls['[data-xh-kind]'] = [{ dataset: { xhKind: 'tweets' } }];
  box.controls['[data-xh-fresh]'] = [{}];
  h.render(box); await flush();
  box.controls['[data-xh-kind]'][0].onclick(); await flush();
  assert.equal(h.calls.length, 2);
  await box.controls['[data-xh-fresh]'][0].onclick();
  assert.equal(h.calls.length, 3);
  assert.match(h.calls[2].url, /fresh=1/);
});

test('cached boards expire when revisited and refresh while still visible', async () => {
  const h = harness(async () => board()); const box = h.box();
  h.render(box); await flush();
  h.advance(599999); h.render(box); await flush();
  assert.equal(h.calls.length, 1);
  h.advance(1); h.render(box); await flush();
  assert.equal(h.calls.length, 2);
  h.advance(600000, true); await flush();
  assert.equal(h.calls.length, 3);
  box.isConnected = false;
  h.advance(600000, true); await flush();
  assert.equal(h.calls.length, 3);
});

test('saving invalidates inbox so the saved tab immediately reads the new note', async () => {
  let saved = false;
  const h = harness(async (url) => {
    if (url === '/api/xhot/save') { saved = true; return { new: true }; }
    if (url.startsWith('/api/vault/inbox')) return { items: saved ? [{ path: 'saved/new.md' }] : [] };
    return board();
  });
  await h.run('loadInbox(false)');
  const box = h.box(), button = { dataset: { xhSave: item.url }, textContent: '收藏素材', classList: { add() {}, remove() {} } };
  box.controls['[data-xh-save]'] = [button];
  h.render(box); await flush();
  await button.onclick();
  await h.run('loadInbox(false)');
  assert.equal(h.run('C.items[0].path'), 'saved/new.md');
  assert.equal(h.calls.filter(({ url }) => url.startsWith('/api/vault/inbox')).length, 2);
});

test('an old filter failure cannot replace the currently selected successful board', async () => {
  let rejectOld;
  const h = harness((url) => url.includes('kind=articles') ? new Promise((_, reject) => { rejectOld = reject; }) : Promise.resolve(board([{ ...item, kind: 'tweets', text: '新榜单' }])));
  const box = h.box(); h.render(box); await flush();
  h.run("XH.kind='tweets'"); h.render(box); await flush();
  rejectOld(new Error('旧请求失败')); await flush();
  assert.match(box.innerHTML, /新榜单/);
  assert.doesNotMatch(box.innerHTML, /旧请求失败/);
});

test('invalid source links have no actions and remote ranks render as text', async () => {
  const h = harness(async () => board([{ ...item, url: '', rank: '<img src=x onerror=alert(1)>' }]));
  const box = h.box(); h.render(box); await flush();
  assert.doesNotMatch(box.innerHTML, /data-xh-save|class="xh-link"|<img/);
  assert.match(box.innerHTML, /&lt;img/);
});

const manyItems = (n = 25) => Array.from({ length: n }, (_, i) => ({ ...item, rank: i + 1, title: `长文-${i + 1}`, url: `https://x.com/a/status/${i + 1}` }));
const visibleRows = (box) => (box.innerHTML.match(/<li class="xh-row">/g) || []).length;

test('long boards show ten at a time, collapse, and keep the complete cached board', async () => {
  const h = harness(async () => board(manyItems())); const box = h.box();
  box.controls['[data-xh-more]'] = [{}];
  box.controls['[data-xh-less]'] = [{}];
  h.render(box); await flush();
  assert.equal(visibleRows(box), 10);
  assert.match(box.innerHTML, /role="status">10 \/ 25</);
  assert.doesNotMatch(box.innerHTML, /长文-11</);
  box.controls['[data-xh-more]'][0].onclick();
  assert.equal(visibleRows(box), 20);
  box.controls['[data-xh-more]'][0].onclick();
  assert.equal(visibleRows(box), 25);
  assert.doesNotMatch(box.innerHTML, /data-xh-more/);
  box.controls['[data-xh-less]'][0].onclick();
  assert.equal(visibleRows(box), 10);
  assert.equal(h.run('XH.data[xhKey()].items.length'), 25);
  assert.equal(h.calls.length, 1);
});

test('each changed filter resets the visible batch, including cached filters', async () => {
  const h = harness(async () => board(manyItems())); const box = h.box();
  const controls = {
    '[data-xh-kind]': { dataset: { xhKind: 'tweets' } },
    '[data-xh-period]': { dataset: { xhPeriod: '48h' } },
    '[data-xh-dim]': { dataset: { xhDim: 'latest' } },
    '[data-xh-cat]': { value: 'tech' },
  };
  box.controls['[data-xh-more]'] = [{}];
  for (const [selector, control] of Object.entries(controls)) box.controls[selector] = [control];
  h.render(box); await flush();
  for (const [selector, control] of Object.entries(controls)) {
    box.controls['[data-xh-more]'][0].onclick();
    assert.equal(visibleRows(box), 20);
    if (selector === '[data-xh-cat]') control.onchange(); else control.onclick();
    await flush();
    assert.equal(visibleRows(box), 10, `${selector} resets pagination`);
  }
  // Return to an already cached board; no network or old batch count leaks through.
  h.run("XH.kind='articles'; XH.period='24h'; XH.category='ai'");
  h.render(box); await flush();
  assert.equal(visibleRows(box), 10);
  assert.equal(h.calls.length, 5);
});

test('batch expansion and collapse preserve a topic expansion and its actions', async () => {
  const topics = Array.from({ length: 12 }, (_, i) => ({ id: `t${i}`, rank: i + 1, title: `话题 ${i}`, text: '话题摘要', tags: [], tweets: [item], tweet_count: 1, reads: 100, heat: 1 }));
  const h = harness(async () => board(topics)); const box = h.box();
  h.run("XH.kind='topics'");
  box.controls['[data-xh-open]'] = [{ dataset: { xhOpen: 't0' } }];
  box.controls['[data-xh-more]'] = [{}]; box.controls['[data-xh-less]'] = [{}];
  h.render(box); await flush();
  box.controls['[data-xh-open]'][0].onclick();
  assert.match(box.innerHTML, /data-xh-open="t0" aria-expanded="true"/);
  assert.match(box.innerHTML, /data-xh-save=/);
  box.controls['[data-xh-more]'][0].onclick();
  assert.match(box.innerHTML, /话题 11/);
  assert.match(box.innerHTML, /aria-expanded="true"/);
  box.controls['[data-xh-less]'][0].onclick();
  assert.doesNotMatch(box.innerHTML, /话题 11/);
  assert.match(box.innerHTML, /aria-expanded="true"/);
  assert.equal(h.calls.length, 1);
});

test('refresh failures retain cached rows and batch size; retry replaces them once', async () => {
  let attempts = 0;
  const h = harness(async () => {
    attempts++;
    if (attempts === 2) throw new Error('来源暂时不可用');
    return board(manyItems());
  });
  const box = h.box();
  for (const selector of ['[data-xh-more]', '[data-xh-fresh]', '[data-xh-retry]']) box.controls[selector] = [{}];
  h.render(box); await flush(); box.controls['[data-xh-more]'][0].onclick();
  const pending = box.controls['[data-xh-fresh]'][0].onclick();
  assert.equal(visibleRows(box), 20);
  assert.match(box.innerHTML, /xh is-refreshing/);
  await pending;
  assert.equal(visibleRows(box), 20);
  assert.match(box.innerHTML, /更新失败，保留上次的榜单/);
  assert.match(box.innerHTML, /data-xh-retry/);
  await box.controls['[data-xh-retry]'][0].onclick();
  assert.equal(visibleRows(box), 20);
  assert.doesNotMatch(box.innerHTML, /来源暂时不可用/);
  assert.equal(h.calls.length, 3);
});

test('initial errors can retry and empty boards explain recovery', async () => {
  let attempts = 0;
  const h = harness(async () => { if (++attempts === 1) throw new Error('暂不可用'); return board([]); });
  const box = h.box(); box.controls['[data-xh-retry]'] = [{}];
  h.render(box); await flush();
  assert.match(box.innerHTML, /暂时读不到热榜/);
  await box.controls['[data-xh-retry]'][0].onclick();
  assert.match(box.innerHTML, /这个筛选下暂时没有内容/);
  assert.match(box.innerHTML, /换个榜单、分类或时间/);
  assert.doesNotMatch(box.innerHTML, /暂时读不到热榜/);
});

test('late results populate their cache without redrawing the current board', async () => {
  let resolveOld;
  const h = harness((url) => url.includes('kind=articles') ? new Promise((resolve) => { resolveOld = resolve; }) : Promise.resolve(board(manyItems())));
  const box = h.box(); let writes = 0, html = '';
  Object.defineProperty(box, 'innerHTML', { get: () => html, set: (value) => { writes++; html = value; } });
  box.controls['[data-xh-more]'] = [{}];
  h.render(box); await flush(); h.run("XH.kind='tweets'"); h.render(box); await flush();
  box.controls['[data-xh-more]'][0].onclick();
  const before = writes;
  resolveOld(board()); await flush();
  assert.equal(writes, before);
  assert.equal(visibleRows(box), 20);
  assert.equal(h.run('Object.keys(XH.data).length'), 2);
});

test('filter groups expose their selected state and background refresh preserves scroll', async () => {
  const h = harness(async () => board()); const box = h.box();
  h.run('window.scrollY=420; window.scrollX=0; window.scrollTo=(position)=>{window.lastScroll=position}');
  h.render(box); await flush();
  assert.match(box.innerHTML, /role="group" aria-label="榜单"/);
  assert.match(box.innerHTML, /aria-pressed="true" data-xh-kind="articles"/);
  assert.match(box.innerHTML, /aria-pressed="false" data-xh-kind="tweets"/);
  assert.match(box.innerHTML, /xh-filter-label">分类/);
  assert.equal(h.run('window.lastScroll.top'), 420);
});


test('the board opens on 持续在涨 with an hourly line and no time/sort filters', async () => {
  const rising = { ...item, kind: 'tweets', text: '一条一直有人看的推文', gained: 23456, hours: 12, trend: [0, 5, 9, 12, 20, 18, 22, 25, 30, 28, 31, 35, 33] };
  const h = harness(() => Promise.resolve({ ...board([rising]), kind: 'rising' }), { startOnRising: true });
  const box = h.box();
  h.render(box); await flush();
  assert.match(h.calls[0].url, /kind=rising/);
  assert.match(box.innerHTML, /aria-pressed="true" data-xh-kind="rising"/);
  assert.match(box.innerHTML, /近 10 小时 \+2\.3万 阅读/);
  assert.match(box.innerHTML, /class="xh-spark"/);
  assert.doesNotMatch(box.innerHTML, /data-xh-period/);
});
