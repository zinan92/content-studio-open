'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/content_studio/static/consult.js'), 'utf8');
const copy = (value) => JSON.parse(JSON.stringify(value));
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const client = (name = '甲', profile = {}) => ({ name, profile: { 来源: '', 首次咨询收费: '', 画像: '', 微信名: '', 后续方案: '', 报价: '', ...profile }, consults: [], files: [] });
function element() {
  const listeners = {};
  return { innerHTML: '', textContent: '', isConnected: true, dataset: {}, controls: {}, open: false, listeners,
    style: {}, getClientRects(){return [{}];}, scrollHeight:96, classList: {add(){},remove(){}}, setAttribute(){}, addEventListener(type, fn){listeners[type]=fn;},
    showModal(){this.open=true;}, close(){this.open=false;listeners.close?.();}, focus(){this.focused=true;}, closest(){return this;},
  };
}
function harness(api = async () => ({clients:[]})) {
  const nodes = { '#clientsBody': element(), '#csFile': element(), '#csName': element(), '#csDay': element(), '#csMsg': element(), '#consultDlg': element() };
  const calls = [], timers = [], notices = [];
  const context = vm.createContext({
    window:{VIEWS:{}}, S:{view:'consults'}, console, Date, encodeURIComponent,
    document:{activeElement:null,addEventListener(){},createElement(){
      const dialog=element();dialog.controls={ '[data-client-save-status]':[element()], '[data-client-save]':[element()], '[data-client-live]':[element()], '[data-field]':[] };return dialog;
    },body:{appendChild(node){nodes['#'+node.id]=node;}}},
    $:(selector, root)=>root ? root.controls[selector]?.[0] || null : nodes[selector] || null,
    $$:(selector, root)=>root?.controls[selector] || [],
    esc:(value)=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    api:(url,options)=>{calls.push({url,options:copy(options||{})});return api(url,options);},
    toast:(text)=>notices.push(text), confirm:()=>true, setTimeout:(fn)=>{timers.push(fn);return timers.length;},clearTimeout(){},
  });
  const body=nodes['#clientsBody'];let markup='';body.replacements=0;
  Object.defineProperty(body,'innerHTML',{get(){return markup;},set(value){
    markup=value;body.replacements++;
    body.controls={};
    if(!value.includes('id="clientTable"'))return;
    body.controls['#clientTable']=[element()];body.controls['[data-client-counts]']=[element()];body.controls['[data-client-error]']=[element()];
    body.controls['[data-client-row]']=[...value.matchAll(/data-client-row="([^"]+)"/g)].map(match=>{
      const row=element();row.dataset.clientRow=match[1];
      for(const selector of ['[data-client-save-status]','[data-client-save]','[data-client-live]','[data-client-summary]','[data-client-progress]','[data-client-upload]','[data-cl-del]'])row.controls[selector]=[element()];
      row.controls['[data-field]']=Object.keys(client().profile).map(key=>{const input=element();input.dataset={client:match[1],field:key};input.tagName=key==='后续方案'?'SELECT':'TEXTAREA';input.focus=()=>{context.document.activeElement=input;};return input;});
      row.controls['[data-cs-retry], [data-field]']=row.controls['[data-field]'];
      return row;
    });
  }});
  vm.runInContext(source,context);
  const run=(code)=>vm.runInContext(code,context);
  const seed=(rows)=>{context.rows=rows;run('CS.rows=rows');};
  return {context,nodes,calls,timers,notices,run,seed,row:(name)=>body.controls['[data-client-row]']?.find(row=>row.dataset.clientRow===name)};
}

test('one compact row per client; files, retry, Finder and upload stay on the row, fields fold under 改资料 (10/11 作者)', () => {
  const h=harness();const row=client('客户带很长的名字');
  row.consults=[{slug:'failed-job',day:'2026-10-08',stage:'failed',error:'转写失败'}];
  row.files=[{day:'1008',sent:[{label:'纪要',pdf:'纪要.pdf',html:'纪要.html',pdf_url:'/pdf',html_url:'/html'}],mine:[{label:'分析',obsidian:'obsidian://open?path=analysis'}]}];
  h.seed([row]);h.run('renderClients()');const html=h.nodes['#clientsBody'].innerHTML;
  assert.doesNotMatch(html,/<table|查看详情|clientDetailDlg|data-client-open/);
  assert.match(html,/class="cl-item" data-client-row=/);
  assert.equal((html.match(/data-field=/g)||[]).length,6);
  assert.match(html,/data-client-save=/);assert.match(html,/data-client-upload/);
  const fold=html.match(/<details class="cl-edit">[\s\S]*?<\/details>/g)||[];
  assert.equal(fold.length,1);assert.match(fold[0],/改资料/);assert.match(fold[0],/data-cl-del/);assert.equal((fold[0].match(/data-field=/g)||[]).length,6);
  assert.doesNotMatch(fold[0],/href=|data-cs-retry|data-client-upload/);
  assert.doesNotMatch(html,/style=/);
  h.run('updateClientLive()');
  const live=h.row('客户带很长的名字').controls['[data-client-live]'][0].innerHTML;
  assert.match(live,/href="\/pdf"/);assert.match(live,/href="\/html"/);assert.match(live,/obsidian:\/\/open/);
  assert.match(live,/data-cl-reveal/);assert.match(live,/data-cs-retry="failed-job"/);
});

test('exact drafts survive navigation and editing another customer without implicit writes', () => {
  const h=harness();h.seed([client('甲'),client('乙')]);h.run('renderClients()');
  const input=h.row('甲').controls['[data-field]'].find(input=>input.dataset.field==='画像');
  input.value='  我的原话\n\n';h.context.input=input;
  h.run("clientInput({type:'input',target:input});S.view='today';editClient('乙','报价','三期');S.view='consults';renderClients()");
  assert.equal(h.run("clientValue(clientDraft('甲'),'画像')"),'  我的原话\n\n');
  assert.equal(h.run("clientValue(clientDraft('乙'),'画像')"),'');
  assert.equal(h.row('甲').controls['[data-field]'].find(input=>input.dataset.field==='画像').value,'  我的原话\n\n');
  assert.match(h.row('甲').controls['[data-client-save-status]'][0].textContent,/未保存/);
  assert.equal(h.calls.length,0);
});

test('explicit save sends changed fields together and failure retains exact retry payload', async () => {
  let fail=true;
  const h=harness(async (url,options)=>{if(fail)throw new Error('写入失败');return {profile:{来源:options.body.来源,报价:options.body.报价}};});
  h.seed([client()]);h.run("editClient('甲','来源','抖音');editClient('甲','报价','  两期付款  ')");
  assert.equal(await h.run("saveClientProfile('甲')"),false);
  assert.match(h.run("clientSaveStatus(clientDraft('甲'))"),/草稿已保留/);
  assert.deepEqual(copy(h.run("clientDraft('甲').values")),{来源:'抖音',报价:'  两期付款  '});
  fail=false;await h.run("saveClientProfile('甲')");
  assert.deepEqual(h.calls[0],h.calls[1]);assert.deepEqual(h.calls[1].options.body,{来源:'抖音',报价:'  两期付款  '});
  assert.equal(h.calls[1].options.method,'PUT');assert.deepEqual(copy(h.run("clientDraft('甲').values")),{});
});

test('save response preserves newer edits including a revert to the old baseline and never paints another client', async () => {
  const pending=deferred();const h=harness(()=>pending.promise);h.seed([client('甲',{来源:'原来源'}),client('乙',{来源:'乙来源'})]);
  h.run("renderClients();editClient('甲','来源','已提交来源')");const saving=h.run("saveClientProfile('甲')");
  h.run("editClient('甲','来源','原来源');editClient('乙','画像','乙未保存画像')");const other=h.row('乙');
  pending.resolve({profile:{来源:'已提交来源'}});await saving;
  assert.equal(h.run("clientValue(clientDraft('甲'),'来源')"),'原来源');
  assert.equal(h.run("clientDraft('甲').values['来源']"),'原来源');
  assert.equal(h.row('乙'),other);assert.equal(h.run("clientValue(clientDraft('乙'),'画像')"),'乙未保存画像');
});

test('job polling updates only the live region and leaves focused profile fields and drafts intact', async () => {
  const fresh=client('甲');fresh.consults=[{slug:'job',day:'2026-10-08',stage:'analyzing',running:true}];
  const h=harness(async()=>({clients:[fresh]}));h.seed([client()]);h.run("renderClients();editClient('甲','画像','一半未保存')");
  const row=h.row('甲'),body=h.nodes['#clientsBody'],before=body.replacements;
  const field=row.controls['[data-field]'].find(input=>input.dataset.field==='画像');field.value='一半未保存';h.context.document.activeElement=field;
  await h.run('loadClients()');
  assert.equal(body.replacements,before);assert.equal(h.context.document.activeElement,field);assert.equal(field.value,'一半未保存');assert.equal(h.run("clientValue(clientDraft('甲'),'画像')"),'一半未保存');
  assert.match(row.controls['[data-client-live]'][0].innerHTML,/分析中/);assert.equal(h.timers.length,1);
});

test('a pre-save poll cannot restore stale profile data after a successful save', async () => {
  const poll=deferred();const h=harness((url,options)=>options?.method==='PUT'?Promise.resolve({profile:{来源:'新来源'}}):poll.promise);
  h.seed([client('甲',{来源:'旧来源'})]);h.run("clientDraft('甲')");const loading=h.run('loadClients()');
  h.run("editClient('甲','来源','新来源')");await h.run("saveClientProfile('甲')");
  poll.resolve({clients:[client('甲',{来源:'旧来源'})]});await loading;
  assert.equal(h.run("clientDraft('甲').base['来源']"),'新来源');assert.equal(h.run("CS.rows[0].profile['来源']"),'新来源');
});

test('save is single-flight but does not prevent input for the next revision', async () => {
  const pending=deferred();const h=harness(()=>pending.promise);h.seed([client()]);
  h.run("editClient('甲','微信名','提交版')");const saving=h.run("saveClientProfile('甲')");
  assert.equal(await h.run("saveClientProfile('甲')"),false);h.run("editClient('甲','微信名','下一版')");
  pending.resolve({profile:{微信名:'提交版'}});await saving;
  assert.equal(h.calls.length,1);assert.equal(h.run("clientDraft('甲').values['微信名']"),'下一版');
});

test('table upload reuses the upload form with the selected client name', async () => {
  const h=harness();const button=element();button.dataset={clientUpload:'客户乙'};h.context.button=button;
  await h.run('clientAction({target:button})');
  assert.equal(h.nodes['#csName'].value,'客户乙');assert.equal(h.nodes['#consultDlg'].open,true);assert.equal(h.calls.length,0);
});


test('refresh after a job mutation waits for any older poll then reads new state', async () => {
  const old=deferred();let reads=0;
  const fresh=client('甲');fresh.consults=[{slug:'retry-job',stage:'analyzing',running:true,day:'2026-10-08'}];
  const h=harness(()=>++reads===1?old.promise:Promise.resolve({clients:[fresh]}));h.seed([client()]);
  const polling=h.run('loadClients()');const refreshing=h.run('loadClients(true)');
  old.resolve({clients:[client()]});await polling;await refreshing;
  assert.equal(reads,2);assert.equal(h.run('CS.rows[0].consults[0].stage'),'analyzing');
});

test('deletion locks only that client against save/upload/retry and failure restores controls and drafts', async () => {
  const deletion=deferred();
  const h=harness(async (url,options)=>{
    if(options?.method==='DELETE')return deletion.promise;
    if(options?.method==='PUT')return {profile:options.body};
    return {clients:[]};
  });
  const a=client('甲');a.consults=[{slug:'甲失败',stage:'failed',day:'2026-10-08'}];
  h.seed([a,client('乙')]);h.run("renderClients();editClient('甲','画像','保留草稿')");
  const dialog=h.row('甲'),remove=element(),upload=element(),retry=element(),field=element();
  remove.dataset={clDel:'甲'};upload.dataset={clientUpload:'甲'};retry.dataset={csRetry:'甲失败',clientOwner:'甲'};
  dialog.controls['[data-cl-del]']=[remove];dialog.controls['[data-client-upload]']=[upload];dialog.controls['[data-cs-retry], [data-field]']=[retry,field];
  h.context.remove=remove;h.context.upload=upload;h.context.retry=retry;
  const pending=h.run('clientAction({target:remove})');
  assert.equal(h.run("clientDraft('甲').deleting"),true);
  assert.equal(dialog.controls['[data-client-save]'][0].disabled,true);
  assert.equal(upload.disabled,true);assert.equal(retry.disabled,true);assert.equal(field.disabled,true);
  assert.equal(await h.run("saveClientProfile('甲')"),false);
  await h.run('clientAction({target:upload})');await h.run('clientAction({target:retry})');
  assert.equal(h.nodes['#consultDlg'].open,false);assert.equal(h.calls.length,1);
  h.run("editClient('乙','来源','不受影响')");await h.run("saveClientProfile('乙')");
  assert.equal(h.calls[1].url,'/api/clients/%E4%B9%99');
  deletion.reject(new Error('文件被占用'));await pending;
  assert.equal(h.run("clientDraft('甲').deleting"),false);
  assert.equal(h.run("clientDraft('甲').values['画像']"),'保留草稿');
  assert.match(dialog.controls['[data-client-save-status]'][0].textContent,/删除失败：文件被占用/);
  assert.equal(dialog.controls['[data-client-save]'][0].disabled,false);
  assert.equal(upload.disabled,false);assert.equal(retry.disabled,false);assert.equal(remove.disabled,false);
});

test('a poll started before successful deletion cannot bring the customer row back', async () => {
  const old=deferred();let reads=0;
  const h=harness((url,options)=>options?.method==='DELETE'?Promise.resolve({}):++reads===1?old.promise:Promise.resolve({clients:[]}));
  h.seed([client('甲')]);h.run('renderClients()');
  const polling=h.run('loadClients()');
  const remove=element();remove.dataset={clDel:'甲'};h.context.remove=remove;
  const deleting=h.run('clientAction({target:remove})');
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.run('CS.rows.length'),0);
  old.resolve({clients:[client('甲')]});await polling;await deleting;
  assert.equal(h.run('CS.rows.length'),0);assert.equal(h.run("CS.drafts['甲']"),undefined);
  assert.doesNotMatch(h.nodes['#clientsBody'].innerHTML,/data-client-row/);
});

test('long editable fields grow rather than truncate and select changes remain explicit drafts', () => {
  const h=harness();h.seed([client('甲')]);h.run('renderClients()');
  const row=h.row('甲'),input=row.controls['[data-field]'].find(input=>input.dataset.field==='画像');
  input.value='很长的原话\n'.repeat(40);input.scrollHeight=960;h.context.input=input;
  h.run("clientInput({type:'input',target:input})");
  assert.equal(input.style.height,'962px');assert.equal(h.run("clientDraft('甲').values['画像']"),input.value);
  const select=row.controls['[data-field]'].find(input=>input.dataset.field==='后续方案');select.value='要出方案';h.context.select=select;
  h.run("clientInput({type:'change',target:select})");
  assert.equal(h.run("clientDraft('甲').values['后续方案']"),'要出方案');assert.equal(h.calls.length,0);
});
