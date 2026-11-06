'use strict';
/* 打包 · 一条视频的文章版：整理原话出草稿（或设置里选的写作 skill） → 看、改 → 下一步配图。9/29 起在「03 打包」里显示（pack.js 借这个 render）。
   9/29 作者：写完之后只有两条路——重写，或者去配图。复制、下载、交给研习室、发公众号这些都拿掉：
   不配图、不排版他不会发；发在发布台。重写必须说这次要怎么改，只改他说的。 */
window.VIDEO_TABS = window.VIDEO_TABS || [];

const AR = { topicId: null, draft: null, dirty: false, mode: 'preview' };

async function startWrite(topicId, instruction) {
  try {
    const res = await api(`/api/topics/${topicId}/write`, { method: 'POST', body: instruction ? { instruction } : {} });
    toast(res.message);
    if (window.refreshTopics) await window.refreshTopics();
  } catch (err) { toast(err.message); }
}

document.addEventListener('click', (e) => {
  const write = e.target.closest('[data-write]');
  if (write) { e.preventDefault(); startWrite(Number(write.dataset.write)); return; }
});

async function loadDraft() {
  AR.draft = null;
  try { AR.draft = { ...(await api(`/api/topics/${AR.topicId}/article`)), topic_id: AR.topicId }; } catch (err) { AR.draft = { error: err.message, topic_id: AR.topicId }; }
  AR.dirty = false;
}

function refreshWorkTab() {
  const box = $('#videoBody');
  if (box) box.dataset.sig = '';
  if (window.rerenderPackRow) window.rerenderPackRow('article');
  renderView();
}

window.VIDEO_TABS.push({
  key: 'article',
  label: 'X 图文文章',
  badge: (t) => (t.write_state === 'running' ? '写作中' : t.article_path ? '已写' : ''),
  async render(topic, body) {
    if (AR.dirty && AR.topicId === topic.id && body.querySelector('#artText')) return; // never overwrite unsaved edits
    if (AR.topicId !== topic.id) { AR.topicId = topic.id; AR.draft = null; AR.mode = 'preview'; }
    if (topic.article_path && (!AR.draft || AR.draft.topic_id !== topic.id)) await loadDraft();
    let main = '';
    {
      if (topic.write_state === 'running') {
        main = `<div class="empty"><span class="spin"></span><b>正在整理《${esc(topic.title)}》</b><span>照视频字幕（SRT）整理，一般 1–5 分钟。写完自动出现在这里，可以先去做别的。</span></div>`;
      } else if (!topic.article_path) {
        main = `<div class="empty"><b>把这条写成文字版（X 图文文章）</b>${topic.write_state === 'failed' ? `<span class="err">${esc(topic.write_error || '写作失败')}</span>` : ''}<span>${topic.video_project || topic.published_video_id ? '以这条视频的原话为主，' : ''}${topic.note_paths.length ? `加上选题关联的 ${topic.note_paths.length} 条 Obsidian 笔记，` : ''}${S.state && S.state.settings.writer_skill ? `交给 ${esc(S.state.settings.writer_skill)} 写成文字版。作者是你。` : '整理成文字版：只删口语、可以调句子顺序，不改你的词。'}${topic.formats === 'video' ? '（这条原来只做视频，点了之后改成「文章 + 视频」）' : ''}</span><button class="btn primary" type="button" data-write="${topic.id}">${topic.write_state === 'failed' ? '重写' : '写文章'}</button></div>`;
      } else if (AR.draft && AR.draft.error) {
        main = `<div class="empty"><b>${esc(AR.draft.error)}</b></div>`;
      } else if (AR.draft) {
        const d = AR.draft;
        const chars = d.markdown.replace(/\s/g, '').length;
        main = `<div class="art-head">
            <div><h2>${esc(topic.title)}</h2><small>${chars} 字 · ${d.generated_at ? `生成于 ${day(d.generated_at)}` : ''} · 最后修改 ${day(d.updated_at)}${d.sources && d.sources.length ? ` · 照${d.sources.map((x) => (x.title === '视频原话（转写）' ? '<b>视频原话</b>' : `笔记《${esc(x.title)}》`)).join('、')}写` : ''}${d.instruction ? ` · 按「${esc(d.instruction)}」重写过` : ''}</small></div>
            <div class="acts">
              <div class="seg-toggle" role="group"><button type="button" class="${AR.mode === 'preview' ? 'on' : ''}" data-mode="preview">预览</button><button type="button" class="${AR.mode === 'edit' ? 'on' : ''}" data-mode="edit">编辑</button></div>
            </div>
          </div>
          ${AR.mode === 'edit' ? `<textarea id="artText" spellcheck="false">${esc(d.markdown)}</textarea>` : `<article class="md art-md">${renderMarkdown(d.markdown.replace(/!\[([^\]]*)\]\((?!https?:|data:|\/)(?:\.\/)?([^)\s]+)\)/g, (m, alt, rel) => `![${alt}](/api/topics/${topic.id}/article-file/${rel})`))}</article>`}
          <div class="art-foot">
            ${AR.mode === 'edit' ? '<button class="btn primary" type="button" id="artSave">保存</button>' : ''}
            <button class="btn" type="button" id="artRewriteOpen">重写…</button>
            <span class="spacer"></span>
          </div>
          <div class="art-rewrite" id="artRewrite" hidden>
            <label for="artInstr">这次要怎么改？<small>只改你说的地方，其余保持这一版。这一版会另存一份（article.prev.md）。</small></label>
            <textarea id="artInstr" rows="2" placeholder="比如：开头直接给结论；第三段的例子换成视频里讲的那个客户；控制在 2500 字以内"></textarea>
            <div class="acts"><button class="btn primary" type="button" id="artRewriteGo">按这个重写</button><button class="btn ghost" type="button" id="artRewriteCancel">算了</button></div>
          </div>`;
      }
    }
    body.innerHTML = main;
    // 10/20 走查：插图状态写着「好了」，文章里却有 3 张破图。预览里逐张看图加载没有，没出来的就直说
    const art = $('.art-md', body);
    if (art && art.querySelectorAll) {
      let bad = 0;
      const note = document.createElement('p');
      note.className = 'art-broken bad'; note.hidden = true; note.setAttribute('role', 'alert');
      art.before(note);
      art.querySelectorAll('img').forEach((img) => {
        const fail = () => { bad += 1; note.hidden = false; note.textContent = `有 ${bad} 张图没显示出来：文件不在文章目录里，发之前补上或删掉这几处`; };
        if (img.complete && img.src && !img.naturalWidth) fail(); else img.addEventListener('error', fail);
      });
    }
    $$('[data-mode]', body).forEach((b) => (b.onclick = () => { AR.mode = b.dataset.mode; refreshWorkTab(); renderView(); }));
    const text = $('#artText');
    if (text) text.oninput = () => { AR.dirty = true; };
    const save = $('#artSave');
    if (save) save.onclick = async () => {
      try {
        AR.draft = { ...(await api(`/api/topics/${topic.id}/article`, { method: 'PUT', body: { markdown: $('#artText').value } })), topic_id: topic.id };
        AR.dirty = false; AR.mode = 'preview'; refreshWorkTab();
        toast('已保存');
        renderView();
      } catch (err) { toast(err.message); }
    };
    const panel = $('#artRewrite', body);
    const open = $('#artRewriteOpen', body);
    if (open) open.onclick = () => { panel.hidden = false; $('#artInstr', body).focus(); };
    const cancel = $('#artRewriteCancel', body);
    if (cancel) cancel.onclick = () => { panel.hidden = true; };
    const go = $('#artRewriteGo', body);
    if (go) go.onclick = () => {
      const instruction = $('#artInstr', body).value.trim();
      if (!instruction) { toast('先写这次要怎么改'); $('#artInstr', body).focus(); return; }
      if (AR.dirty) { toast('先保存你的修改'); return; }
      startWrite(topic.id, instruction);
    };
  },
});
