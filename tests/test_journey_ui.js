'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = (file) => fs.readFileSync(path.join(__dirname, '../src/content_studio/static', file), 'utf8');
const copy = (value) => JSON.parse(JSON.stringify(value));
function harness(api = async () => ({})) {
  const calls = [], notices = [], navigations = [], timers = [], nodes = {};
  const context = vm.createContext({
    window: {}, S: { view: 'work', workId: 1 }, console,
    esc: (value) => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
    renderMarkdown: (value) => value, day: (value) => value || '',
    localStorage: { getItem() { return null; } },
    navigator: { clipboard: { writeText: async () => {} } },
    featureOn: () => false, confirm: () => true,
    setTimeout: (fn) => { timers.push(fn); return timers.length; }, clearTimeout() {},
    $: (selector, el) => (el?.controls || nodes)[selector]?.[0] || null,
    $$: (selector, el) => (el?.controls || nodes)[selector] || [],
    api: (url, options) => { calls.push({ url, options: copy(options || {}) }); return api(url, options); },
    toast: (message) => notices.push(message), renderView() {},
    go: (view) => { navigations.push(view); context.S.view = view; },
  });
  vm.runInContext(source('video.js') + '\n' + source('board.js') + '\n' + source('mytopics.js'), context);
  const run = (code) => vm.runInContext(code, context);
  const box = () => ({ isConnected: true, innerHTML: '', controls: {
    '[data-document-status]': [{}], 'textarea': [{ value: '' }], '[data-document-save]': [{}], '[data-document-copy]': [{}],
    '[data-document-retry]': [{}], '[data-coupon-redo]': [{}], '[data-outline], [data-coupon-redo]': [{}],
    '[data-document-mode]': [{ dataset: { documentMode: 'preview' } }, { dataset: { documentMode: 'edit' } }],
  } });
  const active = (id, kind) => { context.S.workId = id; context.S.view = 'work'; run(`VD.topicId=${id};VD.tab=${JSON.stringify(kind)}`); };
  return { context, run, box, active, calls, notices, navigations, nodes, timers };
}

test('outline and coupon input drafts survive mode, tab and topic changes including empty text', () => {
  const h = harness();
  for (const kind of ['outline', 'coupon']) {
    h.active(1, kind); const el = h.box(); h.context.el = el;
    h.run(`Object.assign(workDocument(1, '${kind}'), { data: {markdown:'saved'}, mode:'edit' }); drawWorkDocument({id:1}, '${kind}', el, {redo(){}})`);
    const input = el.controls.textarea[0]; input.value = kind === 'coupon' ? '' : '  保留原话\n\n'; input.oninput();
    el.controls['[data-document-mode]'][0].onclick();
    h.active(2, kind); h.active(1, kind);
    h.run(`drawWorkDocument({id:1}, '${kind}', el, {redo(){}})`);
    assert.equal(h.run(`workDocumentText(workDocument(1,'${kind}'))`), input.value);
    assert.match(el.innerHTML, /未保存/);
    assert.equal(h.run(`workDocument(2,'${kind}').draft`), undefined);
  }
});

test('save failure retains exact text and retry sends the same topic and document payload', async () => {
  let fail = true;
  const h = harness(async () => { if (fail) throw new Error('离线'); return {}; });
  h.run("workDocument(1,'coupon').data={markdown:'old'};editWorkDocument(1,'coupon','  一字不改\\n\\n')");
  assert.equal(await h.run("saveWorkDocument(1,'coupon')"), false);
  assert.equal(h.run("workDocumentText(workDocument(1,'coupon'))"), '  一字不改\n\n');
  assert.match(h.run("workDocumentStatus(workDocument(1,'coupon'))"), /草稿已保留/);
  fail = false; await h.run("saveWorkDocument(1,'coupon')");
  assert.deepEqual(h.calls[1], { url: '/api/topics/1/coupon', options: { method: 'PUT', body: { markdown: '  一字不改\n\n' } } });
  assert.equal(h.run("workDocument(1,'coupon').draft"), undefined);
});

test('save acknowledgement preserves newer edits, even when reverted to the previous saved text', async () => {
  let finish;
  const h = harness(() => new Promise((resolve) => { finish = resolve; }));
  h.run("workDocument(1,'outline').data={markdown:'original'};editWorkDocument(1,'outline','first edit')");
  const pending = h.run("saveWorkDocument(1,'outline')");
  h.run("editWorkDocument(1,'outline','original')");
  h.active(2, 'outline'); h.run("workDocument(2,'outline').data={markdown:'other topic'}");
  finish({ markdown: 'first edit' }); await pending;
  assert.equal(h.run("workDocumentText(workDocument(1,'outline'))"), 'original');
  assert.equal(h.run("workDocument(1,'outline').draft"), 'original');
  assert.equal(h.run("workDocumentText(workDocument(2,'outline'))"), 'other topic');
});

test('late outline and coupon reads cannot paint another topic', async () => {
  for (const kind of ['outline', 'coupon']) {
    let finish;
    const h = harness(() => new Promise((resolve) => { finish = resolve; }));
    h.active(1, kind); const el = h.box(); h.context.el = el;
    const pending = h.run(`window.VIDEO_TABS.find(t=>t.key==='${kind}').render({id:1,outline_path:'yes'},el)`);
    h.active(2, kind); el.innerHTML = 'topic two';
    finish(kind === 'outline' ? { markdown: 'topic one' } : { coupon: { markdown: 'topic one' } }); await pending;
    assert.equal(el.innerHTML, 'topic two');
    assert.equal(h.run('VD.outline'), null);
    assert.equal(h.run('CPN.data'), null);
  }
});

test('a stale coupon GET cannot overwrite a completed save', async () => {
  let finishRead;
  const h = harness((url, options) => options?.method === 'PUT' ? Promise.resolve({}) : new Promise((resolve) => { finishRead = resolve; }));
  h.active(1, 'coupon'); const el = h.box(); h.context.el = el;
  h.run("workDocument(1,'coupon').data={markdown:'old'};editWorkDocument(1,'coupon','new')");
  const read = h.run("window.VIDEO_TABS.find(t=>t.key==='coupon').render({id:1},el)");
  await h.run("saveWorkDocument(1,'coupon')");
  finishRead({ coupon: { markdown: 'old' } }); await read;
  assert.equal(h.run("workDocumentText(workDocument(1,'coupon'))"), 'new');
  assert.match(el.innerHTML, /new/);
});

test('rail write / cut / publish open the item in progress at that step; nothing in progress goes to find (10/20)', async () => {
  const h = harness();
  assert.equal(h.run("zxIndex('outline')"), 0);
  assert.equal(h.run("zxIndex('record')"), 1);
  assert.equal(h.run("zxIndex('edit')"), 1);
  assert.equal(h.run("zxIndex('ready')"), 2);
  h.run("BD.data = { focus: { id: 3, title: 't', stage: 'edit', next: { mine: true } }, cards: [] }");
  await h.run("window.goStage('fa')"); assert.equal(h.context.S.packId, 3); assert.equal(h.navigations.at(-1), 'pack');
  await h.run("window.goStage('cut')"); assert.deepEqual(copy(h.run('VD.requested')), { id: 3, tab: 'edit' }); assert.equal(h.navigations.at(-1), 'work');
  await h.run("window.goStage('write')"); assert.deepEqual(copy(h.run('VD.requested')), { id: 3, tab: 'write' });
  await h.run("window.goStage(null)"); assert.deepEqual(copy(h.run('VD.requested')), { id: 3, tab: 'edit' }, 'no step given = where the item is now');
  let picked = null; h.context.window.openInputTab = (tab) => { picked = tab; };
  h.run("BD.data = { focus: null, cards: [] }");
  await h.run("window.goStage('cut')"); assert.equal(picked, 'mine'); assert.match(h.notices.at(-1), /做这条/);
  let captured;
  h.context.window.captureWorkOrigin = (id) => { captured = { id, view: h.context.S.view }; };
  h.context.S.view = 'input'; h.run("openWork(2,'coupon')");
  assert.deepEqual(captured, { id: 2, view: 'input' });
  assert.deepEqual(copy(h.run('VD.requested')), { id: 2, tab: 'coupon' });
});

test('my topics: do-this is the only way in, greyed out while another one is in the pipeline', async () => {
  const data = { focus: { id: 1, title: '正在做的', stage: 'outline' }, held: '《正在做的》还没发完。一次只做一条', trash: [{ id: 9, title: '不做了的那条' }],
    pool: [{ id: 2, title: '有原话的', words: true }, { id: 3, title: '别人的材料', words: false, skeleton: false, start: 'focus' }] };
  const h = harness(async () => data);
  const body = { innerHTML: '', dataset: {}, controls: {} };
  await h.run('(b) => window.renderMyTopics(b, () => "")')(body);
  assert.match(body.innerHTML, /正在做<\/small><b>正在做的/);
  assert.equal((body.innerHTML.match(/data-my-do="\d+" disabled/g) || []).length, 2);  // 一次只做一条：别的都是灰的
  assert.doesNotMatch(body.innerHTML, /换成这条|排期|日历/);
  assert.match(body.innerHTML, /别人的材料 · 做的时候先口述一遍/);
  assert.match(body.innerHTML, /不做了的 1 条/);
  h.run('MY.data = null'); data.focus = null; data.held = null;
  body.dataset.sig = '';
  await h.run('(b) => window.renderMyTopics(b, () => "")')(body);
  assert.match(body.innerHTML, /现在没有正在做的/);
  assert.equal((body.innerHTML.match(/disabled/g) || []).length, 0);
});


test('return after an unobserved background rewrite revalidates outline without discarding local drafts', async () => {
  let markdown = '旧骨架';
  const h = harness(async (url, options) => {
    if (options?.method === 'POST') { markdown = '后台新骨架'; return {message:'完成'}; }
    return {markdown};
  });
  h.active(1, 'outline'); const el = h.box(); h.context.el = el;
  h.run('window.refreshTopics=null');
  const render = () => h.run("window.VIDEO_TABS.find(t=>t.key==='outline').render({id:1,outline_path:'yes'},el)");
  await render(); assert.match(el.innerHTML, /旧骨架/);
  await h.run('startOutline(1)');
  h.active(2, 'outline'); h.active(1, 'outline');
  h.run('window.invalidateWork()'); await render();
  assert.match(el.innerHTML, /后台新骨架/); assert.doesNotMatch(el.innerHTML, /旧骨架/);
  h.run("editWorkDocument(1,'outline','我的未保存改动')");
  markdown = '又一次后台更新'; await render();
  assert.equal(h.run("workDocument(1,'outline').data.markdown"), '又一次后台更新');
  assert.equal(h.run("workDocumentText(workDocument(1,'outline'))"), '我的未保存改动');
  assert.match(el.innerHTML, /我的未保存改动/);
});

test('failed coupon read labels cached content, retries the GET and preserves the exact local draft', async () => {
  let fail = true;
  const h = harness(async () => { if (fail) throw new Error('读取超时'); return {coupon:{markdown:'服务器新稿'},error:'生成中断'}; });
  h.active(1,'coupon'); const el = h.box(); h.context.el = el;
  h.context.draftText = '  还没保存\n';
  h.run("workDocument(1,'coupon').data={markdown:'已缓存'};editWorkDocument(1,'coupon',draftText)");
  await h.run("window.VIDEO_TABS.find(t=>t.key==='coupon').render({id:1},el)");
  assert.match(el.innerHTML, /读取最新密度失败：读取超时/);
  assert.match(el.innerHTML, /当前内容和草稿已保留/);
  assert.equal(h.run("workDocumentText(workDocument(1,'coupon'))"), '  还没保存\n');
  fail = false; await el.controls['[data-document-retry]'][0].onclick();
  assert.equal(h.calls.filter(call=>call.url==='/api/topics/1/coupon').length,2);
  assert.doesNotMatch(el.innerHTML, /读取超时/);
  assert.match(el.innerHTML, /上一次重写未完成：生成中断/);
  assert.equal(h.run("workDocumentText(workDocument(1,'coupon'))"), '  还没保存\n');
});

test('cached coupon after read failure still binds a real guarded rewrite action', async () => {
  const h = harness(async (url, options) => { if (options?.method==='POST') return {message:'已开始重写'}; throw new Error('读取失败'); });
  h.active(1,'coupon'); const el=h.box(); h.context.el=el;
  h.run("workDocument(1,'coupon').data={markdown:'旧稿'}");
  await h.run("window.VIDEO_TABS.find(t=>t.key==='coupon').render({id:1},el)");
  await el.controls['[data-coupon-redo]'][0].onclick({target:{}});
  assert.equal(h.calls.at(-1).url,'/api/topics/1/coupon');
  assert.equal(h.calls.at(-1).options.method,'POST');
  assert.equal(h.notices.at(-1),'已开始重写');
});

test('the rail marks done steps, the current step, and greys everything out when nothing is in progress (10/20)', () => {
  const h = harness();
  const el = () => { const set = new Set(); return { set, classList: { toggle: (k, on) => (on ? set.add(k) : set.delete(k)) }, innerHTML: '', hidden: false, textContent: '' }; };
  for (const k of ['write', 'cut', 'fa']) h.nodes[`.rail [data-zx="${k}"]`] = [el()];
  for (const id of ['#navWrite', '#navCut', '#navFa', '#railNow', '#railNowTitle']) h.nodes[id] = [el()];
  const cls = (k) => [...h.nodes[`.rail [data-zx="${k}"]`][0].set].sort().join(' ');
  h.run("paintRailStages({ focus: { id: 1, title: '你用AI不赚钱', stage: 'ready', next: { mine: true } } })");
  assert.equal(cls('write'), 'done'); assert.equal(cls('cut'), 'done'); assert.equal(cls('fa'), 'now');
  assert.equal(h.nodes['#railNowTitle'][0].textContent, '你用AI不赚钱'); assert.equal(h.nodes['#railNow'][0].hidden, false);
  h.run("paintRailStages({ focus: { id: 1, title: 't', stage: 'record', next: { mine: true } } })");
  assert.equal(cls('write'), 'done'); assert.equal(cls('cut'), 'now'); assert.equal(cls('fa'), '');
  h.run("paintRailStages({ focus: null })");
  assert.equal(cls('write'), 'idle'); assert.equal(cls('fa'), 'idle'); assert.equal(h.nodes['#railNow'][0].hidden, true);
});
