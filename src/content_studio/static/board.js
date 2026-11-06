'use strict';
/* 加工中：正在做的这一条（进度条）+ 机器在做的（剪辑、待发）。
   10/19 作者 拿掉排期：开始做只有一个入口，选题 →「我的选题」点「做这条」（mytopics.js）；一次只有一条，发完才轮到下一条。 */
window.VIEWS = window.VIEWS || {};

const BD = { data: null, at: 0 };
const QA_SHORT = { go: '可以拍', patch: '先补再拍', thin: '素材太薄' };
// 每个阶段一个图标，选题池的行和进度条上用的是同一套，所以一眼能对上。
const MS_ICON = { topic: '◎', outline: '▤', record: '▶', edit: '✂', ready: '⏳', shipped: '✓' };

async function loadBoard(force) {
  const running = BD.data && BD.data.cards.some((c) => c.next.text === '提纲生成中');
  if (!force && BD.data && Date.now() - BD.at < (running ? 4000 : 20000)) return BD.data;
  BD.data = await api(`/api/board?day=${new Date().toLocaleDateString('sv-SE')}`);
  BD.at = Date.now();
  paintRailStages(BD.data);
  return BD.data;
}

/* 10/20 左栏 = 找 写 剪 发 盘。正在做的那条走到哪：写（还没稿 / 在写）→ 剪（拍、放素材、剪）→ 发（有成片）。
   做完的打勾（绿），现在这步亮（橙）；没有正在做的，写剪发都是灰的，点了去「找」。 */
const ZX_STEPS = ['write', 'cut', 'fa'];
const zxIndex = (stage) => (stage === 'outline' ? 0 : ['record', 'edit'].includes(stage) ? 1 : stage === 'ready' ? 2 : -1);
function paintRailStages(d) {
  const f = d && d.focus;
  const at = f ? zxIndex(f.stage) : -1;
  ZX_STEPS.forEach((k, i) => {
    const b = $(`.rail [data-zx="${k}"]`);
    if (!b) return;
    b.classList.toggle('done', Boolean(f) && i < at);
    b.classList.toggle('now', Boolean(f) && i === at);
    b.classList.toggle('idle', !f);
    const n = $(`#nav${k === 'write' ? 'Write' : k === 'cut' ? 'Cut' : 'Fa'}`);
    if (n) n.innerHTML = f && i === at && f.next.mine ? '<i class="wait" title="正在做的这条在等你"></i>' : f && i < at ? '✓' : '';
  });
  const now = $('#railNow');
  if (now) { now.hidden = !f; $('#railNowTitle').textContent = f ? f.title : ''; }
}
window.zxCurrent = () => { const f = BD.data && BD.data.focus; return f ? ZX_STEPS[zxIndex(f.stage)] || 'write' : null; };
/* 点左栏的 写 / 剪 / 发：打开正在做的那条的那一步；没有正在做的，去「找」 */
window.goStage = async (zx) => {
  let d = BD.data;
  if (!d) { try { d = await loadBoard(false); } catch (err) { toast(err.message); return; } }
  const f = d.focus;
  if (!f) { toast('现在没有正在做的：在「找」里挑一条，点「做这条」'); window.openInputTab('mine'); return; }
  const step = zx || ZX_STEPS[zxIndex(f.stage)] || 'write';
  if (step === 'fa') { S.packId = f.id; go('pack'); return; }
  openWork(f.id, step === 'cut' ? 'edit' : 'write');
};

window.refreshBoard = async () => { BD.data = null; try { await loadBoard(true); } catch (_) { /* shown on render */ } };
window.refreshTopics = async () => { await window.refreshBoard(); if (window.invalidateMyTopics) window.invalidateMyTopics(); if (window.invalidateWork) window.invalidateWork(); if (window.invalidatePublish) window.invalidatePublish(); if (window.invalidatePack) window.invalidatePack(); renderView(); };
window.patchTopic = async (id, body, message) => {
  try {
    await api(`/api/topics/${id}`, { method: 'PATCH', body });
    if (message) toast(message);
    await window.refreshTopics();
  } catch (err) { toast(err.message); }
};

function openWork(id, tab) {
  if (window.captureWorkOrigin) window.captureWorkOrigin(id);
  S.workId = id;
  if (typeof VD !== 'undefined') VD.requested = { id, tab };
  if (window.invalidateWork) window.invalidateWork();
  go('work');
}
window.openWork = openWork;

async function act(path, { method = 'POST', body, message } = {}) {
  try {
    const res = await api(path, { method, body });
    if (message) toast(typeof message === 'function' ? message(res) : message);
    await window.refreshTopics();
    return res;
  } catch (err) { toast(err.message); return null; }
}

function streakChip(k) {
  if (!k) return '';
  if (k.today_done) return `<div class="streak ok"><b class="num">${k.days}</b><span>天连续拍摄</span></div>`;
  if (k.days > 0) return `<div class="streak warn"><b class="num">${k.days}</b><span>天连续 · 今天还没拍</span></div>`;
  return `<div class="streak broken"><b class="num">${k.days_since_last ?? '—'}</b><span>天没拍了</span></div>`;
}

/* 10/20：「加工中」这一页不要了——左栏「写 剪 发」就是它。旧书签 #board 落到正在做的那一步；没有正在做的落到「找」。 */
window.VIEWS.board = {
  async render() { S.replaceNext = true; await window.goStage(null); },
};
