const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/content_studio/static/tracked.js', 'utf8');
const code = source.slice(0, source.indexOf('/* ---- 弹层：点按钮、调接口 ---- */'));
const ctx = vm.createContext({});
vm.runInContext(code, ctx);

const BASE = '# 闭环\n\n第一段，对吧？我觉得闭环最重要。\n\n第二段，流量只是第一步。先了解你自己。\n\n好，peace.';
const at = (s) => [BASE.indexOf(s), BASE.indexOf(s) + s.length];
const mk = (id, reason, op, anchor, more = {}) => {
  const [start, end] = at(anchor);
  return { id, reason, op, anchor, text: '', note: `为什么${id}`, start, end, pos: 'after', fresh: false, downgraded: false, inline: true, status: 'pending', edit: null, source: 'round1', ...more };
};
const trk = (changes) => ({ base: BASE, changes, scores: { before: { 高密度: { score: 62, why: '' }, 痛点: { score: 55, why: '' } }, after: null }, budget: 0, dropped: [], rescoring: false });
const OPT = { view: 'marks', filter: [], selected: null };
const html = (t, o = {}) => ctx.trkParagraphs(t, { ...OPT, ...o }).map((p) => p.html).join('|');

test('original text stays plain and each change is drawn where it belongs', () => {
  const t = trk([mk('c1', '风格', 'replace', '，对吧？', { text: '。' }), mk('c2', '高密度', 'delete', '先了解你自己。'), mk('c3', '稀缺', 'comment', '流量只是第一步')]);
  const out = html(t);
  assert.match(out, /第一段<del class="trk-c"[^>]*>，对吧？<\/del><ins class="trk-c"[^>]*>。<\/ins><span class="trk-tag">风格<\/span>我觉得闭环最重要。/);
  assert.match(out, /第二段，<mark class="trk-c"[^>]*>流量只是第一步<\/mark><span class="trk-tag">稀缺<\/span>。<del class="trk-c"[^>]*>先了解你自己。<\/del>/);
  assert.match(out, /^闭环\|/);  // 标题是第一段
});

test('a moved sentence shows the new place at the top and the old place struck out', () => {
  const t = trk([mk('c1', '开头', 'move', '先了解你自己。')]);
  const paras = ctx.trkParagraphs(t, OPT).map((p) => p.html);
  assert.match(paras[1], /<ins class="trk-c"[^>]*>先了解你自己。<\/ins>/);  // 标题后面第一段
  assert.match(paras.join('|'), /<del class="trk-c"[^>]*>先了解你自己。<\/del>/);
});

test('accepted changes read as normal text, rejected ones restore the original, pending ones stay marked', () => {
  const t = trk([mk('c1', '风格', 'replace', '，对吧？', { text: '。', status: 'accepted' }), mk('c2', '高密度', 'delete', '先了解你自己。', { status: 'rejected' })]);
  const out = html(t);
  assert.match(out, /第一段<span class="trk-c done-accepted"[^>]*>。<\/span>我觉得/);
  assert.doesNotMatch(out, /，对吧？/);
  assert.match(out, /。先了解你自己。\|/);  // 不要 = 回到原文，没有任何标记
  assert.doesNotMatch(out, /<del[^>]*>先了解/);
});

test('clean view shows only what he accepted; pending and rejected fall back to his words', () => {
  const t = trk([mk('c1', '风格', 'replace', '，对吧？', { text: '。' }), mk('c2', '高密度', 'delete', '先了解你自己。', { status: 'accepted' })]);
  const out = html(t, { view: 'clean' });
  assert.match(out, /第一段，对吧？我觉得闭环最重要。/);  // 没处理的先不算
  assert.doesNotMatch(out, /先了解你自己/);
  assert.doesNotMatch(out, /<ins|<del|<mark/);
});

test('a comment never changes the text and is drawn as a highlight with its reason', () => {
  const t = trk([mk('c1', '稀缺', 'comment', '我觉得闭环最重要')]);
  assert.equal(html(t).replace(/<[^>]+>/g, ''), '闭环|第一段，对吧？我觉得闭环最重要稀缺。|第二段，流量只是第一步。先了解你自己。|好，peace.');
  const resolved = html(trk([mk('c1', '稀缺', 'comment', '我觉得闭环最重要', { status: 'resolved' })]));
  assert.doesNotMatch(resolved, /<mark/);
});

test('a comment that sits on another change is not drawn twice', () => {
  const t = trk([mk('c1', '高密度', 'delete', '先了解你自己。'), mk('c2', '痛点', 'comment', '先了解你自己。', { inline: false })]);
  assert.equal((html(t).match(/先了解你自己/g) || []).length, 1);
});

test('new words are labelled as new and need his confirmation; his own edit replaces the proposal', () => {
  const t = trk([mk('c1', '共鸣', 'insert', '第二段，流量只是第一步。', { text: '这不只是做自媒体的事。', fresh: true })]);
  assert.match(html(t), /<ins class="trk-c fresh"[^>]*>这不只是做自媒体的事。<\/ins><span class="trk-tag">共鸣<\/span>/);
  assert.match(ctx.trkCard(t, 'c1'), /新写 · 待你确认/);
  t.changes[0].edit = '他改过的一句。';
  t.changes[0].status = 'edited';
  assert.match(html(t), /done-edited[^>]*>他改过的一句。/);
});

test('the filter dims everything that is not the chosen reason', () => {
  const t = trk([mk('c1', '风格', 'delete', '，对吧？'), mk('c2', '痛点', 'comment', '先了解你自己。')]);
  const out = html(t, { filter: ['痛点'] });
  assert.match(out, /<del class="trk-c dim"/);
  assert.match(out, /<mark class="trk-c"/);
});

test('budget counts only what really changed, ignores comments and rejected changes', () => {
  const size = BASE.replace(/^#[^\n]*\n*/, '').length;
  const t = trk([mk('c1', '高密度', 'delete', '先了解你自己。'), mk('c2', '风格', 'replace', '好，peace.', { text: '好，**peace.**' }),
    mk('c3', '稀缺', 'comment', '我觉得闭环最重要'), mk('c4', '痛点', 'delete', '，对吧？', { status: 'rejected' })]);
  const want = ('先了解你自己。'.length * 100) / size;
  assert.ok(Math.abs(ctx.trkBudget(t) - Math.max(want, 0)) < 0.5, `${ctx.trkBudget(t)} vs ${want}`);
  assert.equal(ctx.trkBudget(trk([mk('c1', '稀缺', 'comment', '我觉得闭环最重要')])), 0);
});

test('the dialog lists every change, counts them and blocks the rescore while edits are pending', () => {
  const post = { id: 'p', source_title: '闭环', text: BASE, summary: false,
    trk: trk([mk('c1', '风格', 'replace', '，对吧？', { text: '。' }), mk('c2', '稀缺', 'comment', '我觉得闭环最重要')]) };
  const out = ctx.trkHtml(post, { view: 'marks', color: 'type', filter: [], selected: 'c1' });
  assert.match(out, /待处理 <b>2<\/b> · 已接受 <b>0<\/b>/);
  assert.equal((out.match(/data-trk-pick=/g) || []).length, 2);
  assert.match(out, /data-trk-all="accepted"[\s\S]*data-trk-all="rejected"/);
  assert.match(out, /data-trk-rescore disabled/);   // 还有 1 处修改没处理
  assert.match(out, /还有 1 处没处理/);
  post.trk.changes[0].status = 'accepted';
  assert.doesNotMatch(ctx.trkHtml(post, { view: 'marks', color: 'type', filter: [], selected: 'c1' }), /data-trk-rescore disabled/);
});

test('scores show before and after against the 80 target', () => {
  const t = trk([]);
  t.scores.after = { 高密度: { score: 82, why: '' } };
  const out = ctx.trkScores(t);
  assert.match(out, /<td>高密度<\/td><td>62<\/td><td><b>82<\/b><\/td>/);
  assert.match(out, /<td>痛点<\/td><td>55<\/td><td>—<\/td>/);
  assert.match(out, /progress[^>]*value="82"[^>]*class="ok"/);
});

test('a replacement that only adds bold marks is drawn once, not as delete-then-insert', () => {
  const t = trk([mk('c1', '稀缺', 'replace', '我觉得闭环最重要', { text: '**我觉得闭环最重要**' })]);
  const out = html(t);
  assert.doesNotMatch(out, /<del/);
  assert.match(out, /<ins class="trk-c"[^>]*><strong>我觉得闭环最重要<\/strong><\/ins>/);
});

test('a comment he has read keeps a dotted marker so its place is not lost', () => {
  const t = trk([mk('c1', '稀缺', 'comment', '我觉得闭环最重要', { status: 'resolved' })]);
  assert.match(html(t), /<span class="trk-c done-resolved"[^>]*>我觉得闭环最重要<\/span>/);
  assert.equal(html(t, { view: 'clean' }).replace(/<[^>]+>/g, ''), '闭环|第一段，对吧？我觉得闭环最重要。|第二段，流量只是第一步。先了解你自己。|好，peace.');
});

test('the original view shows only his words, without a single mark', () => {
  const t = trk([mk('c1', '风格', 'replace', '，对吧？', { text: '。', status: 'accepted' }), mk('c2', '稀缺', 'comment', '我觉得闭环最重要')]);
  const out = html(t, { view: 'orig' });
  assert.equal(out.replace(/<[^>]+>/g, ''), '闭环|第一段，对吧？我觉得闭环最重要。|第二段，流量只是第一步。先了解你自己。|好，peace.');
  assert.doesNotMatch(out, /<ins|<del|<mark|trk-c/);
});

test('a bold-only change says the words did not change instead of showing identical before and after', () => {
  const t = trk([mk('c1', '风格', 'replace', '我觉得闭环最重要', { text: '**我觉得闭环最重要**' })]);
  const card = ctx.trkCard(t, 'c1');
  assert.match(card, /只加粗/);
  assert.match(card, /字一个没变/);
  assert.doesNotMatch(card, /<del>/);
  assert.doesNotMatch(card, /data-trk-act="edited"/);
});

test('the dialog offers undo with the last action named, and reset-all', () => {
  const post = { id: 'p', text: BASE, summary: false, trk: { ...trk([mk('c1', '风格', 'delete', '，对吧？')]), history: [{ label: '全部接受', state: {} }] } };
  const st = { view: 'marks', color: 'type', filter: [], selected: 'c1' };
  const out = ctx.trkHtml(post, st);
  assert.match(out, /data-trk-undo title="撤销：全部接受">撤销（全部接受）/);
  assert.match(out, /data-trk-all="reset"/);
  assert.match(out, /data-trk-view="orig"/);
  post.trk.history = [];
  assert.match(ctx.trkHtml(post, st), /data-trk-undo disabled/);
});

test('scores say when they are out of date, and that they will be redone by themselves', () => {
  const t = trk([]);
  t.scores.after = { 高密度: { score: 70, why: '' } };
  t.scores.stale = true;
  assert.match(ctx.trkScores(t), /这是改动之前那一版的分，修改都处理完会自动重打/);
  const done = trk([]);
  assert.match(ctx.trkScores(done), /修改都处理完了，马上自动打分/);
  done.rescoring = true;
  assert.match(ctx.trkScores(done), /在重新打分/);
});

test('the summary checkbox stays ticked while it is being written and says so', () => {
  const base = { id: 'p', text: BASE, trk: trk([]) };
  const st = { view: 'marks', color: 'type', filter: [], selected: null };
  const busy = ctx.trkHtml({ ...base, summary: false, summary_busy: true }, st);
  assert.match(busy, /data-trk-summary checked disabled/);
  assert.match(busy, /在写，一两分钟/);
  assert.match(ctx.trkHtml({ ...base, summary: false, summary_error: '第一句不对' }, st), /没写成：第一句不对/);
});

test('withdraw is called put-back and the reject button says it counts as handled', () => {
  const t = trk([mk('c1', '风格', 'delete', '，对吧？', { status: 'accepted' })]);
  const card = ctx.trkCard(t, 'c1');
  assert.match(card, /data-trk-act="pending"[^>]*>放回待处理/);
  assert.match(card, /data-trk-act="rejected"[^>]*title="[^"]*算处理过/);
  assert.doesNotMatch(card, />撤回</);
});


test('clicking one change shows only that one; the others turn into plain text in their current state', () => {
  const t = trk([mk('c1', '风格', 'replace', '，对吧？', { text: '。', status: 'accepted' }), mk('c2', '高密度', 'insert', '先了解你自己。', { text: '一句。', fresh: true })]);
  const all = html(t);
  assert.match(all, /done-accepted/);
  assert.match(all, /<ins class="trk-c fresh"/);
  const focused = html(t, { focus: 'c2' });
  assert.doesNotMatch(focused, /done-accepted|<del/);       // 别的修改不带颜色
  assert.match(focused, /第一段。我觉得闭环最重要。/);        // 接受过的按接受后的字显示
  assert.match(focused, /<ins class="trk-c fresh"[^>]*>一句。<\/ins>/);   // 点的这一处还亮着
  const pending = trk([mk('c1', '风格', 'delete', '，对吧？'), mk('c2', '稀缺', 'insert', '先了解你自己。', { text: '一句。', fresh: true })]);
  assert.match(html(pending, { focus: 'c2' }), /第一段，对吧？我觉得/);  // 没处理的显示你的原文
});

test('the dialog shows the budget against the article\'s own percentage and lets it be changed', () => {
  const post = { id: 'p', text: BASE, summary: false, trk: { ...trk([]), pct_effective: 35, overflow: [] } };
  const out = ctx.trkHtml(post, { view: 'marks', color: 'type', filter: [], selected: null, focus: null });
  assert.match(out, /progress max="35"/);
  assert.match(out, /id="trkPct"[^>]*value="35"/);
  assert.match(out, /data-trk-pct/);
  post.trk.pct_effective = undefined;
  assert.match(ctx.trkHtml(post, { view: 'marks', color: 'type', filter: [], selected: null, focus: null }), /progress max="20"/);   // 默认 20
});

test('changes that did not fit are listed folded, not shown as comments', () => {
  const post = { id: 'p', text: BASE, summary: false,
    trk: { ...trk([mk('c1', '风格', 'delete', '，对吧？')]), overflow: [mk('o1', '稀缺', 'insert', '先了解你自己。', { text: '一句。', status: 'overflow' })] } };
  const out = ctx.trkHtml(post, { view: 'marks', color: 'type', filter: [], selected: null, focus: null });
  assert.match(out, /超出预算，没放进来 1 条/);
  assert.match(out, /把上面的预算调高/);
});

test('with focus on, the bar says so and offers a way back to everything', () => {
  const post = { id: 'p', text: BASE, summary: false, trk: trk([mk('c1', '风格', 'delete', '，对吧？')]) };
  const out = ctx.trkHtml(post, { view: 'marks', color: 'type', filter: [], selected: 'c1', focus: 'c1' });
  assert.match(out, /只看这一处[\s\S]*data-trk-unfocus/);
});

test('after any action the dialog and the card repaint from the fresh data', async () => {
  const calls = [];
  const full = vm.createContext({ window: {}, document: { querySelector: (s) => (s === '.trk-dlg' ? {} : null), addEventListener() {}, removeEventListener() {}, body: { classList: { add() {}, remove() {} } } },
    localStorage: { getItem: () => null, setItem() {} }, xlLoad: async () => calls.push('load'), xlRender: () => calls.push('render'), toast() {} });
  vm.runInContext(source, full);
  full.trkPaint = () => calls.push('paint');   // 函数声明挂在全局上，调用时现查，这里换成探针
  await full.trkRefresh();
  assert.deepEqual(calls, ['load', 'paint', 'render']);
});

test('the article polish uses its own endpoints and its images come from the article folder (10/13)', async () => {
  const full = vm.createContext({ document: { querySelector: () => null, addEventListener() {}, removeEventListener() {}, body: { classList: { add() {}, remove() {} }, appendChild() {} }, createElement: () => ({}) }, localStorage: { getItem: () => null, setItem() {} }, window: {} });
  vm.runInContext(source, full);
  vm.runInContext("TRK.topic = true; TRK.id = 12; TRK.doc = 'polish'", full);
  assert.equal(vm.runInContext("trkUrl('trk/undo')", full), '/api/topics/12/polish/trk/undo');
  vm.runInContext("TRK.doc = 'script'", full);
  assert.equal(vm.runInContext("trkUrl('trk')", full), '/api/topics/12/script/trk');
  const html = vm.runInContext("trkCleanParagraphs({ id: '12', _topic: true, _doc: 'polish', text: '# 标题\\n\\n正文。\\n\\n![问卷](illustrations/01-q.png)' })", full);
  assert.match(html, /src="\/api\/topics\/12\/article-file\/illustrations\/01-q\.png"/);
  const spoken = vm.runInContext("trkCleanParagraphs({ id: '12', _topic: true, _doc: 'script', text: '# 标题\\n\\n正文。' })", full);
  assert.match(spoken, /<p>正文。<\/p>/);
});

test('save bar says what is already saved; discard is off until something changed (10/13)', () => {
  const t = trk([mk('c1', '风格', 'replace', '，对吧？', { text: '。' }), mk('c2', '高密度', 'delete', '先了解你自己。')]);
  const snap = ctx.trkSnap(t);
  assert.match(ctx.trkSaveBar(t, snap), /还没有改动[\s\S]*data-trk-discard disabled[\s\S]*data-trk-close>保存</);
  t.changes[0].status = 'accepted';
  t.changes[1].status = 'accepted';
  assert.equal(ctx.trkDirty(t, snap), 2);
  assert.match(ctx.trkSaveBar(t, snap), /这次处理了 2 处，每一下都已经存进正文/);
  assert.doesNotMatch(ctx.trkSaveBar(t, snap), /data-trk-discard disabled/);
  assert.equal(ctx.trkSavedMsg(t, 0), '没有改动');
  assert.match(ctx.trkSavedMsg({ ...t, rescoring: true }, 2), /存好了：2 处修改在正文里 · 在按新正文重打分/);
  assert.match(ctx.trkSavedMsg({ ...t, scores: { before: {}, after: { 痛点: { score: 85 } } } }, 2), /改后打分已出来/);
  t.changes[1].status = 'pending';
  assert.match(ctx.trkSavedMsg(t, 1), /还有 1 处没处理/);
});
