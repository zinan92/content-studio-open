'use strict';

/* 加工中的「口播稿」页签（10/12 作者）：付息稿 / 他自己贴的稿子 / 拍完的逐字稿，走和 X 长文同一个批注视图。
   接口在 /api/topics/{id}/script；视图本身在 tracked.js。 */
(() => {
  const SC = { poll: null, data: {}, busy: false };
  const SOURCES = {
    note: ['用我的原话', '这条内容挂的你原始输出里的笔记，一个字不删、不重写，直接打分、提修改（只加不删，口癖、重复除外）。'],
    coupon: ['付息稿整理成口播稿', '还没有你自己的话时用：把「密度」那页的付息稿按 11 点整理成连着说的口语。会压到一条视频的时长。'],
    transcript: ['用拍完的逐字稿', '视频拍完转出来的逐字稿是你的原话，不重写，直接打分、提修改。'],
  };

  const counts = (trk) => {
    const edits = trk.changes.filter((c) => c.op !== 'comment');
    return { total: edits.length, left: edits.filter((c) => c.status === 'pending').length, done: edits.filter((c) => c.status !== 'pending').length };
  };

  async function start(topic, source, text, force, el) {
    if (SC.busy) return;
    SC.busy = true;
    try {
      const r = await api(`/api/topics/${topic.id}/script`, { method: 'POST', body: { source, text, force: !!force } });
      toast(r.message || '开始了');
    } catch (err) {
      if (/确定的话再点一次/.test(err.message) && window.confirm(`${err.message}\n\n继续吗？旧的会留一份 .bak 备份。`)) { SC.busy = false; return start(topic, source, text, true, el); }
      toast(err.message);
    }
    SC.busy = false;
    redraw();
  }

  function redraw() {
    if (typeof VD === 'undefined' || typeof renderView !== 'function') return;
    VD.forceRender = true;
    if (S.view === 'work') renderView();
  }

  function sourceButtons(topic, d, handled) {
    const has = d.has || {};
    const own = (d.mode || {}).mode === 'own';
    const again = handled !== null;
    const card = (key, enabled, why, primary) => `<div class="sc-src"><b>${SOURCES[key][0]}</b><p>${SOURCES[key][1]}</p><button class="btn${primary ? ' primary' : ''}" type="button" data-sc-src="${key}"${enabled ? '' : ` disabled title="${why}"`}>${again ? '重新来一遍' : '开始'}</button></div>`;
    const note = card('note', has.note, '这条没有挂你原始输出里的笔记', own && has.note);
    const transcript = card('transcript', has.transcript, '这条视频还没有转写的逐字稿', own && !has.note);
    const coupon = card('coupon', has.coupon || has.skeleton, '先写骨架和密度', !own);
    const paste = `<div class="sc-src"><b>贴进自己的稿子</b><p>你自己写的、别处整理好的稿子，贴在这里，不重写，直接打分、提修改。</p>
        <textarea id="scPaste" rows="5" placeholder="把稿子贴在这里（至少 200 字）" spellcheck="false" aria-label="贴进来的稿子"></textarea>
        <button class="btn" type="button" data-sc-src="paste">用这份稿子</button></div>`;
    // 已经有你的话：原话、逐字稿、贴稿在前，付息稿那条路放最后；还没有：付息稿在前
    return `<div class="sc-sources">${own ? note + transcript + paste + coupon : coupon + note + transcript + paste}</div>`;
  }

  window.VIDEO_TABS.push({
    key: 'script', label: '口播稿',
    show: () => typeof featureOn === 'function' && featureOn('xline') && !!window.openTracked,
    badge: (t) => {
      const d = SC.data[t.id];
      if (!d) return '';
      if (d.running) return '在做';
      if (!d.script) return '';
      const c = counts(d.script.trk);
      return c.left ? `待处理 ${c.left}` : '已处理';
    },
    async render(topic, el) {
      clearTimeout(SC.poll);
      let d;
      try { d = await api(`/api/topics/${topic.id}/script`); } catch (err) {
        el.innerHTML = `<div class="empty" role="alert"><b>读不到口播稿：${esc(err.message)}</b></div>`;
        return;
      }
      SC.data[topic.id] = d;
      if (!el.isConnected) return;
      if (!d.available) { el.innerHTML = '<div class="empty"><b>这台机器没有带清单的 park-writing</b><span>口播稿走的是 park-writing 的写作流程，先装好它。</span></div>'; return; }
      if (d.running) {
        el.innerHTML = `<div class="empty"><span class="spin"></span><b>在做口播稿：${esc(d.stage || '准备')}</b><span>一般 4 到 6 分钟：先整理成口语，再打分、提修改。</span></div>`;
        SC.poll = setTimeout(() => { if (VD.topicId === topic.id && VD.tab === 'script') redraw(); }, 5000);
        return;
      }
      const err = d.error ? `<p class="journey-save-state bad" role="alert">${esc(d.error)}</p>` : '';
      if (!d.script) {
        el.innerHTML = `<div class="sc-body">${err}<div class="sc-head"><h3>口播稿</h3><p>已经有你自己的话，就直接用原话；还没有，才从付息稿整理。然后一次打分、提修改（没有评论，只加不删），你逐条接受、改一改或不要。</p></div>${sourceButtons(topic, d, null)}</div>`;
      } else {
        const trk = d.script.trk, c = counts(trk), pct = Number(trk.pct_effective || trk.max_pct || trk.pct || 20);
        const before = (trk.scores || {}).before || {}, after = (trk.scores || {}).after || null;
        // 10/13 作者：park-writing 清单里有评判清单（review）就画 9 项总评（0–10 分）；老清单退回原来的打分（0–100）
        const items = d.review || [];
        const shown = (n) => (items.length ? (n / 10).toFixed(1) : n);
        const reasonsOf = {};
        const chips = items.length ? items.map((it) => { reasonsOf[it.title] = it.reasons; return it.title; }) : Object.keys(before);
        const score = chips.map((k) => {
          if (!before[k]) {
            const it = items.find((x) => x.title === k) || {};
            return `<span class="sc-score na" title="${it.second ? '发文章前（第二轮）才查' : '这一次没打分'}">${esc(k)} <b>—</b></span>`;
          }
          return `<button type="button" class="sc-score" data-sc-why="${esc(k)}" aria-expanded="false">${esc(k)} <b>${shown(before[k].score)}</b>${after && after[k] ? ` → <b>${shown(after[k].score)}</b>` : ''}</button>`;
        }).join('');
        const paras = d.script.text.split(/\n\s*\n/).filter((p) => p.trim());
        el.innerHTML = `<div class="sc-body">${err}<div class="sc-head"><h3>${esc(d.title || '口播稿')}</h3>
          <p>改了 <b>${c.total}</b> 处，已处理 <b>${c.done}</b>${c.left ? `，待处理 <b>${c.left}</b>` : '，都处理完了'} · 预算 ${Number(trk.budget || 0).toFixed(1)}% / ${pct}%${(trk.overflow || []).length ? ` · 没放进来 ${trk.overflow.length}` : ''}</p>
          <div class="sc-scores">${score}</div><p class="sc-why" id="scWhy" role="status" hidden></p>
          <div class="sc-acts"><button class="btn primary" type="button" id="scOpen">打开批注视图</button><button class="btn" type="button" id="scCopy">复制口播稿</button></div></div>
          <article class="sc-text">${paras.map((p, i) => (i === 0 && /^#\s/.test(p) ? `<h4>${esc(p.replace(/^#+\s*/, ''))}</h4>` : `<p>${esc(p)}</p>`)).join('')}</article>
          <details class="sc-again"><summary>重新来一遍（会清掉你已经处理的 ${c.done} 处）</summary>${sourceButtons(topic, d, c.done)}</details></div>`;
        // 点一项看理由和它提了几处修改（理由是模型打分时写的一句话）
        $$('[data-sc-why]', el).forEach((b) => (b.onclick = () => {
          const k = b.dataset.scWhy, box = $('#scWhy', el), open = b.getAttribute('aria-expanded') === 'true';
          $$('[data-sc-why]', el).forEach((x) => x.setAttribute('aria-expanded', 'false'));
          if (open) { box.hidden = true; return; }
          b.setAttribute('aria-expanded', 'true');
          const item = (after && after[k]) || before[k] || {};
          const reasons = reasonsOf[k] || [k];
          const n = (trk.changes || []).filter((x) => reasons.includes(x.reason) && x.op !== 'comment').length;
          box.textContent = `${k}：${item.why || '没写理由'}${n ? ` · 提了 ${n} 处修改，点「打开批注视图」逐条看` : ' · 没有要改的'}`;
          box.hidden = false;
        }));
        $('#scOpen', el).onclick = () => window.openTracked(topic.id, { topic: true, post: { id: String(topic.id), text: d.script.text, trk, source_title: d.title || '', _topic: true, summary: false } });
        $('#scCopy', el).onclick = () => navigator.clipboard.writeText(d.script.text).then(() => toast('已复制'), () => toast('复制失败'));
      }
      $$('[data-sc-src]', el).forEach((b) => (b.onclick = () => {
        const source = b.dataset.scSrc;
        const text = source === 'paste' ? ($('#scPaste', el).value || '') : '';
        if (source === 'paste' && text.trim().length < 200) { toast('贴进来的稿子太短，至少 200 字'); return; }
        start(topic, source, text, false, el);
      }));
    },
  });

  // 批注视图里处理了修改、关掉了：回到这个页签时数字要是新的
  window.onTrackedChange = (id) => {
    if (typeof VD !== 'undefined' && VD.topicId === id && VD.tab === 'script') redraw();
  };
})();
