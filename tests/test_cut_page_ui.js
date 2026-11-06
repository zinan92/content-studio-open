'use strict';
/* 剪辑页简化（10/19 作者「简单一点」）：卡住那行只在有东西在跑时出现；文件夹名对不上只是一行小字。 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = (file) => fs.readFileSync(path.join(__dirname, '../src/content_studio/static', file), 'utf8');

function harness(reply) {
  const nodes = {};
  const context = vm.createContext({
    window: { VIDEO_TABS: [], addEventListener() {} }, document: { addEventListener() {} }, S: { view: 'work' }, VD: { tab: 'edit', topicId: 1 }, console,
    esc: (v) => String(v ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
    day: (v) => v || '', featureOn: () => true, localStorage: { getItem: () => null, setItem() {} },
    setTimeout: () => 0, clearTimeout() {}, renderView() {}, toast() {},
    $: (sel) => nodes[sel] || null, $$: () => [],
    api: async (url) => reply(url),
  });
  vm.runInContext(source('videoproject.js'), context);
  return { context, nodes, run: (code) => vm.runInContext(code, context) };
}

test('the activity line stays hidden unless something is working in the project', async () => {
  for (const [state, workers, hidden] of [['stalled', [], true], ['idle', [], true], ['working', [{ kind: 'codex', elapsed: '3:00', command: 'x' }], false], ['stalled', [{ kind: 'claude', elapsed: '1:00', command: 'y' }], false]]) {
    const h = harness(() => ({ state, say: '说明', step: 8, step_minutes: 33, last_write: { path: 'part-a-hook/edit.json', seconds_ago: 1980 }, workers }));
    h.nodes['#vpAct'] = { hidden: false, innerHTML: '' };
    await h.run('renderActivity({ id: 1 })');
    assert.equal(h.nodes['#vpAct'].hidden, hidden, `${state} with ${workers.length} workers`);
    assert.ok(!h.nodes['#vpAct'].innerHTML.includes('part-a-hook/edit.json'), 'no file paths in the line');
  }
});

test('a folder name that does not match the title is one small inline note, not a banner', () => {
  const h = harness(() => ({}));
  const box = { innerHTML: '', parentElement: null };
  h.context.box = box;
  h.run(`VP.draft = {}; renderPlan({ id: 1, title: '一人公司的第一个客户从哪来' }, { project: '2026-10-18_工作台复盘', has_video: true, locked: true,
    plan: { hook: true, motion: true }, blocks: [{ key: 'words', label: '逐字稿', state: 'done' }, { key: 'hook', label: 'Hook', state: 'current' }] }, box)`);
  assert.ok(box.innerHTML.includes('cut-proj') && box.innerHTML.includes('名字对不上'));
  assert.ok(!box.innerHTML.includes('banner'));
  // 10/20 一条内容一个名字：对得上时文件夹名不露出来
  h.run(`renderPlan({ id: 2, title: '工作台复盘' }, { project: '2026-10-18_工作台复盘', has_video: true, locked: true,
    plan: { hook: true, motion: true }, blocks: [{ key: 'words', label: '逐字稿', state: 'done' }] }, box)`);
  assert.ok(!box.innerHTML.includes('2026-10-18_工作台复盘'));
});
