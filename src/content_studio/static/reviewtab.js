'use strict';

/* 加工中的「拍后」页签（10/13 作者）：录完、字幕放进项目后，用 park-writing 的 9 项清单给成片打分、写批注。
   只打分、只批注，一个字不改；批注写成「下一条要注意的」，下一条口述前会提醒他。
   字幕一放进项目就自动出（后台）；已经有字幕、还没批注过的内容，打开这个页签时自动起一次。
   接口在 /api/topics/{id}/review；规则在 park-writing 的清单里（review、post-shoot）。 */
(() => {
  const RV = { poll: null, data: {}, auto: {}, busy: false };

  async function start(topic, force) {
    if (RV.busy) return;
    RV.busy = true;
    try {
      const r = await api(`/api/topics/${topic.id}/review`, { method: 'POST', body: { force: !!force } });
      if (r.message && force) toast(r.message);
    } catch (err) { toast(err.message); }
    RV.busy = false;
    redraw();
  }

  function redraw() {
    if (typeof VD === 'undefined' || typeof renderView !== 'function') return;
    VD.forceRender = true;
    if (S.view === 'work') renderView();
  }

  const note = (text) => `<div class="empty"><b>${text[0]}</b>${text[1] ? `<span>${text[1]}</span>` : ''}</div>`;

  function itemRow(item, s) {
    if (!s) return `<li class="rv-item na"><b>${esc(item.title)}</b><span class="rv-score">—</span><p>${item.id === 'typo' ? '拍视频没有导语；错字通顺发文章前才查' : '这一次没打分'}</p></li>`;
    return `<li class="rv-item"><b>${esc(item.title)}</b><span class="rv-score">${s.score}<small>/10</small></span>
      <p>${esc(s.why || '没写理由')}</p>${s.quote ? `<blockquote>字幕里：「${esc(s.quote)}」</blockquote>` : ''}</li>`;
  }

  window.VIDEO_TABS.push({
    key: 'review', label: '拍后',
    show: (t) => typeof featureOn === 'function' && featureOn('xline') && Boolean(t.video_project || t.published_video_id),
    badge: (t) => {
      const d = RV.data[t.id];
      if (!d) return '';
      if (d.running) return '在做';
      return d.review ? `${(d.review.next || []).length} 条` : '';
    },
    async render(topic, el) {
      clearTimeout(RV.poll);
      let d;
      try { d = await api(`/api/topics/${topic.id}/review`); } catch (err) {
        el.innerHTML = `<div class="empty" role="alert"><b>读不到拍后批注：${esc(err.message)}</b></div>`;
        return;
      }
      RV.data[topic.id] = d;
      if (!el.isConnected) return;
      if (!d.available) { el.innerHTML = note(['这台机器的 park-writing 还没有评判清单', '把 park-writing 更新到带 review 和 post-shoot 的版本，这里就会出批注。']); return; }
      if (d.running) {
        el.innerHTML = `<div class="empty"><span class="spin"></span><b>在做拍后批注</b><span>按 9 项清单给成片打分，一两分钟。</span></div>`;
        RV.poll = setTimeout(() => { if (VD.topicId === topic.id && VD.tab === 'review') redraw(); }, 4000);
        return;
      }
      if (!d.has_transcript) { el.innerHTML = note(['还没有字幕', '录完把剪映导出的视频和字幕（.srt）放进项目，这里会自动出批注。']); return; }
      // 字幕在、这一份还没批注过：自动起一次（每条内容每次打开最多一次；失败了不自动再来，等他点）
      if (d.can_auto && !RV.auto[topic.id]) { RV.auto[topic.id] = true; start(topic, false); return; }
      const err = d.error ? `<p class="journey-save-state bad" role="alert">${esc(d.error)}</p>` : '';
      if (!d.review) {
        el.innerHTML = `<div class="sc-body">${err}<div class="sc-head"><h3>拍后批注</h3><p>字幕已经在了，还没有批注。只打分、只批注，不改你的稿。</p>
          <div class="sc-acts"><button class="btn primary" type="button" id="rvStart">现在批注</button></div></div></div>`;
        $('#rvStart', el).onclick = () => start(topic, true);
        return;
      }
      const rec = d.review, byTitle = rec.scores || {};
      const items = (rec.items && rec.items.length ? rec.items : Object.keys(byTitle).map((title) => ({ id: byTitle[title].id, title })));
      el.innerHTML = `<div class="sc-body">${err}<div class="sc-head"><h3>拍后批注</h3>
        <p>按 9 项清单给拍完的成片打分；只批注，没改你的稿，也不用补拍。${d.stale ? ' <b class="bad">字幕换过了，这份是按旧字幕做的。</b>' : ''}</p>
        <div class="sc-acts"><button class="btn${d.stale ? ' primary' : ''}" type="button" id="rvAgain">${d.stale ? '按新字幕重来' : '重新批注'}</button></div></div>
        ${(rec.next || []).length ? `<div class="rv-next"><b>下一条要注意的</b><ol>${rec.next.map((n) => `<li>${esc(n)}</li>`).join('')}</ol><small>下一条口述前，这里会提醒你。</small></div>` : ''}
        <ul class="rv-list">${items.map((it) => itemRow(it, byTitle[it.title])).join('')}</ul></div>`;
      $('#rvAgain', el).onclick = () => start(topic, true);
    },
  });
})();
