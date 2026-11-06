'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/content_studio/static/input.js'), 'utf8');
const flush = () => new Promise((resolve) => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const noteItem = (name, source = 'saved') => ({ path: `${name}.md`, title: name, source, source_label: source, summary: '摘要', modified_at: '2026-10-08T12:00:00', triage: null });
const inbox = (items = []) => ({ items, since: '2026-10-08' });
const issue = (path) => ({ path, title: `日报-${path}`, day: '2026-10-08', is_today: true, sections: [], history: [{ path, day: '2026-10-08' }] });
function harness(api) {
  const body = { innerHTML: '', dataset: {}, isConnected: true, controls: {}, querySelector: () => null, contains: () => false };
  const nav = {}, calls = [], routes = [], notices = [], storage = new Map(); let renders = 0;
  const context = vm.createContext({
    window: { VIEWS: {}, innerWidth: 1440, scrollY: 100, scrollTo: () => {} },
    document: { activeElement: null }, URLSearchParams, Date, console,
    S: { view: 'input', state: { vault: { ok: true }, daily_sources: [{ key: 'ai_daily', label: 'AI 日报' }] } },
    api: (url, opts) => { calls.push({ url, opts }); return api(url, opts); },
    $: (selector, root = body) => selector === '#inputBody' ? body : selector === '#navIn' ? nav : (root.controls[selector] || [])[0] || null,
    $$: (selector, root = body) => root.controls[selector] || [],
    esc: (s) => String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
    xcBtn: () => '<button class="xc-btn">发 X</button>', fmt: String, cleanTitle: (s) => s,
    toast: (message) => notices.push(message), renderView: () => { renders++; },
    go: (view) => { routes.push(view); context.S.view = view; },
    localStorage: { getItem: (key) => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) },
  });
  vm.runInContext(source, context);
  vm.runInContext("C.tab = 'all'", context);  // 10/19 起默认落在「我的选题」（mytopics.js，这里没加载）；这些测的是来源列表
  return { body, context, calls, routes, notices, get renders() { return renders; }, run: (s) => vm.runInContext(s, context), render: () => context.window.VIEWS.input.render() };
}

test('late inbox success never auto-opens a note or navigates after leaving input', async () => {
  const pending = deferred(); const h = harness(() => pending.promise);
  const rendering = h.render(); await flush();
  h.run("S.view='settings'"); const before = h.body.innerHTML;
  pending.resolve(inbox([noteItem('旧文章')])); await rendering;
  assert.equal(h.context.S.view, 'settings'); assert.deepEqual(h.routes, []);
  assert.equal(h.run('C.open'), null); assert.equal(h.body.innerHTML, before);
  assert.equal(h.run('C.items[0].title'), '旧文章', 'read cache remains usable');
  assert.equal(h.calls.length, 1);
});

test('a late inbox failure cannot replace a different page with an error', async () => {
  const pending = deferred(); const h = harness(() => pending.promise);
  const rendering = h.render(); await flush(); h.run("S.view='settings'");
  h.body.innerHTML = '设置页面'; pending.reject(new Error('旧错误')); await rendering;
  assert.equal(h.body.innerHTML, '设置页面'); assert.deepEqual(h.routes, []);
});

test('switching source tabs while loading only selects a note from the current source', async () => {
  const pending = deferred(); const h = harness((url) => url.includes('/inbox?') ? pending.promise : Promise.resolve({ title: '原话', path: '原话.md', body: '原话正文' }));
  const older = h.render(); await flush(); h.run("C.tab='clipping'"); const newer = h.render();
  pending.resolve(inbox([noteItem('收藏'), noteItem('原话', 'clipping')])); await Promise.all([older, newer]); await flush();
  assert.equal(h.run('C.open'), '原话.md');
  assert.equal(h.calls.filter((c) => c.url.includes('/inbox?')).length, 1);
  assert.equal(h.calls.filter((c) => c.url.includes('/note?')).length, 1);
  assert.match(h.calls.find((c) => c.url.includes('/note?')).url, /%E5%8E%9F%E8%AF%9D/);
});

test('slower old note cannot overwrite a later selected note or its error state', async () => {
  const a = deferred(), b = deferred();
  const h = harness((url) => url.includes('a.md') ? a.promise : url.includes('b.md') ? b.promise : Promise.resolve(inbox()));
  const older = h.run("openNote('a.md')"); const newer = h.run("openNote('b.md')");
  b.resolve({ title: '文章 B', path: 'b.md', body: 'B 原文' }); await newer;
  const before = h.renders; a.reject(new Error('A 失败')); await older;
  assert.equal(h.run('C.open'), 'b.md'); assert.equal(h.run('C.note.body'), 'B 原文');
  assert.equal(h.renders, before);
  await h.render(); assert.match(h.body.innerHTML, /B 原文/); assert.doesNotMatch(h.body.innerHTML, /A 失败/);
});

test('note completion after changing tabs does not replace the new source selection', async () => {
  const a = deferred(); const h = harness(() => a.promise);
  const older = h.run("openNote('a.md')"); h.run("C.tab='clipping'; C.open=null; C.note=null");
  const before = h.renders; a.resolve({ title: '旧收藏', body: '旧正文' }); await older;
  assert.equal(h.run('C.note'), null); assert.equal(h.renders, before);
});

test('different day windows cache separately and stale background loads cannot overwrite a refresh', async () => {
  const day1 = deferred(), day7 = deferred();
  const h = harness((url) => url.includes('days=1') ? day1.promise : day7.promise);
  const old = h.run('loadInbox(false)'); h.run('C.days=7'); const current = h.run('loadInbox(false)');
  day7.resolve(inbox([noteItem('近七天')])); await current;
  day1.resolve(inbox([noteItem('一天')])); await old;
  assert.equal(h.run('C.items[0].title'), '近七天');
  h.run('C.days=1'); await h.run('loadInbox(false)');
  assert.equal(h.run('C.items[0].title'), '一天'); assert.equal(h.calls.length, 2);
  const stale = deferred(), fresh = deferred(); let n = 0;
  const f = harness(() => ++n === 1 ? stale.promise : fresh.promise);
  const x = f.run('loadInbox(false)'), y = f.run('loadInbox(true)');
  fresh.resolve(inbox([noteItem('新缓存')])); await y;
  stale.resolve(inbox([noteItem('旧缓存')])); await x;
  assert.equal(f.run('C.items[0].title'), '新缓存');
});

test('inbox invalidation prevents a pre-save response from restoring an obsolete cache', async () => {
  const old = deferred(), fresh = deferred(); let n = 0;
  const h = harness(() => ++n === 1 ? old.promise : fresh.promise);
  const older = h.run('loadInbox(false)'); h.run('window.invalidateInbox()'); const newer = h.run('loadInbox(false)');
  fresh.resolve(inbox([noteItem('刚收藏')])); await newer;
  old.resolve(inbox([])); await older;
  assert.equal(h.run('C.items[0].title'), '刚收藏');
});

test('late daily issue remains cached without replacing the selected notes tab', async () => {
  const pending = deferred(); const h = harness((url) => url.includes('/daily/issue?') ? pending.promise : Promise.resolve(inbox()));
  h.run("C.tab='ai_daily'"); const old = h.render(); await flush();
  h.run("C.tab='saved'"); await h.render(); const before = h.body.innerHTML;
  pending.resolve(issue('today')); await old;
  assert.equal(h.body.innerHTML, before); assert.equal(h.run('D.issue.ai_daily.path'), 'today');
});

test('old daily history response cannot replace the newer selected issue', async () => {
  const a = deferred(), b = deferred(); const h = harness((url) => url.includes('path=a') ? a.promise : b.promise);
  h.run("C.tab='ai_daily'; syncTabs(); D.path.ai_daily='a'"); const old = h.run("renderDaily($('#inputBody'))");
  h.run("D.path.ai_daily='b'"); const current = h.run("renderDaily($('#inputBody'))");
  b.resolve(issue('b')); await current; const before = h.body.innerHTML;
  a.resolve(issue('a')); await old;
  assert.equal(h.run('D.issue.ai_daily.path'), 'b'); assert.equal(h.body.innerHTML, before);
});

test('inbox and note failures offer working retries without losing source tabs', async () => {
  let reads = 0, notes = 0;
  const h = harness(async (url) => {
    if (url.includes('/inbox?')) { if (++reads === 1) throw new Error('暂不可用'); return inbox(); }
    if (++notes === 1) throw new Error('文件正同步'); return { path: 'a.md', title: '恢复的原文', body: '保留原文' };
  });
  h.body.controls['[data-in-retry]'] = [{}]; h.body.controls['[data-note-retry]'] = [{}];
  await h.render(); assert.match(h.body.innerHTML, /选题读取失败/); assert.match(h.body.innerHTML, /AI 日报/);
  h.body.controls['[data-in-retry]'][0].onclick(); assert.equal(h.renders, 1);
  await h.render(); assert.doesNotMatch(h.body.innerHTML, /选题读取失败/);
  await h.run("openNote('a.md')"); await h.render(); assert.match(h.body.innerHTML, /原文读取失败/);
  await h.body.controls['[data-note-retry]'][0].onclick(); await h.render();
  assert.match(h.body.innerHTML, /保留原文/); assert.doesNotMatch(h.body.innerHTML, /原文读取失败/);
});

test('feed responses cannot overwrite or populate a different selected tab', async () => {
  const pending = deferred(); const h = harness(() => pending.promise);
  h.run("C.tab='teacher'; syncTabs()"); const old = h.run("renderFeed($('#inputBody'), 'teacher')");
  h.run("C.tab='saved'"); h.body.innerHTML = '收藏列表';
  pending.resolve({ teacher: [], benchmark: [], accounts: { teacher: [], benchmark: [] }, counts: { teacher: { unseen: 0 }, benchmark: { unseen: 0 } } });
  await old; assert.equal(h.body.innerHTML, '收藏列表'); assert.equal(h.run('FD.data'), null);
});

test('K line completion after leaving input updates its cache without touching another view', async () => {
  const pending = deferred(); const h = harness(() => pending.promise);
  h.run("C.tab='kline'; S.state.daily_sources.push({key:'kline_daily',label:'K线日报'}); syncTabs()");
  const old = h.run("renderKline($('#inputBody'))"); h.run("S.view='settings'"); h.body.innerHTML = '设置';
  pending.resolve({ groups: [], count: 0 }); await old;
  assert.equal(h.body.innerHTML, '设置'); assert.equal(h.run('K.data.count'), 0);
});

test('note list uses distinct reading controls and preserves all secondary actions', async () => {
  const h = harness(async () => inbox([{ ...noteItem('收藏标题'), url: 'https://example.com/article' }]));
  h.run('window.innerWidth=800'); await h.render();
  assert.match(h.body.innerHTML, /button class="in-read"[^>]*data-note="收藏标题.md"/);
  assert.match(h.body.innerHTML, /data-pool="n:收藏标题.md">加入选题/);
  assert.match(h.body.innerHTML, /details class="in-more"/);
  assert.match(h.body.innerHTML, /data-mark="shot"/); assert.match(h.body.innerHTML, /data-mark="ignored"/);
  assert.match(h.body.innerHTML, /class="xc-btn"/); assert.match(h.body.innerHTML, /https:\/\/example.com\/article/);
  assert.match(h.body.innerHTML, /最近不含日报/);
  assert.match(h.body.innerHTML, /aria-selected="true"[^>]*data-tab="all"/);
});
