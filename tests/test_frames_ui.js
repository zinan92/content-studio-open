const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  const nodes = Object.fromEntries(['frameOne', 'frameSeries', 'framesMsg', 'frameEditor', 'frameName', 'framePath', 'frameText', 'frameMsg', 'frameSave', 'frameCancel'].map(id => [id, {hidden: true, textContent: '', value: ''}]));
  const one = [{dataset: {frameKey: 'skeleton'}}, {dataset: {frameKey: 'coupon'}}];
  const series = [{dataset: {frameFolder: '系列1 示例'}}];
  const pending = [];
  const ctx = vm.createContext({window: {}, URLSearchParams,
    $: s => nodes[s.slice(1)], $$: s => s === '[data-frame-key]' ? one : series,
    esc: s => String(s).replaceAll('<', '&lt;'),
    api: (url, options) => new Promise((resolve, reject) => pending.push({url, options, resolve, reject}))});
  vm.runInContext(fs.readFileSync(require.resolve('../src/content_studio/static/frames.js'), 'utf8'), ctx);
  const data = {layer_one: [{key: 'skeleton', label: '一勾式骨架', file: '一勾式骨架.md'}], series: [{folder: '系列1 示例', path: '~/系列框架/系列1 示例.md', has_frame: false}]};
  async function load() { const done = ctx.window.loadFrames(); pending.shift().resolve(data); await done; }
  async function open() { const done = series[0].onclick(); pending.shift().resolve({name: '系列1 示例.md', path: '~/系列框架/系列1 示例.md', body: '# 初稿'}); await done; }
  return {nodes, one, series, pending, ctx, data, load, open};
}

test('loads once and switching back preserves unsaved edits; save keeps exact Markdown', async () => {
  const h = harness(); await h.load(); await h.open();
  const text = '---\nkey: value\n---\n# 规则\n尾部空格  \n';
  h.nodes.frameText.value = text;
  await h.ctx.window.loadFrames();
  assert.equal(h.pending.length, 0);
  assert.equal(h.nodes.frameText.value, text);
  const saving = h.nodes.frameSave.onclick();
  const put = h.pending.shift();
  assert.equal(put.options.method, 'PUT');
  assert.deepEqual(JSON.parse(put.options.body), {kind: 'series', folder: '系列1 示例', text});
  put.resolve({}); await new Promise(resolve => setImmediate(resolve));
  h.pending.shift().resolve(h.data); await saving;
  assert.equal(h.nodes.frameMsg.textContent, '已保存');
  assert.equal(h.nodes.frameText.readOnly, false);
  h.nodes.frameCancel.onclick(); assert.equal(h.nodes.frameEditor.hidden, true);
});

test('empty text makes no request and failed save retains the draft for retry', async () => {
  const h = harness(); await h.load(); await h.open();
  h.nodes.frameText.value = ' \n'; await h.nodes.frameSave.onclick();
  assert.equal(h.pending.length, 0); assert.equal(h.nodes.frameMsg.textContent, '内容是空的');
  h.nodes.frameText.value = '新内容';
  const save = h.nodes.frameSave.onclick();
  await h.one[0].onclick(); // Saving cannot switch the destination underneath the request.
  assert.equal(h.pending.length, 1);
  h.pending.shift().reject(new Error('写入失败')); await save;
  assert.equal(h.nodes.frameText.value, '新内容');
  assert.equal(h.nodes.frameMsg.textContent, '写入失败');
  assert.equal(h.nodes.frameSave.disabled, false);
});

test('late document response cannot overwrite the more recently selected file', async () => {
  const h = harness(); await h.load();
  const first = h.one[0].onclick(), second = h.one[1].onclick();
  const [a, b] = h.pending.splice(0);
  b.resolve({name: '付息稿.md', path: '~/付息稿.md', body: '付息规则'}); await second;
  a.resolve({name: '一勾式骨架.md', path: '~/一勾式骨架.md', body: '骨架规则'}); await first;
  assert.equal(h.nodes.frameName.textContent, '付息稿.md');
  assert.equal(h.nodes.frameText.value, '付息规则');
});
