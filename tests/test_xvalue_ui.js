const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/content_studio/static/xline.js', 'utf8');
const code = source.slice(source.indexOf('function xvPrepState('), source.indexOf('function xvValue('));
const ctx = vm.createContext({ esc: (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])) });
vm.runInContext(code, ctx);

test('only a running article spins; a failed one says so and offers 重做 (10/13)', () => {
  const failed = ctx.xvPrepState({ id: 'A0', prep: 'failed', prep_error: '写作命令失败（退出码 1）：ERROR: stream disconnected\n第二行' });
  assert.doesNotMatch(failed, /spin|在改写/);
  assert.match(failed, /data-xd-redo="A0"[^>]*>重做/);
  assert.match(failed, />没做成：写作命令失败（退出码 1）：ERROR: stream disconnected</);
  assert.match(ctx.xvPrepState({ id: 'A0', prep: 'running' }), /spin[\s\S]*在改写/);
  assert.match(ctx.xvPrepState({ id: 'A0', prep: null }), /排着/);
  assert.doesNotMatch(ctx.xvPrepState({ id: 'A0', prep: null }), /spin/);
  assert.match(ctx.xvPrepState({ id: 'A0', prep: 'ready' }), /data-xd-draft="A0">存进 X 草稿/);
});
