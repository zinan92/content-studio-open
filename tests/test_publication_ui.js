'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = (name) => fs.readFileSync(path.join(__dirname, '../src/content_studio/static', name), 'utf8');
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const flush = () => new Promise((resolve) => setImmediate(resolve));
const fact = (state, more = {}) => ({ state, label: { published:'已发布',draft:'在草稿箱',unknown:'结果待核实',ready:'可准备发布',not_ready:'素材未齐',wait:'等待前置条件' }[state] || state, ...more });
const platform = (key) => ({ key, label: key, today: { views: 0, read: 'read' }, pending: [], days: [], posts: [], notes: [], defaults: { choices: [], forms: [], traffic_tags: [], on: true, handle: '' } });
function harness(api = async () => ({})) {
  const nodes = {}, calls = [], liveCalls = [], modes = [], controls = {}, timers = [], liveTimers = [];
  const box = () => ({ isConnected: true, innerHTML: '', dataset: {}, controls: {}, contains: () => false, querySelector: () => null });
  nodes['#platformBody'] = box(); nodes['#packBody'] = box(); nodes['#summaryBody'] = box();
  const context = vm.createContext({
    window: { VIEWS: {}, scrollTo() {} }, S: { view:'platform', platformKey:'x', packId:1, platforms:[] }, URL, Date, console,
    document: { activeElement:null, body: {contains: (el) => el.isConnected} },
    api: (url, options) => {if(url === '/api/xline/live'){liveCalls.push({url,options}); return Promise.resolve({kpi:[]});} calls.push({url,options});return api(url, options);},
    $: (selector, root) => (root?.controls || controls)[selector]?.[0] || nodes[selector] || null,
    $$: (selector, root) => (root?.controls || controls)[selector] || [],
    esc: (s) => String(s ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),
    fmt: (n) => String(n), day: (v) => v || '', cleanTitle: (v) => v, platformOff: () => false,
    featureOn: () => true, renderView() {}, toast() {}, clearTimeout() {}, setTimeout: (fn,ms) => { if(ms > 250000){liveTimers.push(fn);return -liveTimers.length;} timers.push(fn); return timers.length; },
  });
  for (const name of ['platform.js','pack.js','output.js','xline.js']) vm.runInContext(source(name), context);
  return {context, nodes, calls, liveCalls, liveTimers, modes, timers, box, run:(code)=>vm.runInContext(code,context)};
}

test('platform requests cannot overwrite a newer platform cache or page', async () => {
  const a=deferred(),b=deferred(); const h=harness((url)=>url.endsWith('/x')?a.promise:b.promise);
  const old=h.context.window.VIEWS.platform.render(); h.run("S.platformKey='douyin'"); const current=h.context.window.VIEWS.platform.render();
  b.resolve(platform('douyin')); await current; const html=h.nodes['#platformBody'].innerHTML;
  a.resolve(platform('x')); await old;
  assert.equal(h.run('PP.data.key'),'douyin'); assert.equal(h.nodes['#platformBody'].innerHTML,html);
});

test('platform late failure cannot replace a newly selected platform page', async () => {
  const a=deferred(),b=deferred();let n=0;const h=harness(()=>++n===1?a.promise:b.promise);
  const old=h.context.window.VIEWS.platform.render();h.run("S.platformKey='channels'");const current=h.context.window.VIEWS.platform.render();
  b.resolve(platform('channels'));await current;const html=h.nodes['#platformBody'].innerHTML;
  a.reject(new Error('old error'));await old;
  assert.equal(h.nodes['#platformBody'].innerHTML,html);assert.match(html,/新内容默认发什么/);assert.match(html,/pp-pend/);assert.match(html,/pp-data/);
});

test('all platform tasks share one page; the X page is the same as the others, no X-only section (10/19)', async()=>{
  const h=harness(async(url)=>platform(url.split('/').pop()));
  h.context.window.renderXDaily=(box,mode)=>h.modes.push(mode);h.context.window.renderXHot=()=>h.modes.push('hot');
  h.nodes['#ppXDaily']=h.box();h.nodes['#ppXSources']=h.box();h.nodes['#ppXHot']=h.box();
  for(const key of ['douyin','channels','xiaohongshu','x']){
    h.context.S.platformKey=key;await h.context.window.VIEWS.platform.render();const html=h.nodes['#platformBody'].innerHTML;
    assert.match(html,/pp-pend/);assert.match(html,/pp-data/);  // 10/19 作者：X 改回和抖音、小红书、视频号一个格式
    assert.match(html,/pp-def/);assert.doesNotMatch(html,/data-pp-tab=|role="tablist"/);
  }
  assert.deepEqual(h.modes,[]);assert.doesNotMatch(h.nodes['#platformBody'].innerHTML,/ppXDaily|xd-counts|ppXHot|ppXSources/);  // 10/19 作者：长文、短帖、每天发多少都拿掉
  h.context.featureOn=()=>false;await h.context.window.VIEWS.platform.render();assert.doesNotMatch(h.nodes['#platformBody'].innerHTML,/ppXDaily|ppXSources|ppXHot/);
});

test('manual upload is primary and registering a receipt remains a separate action',()=>{
  const h=harness();h.context.row={form:'video',label:'视频',ready:true,action:'hand',upload_url:'https://example.com/upload',presentation:fact('ready')};
  const html=h.run("ppFormRow({topic_id:1},row,{key:'channels',label:'视频号'})");
  assert.match(html,/class="btn small primary" href="https:\/\/example.com\/upload"/);
  assert.match(html,/data-pp-sent="1\|video\|channels">已上传，登记链接/);  // 10/20：key 带上平台，「发」表里几个平台不会一起弹链接框assert.doesNotMatch(html,/data-pp-send=/);
});

test('draft and unknown facts remain distinct and existing send authorization actions are retained',()=>{
  const h=harness();h.context.row={form:'text',label:'文字',ready:true,action:'draft',job:{draft:true,draft_link:'https://example.com/draft'},presentation:fact('draft')};
  const html=h.run("ppFormRow({topic_id:1},row,{key:'wechat_mp',label:'公众号'})");
  assert.match(html,/在草稿箱/);assert.doesNotMatch(html,/data-pp-send=|✓ 发了/);
  h.context.p=fact('unknown',{reason:'请先核对后台'});assert.match(h.run('publicationFact(p)'),/结果待核实.*请先核对后台/);
});

test('pack lanes count published receipts independently of material readiness and keep safe links',()=>{
  const h=harness();h.run('PK.data={topic:{id:1}}');h.context.v={armed:true,lanes:[
    {key:'x',label:'X',form_label:'文字',ready:true,presentation:fact('draft',{draft_link:'https://example.com/draft'})},
    {key:'douyin',label:'抖音',form_label:'视频',ready:true,presentation:fact('published',{url:'https://example.com/post',published_at:'2026-10-08T12:00:00'})},
    {key:'channels',label:'视频号',form_label:'视频',ready:false,presentation:fact('not_ready')},
  ]};const html=h.run('ctaInner(v)');assert.match(html,/发了 1 \/ 3/);assert.match(html,/回执 ↗/);assert.match(html,/草稿 ↗/);assert.doesNotMatch(html,/可以发了|去抖音核对/);
  // 10/20：标题没定稿时不给「开始发」，说先定标题；每个平台一行
  assert.match(html,/先定上面的标题/);assert.equal((html.match(/data-release="1"/g)||[]).length,0);assert.equal((html.match(/data-fa-plat=/g)||[]).length,3);
  h.context.p=fact('published',{url:'javascript:alert(1)'});assert.doesNotMatch(h.run('publicationFact(p)'),/href=/);
  assert.match(h.run('formsBlock()'),/<details[^>]*><summary>调整发布形式/);
});

test('late pack load cannot replace another selected topic or change its route id',async()=>{
  const a=deferred(),b=deferred();const h=harness((url)=>url.includes('/publish/desk')?url.includes('topic_id=1')?a.promise:b.promise:url==='/api/topics'?Promise.resolve([{id:1},{id:2}]):Promise.resolve({armed:true,steps:[]}));
  const old=h.run('loadPack(false)');h.run('S.packId=2');const current=h.run('loadPack(false)');b.resolve({topic:{id:2}});await current;a.resolve({topic:{id:1}});await old;
  assert.equal(h.run('PK.data.topic.id'),2);assert.equal(h.run('S.packId'),2);
});

test('summary sheet has an 鸡蛋 column: a link to the reply script in Obsidian, or a dash',()=>{
  const h=harness();const v=(id,egg)=>({video_id:id,topic_id:null,title:'标题'+id,published_at:'2026-10-08',likes:0,multiple:null,video:null,done:{},links:{},missing:[],egg});
  h.context.bf={platforms:[{key:'x',label:'X'}],videos:[v('1',{title:'爆款拆解',sent:'2026-10-11',open_url:'obsidian://open?path=%2Fa.md'}),v('2',null)]};
  h.context.mx={rows:[],publication_warnings:[]};
  const html=h.run('sheetBlock(bf,mx)');
  assert.match(html,/<th[^>]*>鸡蛋<\/th>/);assert.match(html,/href="obsidian:\/\/open\?path=%2Fa\.md"[^>]*>爆款拆解 ↗/);
  assert.equal((html.match(/没有记鸡蛋话术/g)||[]).length,1);
});

test('summary sheet keeps the original one-word cells but a draft fact beats a stale backfill record',()=>{
  const h=harness();h.context.bf={platforms:[{key:'x',label:'X'}],videos:[{video_id:'1',topic_id:1,title:'标题',published_at:'2026-10-08',likes:0,multiple:null,video:'master',done:{x:'record'},links:{x:'https://example.com/old'},missing:[]}]};
  h.context.mx={rows:[{video_id:'1',total:0,cells:{x:{state:'none',publication_state:'draft',forms:[{form:'text',presentation:fact('draft')}]}}}],publication_warnings:[]};
  const html=h.run('sheetBlock(bf,mx)');assert.match(html,/>草稿</);assert.doesNotMatch(html,/已发 ↗|href="https:\/\/example.com\/old"|查看各形式/);
});

test('X pending load follows the current mount and recovers from errors with retry',async()=>{
  const a=deferred();const h=harness(()=>a.promise);const old=h.box(),current=h.box();current.controls['[data-xl-retry]']=[{dataset:{xlRetry:'source'}}];h.context.old=old;h.context.current=current;
  h.run("window.renderXDaily(old,'pending')");old.isConnected=false;h.run("window.renderXDaily(current,'sources')");
  a.reject(new Error('temporary'));await flush();assert.match(current.innerHTML,/暂时读不到/);assert.equal(h.calls.length,2);assert.ok(current.controls['[data-xl-retry]'][0].onclick);
});

test('duplicate publication associations are disclosed without adding a repair action',()=>{
  const h=harness();h.context.w=[{platform:'x',topic_ids:[1,2],publications:[{topic_id:1,title:'第一条'},{topic_id:2,title:'第二条'}],message:'同一 X 帖子关联两条内容'}];const html=h.run('publicationWarnings(w)');
  assert.match(html,/同一 X 帖子关联两条内容/);assert.match(html,/《第一条》、《第二条》/);assert.doesNotMatch(html,/<button|data-.*repair/);
});

test('unresolved delivery blocks new sends even when all materials are ready',()=>{
  const h=harness();
  for(const state of ['unknown','awaiting_confirm']){
    h.context.row={form:'text',label:'文字',ready:true,action:'auto',upload_url:'https://x.com/compose',job:{state},presentation:fact(state)};
    const html=h.run("ppFormRow({topic_id:1},row,{key:'x',label:'X',admin:'https://x.com/home'})");
    assert.match(html,/去后台核对/);assert.match(html,/data-pp-sent=/);assert.doesNotMatch(html,/data-pp-send=|再发一次|发到 X/);
  }
  h.context.cell={form:'video',state:'unknown'};
  const other=h.run("ppCell(cell,{key:'youtube',admin:'https://studio.youtube.com/'},{topic_id:1,cells:{youtube:[cell]}})");
  assert.doesNotMatch(other,/data-pp-send3=/);assert.match(other,/已核实发布/);
});

test('existing draft keeps verification and registration after preparation becomes invalid',()=>{
  const h=harness();h.context.row={form:'text',label:'文字',ready:false,why:'标题和文案还没定稿',action:'draft',job:{state:'done',draft:true,draft_link:'https://example.com/draft'},presentation:fact('draft')};
  const html=h.run("ppFormRow({topic_id:1},row,{key:'wechat_mp',label:'公众号'})");
  assert.match(html,/去后台查看草稿/);assert.match(html,/data-pp-sent="1\|text\|wechat_mp"/);assert.doesNotMatch(html,/data-pp-send=/);
  h.run("PP.linkFor='1|text|wechat_mp'");assert.match(h.run("ppFormRow({topic_id:1},row,{key:'wechat_mp',label:'公众号'})"),/data-pp-sent-go="1\|text\|wechat_mp"/);
});

test('topic deep-link scrolls to its pending item; X page has the same sections as the other platforms (10/19)',async()=>{
  const h=harness(async()=>platform('x'));h.context.window.renderXDaily=()=>{};let scrolls=0;
  h.nodes['#ppItem-17']={scrollIntoView(){scrolls++;}};
  h.run('S.platformTopic=17');await h.context.window.VIEWS.platform.render();
  const html=h.nodes['#platformBody'].innerHTML;
  assert.equal(scrolls,1);assert.equal(h.run('S.platformTopic'),17);assert.match(html,/pp-pend/);assert.match(html,/pp-data/);assert.doesNotMatch(html,/data-xd-counts-slot|ppXDaily/);assert.match(html,/pp-def/);assert.doesNotMatch(html,/x-more/);
});

test('matrix loader reads every sheet row beyond the old thirty-item limit in bounded pages',async()=>{
  const rows=Array.from({length:550},(_,i)=>({video_id:String(i+1),cells:{x:{state:'sent',publication_state:'published'}}}));
  const h=harness(async(url)=>{const q=new URL(url,'https://example.com').searchParams;const offset=Number(q.get('offset')),limit=Number(q.get('limit'));return {rows:rows.slice(offset,offset+limit),publication_warnings:[],metrics_complete:true};});
  h.context.sheet={videos:rows};const matrix=await h.run('loadPublicationMatrix(sheet)');
  assert.equal(h.calls.length,2);assert.match(h.calls[0].url,/limit=500&offset=0/);assert.match(h.calls[1].url,/limit=50&offset=500/);
  assert.equal(matrix.rows.length,550);assert.equal(matrix.rows[549].video_id,'550');assert.equal(matrix.read_warning,'');
});

const localXQueue = () => ({today:{day:'2026-10-08',sent:0,queued:0,pending:1,posts:[{id:'local-1',text:'本地待勾选正文',state:'pending',long:true,manual_publish:true,prep:'ready'}],long_planned_at:'2026-10-08'},tomorrow:{day:'2026-10-09',posts:[]},ahead:[],window:'09:00–22:00',plan_at:'21:00',per_day:10,per_day_long:3});
const xSources = (posts=[]) => ({today:999,sources:[],skipped:[],used:[],posts});

test('X pending first mount reads only the local queue and shows today\'s items as a list plus the open one',async()=>{
  const h=harness(async(url)=>{assert.equal(url,'/api/xline/daily');return localXQueue();});
  const box=h.box();h.context.xbox=box;h.run("window.renderXDaily(xbox,'pending')");await flush();
  assert.deepEqual(h.calls.map(c=>c.url),['/api/xline/daily']);assert.match(box.innerHTML,/本地待勾选正文/);
  assert.match(box.innerHTML,/data-xd-draft="local-1"/);assert.match(box.innerHTML,/data-xv="local-1"/);  // 10/12 晚：价值线卡片，存草稿 / 拆成短帖 / 不发
  assert.doesNotMatch(box.innerHTML,/正在读取X 素材|xl-posted">/);
});

test('slow then rejected public sources never hold up or replace the newly mounted local X queue',async()=>{
  const source=deferred();const h=harness((url)=>url==='/api/xline/daily'?Promise.resolve(localXQueue()):source.promise);
  const old=h.box(),current=h.box();h.context.old=old;h.context.current=current;
  h.run("window.renderXDaily(old,'sources')");assert.equal(h.calls[0].url,'/api/xline');
  old.isConnected=false;h.run("window.renderXDaily(current,'pending')");await flush();
  assert.match(current.innerHTML,/本地待勾选正文/);assert.doesNotMatch(current.innerHTML,/正在读取X 待发队列/);
  const html=current.innerHTML;source.reject(new Error('公开素材失败'));await flush();
  assert.equal(current.innerHTML,html);assert.equal(h.run("XL.errors.source"),'公开素材失败');assert.equal(h.run('XL.daily.today.sent'),0);
});

test('X source and daily failures retry independently without erasing either cache',async()=>{
  let sourceCalls=0;const h=harness(async(url)=>{if(url==='/api/xline/daily')return localXQueue();if(++sourceCalls===1)throw new Error('素材失败');return xSources();});
  const box=h.box();box.controls['[data-xl-retry]']=[{dataset:{xlRetry:'source'}}];h.context.xbox=box;
  h.run("window.renderXDaily(xbox,'pending')");await flush();h.run("window.renderXDaily(xbox,'sources')");await flush();
  assert.match(box.innerHTML,/素材失败/);box.controls['[data-xl-retry]'][0].onclick();await flush();
  assert.equal(sourceCalls,2);assert.doesNotMatch(box.innerHTML,/素材失败/);assert.equal(h.run('XL.daily.today.posts[0].id'),'local-1');
  h.run("window.renderXDaily(xbox,'pending')");assert.match(box.innerHTML,/本地待勾选正文/);assert.equal(h.calls.filter(c=>c.url==='/api/xline/daily').length,1);
});


test('X daily failure retries without re-reading an already available public source cache',async()=>{
  let dailyCalls=0;const h=harness(async(url)=>{if(url==='/api/xline')return xSources();if(++dailyCalls===1)throw new Error('本地队列失败');return localXQueue();});
  const box=h.box();box.controls['[data-xl-retry]']=[{dataset:{xlRetry:'daily'}}];h.context.xbox=box;
  h.run("window.renderXDaily(xbox,'sources')");await flush();h.run("window.renderXDaily(xbox,'pending')");await flush();
  assert.match(box.innerHTML,/本地队列失败/);box.controls['[data-xl-retry]'][0].onclick();await flush();
  assert.match(box.innerHTML,/本地待勾选正文/);assert.equal(h.calls.filter(c=>c.url==='/api/xline').length,1);assert.equal(dailyCalls,2);
});

test('X queue polling refreshes daily facts without starting public source collection',async()=>{
  const h=harness(async(url)=>{assert.equal(url,'/api/xline/daily');const q=localXQueue();q.today.queued=1;return q;});
  const box=h.box();h.context.xbox=box;h.run("window.renderXDaily(xbox,'pending')");await flush();
  assert.equal(h.timers.length,1);await h.timers[0]();assert.equal(h.calls.length,2);
  assert.ok(h.calls.every(call=>call.url==='/api/xline/daily'));assert.match(box.innerHTML,/本地待勾选正文/);
});


test('other-platform published cells show one status, timestamp and receipt while retaining form labels',()=>{
  const h=harness();const timestamp='2026-10-08T12:30:00+08:00',url='https://www.youtube.com/watch?v=example123';
  h.context.cell={state:'sent',form:'video',label:'视频',at:timestamp,url,presentation:fact('published',{published_at:timestamp,url})};
  h.context.timestamp=timestamp;
  const html=h.run("ppCell(cell,{key:'youtube'},{topic_id:1,cells:{youtube:[cell,{form:'text'}]}})");
  assert.equal((html.match(/已发布/g)||[]).length,1);assert.doesNotMatch(html,/✓ 发了/);
  const displayedTime=h.run('ppWhen(timestamp)');assert.equal(html.split(displayedTime).length-1,1);
  assert.equal((html.match(/href=/g)||[]).length,1);assert.match(html,/回执 ↗/);assert.match(html,/<span>视频<\/span>/);
});

test('other-platform draft verification and registration survive published-display deduplication',()=>{
  const h=harness();h.context.cell={state:'draft',form:'text',label:'文字',draft_link:'https://mp.weixin.qq.com/',presentation:fact('draft')};
  const html=h.run("ppCell(cell,{key:'wechat_mp'},{topic_id:1,cells:{wechat_mp:[cell]}})");
  assert.match(html,/去群发/);assert.match(html,/data-pp-sent3="1\|text\|wechat_mp"/);assert.match(html,/<button[^>]*>登记已群发<\/button>/);assert.doesNotMatch(html,/>已经群发了</);
  h.context.cell={state:'sent',form:'video',url:'https://example.com/post'};
  assert.match(h.run("ppCell(cell,{key:'youtube'},{topic_id:1,cells:{youtube:[cell]}})"),/✓ 发了/);
});


test('simultaneous X queue and source mounts keep independent data, errors and polling',async()=>{
  const source=deferred();let dailyCalls=0;
  const h=harness((url)=>{if(url==='/api/xline')return source.promise;dailyCalls++;const data=localXQueue();data.today.queued=1;return Promise.resolve(data);});
  const queue=h.box(),materials=h.box();materials.controls['[data-xl-retry]']=[{dataset:{xlRetry:'source'}}];
  h.context.queue=queue;h.context.materials=materials;
  h.run("window.renderXDaily(queue,'pending');window.renderXDaily(materials,'sources')");await flush();
  assert.match(queue.innerHTML,/本地待勾选正文/);assert.match(materials.innerHTML,/正在读取X 素材/);
  assert.equal(dailyCalls,1);await h.timers[0]();assert.equal(dailyCalls,2);assert.match(queue.innerHTML,/data-xd-draft="local-1"/);
  source.reject(new Error('素材离线'));await flush();assert.match(materials.innerHTML,/素材离线/);assert.doesNotMatch(queue.innerHTML,/素材离线/);
  assert.equal(h.run('XL.mounts.pending===queue && XL.mounts.sources===materials'),true);
});

test('summary matrix and combined sheet suppress association warnings without changing publication facts',()=>{
  const h=harness();h.context.warning={platform:'x',post_id:'123',topic_ids:[1,2],message:'重复关联不应出现在汇总'};
  h.context.mx={platforms:[{key:'x',label:'X'}],rows:[{video_id:'1',title:'标题',published_at:'2026-10-08',total:0,multiple:null,cells:{x:{state:'views',views:0,publication_state:'published'}}}],publication_warnings:[h.context.warning]};
  h.context.bf={platforms:[{key:'x',label:'X'}],videos:[{video_id:'1',topic_id:1,title:'标题',published_at:'2026-10-08',likes:0,multiple:null,video:'master',done:{x:'record'},missing:[]}]};
  for(const call of ['matrixBlock(mx)','sheetBlock(bf,mx)']){
    const html=h.run(call);assert.doesNotMatch(html,/发布关联需要核对|重复关联不应出现在汇总/);assert.match(html,/class="num mx-0">0</);
  }
  assert.equal(h.run('mx.publication_warnings.length'),1);
});


test('one release action hands off all destinations without opening or sending to any platform',async()=>{
  const pending=deferred();const h=harness(()=>pending.promise);h.context.view={copy_locked:true,lanes:[{key:'douyin',label:'抖音',form:'video',form_label:'视频',ready:true,presentation:fact('ready')},{key:'x',label:'X',form:'video',form_label:'视频',ready:true,presentation:fact('ready')}]};
  const el=h.box();const button={};el.controls['[data-release]']=[button];h.context.el=el;
  h.run('wireRelease(9,el,view)');const first=button.onclick();await button.onclick();assert.equal(h.calls.length,1);assert.equal(h.calls[0].url,'/api/topics/9/pack/handoff');assert.equal(h.calls[0].options.method,'POST');
  pending.resolve({...h.context.view,lanes:h.context.view.lanes.map(l=>({...l,handed:true})),handoff:{platforms:['douyin','x']}});await first;
  assert.match(el.innerHTML,/发到 2 个平台/);assert.doesNotMatch(el.innerHTML,/data-release=/);assert.doesNotMatch(el.innerHTML,/goPlatform|data-pp-send/);
});
test('failed handoff remains retryable without losing the current form states',async()=>{
  let fail=true;const h=harness(async()=>{if(fail)throw new Error('offline');return {...h.context.view,lanes:h.context.view.lanes.map(l=>({...l,handed:true})),handoff:{platforms:['x']}};});h.context.view={copy_locked:true,lanes:[{key:'x',label:'X',form_label:'视频',ready:true,presentation:fact('ready')}]};
  const el=h.box(),button={};el.controls['[data-release]']=[button];h.context.el=el;h.run('wireRelease(1,el,view)');await button.onclick();assert.match(el.innerHTML,/offline/);assert.match(el.innerHTML,/可以重试/);
  fail=false;await button.onclick();assert.match(el.innerHTML,/发到 1 个平台/);assert.equal(h.calls.filter(c=>c.url==='/api/topics/1/pack/handoff').length,2);
});

test('a lane that is not ready does not hold back the ones that are (10/13)',()=>{
  const h=harness(async()=>({}));h.run('PK.data={topic:{id:1}}');
  h.context.view={copy_locked:true,lanes:[
    {key:'douyin',label:'抖音',form:'video',form_label:'视频',ready:true,presentation:fact('ready')},
    {key:'x',label:'X',form:'text',form_label:'文章',ready:false,why:'文章还没写好',presentation:fact('not_ready')},
  ]};
  const html=h.run('ctaInner(view)');
  assert.doesNotMatch(html,/data-release="1"[^>]*disabled/);assert.match(html,/>开始发</);assert.match(html,/先备好 抖音 的上传包/);assert.match(html,/文章还没写好/);
  // 抖音放过了，X 还没好：没有「开始发」，X 那一行说差什么
  h.context.view={copy_locked:true,lanes:[{...h.context.view.lanes[0],handed:true},h.context.view.lanes[1]]};
  const after=h.run('ctaInner(view)');assert.doesNotMatch(after,/data-release=/);assert.match(after,/发到 2 个平台/);assert.match(after,/文章还没写好/);
  // X 的文章好了：「开始发」重新出来，只备 X
  h.context.view={copy_locked:true,lanes:[{...h.context.view.lanes[0]},{...h.context.view.lanes[1],ready:true,why:''}]};
  const later=h.run('ctaInner(view)');assert.doesNotMatch(later,/disabled/);assert.match(later,/>开始发</);assert.match(later,/先备好 X 的上传包/);
});

test('X 长文 title edits in place and saves back as the first "# " line (10/10)', async () => {
  const h = harness(async () => ({}));
  const post = { id: 'L1', long: true, format: 'article', state: 'pending', prep: 'ready', text: '# 旧标题\n\n第一段\n' };
  h.context.post = post; h.run("XL.daily = { today: { day: '2026-10-10', posts: [post] }, tomorrow: { day: '2026-10-11', posts: [] }, ahead: [] }");
  const html = h.run("xdReader(XL.daily.today.posts[0], '2026-10-10')");
  assert.match(html, /<h3 class="xd-blk"[^>]*data-xd-blk="0" data-xd-post="L1">旧标题<\/h3>/);
  const sent = h.run("xdReader({...XL.daily.today.posts[0], state:'sent'}, '2026-10-10')");
  assert.match(sent, /<h3>旧标题<\/h3>/);

  const textarea = { value: '', style: {}, scrollHeight: 10, focus() {} };
  const saveBtn = { onclick: null }, editor = { className: '', innerHTML: '', remove() {}, controls: { textarea: [textarea], '[data-act="save"]': [saveBtn], '[data-act="cancel"]': [{}] } };
  h.context.document.createElement = () => editor;
  const title = { dataset: { xdPost: 'L1', xdBlk: '0' }, replaceWith() {} };
  const box = { querySelector: () => null, controls: { '[data-xd-blk]:not([data-xd-blk-del])': [title] } };
  h.context.box = box; h.run('xdBindBlocks(box, () => {})');
  title.onclick();
  assert.match(editor.innerHTML, /<textarea>旧标题<\/textarea>/);
  textarea.value = '# 新标题\n换行';
  await saveBtn.onclick({ target: {} }); await flush();
  const patch = h.calls.find((c) => c.options?.method === 'PATCH');
  assert.equal(patch.options.body.text, '# 新标题 换行\n\n第一段\n');
});

test('X QA block lists each change with a revert, and says so when nothing changed or it failed (10/10)', () => {
  const h = harness(async () => ({}));
  const base = { id: 'P1', long: true, format: 'post', state: 'pending', prep: 'ready', text: '# 题\n\n想清楚变现路径。' };
  h.context.x = { ...base, qa: 'ready', qa_before: '# 题\n\n想清楚变线路径。', qa_changes: [{ kind: '错字', before: '变线路径', after: '变现路径', why: '同音字' }] };
  const html = h.run("xdReader(x, '2026-10-10')");
  assert.match(html, /改了 1 处/); assert.match(html, /<del>变线路径<\/del> → <ins>变现路径<\/ins>/); assert.match(html, /data-xd-qa-revert="P1"/);
  h.context.x = { ...base, qa: 'ready', qa_changes: [] };
  assert.match(h.run("xdReader(x, '2026-10-10')"), /没有要改的/);
  h.context.x = { ...base, qa: 'failed', qa_error: 'QA 没按格式输出' };
  assert.match(h.run("xdReader(x, '2026-10-10')"), /QA 没做成，原文照旧：QA 没按格式输出/);
  h.context.x = { ...base, state: 'sent', qa: 'ready', qa_changes: [{ kind: '错字', before: 'a', after: 'b' }] };
  assert.doesNotMatch(h.run("xdReader(x, '2026-10-10')"), /xd-qa/);
});

test('X QA completeness warning and note remain visible without edits and on approved posts', () => {
  const h = harness(async () => ({}));
  const base = { id: 'P1', long: true, state: 'approved', prep: 'ready', qa: 'ready', qa_complete: false,
    qa_issues: ['没有开头', '<script>'], qa_note: 'QA 觉得还不完整，你看一眼再决定' };
  h.context.x = base;
  const html = h.run('xdQA(x, true)');
  assert.match(html, /完整度：不过/);
  assert.match(html, /<li>没有开头<\/li>/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /class="xd-qa-note">QA 觉得还不完整，你看一眼再决定/);
  assert.match(html, /勾之前看一眼/);
  h.context.x = { ...base, qa_changes: [{ kind: '删', before: '放这个视频', after: '' }, { kind: '编号', before: '', after: '去掉编号' }] };
  const edited = h.run('xdQA(x, true)');
  assert.match(edited, /<del>放这个视频<\/del>（删掉）/);
  assert.match(edited, /<i>编号<\/i>去掉编号/);
  assert.ok(edited.indexOf('完整度：不过') < edited.indexOf('<ol>'));
});

test('X value warning names failures, passes show checks, held card explains override', () => {
  const h = harness();
  h.context.x = {id:'p', long:true, prep:'ready', state:'pending', text:'标题\n\n正文', qa:'ready', qa_value_ok:false,
    qa_value:{痛点:{ok:true,why:''},解法:{ok:false,why:'没有步骤 <补>'},收藏:{ok:false,why:'无法复用'}}, qa_value_held:true};
  const html=h.run('xdReader(x, "2026-10-11")');
  assert.match(html, /价值不够，没发；你再勾一次就照发/);
  assert.match(html, /价值：不过/); assert.match(html, /解法：没有步骤 &lt;补&gt;/);
  assert.match(html, /收藏：无法复用/);
  h.context.x.qa_value_ok=true;
  assert.match(h.run('xdQA(x, true)'), /价值：痛点 ✓ 解法 ✓ 收藏 ✓/);
});

test('auto-send shows only the next card per lane; sent and QA-dropped fold away (10/11 作者)', () => {
  const h=harness();
  h.context.dd={today:{day:'2026-10-11',next_at:'14:20',posts:[
    {id:'s1',text:'发了的短帖',state:'sent',sent_at:'2026-10-11T10:00:00+08:00',url:'https://x.com/i/status/1'},
    {id:'s2',text:'下一条短帖',state:'approved'},
    {id:'s3',text:'后面的短帖',state:'approved'},
    {id:'s4',text:'没过的短帖',state:'rejected',auto:true,auto_reason:'没过 QA：错字太多'},
    {id:'q1',text:'引用正文',state:'pending',qa:'running',long:true,quote_url:'https://x.com/a/status/9',source_kind:'热点 · AB',source_title:'原帖标题'},
    {id:'l1',text:'# 长文',state:'pending',long:true,prep:'ready'}]}};
  const html=h.run('xaAuto(dd)');
  assert.match(html,/下一条短帖/); assert.doesNotMatch(html,/后面的短帖/);
  assert.match(html,/约 14:20 发/); assert.match(html,/xa-card more/);
  assert.match(html,/<summary>今天已发 1<\/summary>/); assert.match(html,/<summary>没发 1<\/summary>/); assert.match(html,/错字太多/);
  assert.match(html,/引用正文/); assert.match(html,/QA 在看/); assert.match(html,/引用 AB/);
  assert.doesNotMatch(html,/# 长文/); assert.doesNotMatch(html,/style=/);
});

test('reply lane: API mode shows send time; manual mode opens X prefilled and records the hand-off', async () => {
  const h=harness(async()=>({mode:'manual',queue:0,next:null,done_today:[]}));
  h.run("XR.loaded=true;XR.data={mode:'api',queue:3,next_at:'15:04',next:{id:'7',author:'作者',text:'原帖',url:'https://x.com/a/status/7',draft:'判断 & 中文'},done_today:[{author:'甲',draft:'回过的',state:'sent',reply_url:'https://x.com/i/status/8'}]}");
  let html=h.run('xaReplies()');
  assert.match(html,/约 15:04 发/); assert.doesNotMatch(html,/去 X 回复/); assert.match(html,/<summary>今天已回 1<\/summary>/);
  h.run("XR.data.mode='manual';XR.data.api_blocked={reason:'403'}");
  html=h.run('xaReplies()');
  assert.match(html,/X 不让工作台直接回复/); assert.match(html,/data-xa-retry-api/);
  const href=html.match(/data-xa-hand="7" href="([^"]+)"/)[1].replaceAll('&amp;','&');
  const url=new URL(href);
  assert.equal(url.searchParams.get('in_reply_to'),'7'); assert.equal(url.searchParams.get('text'),'判断 & 中文');
  const a={dataset:{xaHand:'7'}}, box=h.box(); box.controls={'[data-xa-hand]':[a]}; h.context.box=box;
  h.run('xaBind(box)'); a.onclick(); await flush();
  assert.equal(h.calls[0].url,'/api/xline/replies/7/handed');
});

test('X pending DOM orders today, auto-send, then the long queue; no source list', async () => {
  const h=harness(async () => localXQueue());
  const box=h.box(); h.context.box=box;
  h.run("window.renderXDaily(box,'pending')"); await flush();
  const positions=['data-xl-live','aria-label="价值线"','aria-label="流量线"'].map(s=>box.innerHTML.indexOf(s));
  assert.ok(positions.every((p,i)=>p>=0 && (!i || p>positions[i-1])), positions.join());
  assert.doesNotMatch(box.innerHTML,/xl-src|从这里挑/);
  assert.doesNotMatch(box.innerHTML,/style=/);
  assert.equal(h.liveCalls.length,1);
  await h.liveTimers.at(-1)(); assert.equal(h.liveCalls.length,2);
  h.run("S.platformKey='douyin'"); await h.liveTimers.at(-1)(); assert.equal(h.liveCalls.length,2);
});

test('today card: hourly lines start at midnight, need two real readings, and KPI uses native progress', () => {
  const h=harness();
  const today=source('today.js');
  vm.runInContext(today.slice(today.indexOf('function lineChart('),today.indexOf('/* 钱这一层（10/5）')), h.context);
  h.context.md=x=>x;
  h.run("XL_LIVE.data={followers_midnight:90,progress:{expected:95,gap:10,target:{end_day:'2026-10-31',end:10000}},followers_now:105,kpi:[{key:'posts',label:'发帖',done:30,target:100,ok:false},{key:'impressions',label:'曝光',done:250000,target:200000,ok:true},{key:'replies',label:'回复',done:12,target:null,ok:null}],followers_hourly:[{at:'2026-10-11T08:00:00+08:00',followers:100}]}");
  let html=h.run('xlLive()');
  assert.doesNotMatch(html,/rl-svg/);  // 只有一个读数：不画一个点
  assert.match(html,/10\/31 前到 10000/); assert.match(html,/超前 10/); assert.match(html,/xt-goal/);
  assert.match(html,/max="100" value="30"/); assert.match(html,/max="200000" value="200000"/); assert.match(html,/xt-stat ok/); assert.match(html,/另回复 12/);
  h.run("XL_LIVE.data.followers_hourly.push({at:'2026-10-11T09:00:00+08:00',followers:105})");
  html=h.run('xlLive()');
  assert.match(html,/00:00<\/text>/); assert.match(html,/09:00<\/text>/); assert.match(html,/aria-label="粉丝按小时"/);
  assert.doesNotMatch(html,/NaN|style=/);
});

test('delayed live response and refresh timer follow the latest X page mount', async () => {
  const h=harness(), waiting=deferred();
  const old=h.box(), current=h.box(), live={innerHTML:''};
  current.controls={'[data-xl-live]':[live]};
  h.context.old=old; h.context.current=current;
  let reads=0;
  h.context.api=async () => { reads++; return waiting.promise; };
  h.run('XL.mounts.pending=old'); const pending=h.run('xlLiveLoad(old)');
  old.isConnected=false; h.run('XL.mounts.pending=current'); await h.run('xlLiveLoad(current)');
  assert.equal(reads,1);
  waiting.resolve({followers_now:123,kpi:[{key:'posts',label:'发帖',done:20,target:100,ok:false}]});
  await pending;
  assert.match(live.innerHTML,/123/);
  assert.equal(h.liveTimers.length,1);
  await h.liveTimers[0](); assert.equal(reads,2);
});

test('quotes blocked by X show a one-tap 去 X 发 card; weak long posts stay hidden (10/12 作者)', async () => {
  const h=harness(async()=>({}));
  h.context.dd={quotes_mode:'manual',today:{day:'2026-10-12',posts:[
    {id:'q1',text:'引用判断',state:'ready_manual',long:true,quote_url:'https://x.com/a/status/9',intent_url:'https://x.com/intent/post?text=a&url=b',source_kind:'热点 · AB'},
    {id:'q0',text:'点过的',state:'handed',long:true,quote_url:'https://x.com/a/status/8'},
    {id:'l1',text:'# 藏起来的长文',state:'pending',long:true,prep:'ready',hidden:true},
    {id:'l2',text:'# 给他看的长文',state:'pending',long:true,prep:'ready'}]}};
  const html=h.run('xaAuto(dd)');
  assert.match(html,/data-xa-qhand="q1" href="https:\/\/x.com\/intent\/post\?text=a&amp;url=b"/);
  assert.match(html,/X 不让工作台直接发引用/); assert.match(html,/<summary>今天已发 1<\/summary>/);
  const list=h.run("xdSplit(dd.today.posts,'2026-10-12')");
  assert.doesNotMatch(list,/藏起来的长文/); assert.match(list,/给他看的长文/);
  h.run("XR.loaded=true;XR.data={mode:'manual',queue:1,next:{id:'7',author:'甲',text:'原帖',url:'u',draft:'原话改的一句',source_note:'003_原始输出/AI 工具.md'},done_today:[]}");
  assert.match(h.run('xaReplies()'),/原话来自《AI 工具》/);
});

test('hidden long posts show where each one is in the merge (10/12 作者: 我怎么能看到进度)', () => {
  const h=harness();
  h.context.dd={merging:null,today:{day:'2026-10-12',merge:{count:2,max:6,waiting:3},posts:[
    {id:'a',text:'# 甲',long:true,state:'pending',hidden:true,hidden_reason:'价值不够',merged_into:'m'},
    {id:'b',text:'# 乙',long:true,state:'pending',hidden:true,hidden_reason:'不完整',merge_tries:1},
    {id:'m',text:'# 合起来',long:true,state:'pending',hidden:true,merged_from:['a','c']},
    {id:'v',text:'# 看得到',long:true,state:'pending',prep:'ready',merged_from:['x','y']}]}};
  let html=h.run('xdMergeStrip(dd)');
  assert.match(html,/3 篇没给你看/); assert.match(html,/今天拼了 2 次（最多 6）/); assert.match(html,/3 篇等着拼/);
  assert.match(html,/拼进了《合起来》/); assert.match(html,/等新藏进来的一起再试/); assert.match(html,/QA 还是没过/);
  h.run("dd.merging='2026-10-12'"); assert.match(h.run('xdMergeStrip(dd)'),/class="spin"/);
  assert.match(h.run("xdSplit(dd.today.posts,'2026-10-12')"),/合并长帖/);
});

test('today picks: four buttons per open pick, chosen ones fold with where they are (10/12 作者)', async () => {
  const h=harness(async()=>({}));
  h.context.dd={today:{day:'2026-10-12',picks:[
    {id:'K0',title:'没选的',text:'没选的\n正文第一段',chars:900,choice:null},
    {id:'K1',title:'发文的',text:'x',choice:'article',made:['A1']},
    {id:'K2',title:'拆的',text:'x',choice:'split',split:'done',made:['K2-S0','K2-S1']}],
    posts:[{id:'A1',long:true,manual_publish:true,state:'drafted',prep:'ready',url:'https://x.com/compose/articles'},
           {id:'K2-S0',state:'sent',sent_at:'2026-10-12T10:00:00+08:00'},{id:'K2-S1',state:'approved'}]}};
  const html=h.run('xkPicks(dd)');
  assert.equal((html.match(/data-xk="K0"/g)||[]).length,4); assert.doesNotMatch(html,/data-xk="K1"/);
  assert.match(html,/1 篇等你选/); assert.match(html,/选过的 2 篇/);
  assert.match(html,/已存进 X 草稿/); assert.match(html,/拆成 2 条短帖 · 发了 1/);
  assert.doesNotMatch(html,/style=/);
});
