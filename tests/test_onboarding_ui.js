'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const app=fs.readFileSync(path.join(__dirname,'../src/content_studio/static/app.js'),'utf8');
const source=app.slice(app.indexOf('function setupSteps(st)'),app.indexOf('/* 品牌：'));
const fresh=()=>({setup:{present:false},cookies:{ok:false,message:'等待导入'},vault:{ok:false},settings:{},brand:{}});
const returning=()=>({setup:{present:true},self_account:{nickname:'我的账号'},cookies:{ok:false,message:'登录信息待更新'},vault:{ok:true,path:'/notes'},settings:{obsidian_vault:'/notes'},brand:{name:'我的工作台'}});
function harness(initial={}, api=async()=>({})) {
  const stored=new Map(Object.entries(initial)),calls=[],notices=[];
  const summary={},toggle={},panel={open:false,controls:{'.su-summary':[summary],'[data-su-toggle]':[toggle],'input:not([type="file"])':[]}},root={controls:{'#setupCard':[panel]}};
  const context=vm.createContext({
    esc:(value)=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    localStorage:{getItem:key=>stored.get(key)??null,setItem:(key,value)=>stored.set(key,value)},
    $:(selector,element)=>element?.controls[selector]?.[0]||null,
    $$:(selector,element)=>element?.controls[selector]||[],
    api:(url,options)=>{calls.push({url,options:JSON.parse(JSON.stringify(options))});return api(url,options);},
    toast:text=>notices.push(text),refreshAll:async()=>{},root,
  });
  vm.runInContext(source,context);
  const run=(code)=>vm.runInContext(code,context);
  const html=(state)=>{context.state=state;const output=run('setupCard(state)');panel.open=/<details[^>]* open>/.test(output);return output;};
  const fields=(group,values)=>{
    const inputs=Object.entries(values).map(([id,value])=>({id,value,tagName:'INPUT'}));
    inputs.forEach(input=>{root.controls['#'+input.id]=[input];panel.controls['input:not([type="file"])'].push(input);});
    const button={tagName:'BUTTON'},section={controls:{'input, button':[...inputs,button]}};
    root.controls[`[data-setup-group="${group}"]`]=[section];
    if(group==='profile')root.controls['#suProfile']=[{}];
    if(group==='vault')root.controls['#suVaultGo']=[button];
    root.controls[group==='profile'?'#suProfileErr':'#suVaultErr']=[{}];
    return inputs;
  };
  return {run,html,fields,context,root,panel,summary,toggle,stored,calls,notices};
}

test('new installation expands real missing steps and keeps the existing setup form contracts',()=>{
  const h=harness(),html=h.html(fresh());
  assert.match(html,/<details[^>]* open>/);assert.match(html,/还差 3 步/);
  for(const id of ['suProfile','suBrand','suName','suDouyin','suEditor','suBoss','suCookieFile','suCookieGo','suVault','suVaultGo'])assert.match(html,new RegExp(`id="${id}"`));
  assert.equal(h.run('setupNeeded(state)'),true);
});

test('returning installation with only missing cookies stays compact and completed forms are omitted',()=>{
  const h=harness(),state=returning(),html=h.html(state);
  assert.doesNotMatch(html,/<details[^>]* open>/);assert.match(html,/还差 1 步/);assert.match(html,/抖音登录/);
  assert.doesNotMatch(html,/id="suProfile"|id="suVault"/);assert.match(html,/id="suCookieFile"/);
  assert.equal(h.run('setupNeeded(state)'),true);
  state.cookies.ok=true;assert.equal(h.html(state),'');assert.equal(h.run('setupNeeded(state)'),false);
});

test('explicit expansion preference persists without changing setup readiness',()=>{
  const h=harness();h.html(returning());h.run('bindSetup(root)');
  h.summary.onclick({preventDefault(){}});
  assert.equal(h.panel.open,true);assert.equal(h.stored.get('cs-setup-expanded'),'open');
  assert.equal(h.run('setupNeeded(state)'),true);assert.equal(h.context.state.cookies.ok,false);
  const reopened=harness(Object.fromEntries(h.stored));assert.match(reopened.html(returning()),/<details[^>]* open>/);
  h.summary.onclick({preventDefault(){}});assert.equal(h.stored.get('cs-setup-expanded'),'closed');
  const collapsed=harness(Object.fromEntries(h.stored));assert.doesNotMatch(collapsed.html(fresh()),/<details[^>]* open>/);
});

test('identity and vault input survives setup redraw but only the display preference reaches storage',()=>{
  const h=harness();h.html(fresh());
  const inputs=h.fields('profile',{suBrand:'  改到一半  ',suName:'名字',suDouyin:'https://www.douyin.com/user/example',suEditor:'编辑',suBoss:'同事'});
  const [vault]=h.fields('vault',{suVault:'~/还没选完'});h.run('bindSetup(root)');
  for(const input of [...inputs,vault])input.oninput();
  const html=h.html(fresh());assert.match(html,/value="  改到一半  "/);assert.match(html,/value="~\/还没选完"/);
  assert.equal(h.stored.size,0);assert.equal(h.calls.length,0);
});

test('failed submission reopens setup and preserves entered values and failure across redraws',async()=>{
  let reject;const h=harness({},()=>new Promise((resolve,no)=>{reject=no;}));h.html(fresh());
  const inputs=h.fields('profile',{suBrand:'草稿名',suName:'作者',suDouyin:'主页输入',suEditor:'编辑',suBoss:'同事'});h.run('bindSetup(root)');inputs.forEach(input=>input.oninput());
  const saving=h.root.controls['#suProfile'][0].onsubmit({preventDefault(){}});
  assert.equal(inputs[0].disabled,true);
  h.summary.onclick({preventDefault(){}});assert.equal(h.panel.open,false);
  reject(new Error('主页链接不正确'));await saving;
  assert.equal(h.panel.open,true);assert.equal(inputs[0].disabled,false);
  const html=h.html(fresh());assert.match(html,/主页链接不正确/);assert.match(html,/value="草稿名"/);assert.match(html,/<details[^>]* open>/);
  assert.equal(h.run('setupNeeded(state)'),true);
});

test('profile and vault save use the original APIs and do not set readiness locally',async()=>{
  const h=harness();h.html(fresh());
  h.fields('profile',{suBrand:'品牌',suName:'作者',suDouyin:'主页',suEditor:'编辑',suBoss:'同事'});h.fields('vault',{suVault:'/notes'});h.run('bindSetup(root)');
  await h.root.controls['#suProfile'][0].onsubmit({preventDefault(){}});await h.root.controls['#suVaultGo'][0].onclick();
  assert.deepEqual(h.calls,[{url:'/api/setup/profile',options:{method:'POST',body:{brand:'品牌',name:'作者',douyin:'主页',editor:'编辑',boss:'同事'}}},{url:'/api/settings',options:{method:'PUT',body:{obsidian_vault:'/notes'}}}]);
  assert.equal(h.run('setupNeeded(state)'),true);
});

test('polling keeps the selected native file input after focus moves or setup collapses',()=>{
  const start=app.indexOf("  const gb = $('#globalBanner');"),end=app.indexOf('  renderPlatformStrip();',start);  // 10/19 复盘合页拿掉了汇总的「近7天」计数，块到这里为止
  const guard=app.slice(start,end);
  const file={files:[{}]},panel={open:false},focus={matches:()=>false};let replacements=0,html='existing setup';
  const bannerNode={contains:()=>false,get innerHTML(){return html;},set innerHTML(value){replacements++;html=value;}};
  const context=vm.createContext({
    st:returning(),banner:['replacement'],document:{activeElement:focus},
    $:(selector,root)=>selector==='#globalBanner'?bannerNode:selector==='#setupCard'?panel:selector==='#suCookieFile'&&root===panel?file:null,
    bindSetup(){},setupNeeded:(state)=>!(state.setup.present&&state.self_account&&state.cookies.ok&&state.vault.ok&&state.settings.obsidian_vault),
    setupCard:Object.assign(()=>'',{state:{saving:{}}}),
  });
  vm.runInContext('function repaint(){'+guard+'}',context);
  vm.runInContext('repaint()',context);
  assert.equal(replacements,0);assert.equal(file.files.length,1);
  panel.open=true;vm.runInContext('repaint()',context);assert.equal(replacements,0);
  file.files=[];context.setupCard.state.saving.cookies=true;vm.runInContext('repaint()',context);assert.equal(replacements,0);
  context.st.cookies.ok=true;context.banner=[];vm.runInContext('repaint()',context);
  assert.equal(replacements,1);assert.equal(html,'','server-completed setup disappears even as its request settles');
});
