'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/content_studio/static/videoproject.js'), 'utf8');
const fixture = () => ({
  schema: {
    sliders: [
      { key: 'density', name: '密度', levels: [{ value: 'low', label: '低' }, { value: 'medium', label: '中' }] },
      { key: 'effort', name: '动效努力', levels: [{ value: 'a', label: '文字卡' }, { value: 'b', label: '图表' }, { value: 'c', label: '尚未实现', available: false }] },
      { key: 'edit', name: '剪辑', levels: [{ value: 'keep', label: '不动粗剪' }, { value: 'cut', label: '尚未实现', available: false }] },
    ],
    choices: [{ key: 'prefer', name: '偏爱', type: 'components' }, { key: 'avoid', name: '不用', type: 'components' }],
    per_video: [{ key: 'banned_words', name: '禁用词' }],
    presets: [{ name: '快出', values: { density: 'low', effort: 'a' }, available: true }],
  },
  values: { density: 'medium', effort: 'b', edit: 'keep', prefer: ['Cycle'], avoid: [], banned_words: [] },
  source: { density: 'repo', effort: 'repo', edit: 'repo', prefer: 'user', avoid: 'user' },
  components: [{ key: 'Cycle', name: '循环图', form: 'diagram' }],
});
const copy = (value) => JSON.parse(JSON.stringify(value));
function harness(api = async () => ({ settings: fixture() })) {
  const controls = {
    '.ms-advanced': [{}], '[data-shotcraft-library]': [{open:false}], '[data-shotcraft-body]': [{innerHTML:'',controls:{}}], '[data-shotcraft-count]': [{}], '#vsSave': [{}], '#vsDefault': [{}], '#vsUndo': [{}],
    '[data-level]': [{ dataset: { level: 'density', value: 'low' }, focus() {} }],
    '[data-style]': ['prefer', 'default', 'avoid'].map((preference) => ({ dataset: { style: 'Cycle', preference }, focus() {} })),
    '[data-preset]': [{ dataset: { preset: '0' }, focus() {} }],
    '[data-per]': [{ dataset: { per: 'banned_words' }, value: '', focus() {} }],
  };
  const box = { isConnected: true, innerHTML: '', controls };
  const calls = [];
  const context = vm.createContext({
    window: { addEventListener() {} }, console, box,
    esc: (value) => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
    $: (selector, target) => target?.controls[selector]?.[0] || null,
    $$: (selector, target) => target?.controls[selector] || [],
    api: (url, options) => { calls.push({ url, options: copy(options || {}) }); return api(url, options); },
    toast() {}, renderView() {},
  });
  vm.runInContext(source, context);
  context.initial = fixture();
  vm.runInContext('VP.set[42] = { data: initial, draft: {} }; VP.set.default = { data: initial, draft: {} }; MOTION_CATALOG = { components: [{ key: "Cycle", video_url: "/api/video-v2/media/components/Cycle.mp4" }], shotcraft: [] };', context);
  const run = (code) => vm.runInContext(code, context);
  const draw = (id = 42) => run(`drawV2Settings({id:${JSON.stringify(id)}}, box)`);
  draw();
  return { box, calls, controls, run, draw, state: () => copy(run('VP.set[42]')) };
}

test('named settings remain while the original reference library is collapsed and component preferences are absent', () => {
  const h = harness();
  assert.doesNotMatch(h.box.innerHTML, /type="range"|尚未实现|data-level="edit"/);
  assert.match(h.box.innerHTML, /data-level="density"/);
  assert.match(h.box.innerHTML, /不动粗剪/);
  assert.match(h.box.innerHTML, /data-shotcraft-library>/);
  assert.doesNotMatch(h.box.innerHTML, /data-style=|样式偏好|<video/);
});

test('draft survives redraw and navigation, preset changes remain undoable', () => {
  const h = harness();
  h.controls['[data-preset]'][0].onclick();
  h.draw('default'); h.draw();
  assert.deepEqual(h.state().draft, { density: 'low', effort: 'a' });
  assert.match(h.box.innerHTML, /2 项未保存/);
  assert.deepEqual(copy(h.run('VP.set.default.draft')), {});
  h.controls['#vsUndo'][0].onclick();
  assert.deepEqual(h.state().draft, {});
  assert.equal(h.state().data.values.density, 'medium');
});

test('saving settings does not rewrite previously configured component preferences', async () => {
  const h = harness();
  h.controls['[data-level]'][0].onclick();
  await h.controls['#vsSave'][0].onclick();
  assert.deepEqual(h.calls[0].options.body, {values:{density:'low'},scope:'project'});
  assert.deepEqual(h.state().data.values.prefer, ['Cycle']);
});

test('failed save retains all changes and retry succeeds without losing the selected scope', async () => {
  let fail = true;
  const h = harness(async () => { if (fail) throw new Error('连接中断'); return { settings: fixture() }; });
  h.controls['[data-level]'][0].onclick();
  await h.controls['#vsDefault'][0].onclick();
  assert.deepEqual(h.state().draft, { density: 'low' });
  assert.equal(h.state().saving, false);
  assert.match(h.box.innerHTML, /保存失败：连接中断/);
  fail = false;
  await h.controls['#vsDefault'][0].onclick();
  assert.equal(h.calls[1].options.body.scope, 'default');
  assert.deepEqual(h.state().draft, {});
});

test('per-video settings cannot leak into user defaults', async () => {
  const h = harness();
  h.controls['[data-per]'][0].value = '保证收益，绝对';
  h.controls['[data-per]'][0].onchange();
  await h.controls['#vsDefault'][0].onclick();
  assert.equal(h.calls.length, 0);
  await h.controls['#vsSave'][0].onclick();
  assert.deepEqual(h.calls[0].options.body.values, { banned_words: ['保证收益', '绝对'] });
});

test('pending save blocks duplicate submission, undo and edits until the response arrives', async () => {
  let resolve;
  const h = harness(() => new Promise((done) => { resolve = done; }));
  h.controls['[data-preset]'][0].onclick();
  const pending = h.controls['#vsSave'][0].onclick();
  assert.match(h.box.innerHTML, /正在保存/);
  h.controls['#vsUndo'][0].onclick();
  h.controls['[data-level]'][0].onclick();
  await h.controls['#vsSave'][0].onclick();
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.state().draft, { density: 'low', effort: 'a' });
  resolve({ settings: fixture() }); await pending;
  assert.deepEqual(h.state().draft, {});
});


test('all original shotcraft cards show a lazy poster up front and only load video on hover', () => {
  const h=harness();
  h.run(`MOTION_CATALOG.shotcraft=Array.from({length:157},(_,i)=>({name:'original-shot-'+i,summary:'原始镜头',poster_url:'/p/'+i+'.jpg',video_url:i===0?'/api/video-v2/media/shotcraft/actual.mp4':null,category_zh:'镜头'}))`);
  h.draw();
  assert.equal((h.box.innerHTML.match(/data-shotcraft-card=/g)||[]).length,157);
  assert.match(h.box.innerHTML,/original-shot-156/);
  assert.equal((h.box.innerHTML.match(/<img src="\/p\/\d+\.jpg" alt="" loading="lazy"/g)||[]).length,157,'every card shows its picture without clicking');
  assert.doesNotMatch(h.box.innerHTML,/<video|data-shotcraft-library open/);
  h.run(`var __made=[];document={createElement:(tag)=>{const el={tag,paused:true,play(){el.paused=false;return Promise.resolve();},pause(){el.paused=true;}};__made.push(el);return el;}}`);const made=h.run('__made');
  const classes=new Set();const thumb={controls:{},classList:{add:(c)=>classes.add(c),remove:(c)=>classes.delete(c),contains:(c)=>classes.has(c)},closest:()=>({dataset:{shotcraftCard:'original-shot-0'}}),appendChild(el){thumb.controls.video=[el];}};
  h.box.controls['[data-shotcraft-play]']=[thumb];h.run('bindShotcraftLibrary(box)');
  thumb.onmouseenter();
  assert.equal(made.length,1);assert.equal(made[0].src,'/api/video-v2/media/shotcraft/actual.mp4');assert.equal(made[0].muted,true);assert.equal(made[0].paused,false);
  thumb.onmouseleave();assert.equal(made[0].paused,true);assert.equal(classes.has('playing'),false);
  thumb.onmouseenter();assert.equal(made.length,1,'the same video element is reused');
});

test('library loads on demand and a late response cannot replace partial input or focus', async () => {
  let finish;
  const h=harness(()=>new Promise(resolve=>{finish=resolve;}));
  h.run('MOTION_CATALOG=null');await h.run('loadV2Settings({id:42},box)');
  assert.equal(h.calls.length,0,'collapsed settings should not eagerly load the library');
  const input=h.controls['[data-per]'][0];let redraws=0,html=h.box.innerHTML,focused=false;
  Object.defineProperty(h.box,'innerHTML',{get(){return html;},set(value){html=value;redraws++;input.value='';focused=false;}});
  const pending=h.run('refreshV2Catalog({id:42})');
  input.value='写到一半，';focused=true;
  finish({components:[],shotcraft:[{name:'original-late',summary:'原始卡片',category_zh:'开场'}]});await pending;
  assert.equal(redraws,0);assert.equal(input.value,'写到一半，');assert.equal(focused,true);
  assert.match(h.controls['[data-shotcraft-body]'][0].innerHTML,/original-late/);
  assert.deepEqual(h.state().draft,{});
});
