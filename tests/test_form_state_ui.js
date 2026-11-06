const test = require('node:test');
const assert = require('node:assert/strict');
const {createFormState} = require('../src/content_studio/static/form-state.js');
test('navigation and late refresh preserve exact unsaved form text',()=>{
 const s=createFormState();s.load('general',{path:'old'});s.edit('general',{path:'new / partial '});
 assert.equal(s.load('general',{path:'server'}).values.path,'new / partial ');
});
test('failed save retains values and can retry; duplicate submit is prevented',()=>{
 const s=createFormState();s.load('g',{v:'old'});s.edit('g',{v:'new'});s.begin('g');
 assert.equal(s.begin('g'),null);s.fail('g','offline');assert.equal(s.get('g').values.v,'new');
 assert.ok(s.get('g').dirty);s.complete('g',s.begin('g'));assert.equal(s.get('g').state,'saved');
});
test('save callback cannot clear edits made while request was pending',()=>{
 const s=createFormState();s.load('g',{v:'old'});s.edit('g',{v:'first'});const sent=s.begin('g');s.edit('g',{v:'second'});s.complete('g',sent);
 assert.equal(s.get('g').values.v,'second');assert.ok(s.get('g').dirty);assert.match(s.get('g').message,/新改动/);
 assert.equal(s.load('g',{v:'first'}).values.v,'second');
});
test('independent form groups do not clear each other',()=>{
 const s=createFormState();s.load('tags',{v:''});s.load('links',{v:''});s.edit('tags',{v:'foo'});s.edit('links',{v:'bar'});
 s.complete('links',s.begin('links'));assert.ok(s.get('tags').dirty);assert.ok(s.hasDirty());
});
test('successful write is not rolled back by the pre-save cached server snapshot',()=>{
 const s=createFormState();s.load('g',{v:'old'});s.edit('g',{v:'new'});s.complete('g',s.begin('g'));
 assert.equal(s.load('g',{v:'old'}).values.v,'new');
 assert.equal(s.load('g',{v:'new'}).values.v,'new');
 assert.equal(s.load('g',{v:'later external change'}).values.v,'later external change');
});
test('editing a different setting while skill options load preserves the current writer',()=>{
 const fs=require('node:fs'),vm=require('node:vm');
 const source=fs.readFileSync(require.resolve('../src/content_studio/static/app.js'),'utf8');
 const fn=source.slice(source.indexOf('function readGeneralSettings()'),source.indexOf("$('#setWriterSkill').onchange"));
 const values={'#setVault':{value:'new-vault'},'#setVideoRoot':{value:'video'},'#setArchive':{value:'archive'},'#setWriterSkill':{value:'',dataset:{loading:'1'}}};
 const ctx=vm.createContext({$:id=>values[id],FormState:{get:()=>({values:{writer_skill:'existing-skill'}})}});vm.runInContext(fn,ctx);
 assert.equal(vm.runInContext('readGeneralSettings().writer_skill',ctx),'existing-skill');
 values['#setWriterSkill'].dataset.loading='0';
 assert.equal(vm.runInContext('readGeneralSettings().writer_skill',ctx),'');
});

// Exercise the production binding and its HTTP callbacks, not only the draft store.
function linksHarness() {
 const fs=require('node:fs'),vm=require('node:vm');
 const pending=[], notices=[];
 const status={dataset:{}},submit={disabled:false};
 const form={dataset:{},querySelector:(selector)=>selector==='[data-save-status]'?status:selector==='button[type="submit"]'?submit:null};
 const fields={'#meLinksForm':form,'#setGithub':{value:''},'#setSite':{value:''},'#meLinksErr':{textContent:''}};
 const document={activeElement:null};
 const context=vm.createContext({window:{addEventListener(){}},document,$:selector=>fields[selector],toast:message=>notices.push(message),api:(url,options)=>new Promise((resolve,reject)=>pending.push({url,options,resolve,reject}))});
 for(const file of ['form-state.js','melinks.js'])vm.runInContext(fs.readFileSync(require.resolve('../src/content_studio/static/'+file),'utf8'),context);
 return {context,pending,notices,fields,form,status,submit,document,run:code=>vm.runInContext(code,context)};
}

test('links first slow GET preserves input after the field loses focus',async()=>{
 const h=linksHarness();const loading=h.context.window.fillMeLinksForm();
 assert.equal(typeof h.form.oninput,'function');
 h.document.activeElement=h.fields['#setGithub'];h.fields['#setGithub'].value='typed-new-user';h.form.oninput();
 h.document.activeElement=null;
 h.pending[0].resolve({github_user:'server-old-user',site:'https://old.example.com'});await loading;
 assert.equal(h.fields['#setGithub'].value,'typed-new-user');
 assert.equal(h.fields['#setSite'].value,'https://old.example.com');
 assert.equal(h.run("FormState.get('links').values.github"),'typed-new-user');
 assert.equal(h.run("FormState.get('links').dirty"),true);
 assert.equal(h.status.dataset.state,'dirty');
});

test('pre-save links GET cannot roll back the completed PUT or repaint the old links',async()=>{
 const h=linksHarness();let loading=h.context.window.fillMeLinksForm();
 h.pending[0].resolve({github_user:'old-user',site:'https://old.example.com'});await loading;
 h.run('ME.links=null');loading=h.context.window.fillMeLinksForm();
 h.fields['#setGithub'].value='new-user';h.fields['#setSite'].value='https://new.example.com';h.form.oninput();
 const saving=h.form.onsubmit({preventDefault(){}});
 assert.equal(h.pending[2].options.method,'PUT');
 h.pending[2].resolve({github_user:'new-user',site:'https://new.example.com'});await saving;
 h.pending[1].resolve({github_user:'old-user',site:'https://old.example.com'});await loading;
 assert.equal(h.run('ME.links.github_user'),'new-user');
 assert.equal(h.fields['#setGithub'].value,'new-user');assert.equal(h.fields['#setSite'].value,'https://new.example.com');
 assert.equal(h.run("FormState.get('links').dirty"),false);
 assert.equal(h.status.dataset.state,'saved');assert.equal(h.submit.disabled,false);
});

test('links edits made while PUT is pending remain an unsaved draft after its acknowledgement',async()=>{
 const h=linksHarness();const loading=h.context.window.fillMeLinksForm();h.pending[0].resolve({github_user:'old',site:''});await loading;
 h.fields['#setGithub'].value='first';h.form.oninput();const saving=h.form.onsubmit({preventDefault(){}});
 h.fields['#setGithub'].value='second';h.form.oninput();h.pending[1].resolve({github_user:'first',site:''});await saving;
 await h.context.window.fillMeLinksForm();
 assert.equal(h.fields['#setGithub'].value,'second');assert.equal(h.run("FormState.get('links').dirty"),true);
 assert.match(h.status.textContent,/上一版已保存；新改动还未保存/);
});
test('normalized save receipt releases acknowledgement and accepts later external updates',()=>{
 const s=createFormState();s.load('tags',{v:''});s.edit('tags',{v:'#foo, #bar'});const ticket=s.begin('tags');
 s.complete('tags',ticket,{v:'foo，bar'});assert.equal(s.get('tags').values.v,'foo，bar');assert.equal(s.get('tags').dirty,false);
 s.load('tags',{v:'foo，bar'});s.load('tags',{v:'external'});assert.equal(s.get('tags').values.v,'external');
});

test('first links read must complete before saving to avoid clearing unknown existing fields',async()=>{
 const h=linksHarness();const loading=h.context.window.fillMeLinksForm();h.fields['#setGithub'].value='typed';h.form.oninput();
 await h.form.onsubmit({preventDefault(){}});assert.equal(h.pending.length,1);assert.equal(h.submit.disabled,true);
 h.pending[0].resolve({github_user:'old',site:'https://existing.example.com'});await loading;
 assert.equal(h.submit.disabled,false);assert.equal(h.fields['#setSite'].value,'https://existing.example.com');
});
