const test = require('node:test');
const assert = require('node:assert/strict');
const ui = require('../src/content_studio/static/ui-state.js');
test('failed video links explain recovery without claiming a cause is certain', () => {
  assert.match(ui.failureHint('API refused and web page does not open it: private, removed or restricted'), /原链接/);
  assert.match(ui.failureHint('cookie expired'), /可能已过期/);
  assert.match(ui.failureHint('unknown stage crash'), /错误详情/);
  assert.match(ui.failureHint('network timeout'), /检查网络/);
});
test('content returns to its source while internal step changes preserve that origin', () => {
  const origins = ui.createWorkOrigins();
  origins.capture(12, {view: 'board', hash: '#board', scrollY: 620});
  origins.capture(12, {view: 'work', hash: '#work/12', scrollY: 0});
  assert.equal(origins.label(12), '正在做的');  // 10/20：加工中那一页没了，旧书签落到正在做的那一步
  assert.equal(origins.get(12).scrollY, 620);
  origins.capture(13, {view:'input',hash:'#input',scrollY:100});
  assert.equal(origins.label(13), '找');
  assert.equal(origins.get(12).hash,'#board');
  assert.equal(origins.get(99).view,'board');
});
