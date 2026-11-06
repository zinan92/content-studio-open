'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../src/content_studio/static/persona.js'),'utf8');
test('illustration gallery and article groups start folded while approved character assets remain visible',async()=>{
  const outer={},group={dataset:{personaGroup:'gallery/article'},open:false};
  const box={innerHTML:'',controls:{'#personaGallery':[outer],'[data-persona-group]':[group]}};
  const data={base:[{file:'avatar.png',label:'头像',v:1}],dir:'persona',name:'作者',ready:true,skill:'illustrations',gallery:[{file:'gallery/article/01.png',title:'文章一',caption:'插图',at:'2026-10-08'}]};
  const context=vm.createContext({window:{},api:async()=>data,esc:String,encodeURIComponent,$:(key,root)=>key==='#personaBody'?box:root.controls[key]?.[0],$$:(key,root)=>root.controls[key]||[]});
  vm.runInContext(source,context);await context.window.renderPersona();
  assert.match(box.innerHTML,/class="pe-base"/);assert.match(box.innerHTML,/path=avatar.png/);
  assert.match(box.innerHTML,/id="personaGallery">/);assert.match(box.innerHTML,/data-persona-group="gallery\/article">/);
  assert.match(box.innerHTML,/gallery%2Farticle%2F01.png/);
  outer.ontoggle({target:{open:true}});group.open=true;group.ontoggle();
  data.gallery.push({file:'gallery/article/02.png',title:'文章一',caption:'插图二',at:'2026-10-08'});
  await context.window.renderPersona();
  assert.match(box.innerHTML,/id="personaGallery" open/);assert.match(box.innerHTML,/data-persona-group="gallery\/article" open/);
  assert.match(box.innerHTML,/path=avatar.png/);
});
