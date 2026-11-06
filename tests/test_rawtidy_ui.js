const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/content_studio/static/rawtidy.js', 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
function harness(api) {
  const nodes = Object.fromEntries(['run', 'status', 'records'].map(k => [`[data-rt-${k}]`, {}]));
  const handlers = {}, calls = [], timers = [], toasts = [];
  let open;
  const dialog = {open: false, setAttribute() {}, querySelector: q => nodes[q],
    addEventListener: (event, fn) => { handlers[event] = fn; },
    showModal() { this.open = true; }, close() { this.open = false; handlers.close(); }};
  vm.runInNewContext(source, {
    document: {createElement: () => dialog, body: {append() {}}, addEventListener: (_, fn) => { open = fn; }},
    api: async (url, opts) => { calls.push({url, opts}); return api(url, opts); },
    esc: s => String(s).replaceAll('<', '&lt;'), toast: s => toasts.push(s),
    setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout() {}, encodeURIComponent,
  });
  const click = (attr, id) => handlers.click({target: {closest: () => ({
    disabled: false, hasAttribute: a => a === attr, dataset: {rtUndo: id},
  })}});
  return {nodes, dialog, calls, timers, toasts, click,
    open: () => open({target: {closest: () => true}, preventDefault() {}})};
}

test('panel polls while busy and shows ratios, previews, discarded reasons and undone status', async () => {
  let busy = true;
  const h = harness(async () => ({busy, records: [{id: 'one', type: 'merge', undone: true,
    source_titles: ['原篇'], change_ratio: .02, coverage: .99, outputs: [{title: '新篇', preview: '<原话>'}]}],
    results: [{group: 2, status: 'discarded', reason: '覆盖不足'}]}));
  h.open(); await flush();
  assert.equal(h.dialog.open, true);
  assert.equal(h.nodes['[data-rt-run]'].disabled, true);
  assert.match(h.nodes['[data-rt-status]'].innerHTML, /rawtidy-spinner/);
  assert.match(h.nodes['[data-rt-records]'].innerHTML, /改了 2.0%，覆盖 99.0%/);
  assert.match(h.nodes['[data-rt-records]'].innerHTML, /&lt;原话>/);
  assert.match(h.nodes['[data-rt-records]'].innerHTML, /disabled>已撤回/);
  assert.match(h.nodes['[data-rt-records]'].innerHTML, /覆盖不足/);
  busy = false; await h.timers.at(-1)();
  assert.equal(h.nodes['[data-rt-run]'].disabled, false);
  await h.click('data-rt-close');
  assert.equal(h.dialog.open, false);
});

test('run sends limit 5; undo posts record id and refreshes; errors remain visible', async () => {
  let error = false;
  const h = harness(async (_, opts) => {
    if (error && opts) throw new Error('来源已经变化');
    return {busy: false, records: []};
  });
  h.open(); await flush();
  await h.click('data-rt-run');
  assert.equal(h.calls[1].url, '/api/rawtidy/run');
  assert.equal(h.calls[1].opts.body.limit, 5);
  await h.click('data-rt-undo', 'one');
  assert.equal(h.calls[3].url, '/api/rawtidy/one/undo');
  assert.equal(h.calls[3].opts.method, 'POST');
  error = true; await h.click('data-rt-run');
  assert.equal(h.toasts.at(-1), '来源已经变化');
});
