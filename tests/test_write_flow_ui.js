const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/content_studio/static/xline.js', 'utf8');
const code = source.slice(source.indexOf('const XD_FLOW ='), source.indexOf('/* 10/10 作者：发之前过一遍 QA'));
const MODULE = { ok: true, default: '流程1', flows: { 流程1: ['opening'], 流程2: ['opening'] }, custom: { 我的: ['opening'] } };
const ctx = vm.createContext({ window: { writeModule: () => MODULE }, esc: (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])), xlHm: (iso) => (iso ? '12:01' : '') });
vm.runInContext(code, ctx);
const row = (id, title, status, more = {}) => ({ id, title, status, at: null, rules: null, note: '', stale: false, runnable: true, gate_failures: [], report: null, ...more });
const live = { id: 'a', state: 'pending', prep: 'ready' };

test('articles without a record render nothing', () => {
  assert.equal(ctx.xdFlow({ id: 'a', state: 'pending' }), '');
});

test('each step is a row; gaps are counted and named, not hidden', () => {
  const html = ctx.xdFlow({ ...live, flow: [
    row('opening', '开头', 'bundled', { note: '没有单独跑' }), row('style', '11 条风格', 'ran', { at: '2026-10-12T11:25:00+08:00', rules: 'abc123' }),
    row('check-complete', '完整度五项', 'never', { note: 'QA 没跑过' }), row('scarcity', '稀缺', 'none', { runnable: false })], flow_stale: [] });
  assert.equal((html.match(/<li>/g) || []).length, 4);
  assert.match(html, /1 步跑了，2 步没单独跑或没过/);
  assert.match(html, /xd-fl-st bad">没跑过/);
  assert.doesNotMatch(html, /data-xd-step/);   // 第一轮是一次调用，没有每一步的按钮
  assert.match(html, /12:01 · 规则 abc123/);
  assert.doesNotMatch(html, /data-xd-rerun/);
});

test('a step that broke a gate shows why, and a report step can be opened', () => {
  const html = ctx.xdFlow({ ...live, flow: [row('style', '11 条风格', 'failed', { gate_failures: ['改动 20%，超过上限 10%'] }),
    row('density', '高密度骨架', 'ran', { report: ['第 1 段｜判断｜ok'] })] });
  assert.match(html, /xd-fl-fail"><li>改动 20%，超过上限 10%/);
  assert.match(html, /标了 1 段/);
});

test('no flow picker once the article is sent, compiled or still being made', () => {
  const flow = [row('style', '11 条风格', 'ran')];
  for (const x of [{ ...live, state: 'sent' }, { ...live, compiled: true }, { ...live, prep: 'running' }]) assert.doesNotMatch(ctx.xdFlow({ ...x, flow }), /data-xd-reflow/);
});

test('stale steps offer a rerun and a flow picker only while the article is waiting', () => {
  const flow = [row('check-complete', '完整度五项', 'ran', { stale: true })];
  const waiting = ctx.xdFlow({ ...live, flow, flow_stale: ['check-complete'] });
  assert.match(waiting, /data-xd-rerun="a"[^>]*>用新规则重跑/);
  assert.match(waiting, /data-xd-flow="a"[\s\S]*<option value="我的"/);   // 自己存的流程也能选
  const sent = ctx.xdFlow({ ...live, state: 'sent', flow, flow_stale: ['check-complete'] });
  assert.doesNotMatch(sent, /data-xd-rerun|data-xd-flow/);
  assert.match(sent, /规则改过/);
});

test('a tracked article whose round-one rules changed offers a redo of round one, not just a QA rerun', () => {
  const flow = [row('ending', '结尾钩子', 'ran', { stale: true })];
  const x = { ...live, flow, flow_stale: ['ending'], trk: { rules: { ending: 'abc' }, changes: [] } };
  const out = ctx.xdFlow(x);
  assert.match(out, /data-xd-redo1="a"[^>]*>用新规则重做第一轮/);
  assert.doesNotMatch(out, /data-xd-rerun/);
  // 只有检查那一步旧了：重跑检查就够
  const onlyQa = ctx.xdFlow({ ...x, flow: [row('check-typo', '错字', 'ran', { stale: true })], flow_stale: ['check-typo'] });
  assert.match(onlyQa, /data-xd-rerun="a"/);
  assert.doesNotMatch(onlyQa, /data-xd-redo1/);
});
