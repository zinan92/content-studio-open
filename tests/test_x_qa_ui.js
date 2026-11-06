const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/content_studio/static/app.js', 'utf8');
const loader = source.slice(source.indexOf('async function loadXqaRules()'), source.indexOf('/* 写作 skill 的空位：'));
const paint = source.slice(source.indexOf('function paintSettingsTabs()'), source.indexOf("$$('#setTabs button').forEach((b) => (b.onclick"));
const saved = (more = {}) => ({ path: '/tmp/config/X 发前 QA.md', save_path: '/tmp/config/X 发前 QA.md', text: '规则正文', bundled: false, resettable: true, ...more });
const flush = () => new Promise(resolve => setImmediate(resolve));
function harness(api, enabled = true) {
  const nodes = Object.fromEntries(['xqaPanel', 'xqaForm', 'xqaText', 'xqaPath', 'xqaReset', 'xqaNote'].map(id => [`#${id}`, { dataset: {}, value: '', textContent: '', hidden: false }]));
  const save = { disabled: false };
  nodes['#xqaForm'].querySelector = () => save;
  const calls = [], toasts = [];
  const ctx = vm.createContext({
    $: id => nodes[id], $$: () => [], document: { activeElement: null }, window: {},
    SET: { tab: 'flow' }, SET_TABS: ['general', 'flow'],
    featureOn: key => key !== 'xline' || enabled, confirm: () => true,
    toast: message => toasts.push(message),
    api: (url, opts) => { calls.push({ url, opts }); return api(url, opts); },
  });
  vm.runInContext(loader + '\n' + paint, ctx);
  return { ctx, nodes, calls, toasts, save, load: () => ctx.loadXqaRules(), paint: () => ctx.paintSettingsTabs() };
}
const edit = (h, text) => { h.nodes['#xqaText'].value = text; h.nodes['#xqaText'].oninput(); };
const submit = h => h.nodes['#xqaForm'].onsubmit({ preventDefault() {} });

test('flow tab loads once, shows path and bundled label, and feature off makes no request', async () => {
  const h = harness(async () => saved({ bundled: true, resettable: false }));
  h.paint(); h.paint(); await flush();
  assert.equal(h.calls.length, 1);
  assert.equal(h.nodes['#xqaText'].value, '规则正文');
  assert.match(h.nodes['#xqaPath'].textContent, /（自带的通用版）$/);
  assert.equal(h.nodes['#xqaReset'].hidden, true);
  const off = harness(async () => { throw new Error('disabled'); }, false);
  off.paint(); await off.load();
  assert.equal(off.calls.length, 0);
});

test('loading never overwrites focused or dirty text', async () => {
  for (const mode of ['focused', 'dirty']) {
    let resolve;
    const h = harness(() => new Promise(r => { resolve = r; }));
    const pending = h.load();
    h.nodes['#xqaText'].value = '正在输入';
    if (mode === 'focused') h.ctx.document.activeElement = h.nodes['#xqaText'];
    else h.nodes['#xqaText'].oninput();
    resolve(saved()); await pending;
    assert.equal(h.nodes['#xqaText'].value, '正在输入');
  }
});

test('save sends edited text and only clears dirty state for the saved version', async () => {
  let resolve;
  const h = harness(async (_, opts) => opts ? new Promise(r => { resolve = r; }) : saved());
  await h.load(); edit(h, '我自己的规则');
  const saving = submit(h);
  assert.equal(h.save.disabled, true);
  assert.equal(h.calls[1].opts.method, 'PUT');
  assert.equal(h.calls[1].opts.body.text, '我自己的规则');
  edit(h, '我在保存时又改了');
  resolve(saved({ text: '我自己的规则' })); await saving;
  assert.equal(h.nodes['#xqaText'].value, '我在保存时又改了');
  assert.equal(h.nodes['#xqaText'].dataset.dirty, '1');
  assert.equal(h.save.disabled, false);
  const next = submit(h);
  resolve(saved({ text: '我在保存时又改了' })); await next;
  assert.equal(h.nodes['#xqaText'].dataset.dirty, undefined);
  assert.equal(h.toasts.at(-1), 'QA 规则存好了，下一篇就按新的');
});

test('reset requires confirmation and refills the bundle; errors preserve edits', async () => {
  let failing = false;
  const h = harness(async (_, opts) => {
    if (failing) throw new Error('保存失败');
    return opts?.method === 'DELETE' ? saved({ text: '自带规则', bundled: true, resettable: false }) : saved();
  });
  await h.load();
  assert.equal(h.nodes['#xqaReset'].hidden, false);
  edit(h, '尚未保存');
  h.ctx.confirm = () => false;
  await h.nodes['#xqaReset'].onclick();
  assert.equal(h.calls.length, 1);
  h.ctx.confirm = () => true;
  await h.nodes['#xqaReset'].onclick();
  assert.equal(h.calls[1].opts.method, 'DELETE');
  assert.equal(h.nodes['#xqaText'].value, '自带规则');
  assert.equal(h.nodes['#xqaReset'].hidden, true);
  edit(h, '保存不能丢掉'); failing = true;
  await submit(h);
  assert.equal(h.nodes['#xqaText'].value, '保存不能丢掉');
  assert.equal(h.nodes['#xqaText'].dataset.dirty, '1');
  assert.equal(h.nodes['#xqaNote'].textContent, '保存失败');
});

test('failed reads can retry without losing the draft', async () => {
  let fail = true;
  const h = harness(async () => { if (fail) throw new Error('读取失败'); return saved(); });
  await h.load();
  assert.equal(h.nodes['#xqaPanel'].dataset.loaded, undefined);
  edit(h, '读取失败后自己填的'); fail = false;
  await h.load();
  assert.equal(h.nodes['#xqaText'].value, '读取失败后自己填的');
  assert.equal(h.nodes['#xqaText'].dataset.dirty, '1');
});


test('reverting to the old baseline while saving still preserves that newer edit', async () => {
  let resolve;
  const h = harness(async (_, opts) => opts ? new Promise(r => { resolve = r; }) : saved());
  await h.load(); edit(h, '提交的新规则');
  const pending = submit(h);
  edit(h, '规则正文');
  assert.equal(h.nodes['#xqaText'].dataset.dirty, undefined);
  resolve(saved({ text: '提交的新规则' })); await pending;
  assert.equal(h.nodes['#xqaText'].value, '规则正文');
  assert.equal(h.nodes['#xqaText'].dataset.dirty, '1');
});
