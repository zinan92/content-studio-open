/* 04 发布 · 全平台追踪（9/29 以前叫「补发队列」）：每条内容发在了哪些平台，一张表看全貌，每格能点开链接。
 * 没发齐的点「补发」：打开和「今天」同一个补发工作台（10/1 作者：不要两个页面做同一件事），包还没定稿的格子在那里点一下去打包。
 * 发布台上的这一条发完了，就回到这张表（作者：「finished the current item, then I should see the full tracking sheet」）。
 * 10/3 作者：「这一条发到哪」那页不要了。导轨上的「发布」直接到这里；发东西只走补发工作台（顶上的主按钮）。 */
window.VIEWS = window.VIEWS || {};

const BF = { data: null, busy: {}, poll: null };

async function loadBackfill() { [BF.data, BF.archive] = await Promise.all([api('/api/backfill'), api('/api/archive')]); }
window.refreshBackfillCount = async () => { try { await loadBackfill(); } catch (_) { /* ignore */ } paintPubSubnav(); };

function paintPubSubnav() {
  // 只剩一页了，不要标签
  $$('[data-pubnav]').forEach((nav) => { nav.innerHTML = ''; nav.hidden = true; });
}
window.paintPubSubnav = paintPubSubnav;

function bfCell(v, p) {
  const url = (v.links || {})[p.key];
  // 抖音上藏起来的（被判违规设成私密）：别的平台照样补发，抖音这格标「藏」，链接别人点不开
  if (p.key === 'douyin') return v.hidden_on_douyin ? '<span class="bf-dot hid" title="抖音上已设为私密；别的平台照样补发">藏</span>' : `<a class="bf-dot on link" href="${esc(url)}" target="_blank" rel="noopener" title="在抖音上打开">↗</a>`;
  const st = v.done[p.key];
  if (v.cancelled && !st) return '<span class="bf-dot off" title="这条不补发了">–</span>';
  if (st === 'record' && url) return `<a class="bf-dot on link" href="${esc(url)}" target="_blank" rel="noopener" title="${esc(p.label)}：${esc(url)}">↗</a>`;
  if (st === 'record') return `<span class="bf-dot on" title="${esc(p.label)}：发过了，没记链接">✓</span>`;
  if (st === 'skip') return `<span class="bf-dot skip" title="${esc(p.label)}：不发（在补发工作台里标的）">不发</span>`;
  if (st === 'mark') return `<button class="bf-dot on mark" type="button" data-bfunmark="${esc(v.video_id)}" data-p="${p.key}" title="${esc(p.label)}：你标过已经发过，点一下撤回">✓</button>`;
  return `<button class="bf-dot" type="button" data-bfmark="${esc(v.video_id)}" data-p="${p.key}" title="${esc(p.label)}：还没发。在工作台外面发过的，点一下标成已发">·</button>`;
}

/* 每条只有一个按钮，永远是下一步：没有成片 → 先下成片；正在下 → 等；有了 → 补发。 */
function bfNext(v) {
  // 9/30 作者：没有时效性的旧内容不补发了。划掉，能点回来。
  if (v.cancelled) return `<span class="bf-file">不补发了</span><button class="linklike" type="button" data-bfcancel="${esc(v.video_id)}" data-on="0">恢复</button>`;
  if (!v.missing.length) return '';
  const drop = `<button class="linklike bf-drop" type="button" data-bfcancel="${esc(v.video_id)}" data-on="1" title="没有时效性了：不再往别的平台补。抖音上那条不动">不补发</button>`;
  const has = v.video === 'master' || v.video === 'download';
  const d = v.download;
  if (!has && d && d.state === 'downloading') return '<span class="bf-file"><span class="spin"></span> 正在下成片…</span>' + drop;
  if (!has && BF.archive && BF.archive.progress && BF.archive.progress.state === 'downloading') return '<span class="bf-file">排队存档中</span>' + drop;
  // 没有成片：原片在另一台电脑上。拷进作品库里这条的「1 成片」（或 SSD 视频目录的任何地方），点顶上「在本机再找一遍」。
  if (!has) return '<span class="bf-file" title="原片在另一台电脑上：拷进作品库这条的「1 成片」，再点顶上「在本机再找一遍」">作品库缺成片 · 在另一台电脑上</span>' + drop;
  const note = v.video === 'master' ? '有成片' : '作品库里有成片';
  return `<span class="bf-file ok">${note}</span><button class="btn small primary" type="button" data-bftake="${esc(v.video_id)}" ${BF.busy[v.video_id] ? 'disabled' : ''}>补发</button>${drop}`;
}

window.VIEWS.backfill = {
  async render() {
    paintPubSubnav();
    const body = $('#backfillBody');
    if (!BF.data) body.innerHTML = '<div class="panel empty"><span class="spin"></span><span>正在对账…</span></div>';
    try { await loadBackfill(); } catch (err) { body.innerHTML = `<div class="panel empty"><b>${esc(err.message)}</b></div>`; return; }
    paintPubSubnav();
    const d = BF.data;
    const cols = d.platforms;
    const todo = d.videos.filter((v) => v.missing.length);
    $('#backfillFigs').innerHTML = `<div class="pub-figs"><span>${d.videos.length} 条内容 · ${todo.length} 条还有平台没发${d.videos.some((v) => v.cancelled) ? ` · ${d.videos.filter((v) => v.cancelled).length} 条不补发` : ''}</span><button class="btn small" type="button" id="bfCsv">下载表格</button><button class="btn primary" type="button" id="bfDesk">打开补发工作台 →</button></div>`;
    $('#bfDesk').onclick = () => { if (window.openBackfillDesk) window.openBackfillDesk(); };
    const row = (v) => `<tr class="${v.cancelled ? 'bf-cancelled' : ''}">
      <td class="bf-title"><b>${esc(v.headline || v.title.slice(0, 30))}</b><small>${day(v.published_at)} · 点赞 ${fmt(v.likes)}${v.multiple !== null ? ` · ${v.multiple}×` : ''}</small>
        <div class="bf-acts">${bfNext(v)}</div></td>
      ${cols.map((p) => `<td class="c ${p.core === false ? 'minor' : ''}">${bfCell(v, p)}</td>`).join('')}
    </tr>`;
    // 10/4 作者：X 先发，抖音 · 小红书 · 视频号同时传；B 站 · YouTube · 公众号降权——放最右、淡一点、按排期自动发，不用看
    const firstMinor = cols.findIndex((p) => p.core === false);
    const head = `<tr><th>内容</th>${cols.map((p, i) => `<th class="c ${p.core === false ? 'minor' : ''} ${i === firstMinor ? 'minor-first' : ''}">${esc(p.label)}${p.key === 'x' ? '<small class="bf-how">先发</small>' : i === firstMinor ? '<small class="bf-how">自动发</small>' : ''}</th>`).join('')}</tr>`;
    const a = BF.archive || {};
    const p = a.progress || {};
    const running = p.state === 'downloading';
    let strip;
    if (!a.path) strip = '<span>还没设作品库目录。去「设置」填一个（建议放在外接硬盘上）。</span>';
    else if (!a.available) strip = `<span class="bad">作品库所在的硬盘没插：${esc(a.path)}</span>`;
    else strip = `<span>作品库有成片 <b>${a.archived}</b> / ${a.total} 条（本机原片 ${a.local}，其余是抖音下载版） · <code>${esc(a.path)}</code></span>
      ${running ? `<span><span class="spin"></span> 正在存：这一轮 ${p.total || '…'} 条，已存 ${p.done || 0} 条（每条之间停 20 秒）</span>`
        : a.pending ? `<button class="btn small" type="button" id="bfArchiveAll">在本机再找一遍（缺 ${a.pending} 条）</button>` : '<span class="bf-file ok">都有成片了</span>'}
      ${p.state === 'failed' && p.failed ? `<span class="bad" title="${esc(p.failed.error || '')}">上一轮停在一条下载失败上，可能是抖音风控；过一会儿再点</span>` : ''}
      <small>按时长和日期在本机找原片，不从抖音下。以后每次同步发现新视频，也只在本机找。</small>`;
    body.innerHTML = `
      <div class="panel bf-archive">${strip}</div>
      <p class="in-note">${esc(d.order)}。X 先发，抖音、小红书、视频号同时传；右边淡的三列（B 站、YouTube、公众号）按排期自动发，不用看。↗ 点开就是那个平台上的这一条；· 是还没发，在工作台外面发过的点一下标成已发。没发齐、作品库里有成片的，点「补发」：打开补发工作台挑平台、预览、现场发。</p>
      <div class="panel bf-tbl"><table><colgroup><col>${cols.map(() => '<col class="bf-pcol">').join('')}</colgroup><thead>${head}</thead><tbody>${d.videos.map(row).join('')}</tbody></table></div>`;
    const csvBtn = $('#bfCsv');
    if (csvBtn) csvBtn.onclick = () => {
      const q = (x) => `"${String(x ?? '').replace(/"/g, '""')}"`;
      const lines = [['内容', '发布日期', ...cols.map((c) => c.label)], ...d.videos.map((v) => [v.headline || v.title, (v.published_at || '').slice(0, 10), ...cols.map((c) => (v.done[c.key] === 'skip' ? '不发' : (v.links || {})[c.key] || (v.done[c.key] ? '已发' : '')))])];
      const blob = new Blob(['\ufeff' + lines.map((l) => l.map(q).join(',')).join('\n')], { type: 'text/csv;charset=utf-8' });
      const a2 = document.createElement('a'); a2.href = URL.createObjectURL(blob); a2.download = `全平台追踪-${new Date().toISOString().slice(0, 10)}.csv`; a2.click(); URL.revokeObjectURL(a2.href);
    };
    const mark = async (vid, p, doneFlag) => { try { await api(`/api/backfill/${vid}/mark`, { method: 'POST', body: { platform: p, done: doneFlag } }); await loadBackfill(); renderView(); } catch (err) { toast(err.message); } };
    $$('[data-bfmark]', body).forEach((b) => (b.onclick = () => mark(b.dataset.bfmark, b.dataset.p, true)));
    $$('[data-bfunmark]', body).forEach((b) => (b.onclick = () => mark(b.dataset.bfunmark, b.dataset.p, false)));
    $$('[data-bfcancel]', body).forEach((b) => (b.onclick = async () => {
      try { await api(`/api/backfill/${b.dataset.bfcancel}/cancel`, { method: 'POST', body: { cancel: b.dataset.on === '1' } }); toast(b.dataset.on === '1' ? '这条不补发了，能点回来' : '恢复了'); await loadBackfill(); renderView(); if (window.refreshTodayBadge) window.refreshTodayBadge(); } catch (err) { toast(err.message); }
    }));
    // 9/29 起发布台要打包定稿过才发（文字平台）：补发接上以后先进打包，定稿了再去发
    // 10/1 作者：补发只走一个窗口。先接上选题（种文案、接成片），然后打开补发工作台，滚到这一条
    $$('[data-bftake]', body).forEach((b) => (b.onclick = async () => {
      const vid = b.dataset.bftake;
      BF.busy[vid] = true; renderView();
      try {
        await api(`/api/backfill/${vid}/take`, { method: 'POST' });
        if (window.openBackfillDesk) window.openBackfillDesk(vid);
      } catch (err) { toast(err.message); }
      BF.busy[vid] = false; await loadBackfill(); renderView();
    }));
    $$('[data-bfdl]', body).forEach((b) => (b.onclick = async () => {
      if (!confirm('从抖音把这条视频下回来？一次只下一条，大概一两分钟。')) return;
      try { await api(`/api/backfill/${b.dataset.bfdl}/download`, { method: 'POST' }); toast('开始下了'); } catch (err) { toast(err.message); }
      await loadBackfill(); renderView();
    }));
    const all = $('#bfArchiveAll');
    if (all) all.onclick = async () => {
      if (!confirm(`按时长和日期在本机再找一遍这 ${a.pending} 条的原片？不会从抖音下。`)) return;
      try { await api('/api/archive/run', { method: 'POST' }); toast('开始存了'); } catch (err) { toast(err.message); }
      await loadBackfill(); renderView();
    };
    clearTimeout(BF.poll);
    if (running || d.videos.some((v) => v.download && v.download.state === 'downloading')) BF.poll = setTimeout(() => { if (S.view === 'backfill') renderView(); }, 3000);
  },
};
