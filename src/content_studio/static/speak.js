'use strict';
/* 加工中 · 你说一遍：复刻的第一步。
 * 10/5 作者：「点击复刻，把拆解的报告放在左边，在右边再开一个新的空白窗口，然后直接口播输入就可以了。」
 * 左边就是拆解报告页那张主线结构 + 为什么爆（app.js 的 reportGridHtml，同一张）；右边一个空白大框，
 * 用电脑的语音输入法说（边说边存，刷新不丢）。10/13 起没有「删口水话」按钮：口癖交给 park-writing 第一轮的「11 条风格」。
 * 「存进原始输出」写进 Obsidian 的 003，挂到这条选题上，接着写骨架。 */
const SP = { data: null, topicId: null, timer: null, poll: null, report: null };

async function spLoad(topicId) {
  SP.data = await api(`/api/topics/${topicId}/speak`);
  SP.topicId = topicId;
  return SP.data;
}

async function spReport(videoId) {
  if (SP.report && SP.report.content_id === videoId) return SP.report;
  try { SP.report = await api(`/api/reports/${videoId}`); } catch (err) { SP.report = { content_id: videoId, error: err.message }; }
  return SP.report;
}

function spSaveSoon(topicId, text) {
  clearTimeout(SP.timer);
  SP.timer = setTimeout(() => spSave(topicId, { dictation: text }), 1200);
}
async function spSave(topicId, body) {
  clearTimeout(SP.timer);
  try { SP.data = await api(`/api/topics/${topicId}/speak`, { method: 'PUT', body }); $('#spSaved') && ($('#spSaved').textContent = '已存'); } catch (err) { toast(err.message); }
}

// 口述（10/13 作者）：别人的材料（日报、收藏、Clippings）放左边，只当话题；说的话是他自己的
function spSourceHtml(src) {
  const parts = (src && src.parts) || [];
  if (!parts.length) return `<div class="panel empty"><b>没有别人的材料</b><span>${esc((src && src.memo) || '直接说就行。')}</span></div>`;
  return parts.map((p) => `<div class="panel"><div class="panel-h"><h2>${esc(p.title)}</h2>${p.url ? `<a class="linklike" href="${esc(p.url)}" target="_blank" rel="noopener">看原文 ↗</a>` : ''}</div><pre class="plain">${esc(p.body)}</pre></div>`).join('');
}

function spSeriesList(d) {
  const eps = d.series_episodes || [];
  if (!eps.length) return `<div class="panel empty"><b>Obsidian 里找不到「${esc(d.series)}」的 系列.md</b></div>`;
  return `<div class="panel sp-series"><div class="panel-h"><h2>${esc(d.series)}</h2><small>${eps.length} 集</small></div>
    <ol>${eps.map((e) => `<li class="${e.n === d.episode ? 'now' : ''}">${esc(e.title)}${e.n === d.episode ? ' <small>← 这一集</small>' : ''}</li>`).join('')}</ol></div>`;
}

window.VIDEO_TABS.push({
  key: 'speak',
  label: '你说一遍',
  show: (t) => Boolean(t.replicate && t.replicate.mode && !t.replicate.note_path),
  badge: (t) => (t.replicate && t.replicate.note_path ? '已存' : '第一步'),
  async render(topic, el) {
    clearTimeout(SP.poll);
    let d;
    try { d = SP.topicId === topic.id && SP.data && !SP.data.running ? SP.data : await spLoad(topic.id); } catch (err) { el.innerHTML = `<div class="empty"><b>${esc(err.message)}</b></div>`; return; }
    // 系列里的一集（10/5）：没有拆解，左边是这个系列的每集标题，这一集高亮
    const isSeries = Boolean(d.series);
    const isOral = d.mode === 'oral';
    const r = isSeries || isOral ? {} : d.video_id ? await spReport(d.video_id) : { error: '找不到这条的拆解报告' };
    // 10/13 作者：上一条拍后批注里「下一条要注意的」，口述前先看一眼（没有就不出现）
    let remind = '';
    if (!d.note_path) {
      try {
        const last = (await api(`/api/review/latest?exclude=${topic.id}`)).review;
        if (last && (last.next || []).length) remind = `<div class="sp-remind"><b>上一条《${esc(last.title || '')}》的批注：这一条要注意的</b><ol>${last.next.map((n) => `<li>${esc(n)}</li>`).join('')}</ol></div>`;
      } catch (_) { /* 提醒读不到不影响口述 */ }
    }
    // 10/20 走查：另一条还没发完时，这里照样让人写，点「存好，出稿」话存下了，稿子却被拦住，页面还说「口播稿在出」。
    // 一开始就说清：话可以先存，稿子等那条发完再出
    const busy = typeof BD !== 'undefined' && BD.data && BD.data.focus && BD.data.focus.id !== topic.id ? BD.data.focus : null;
    if (busy) remind = `<div class="sp-remind sp-hold"><b>《${esc(busy.title)}》还没发完</b><p>一次只做一条。这里的话可以先说、先存；口播稿等那条在「发」里点「这条发完了」以后再出。</p></div>` + remind;
    const left = isOral ? spSourceHtml(d.source) : isSeries ? spSeriesList(d) : r.error ? `<div class="panel empty"><b>${esc(r.error)}</b></div>` : reportGridHtml(r);
    el.innerHTML = `<div class="sp">
      ${isOral ? `<div class="sp-src"><small>口述</small><div><b>${esc(topic.title)}</b></div></div>` : isSeries ? `<div class="sp-src"><small>${esc(d.series)}</small><div><b>第 ${d.episode || '?'} 集 · ${esc(topic.title)}</b></div></div>`
        : `<div class="sp-src"><small>复刻 · 拆解自</small><div><b>${esc(d.author || '')}《${esc(cleanTitle(d.title || ''))}》</b>${d.multiple ? `<span class="fd-hot">平时的 ${d.multiple} 倍</span>` : ''}${d.url ? ` <a class="linklike" href="${esc(d.url)}" target="_blank" rel="noopener">看原视频 ↗</a>` : ''}</div></div>`}
      ${remind}
      <div class="sp-grid">
        <div class="sp-report">${left}</div>
        <div class="sp-talk">
          <label for="spText"><b>${isOral ? (d.source && d.source.parts.length ? '看着左边的材料，说你的看法' : '直接说') : isSeries ? '这一集，直接说' : '看着左边的拆解，直接说'}</b><small>用电脑的语音输入法往这里说，说的都是你自己的经历和判断。边说边存，刷新不丢。</small></label>
          <textarea id="spText" spellcheck="false" placeholder="直接开口说……">${esc(d.dictation || '')}</textarea>
          <div class="sp-acts"><span id="spSaved" class="sp-saved"></span></div>
          <div class="sp-done">
            ${isSeries ? '' : `<label class="sp-title"><span>这条叫什么（标题，可以先随便写）</span><input id="spTitle" value="${esc(topic.title)}" maxlength="60" autocomplete="off"></label>`}
            <button class="btn primary big" type="button" id="spSave">${d.note_path ? '再存一份进原始输出' : busy ? '先存好（稿子等那条发完再出）' : '存好，出稿'}</button>
            <small>${d.note_path ? `已存：${esc(d.note_path)}` : isOral ? `存进 Obsidian 的 ${esc(rawFolder())}，只有你说的话，别人的材料一句不用。存完就是你自己的话，直接出稿，不用再写骨架。` : isSeries ? `存进 Obsidian 的 ${esc(rawFolder())}/${esc(d.series)}/，文件名是「编号 标题」，只有你说的话。改标题去 Obsidian 改 系列.md。` : '存进 Obsidian 的 ${esc(rawFolder())}，只有你说的话，最上面写清结构借自谁。骨架只读这一篇。'}</small>
          </div>
        </div>
      </div>
    </div>`;

    if (!isSeries && !isOral && !r.error) bindReportGrid($('.sp-report', el), r);
    const text = $('#spText', el);
    text.oninput = () => { VD.dirty = true; $('#spSaved').textContent = '…'; spSaveSoon(topic.id, text.value); };
    text.onblur = () => { VD.dirty = false; spSave(topic.id, { dictation: text.value }); };
    const save = $('#spSave', el);
    save.onclick = async () => {
      save.disabled = true; VD.dirty = false;
      await spSave(topic.id, { dictation: text.value });
      try {
        const res = await api(`/api/topics/${topic.id}/speak/save`, { method: 'POST', body: { title: isSeries ? '' : $('#spTitle', el).value } });
        // 装了 park-writing：存完就在后台用你的原话出口播稿，页面直接落在「口播稿」；没装的机器照老的写骨架
        const toScript = Boolean(res.script);
        const held = res.script && res.script.started === false;
        toast(held ? `存好了：${res.name}。${res.script.message || '稿子等正在做的那条发完再出'}` : toScript ? `存好了：${res.name}。口播稿在出，一两分钟` : `存进原始输出了：${res.name}。骨架在写`);
        if (window.refreshTopics) await window.refreshTopics();
        if (window.invalidateWork) window.invalidateWork();
        VD.tab = toScript ? 'script' : 'outline'; renderView();
      } catch (err) { toast(err.message); save.disabled = false; }
    };
  },
});
