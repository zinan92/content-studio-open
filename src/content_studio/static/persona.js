/* 定位 · 我的形象（10/7 作者，原来在设置里）：上面是定稿形象（头像、全身像、四视图、动作参考、水印），下面是每次文章配图里
 * 画出来的形象，按文章分组、新的在前。文件都在形象文件夹（persona.py，作者 的在 Obsidian 里他的配图 skill 下）；这里只看不改。 */
const PERSONA = { busy: false, last: '', galleryOpen: false, groups: {} };  // last：上次画的数据；有任务在跑时 refreshAll 每 3 秒重画设置页，数据没变就不动，图不闪

// 页面上放小图（几十 KB），点开才是原图；地址带版本 v，浏览器缓存住，再打开不用重下（10/7：原图一次近 30 MB，外网要等十来秒）
function personaImg(file, label, v) {
  const full = `/api/persona/file?path=${encodeURIComponent(file)}&v=${encodeURIComponent(v || '')}`;
  return `<a class="pe-img" href="${full}" target="_blank" rel="noopener"><img src="${full}&thumb=1" alt="${esc(label)}" loading="lazy" decoding="async"></a>`;
}

function personaGroups(items) {
  const groups = [];
  for (const g of items) {
    const dir = g.file.split('/').slice(0, -1).join('/');
    let last = groups[groups.length - 1];
    if (!last || last.dir !== dir) { last = { dir, title: g.title, at: g.at, items: [] }; groups.push(last); }
    last.items.unshift(g);  // 列表是新的在前；同一轮里按 01、02、03 的顺序
  }
  return groups;
}

window.renderPersona = async () => {
  const box = $('#personaBody');
  if (!box || PERSONA.busy) return;
  PERSONA.busy = true;
  let d;
  try { d = await api('/api/persona'); } catch (err) { PERSONA.last = ''; box.innerHTML = `<div class="panel empty"><b>读不到个人形象</b><span>${esc(err.message)}</span></div>`; return; } finally { PERSONA.busy = false; }
  const sig = JSON.stringify(d);
  if (sig === PERSONA.last && box.firstChild) return;
  PERSONA.last = sig;
  const base = d.base.length
    ? `<div class="pe-base">${d.base.map((b) => `<figure>${personaImg(b.file, b.label, b.v)}<figcaption>${esc(b.label)}</figcaption></figure>`).join('')}</div>`
    : `<div class="empty"><b>还没有定稿形象</b><span>把 avatar.png、fullbody.png、sheet.png、reference.png 和 spec.md 放进 ${esc(d.dir)}</span></div>`;
  const note = d.skill
    ? `文章配图用 ${esc(d.skill)}：小黑的画法，主角是 ${esc(d.name)}`
    : d.ready
    ? `文章配图用小黑的画法，主角换成 ${esc(d.name)}`
    : '缺 spec.md 或 reference.png：文章配图还是画小黑';
  const groups = personaGroups(d.gallery);
  const gallery = groups.length
    ? groups.map((g) => `<details class="pe-group" data-persona-group="${esc(g.dir)}"${PERSONA.groups[g.dir] ? ' open' : ''}><summary class="pe-gh"><b>${esc(g.title)}</b><small>${esc((g.at || '').slice(0, 10))} · ${g.items.length} 张 · 点开查看</small></summary>
        <div class="pe-grid">${g.items.map((i) => `<figure>${personaImg(i.file, i.caption, i.v)}<figcaption>${esc(i.caption)}</figcaption></figure>`).join('')}</div></details>`).join('')
    : '<div class="empty"><span>还没有。下次给文章配图，画出来的每一张都会存到这里，重新配图也不会删。</span></div>';
  box.innerHTML = `<div class="panel"><div class="panel-h"><h2>定稿形象</h2><small>${note}</small></div>${base}</div>
    <details class="panel" id="personaGallery"${PERSONA.galleryOpen ? ' open' : ''}><summary class="panel-h"><h2>配图里的形象</h2><small>${d.gallery.length} 张 · 点开查看</small></summary>${gallery}</details>`;
  $('#personaGallery', box).ontoggle = (event) => { PERSONA.galleryOpen = event.target.open; };
  $$('[data-persona-group]', box).forEach((group) => { group.ontoggle = () => { PERSONA.groups[group.dataset.personaGroup] = group.open; }; });
};
