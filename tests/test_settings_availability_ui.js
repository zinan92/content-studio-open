'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const app=fs.readFileSync(path.join(__dirname,'../src/content_studio/static/app.js'),'utf8');
const availability=app.slice(app.indexOf('function renderSettingsAvailability()'),app.indexOf('function renderSettings()'));
const writer=app.slice(app.indexOf('async function renderWriterSkill('),app.indexOf('function readGeneralSettings()'));
function harness(off=[]){
  const nodes={'#writerSkillField':{},'#meLinksPanel':{},'#meLinksNote':{},'#setWriterSkill':{dataset:{}}};
  const calls=[];
  const context=vm.createContext({
    $:selector=>nodes[selector],featureOn:key=>!off.includes(key),document:{activeElement:null},
    FormState:{get:()=>({values:{writer_skill:'keep-existing-choice'}})},esc:value=>String(value??''),
    api:async url=>{calls.push(url);return {skills:[]};},
  });
  vm.runInContext(availability+writer,context);
  return {nodes,calls,run:code=>vm.runInContext(code,context)};
}

test('Trial hides unavailable setup sections and keeps writer value without loading the missing picker',async()=>{
  const h=harness(['skills','portal','xline']);h.run('renderSettingsAvailability()');
  await h.run("renderWriterSkill('saved')");
  assert.equal(h.nodes['#writerSkillField'].hidden,true);assert.equal(h.nodes['#meLinksPanel'].hidden,true);
  assert.equal(h.nodes['#setWriterSkill'].value,'keep-existing-choice');
  assert.equal(h.nodes['#setWriterSkill'].dataset.loading,'0');assert.equal(h.nodes['#setWriterSkill'].disabled,true);
  assert.deepEqual(h.calls,[]);
});

test('remaining capability descriptions only name enabled destinations',()=>{
  const portal=harness(['xline']);portal.run('renderSettingsAvailability()');
  assert.equal(portal.nodes['#meLinksPanel'].hidden,false);assert.match(portal.nodes['#meLinksNote'].textContent,/门户/);assert.doesNotMatch(portal.nodes['#meLinksNote'].textContent,/X/);
  const x=harness(['portal']);x.run('renderSettingsAvailability()');
  assert.equal(x.nodes['#meLinksPanel'].hidden,false);assert.match(x.nodes['#meLinksNote'].textContent,/X 素材/);assert.doesNotMatch(x.nodes['#meLinksNote'].textContent,/门户/);
});

test('full edition keeps writing options and public links available',async()=>{
  const h=harness();h.run('renderSettingsAvailability()');await h.run("renderWriterSkill('saved')");
  assert.equal(h.nodes['#writerSkillField'].hidden,false);assert.equal(h.nodes['#meLinksPanel'].hidden,false);
  assert.deepEqual(h.calls,['/api/skills']);assert.equal(h.nodes['#setWriterSkill'].disabled,false);
});
