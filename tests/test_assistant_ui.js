'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/content_studio/static/anna.js'), 'utf8');

function harness(view, request = async () => { throw new Error('network unavailable'); }) {
  const listeners = {}, storage = new Map(), nodes = new Map();
  const document = { activeElement: null, addEventListener() {} };
  function node(id) {
    const classes = new Set(), attributes = new Map();
    const element = {
      hidden: false, inert: false, dataset: {},
      style: { setProperty(key, value) { this[key] = value; } },
      getBoundingClientRect() { return { left: context.window.innerWidth - 16 - (parseFloat(element.style.width) || 368), top: 16, width: parseFloat(element.style.width) || 368, height: context.window.innerHeight - 32 }; },
      classList: {
        toggle(key, on) { if (on) classes.add(key); else classes.delete(key); },
        remove(key) { classes.delete(key); },
        add(key) { classes.add(key); },
        contains(key) { return classes.has(key); },
      },
      setAttribute(key, value) { attributes.set(key, value); },
      removeAttribute(key) { attributes.delete(key); if (key === 'style') for (const field of Object.keys(element.style)) if (field !== 'setProperty') delete element.style[field]; },
      getAttribute(key) { return attributes.get(key); },
      focus() { document.activeElement = element; },
      click() { element.onclick?.(); },
    };
    nodes.set(id, element);
    return element;
  }
  document.body = node('body');
  const main = node('main'), box = node('#anna');
  node('#railAnna'); node('#railWendy');
  let markup = '';
  Object.defineProperty(box, 'innerHTML', {
    get() { return markup; },
    set(value) {
      markup = value;
      nodes.delete('[data-an-edge="w"]');
      if (value.includes('data-an-edge="w"')) node('[data-an-edge="w"]').dataset.anEdge = 'w';
      if (value.includes('class="an-h"')) node('.an-h');
      for (const key of ['#assistantClose', '#assistantRetry']) {
        nodes.delete(key);
        if (value.includes(`id="${key.slice(1)}"`)) node(key);
      }
    },
  });
  const context = vm.createContext({
    document, console, clearTimeout, setTimeout,
    window: { innerWidth: 390, innerHeight: 900, addEventListener(name, callback) { (listeners[name] ||= new Set()).add(callback); }, removeEventListener(name, callback) { listeners[name]?.delete(callback); } },
    localStorage: { getItem(key) { return storage.get(key) ?? null; }, setItem(key, value) { storage.set(key, value); }, removeItem(key) { storage.delete(key); } },
    S: { view, state: {} }, OUTPUT_FAMILY: ['output'],
    teamEnabled: true, featureOn: () => context.teamEnabled,
    $: (selector) => nodes.get(selector) || null,
    $$: (selector) => selector === '[data-an-edge]' ? [nodes.get('[data-an-edge="w"]')].filter(Boolean) : [],
    esc: (value) => String(value), api: request,
  });
  vm.runInContext(source, context);
  const run = (code) => vm.runInContext(code, context);
  const open = () => { run('WDP.open = true'); return run('renderAnna()'); };  // 10/12：Anna 停用，每一页右边都是 Wendy
  const escape = () => {
    let prevented = false;
    for (const listener of listeners.keydown || []) listener({ key: 'Escape', preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
  };
  return { main, box, document, nodes, storage, context, run, open, escape, listeners, dispatch(name, event = {}) { for (const callback of [...(listeners[name] || [])]) callback(event); } };
}

for (const [view, preference, rail] of [['today', 'cs-wendy', '#railWendy'], ['input', 'cs-wendy', '#railWendy']]) {
  for (const action of ['Escape', 'close button']) {
    test(`${view}: ${action} recovers the main page after assistant API failure`, async () => {
      const h = harness(view);
      await h.open();
      assert.equal(h.main.inert, true);
      assert.equal(h.box.hidden, false);
      assert.match(h.box.innerHTML, /network unavailable/);
      assert.equal(h.document.activeElement, h.nodes.get('#assistantClose'));
      if (action === 'Escape') h.escape(); else h.nodes.get('#assistantClose').click();
      assert.equal(h.main.inert, false);
      assert.equal(h.box.hidden, true);
      assert.equal(h.storage.get(preference), 'closed');
      assert.equal(h.document.activeElement, h.nodes.get(rail));
    });
  }
}

test('Escape closes an assistant before its API request settles', async () => {
  let reject;
  const h = harness('today', () => new Promise((_resolve, fail) => { reject = fail; }));
  const pending = h.open();
  assert.equal(h.main.inert, true);
  h.escape();
  assert.equal(h.main.inert, false);
  assert.equal(h.box.hidden, true);
  reject(new Error('late failure'));
  await pending;
  assert.equal(h.main.inert, false);
  assert.equal(h.box.hidden, true);
});

test('disabling the team feature releases an open drawer', async () => {
  const h = harness('input');
  await h.open();
  h.context.teamEnabled = false;
  await h.run('renderAnna()');
  assert.equal(h.main.inert, false);
  assert.equal(h.box.hidden, true);
});


function dragEvent(grip, x, pointerId=7) {
  return {button:0,clientX:x,pointerId,currentTarget:grip,preventDefault(){}};
}

test('desktop left-edge dragging stays right-anchored and updates the workspace reservation without touching chat',async()=>{
  const h=harness('input');h.context.window.innerWidth=1440;await h.open();
  const grip=h.nodes.get('[data-an-edge="w"]');const before=h.box.innerHTML;
  h.nodes.set('#anIn',{value:'还没发出的半句话'});
  grip.onpointerdown(dragEvent(grip,1000));h.dispatch('pointermove',{clientX:900,pointerId:7});
  assert.equal(h.box.style.width,'468px');assert.equal(h.box.style.right,'16px');assert.equal(h.box.style.left,'auto');
  assert.equal(h.document.body.style['--anna-width'],'468px');assert.equal(h.box.innerHTML,before);assert.equal(h.nodes.get('#anIn').value,'还没发出的半句话');
  assert.equal(h.box.getBoundingClientRect().left+h.box.getBoundingClientRect().width,1424);
  h.dispatch('pointerup',{pointerId:7});assert.equal(JSON.parse(h.storage.get('cs-anna-geom')).w,468);assert.equal(h.box.classList.contains('an-dragging'),false);
  assert.equal(h.listeners.pointermove.size,0);assert.equal(h.main.inert,false);
});

test('only the left edge resizes, unrelated pointers are ignored, and cancel restores the starting width',async()=>{
  const h=harness('input');h.context.window.innerWidth=1280;await h.open();const grip=h.nodes.get('[data-an-edge="w"]');
  assert.equal(h.nodes.get('.an-h').onpointerdown,null);
  h.context.event=dragEvent(grip,900);h.context.resizeBox=h.box;
  h.run("startAnnaGesture(event,resizeBox,'move');startAnnaGesture(event,resizeBox,'e')");assert.equal(h.listeners.pointermove?.size || 0,0);
  grip.onpointerdown(h.context.event);h.dispatch('pointermove',{clientX:100,pointerId:8});assert.equal(h.box.style.width,'368px');
  h.dispatch('pointermove',{clientX:800,pointerId:7});assert.equal(h.box.style.width,'468px');
  h.dispatch('pointercancel',{pointerId:7});assert.equal(h.box.style.width,'368px');assert.equal(h.storage.has('cs-anna-geom'),false);
  assert.equal(h.listeners.pointermove.size,0);assert.equal(h.listeners.pointerup.size,0);assert.equal(h.listeners.pointercancel.size,0);
});

test('stored width restores on open and clamps as the window changes while preserving main workspace',async()=>{
  const h=harness('input');h.storage.set('cs-anna-geom',JSON.stringify({w:600,x:12,y:30,h:700}));h.context.window.innerWidth=1440;await h.open();
  assert.equal(h.box.style.width,'600px');assert.equal(h.box.style.right,'16px');
  h.context.window.innerWidth=1100;h.dispatch('resize');assert.equal(h.box.style.width,'352px');assert.equal(h.document.body.style['--anna-width'],'352px');
  assert.equal(1100-236-32-parseFloat(h.box.style.width),480);
  h.context.window.innerWidth=1440;h.dispatch('resize');assert.equal(h.box.style.width,'600px');
  h.context.window.innerWidth=900;h.dispatch('resize');assert.equal(h.box.style.width,'600px');assert.equal(h.main.inert,true);
});

test('keyboard resizing exposes width values and Escape still closes the assistant after a cancelled drag',async()=>{
  const h=harness('input');h.context.window.innerWidth=1440;await h.open();const grip=h.nodes.get('[data-an-edge="w"]');
  assert.equal(grip.getAttribute('role'),'separator');assert.equal(grip.getAttribute('aria-orientation'),'vertical');
  grip.onkeydown({key:'ArrowLeft',preventDefault(){}});assert.equal(h.box.style.width,'384px');assert.equal(grip.getAttribute('aria-valuenow'),384);
  grip.onkeydown({key:'End',preventDefault(){}});assert.equal(h.box.style.width,'640px');
  grip.onkeydown({key:'Home',preventDefault(){}});assert.equal(h.box.style.width,'320px');
  grip.onpointerdown(dragEvent(grip,1100));h.dispatch('pointermove',{clientX:1000,pointerId:7});h.escape();
  assert.equal(h.box.hidden,true);assert.equal(h.main.inert,false);assert.equal(h.listeners.pointermove.size,0);assert.equal(JSON.parse(h.storage.get('cs-anna-geom')).w,320);
});

/* 10/12 作者：「安娜和 Michael 都隐藏，现在整个前台全部都是温迪，全部由你来管。」 */
test('Anna is paused: the rail shows only Wendy, on every page', async () => {
  for (const view of ['today', 'kpi', 'input', 'board', 'work', 'pack', 'consults', 'settings', 'platform']) {
    const h = harness(view);
    if (view === 'platform') h.run("S.platformKey = 'x'");
    h.run('AN.open = true');  // 以前存下的「Anna 开着」不再生效
    await h.run('renderAnna()');
    assert.equal(h.nodes.get('#railAnna').hidden, true, view);
    assert.equal(h.nodes.get('#railWendy').hidden, false, view);
    assert.equal(h.box.hidden, true, view);
  }
});

test('Wendy opens on content pages and the X page too', async () => {
  for (const [view, key] of [['input'], ['board'], ['work'], ['platform', 'x']]) {
    const h = harness(view);
    if (key) h.run(`S.platformKey = '${key}'`);
    h.run('WDP.open = true');
    await h.run('renderAnna()');
    assert.equal(h.run('shownAssistant()'), 'wendy', view);
    assert.equal(h.box.hidden, false, view);
    assert.equal(h.box.classList.contains('wd-panel'), true, view);
  }
});

test('anything that used to open Anna opens Wendy instead', async () => {
  const h = harness('board');
  let opened = null;
  h.context.window.openWendy = (prefill) => { opened = prefill; };
  h.run("window.openAnna('这条怎么改')");
  assert.equal(opened, '这条怎么改');
  assert.equal(h.run('AN.open'), false);
  await h.run("toggleAssistant('anna')");
  assert.equal(h.run('shownAssistant()'), null);
});

test('panel titles come from the brand roles, Wendy defaults to 负责人', () => {
  const h = harness('today');
  assert.equal(h.run('editorRole()'), '流量 CEO');
  assert.equal(h.run('bossRole()'), '负责人');
  h.run("S.state.brand = { editor_role: '增长负责人', boss_role: '营收负责人' }");
  assert.equal(h.run('editorRole()'), '增长负责人');
  assert.equal(h.run('bossRole()'), '营收负责人');
});

test('opening Michael does nothing while he is paused; Wendy still opens', async () => {
  const h = harness('today');
  const shown = () => h.run('shownAssistant()');
  h.run("AN.open = false; WDP.open = false; MIP.state = ''");
  h.run("toggleAssistant('michael')");
  assert.equal(shown(), null);
  h.run("toggleAssistant('wendy')");
  assert.equal(shown(), 'wendy');
});
