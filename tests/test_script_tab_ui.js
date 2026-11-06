const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/content_studio/static/scripttab.js', 'utf8');

function load(extra = {}) {
  const tabs = [];
  const els = {};
  const ctx = vm.createContext({
    window: { VIDEO_TABS: tabs, openTracked: () => {} }, featureOn: () => true, esc: (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])),
    $: (sel) => els[sel] || { onclick: null, value: '' }, $$: () => [], toast() {}, VD: { topicId: 1, tab: 'script' }, S: { view: 'work' }, renderView() {},
    navigator: { clipboard: { writeText: async () => {} } }, clearTimeout() {}, setTimeout: () => 0, ...extra });
  vm.runInContext(source, ctx);
  return { tab: tabs[0], ctx, els };
}
const el = () => ({ isConnected: true, innerHTML: '' });
const script = (changes = []) => ({ text: '# 闭环\n\n第一段。\n\n第二段。', trk: { changes, overflow: [], budget: 3.2, pct_effective: 20, scores: { before: { 高密度: { score: 60 } }, after: { 高密度: { score: 78 } } } } });
const edit = (id, status) => ({ id, op: 'insert', status });

test('the tab is registered and only shown when the xline block is there', () => {
  const { tab } = load();
  assert.equal(tab.key, 'script');
  assert.equal(tab.label, '口播稿');
  assert.equal(tab.show(), true);
  assert.equal(load({ featureOn: () => false }).tab.show(), false);
});

test('without a script it offers the three sources and disables the ones that are not available', async () => {
  const { tab } = load({ api: async () => ({ available: true, running: false, script: null, has: { coupon: true, skeleton: false, transcript: false }, title: '闭环' }) });
  const e = el();
  await tab.render({ id: 1 }, e);
  assert.match(e.innerHTML, /付息稿整理成口播稿/);
  assert.match(e.innerHTML, /data-sc-src="coupon">开始/);
  assert.match(e.innerHTML, /data-sc-src="transcript" disabled/);
  assert.match(e.innerHTML, /id="scPaste"/);
});

test('with no skeleton and no coupon the first source is disabled and says what to do', async () => {
  const { tab } = load({ api: async () => ({ available: true, running: false, script: null, has: { coupon: false, skeleton: false, transcript: true }, title: '闭环' }) });
  const e = el();
  await tab.render({ id: 1 }, e);
  assert.match(e.innerHTML, /data-sc-src="coupon" disabled title="先写骨架和密度"/);
  assert.doesNotMatch(e.innerHTML, /data-sc-src="transcript" disabled/);
});

test('a finished script shows counts, budget, scores and the open-review button; badge says how many are left', async () => {
  const d = { available: true, running: false, error: null, has: {}, title: '闭环', script: script([edit('c1', 'accepted'), edit('c2', 'pending'), edit('c3', 'pending')]) };
  const { tab, els } = load({ api: async () => d });
  els['#scOpen'] = { onclick: null };
  els['#scCopy'] = { onclick: null };
  const e = el();
  await tab.render({ id: 1 }, e);
  assert.match(e.innerHTML, /改了 <b>3<\/b> 处，已处理 <b>1<\/b>，待处理 <b>2<\/b>/);
  assert.match(e.innerHTML, /预算 3\.2% \/ 20%/);
  assert.match(e.innerHTML, /高密度 <b>60<\/b> → <b>78<\/b>/);
  assert.equal(tab.badge({ id: 1 }), '待处理 2');
  assert.match(e.innerHTML, /重新来一遍（会清掉你已经处理的 1 处）/);
  assert.equal(typeof els['#scOpen'].onclick, 'function');
});

test('while it is being made the page shows the stage and polls', async () => {
  const { tab } = load({ api: async () => ({ available: true, running: true, stage: '打分、提修改清单', script: null, has: {} }) });
  const e = el();
  await tab.render({ id: 1 }, e);
  assert.match(e.innerHTML, /在做口播稿：打分、提修改清单/);
  assert.equal(tab.badge({ id: 1 }), '在做');
});

test('content that already has his words puts 用我的原话 first and the coupon path last', async () => {
  const { tab } = load({ api: async () => ({ available: true, running: false, script: null, has: { note: true, coupon: false, skeleton: false, transcript: false }, mode: { mode: 'own', auto: true, why: '挂了你原始输出里的笔记' }, title: '版本答案' }) });
  const e = el();
  await tab.render({ id: 1 }, e);
  const html = e.innerHTML;
  assert.doesNotMatch(html, /scMode/);  // 10/13：没有「有没有我的话」的开关了，口述完都走同一条线
  assert.match(html, /class="btn primary" type="button" data-sc-src="note">开始/);
  assert.ok(html.indexOf('data-sc-src="note"') < html.indexOf('data-sc-src="coupon"'));
  assert.ok(html.indexOf('data-sc-src="paste"') < html.indexOf('data-sc-src="coupon"'));
});

test('content without his words keeps the coupon path first', async () => {
  const { tab } = load({ api: async () => ({ available: true, running: false, script: null, has: { note: false, coupon: true }, mode: { mode: 'draft', auto: false, why: '你在这条内容上选的' }, title: '闭环' }) });
  const e = el();
  await tab.render({ id: 1 }, e);
  const html = e.innerHTML;
  assert.doesNotMatch(html, /scMode|data-sc-mode/);
  assert.match(html, /data-sc-src="note" disabled/);
  assert.ok(html.indexOf('data-sc-src="coupon"') < html.indexOf('data-sc-src="note"'));
});

test('each score is a button: it opens the reason and how many changes it asked for (10/13)', async () => {
  const handlers = {};
  const box = { hidden: true, textContent: '' };
  const chip = { dataset: { scWhy: '高密度' }, attrs: {}, getAttribute(k) { return this.attrs[k] || 'false'; }, setAttribute(k, v) { this.attrs[k] = v; } };
  const { tab, els } = load({
    api: async () => ({ available: true, running: false, title: '闭环', has: {}, script: script([{ id: 'c1', reason: '高密度', op: 'insert', status: 'pending' }, { id: 'c2', reason: '高密度', op: 'comment', status: 'pending' }]) }),
    $$: (sel) => (sel === '[data-sc-why]' ? [chip] : []),
  });
  els['#scWhy'] = box;
  const e = el();
  await tab.render({ id: 1 }, e);
  assert.match(e.innerHTML, /<button type="button" class="sc-score" data-sc-why="高密度"/);
  assert.equal(box.hidden, true);
  chip.onclick();
  assert.equal(box.hidden, false);
  assert.match(box.textContent, /高密度：.*提了 1 处修改/);  // 评论不算修改
  chip.onclick();
  assert.equal(box.hidden, true);
});

test('with the review list in the manifest the page draws the nine items on a ten-point scale and unscored ones as dashes (10/13)', async () => {
  const chip = { dataset: { scWhy: '密度' }, attrs: {}, getAttribute(k) { return this.attrs[k] || 'false'; }, setAttribute(k, v) { this.attrs[k] = v; } };
  const box = { hidden: true, textContent: '' };
  const trk = { changes: [{ id: 'c1', reason: '高密度', op: 'insert', status: 'pending' }, { id: 'c2', reason: '高密度', op: 'comment', status: 'pending' }],
    overflow: [], budget: 3.2, pct_effective: 20, scores: { before: { 留人: { score: 80, why: '好' }, 密度: { score: 82, why: '每段都付息' } }, after: { 密度: { score: 90, why: '更好' } } } };
  const review = [{ id: 'retain', title: '留人', reasons: ['开头'], second: false }, { id: 'density', title: '密度', reasons: ['高密度'], second: false },
    { id: 'tone', title: '口气', reasons: ['风格'], second: false }, { id: 'typo', title: '错字通顺和导语', reasons: [], second: true }];
  const { tab, els } = load({ api: async () => ({ available: true, running: false, title: '闭环', has: {}, review, script: { text: '# 闭环\n\n第一段。', trk } }), $$: (sel) => (sel === '[data-sc-why]' ? [chip] : []) });
  els['#scWhy'] = box;
  const e = el();
  await tab.render({ id: 1 }, e);
  assert.match(e.innerHTML, /data-sc-why="留人"[^>]*>留人 <b>8.0<\/b>/);
  assert.match(e.innerHTML, /密度 <b>8.2<\/b> → <b>9.0<\/b>/);
  assert.match(e.innerHTML, /class="sc-score na" title="这一次没打分">口气 <b>—<\/b>/);
  assert.match(e.innerHTML, /title="发文章前（第二轮）才查">错字通顺和导语 <b>—<\/b>/);
  chip.onclick();
  assert.match(box.textContent, /密度：更好 · 提了 1 处修改/);  // 点开：用清单里这一项对应的原因数修改，评论不算
});
