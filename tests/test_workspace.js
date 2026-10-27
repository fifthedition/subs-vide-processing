'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom'),{IDBFactory}=require('fake-indexeddb');
const read=name=>fs.readFileSync(require('node:path').resolve(__dirname,'../static',name),'utf8'),clone=value=>JSON.parse(JSON.stringify(value));
const delay=()=>new Promise(resolve=>setImmediate(resolve));
async function until(condition){for(let n=0;n<100;n++){if(condition())return;await delay();}assert.fail('UI did not reach the expected state');}
async function editor({database=new IDBFactory(),account='editor',conflict=false}={}){
  const dom=new JSDOM(read('index.html'),{url:'https://studio.example',runScripts:'outside-only'}),w=dom.window,requests=[];
  w.indexedDB=database;w.setInterval=()=>0;w.document.fonts={ready:Promise.resolve()};w.confirm=()=>true;
  w.CSS={escape:value=>value};w.HTMLElement.prototype.scrollIntoView=()=>{};
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.HTMLMediaElement.prototype.pause=()=>{};w.HTMLMediaElement.prototype.load=()=>{};
  w.Teleprompter={snapshot:()=>({previous:-1,current:0,next:1}),draw:()=>{}};
  const p={id:'project',name:'Private words',revision:5,sourceId:null,cueOffsetMs:0,style:{width:1920,height:1080,fontSize:64,background:'#000000',color:'#ffffff',layout:'teleprompter'},
    segments:[{id:'one',startMs:0,endMs:1000,text:'Nádych.'},{id:'two',startMs:2000,endMs:3000,text:'Výdych.'}],reviewed:['one'],favorite:false,archived:false,workflowMode:'narrated',scriptReady:false,
    musicId:'music',music:{id:'music',name:'Music',durationMs:6000,channels:2,sampleRate:48000,bytes:1000},narrations:[],reference:{name:'English',segments:[{id:'en',startMs:0,endMs:1000,text:'English reference stays unchanged'}]}};
  const summaries=()=>[{id:p.id,name:p.name,revision:p.revision,count:p.segments.length,endMs:3000,musicId:'music',favorite:p.favorite,archived:p.archived,scriptReady:p.scriptReady}];
  let rejectSave=conflict;
  w.fetch=async(path,options={})=>{
    requests.push({path,options});let data,status=200;const body=options.body?JSON.parse(options.body):{};
    if(path==='/api/auth/me')data={id:account,username:account,role:'editor',remote:true,csrf:'csrf'};
    else if(path==='/api/projects')data=summaries();
    else if(path==='/api/catalog')data=[];
    else if(path==='/api/health')data={ready:true};
    else if(path==='/api/projects/project'){
      if(options.method==='PUT'){
        if(rejectSave){status=409;data={error:'This session changed in another window. Download your draft JSON before reloading.'};}
        else{Object.assign(p,body,{revision:p.revision+1});data=p;}
      }else data=p;
    }else if(path==='/api/projects/project/narrations')data=[];
    else if(path==='/api/projects/project/ready'){p.revision++;p.scriptReady=true;p.readyRevision=p.revision;data=p;}
    else if(path==='/api/jobs?projectId=project')data=[];
    else if(path==='/api/projects/project/versions')data=[{revision:5,actor:'editor',created:'2026-10-27T15:00:00Z',label:'Saved'},{revision:1,actor:'owner',created:'2026-10-26T15:00:00Z',label:'Created'}];
    else if(path==='/api/projects/project/versions/1')data={...p,revision:1,segments:[{...p.segments[0],text:'Earlier safe words'}]};
    else if(path==='/api/projects/project/versions/5')data=p;
    else if(path==='/api/projects/project/restore'){p.revision++;p.segments[0].text='Earlier safe words';data=p;}
    else throw new Error('Unexpected request '+path);
    return {ok:status<400,status,json:async()=>clone(data)};
  };
  w.eval(read('i18n.js')+'\n'+read('icons.js')+'\n'+read('workspace.js')+'\n'+read('app.js').replace(/start\(\);\s*$/,'window.started=start();')+'\nwindow.app={state,flushSave,loadProject,renderProjects};window.i18n=I18n;');
  await w.started;await delay();
  return {dom,w,requests,project:p,database,set rejectSave(value){rejectSave=value;},get state(){return w.app.state;},async close(){await w.app.state.savePromise?.catch(()=>{});for(let n=0;n<10;n++)await delay();w.WorkspaceUX._test().drafts.db?.close();dom.window.close();}};
}

test('bilingual subtitle actions have meaningful SVG controls and density is a display preference',async()=>{
  const app=await editor(),{w}=app,$=id=>w.document.getElementById(id);
  try{
    const row=$('cueList').firstElementChild;
    assert.equal(row.querySelectorAll('.row-tools button svg').length,4);
    assert.ok(row.querySelector('.cue-body .row-tools'));
    assert.match(row.querySelector('[data-action=split]').getAttribute('aria-label'),/Rozdeliť/);
    row.querySelector('[data-action=seek]').focus();row.querySelector('[data-action=seek]').dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));assert.equal(w.document.activeElement,row.querySelector('[data-action=split]'));
    assert.equal(row.querySelector('.reference-text').textContent,'English reference stays unchanged');
    const revision=app.state.project.revision;
    $('cueDensity').value='compact';$('cueDensity').dispatchEvent(new w.Event('change'));
    assert.equal(w.document.querySelector('.editor-panel').dataset.density,'compact');
    assert.equal(app.state.project.revision,revision);assert.equal(app.state.dirty,false);
    w.i18n.setLanguage('en');
    assert.equal(row.querySelector('.reference-text').textContent,'English reference stays unchanged');
    assert.match(row.querySelector('[data-action=split]').getAttribute('aria-label'),/Split/);
  }finally{await app.close();}
});

test('editing reviewed text clears review; explicit review enables versioned handoff',async()=>{
  const app=await editor(),{w}=app,$=id=>w.document.getElementById(id);
  try{
    const text=$('cueList').querySelector('textarea');text.value='Nový nádych.';text.dispatchEvent(new w.Event('input',{bubbles:true}));
    assert.deepEqual([...app.state.project.reviewed],[]);assert.equal($('markScriptReady').disabled,true);
    await w.app.flushSave();
    const check=$('cueList').querySelector('[data-review=one]');check.checked=true;check.dispatchEvent(new w.Event('change',{bubbles:true}));await until(()=>app.project.reviewed.includes('one'));await delay();
    $('markShownReviewed').click();await until(()=>app.project.reviewed.length===2);await delay();
    await until(()=>!$('markScriptReady').disabled);
    $('markScriptReady').click();await until(()=>app.project.scriptReady);
    assert.ok(app.requests.some(r=>r.path.endsWith('/ready')));await until(()=>/export/.test($('workflowMessage').textContent));
    assert.equal(app.project.segments[0].text,'Nový nádych.');
  }finally{await app.close();}
});

test('save conflicts keep local text in account-scoped IndexedDB and show recovery inside the dialog',async()=>{
  const app=await editor({conflict:true}),{w}=app,$=id=>w.document.getElementById(id);let database=app.database;
  try{
    const text=$('cueList').querySelector('textarea');text.value='Private unfinished words';text.dispatchEvent(new w.Event('input',{bubbles:true}));
    await assert.rejects(w.app.flushSave());await until(()=>$('conflictDialog').open);
    const saved=await w.WorkspaceUX._test().drafts.get('https://studio.example:editor:project');
    assert.equal(saved.project.segments[0].text,'Private unfinished words');
    assert.equal(app.project.segments[0].text,'Nádych.');
    w.WorkspaceUX.feedback('Microphone permission denied. Allow it in the browser and macOS Privacy settings.',true,$('conflictDialog'));
    assert.match($('conflictDialog').querySelector('.dialog-feedback').textContent,/mikrofónu/);
  }finally{await app.close();}
  const other=await editor({database,account:'other'});
  try{assert.equal(other.w.document.getElementById('draftRecoveryBanner').hidden,true);}finally{await other.close();}
  const resumed=await editor({database});
  try{await until(()=>!resumed.w.document.getElementById('draftRecoveryBanner').hidden);assert.match(resumed.w.document.getElementById('draftRecoveryBanner').textContent,/nedokončené/);}finally{await resumed.close();}
});

test('version preview is read-only and restore is an explicit new server action',async()=>{
  const app=await editor(),{w}=app,$=id=>w.document.getElementById(id);
  try{
    $('openVersions').click();await until(()=>$('versionList').children.length===2);
    $('versionList').querySelector('[data-version="1"]').click();await until(()=>!$('restoreVersion').disabled);
    assert.match($('versionComparison').textContent,/Earlier safe words/);
    assert.match($('versionComparison').textContent,/Nádych/);
    assert.equal(app.state.project.segments[0].text,'Nádych.');
    $('restoreVersion').click();await until(()=>app.state.project.revision===6);
    assert.equal(app.state.project.segments[0].text,'Earlier safe words');
    const request=app.requests.find(r=>r.path.endsWith('/restore'));assert.deepEqual(JSON.parse(request.options.body),{revision:5,version:1});
  }finally{await app.close();}
});

test('navigation shortcuts avoid typing and favorites/archive filters keep sessions recoverable',async()=>{
  const app=await editor(),{w}=app,$=id=>w.document.getElementById(id);
  try{
    $('viewExports').click();assert.equal(w.document.querySelector('main').dataset.view,'exports');
    $('viewScript').click();$('cueDensity').focus();
    const before=app.state.selected;$('cueDensity').dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowDown',altKey:true,bubbles:true}));assert.equal(app.state.selected,before);
    $('nextCue').click();assert.equal(app.state.selected,'two');
    $('jumpCue').value='00:00:04.500';$('jumpToCue').click();await delay();assert.equal(app.state.previewMs,4500);
    $('favoriteSession').click();await until(()=>app.project.favorite);await delay();
    $('sessionFilter').value='favorites';$('sessionFilter').dispatchEvent(new w.Event('change'));assert.equal($('projectList').querySelectorAll('[data-project]').length,1);
    $('archiveSession').click();await until(()=>app.project.archived);await delay();
    $('sessionFilter').value='active';$('sessionFilter').dispatchEvent(new w.Event('change'));assert.equal($('projectList').querySelectorAll('[data-project]').length,0);
    $('sessionFilter').value='archived';$('sessionFilter').dispatchEvent(new w.Event('change'));assert.equal($('projectList').querySelectorAll('[data-project]').length,1);
  }finally{await app.close();}
});

test('workflow completion follows the final mix belonging to the current rendered guide and narration',async()=>{
  const app=await editor(),{w}=app;
  try{
    app.state.project.renderSignature='current-script';
    app.state.project.narrations=[{id:'voice',guideJobId:'newguide',timelineRevision:2,hasVoice:true,enhancedIsCurrent:true}];
    app.state.jobs=[{id:'final',kind:'final',status:'complete',renderSignature:'old-script',guideJobId:'oldguide',narrationId:'oldvoice',narrationRevision:2},
      {id:'newguide',kind:'guide',status:'complete',renderSignature:'current-script'}];
    w.WorkspaceUX.decorateCues();
    assert.equal(w.document.getElementById('workflowSteps').lastElementChild.classList.contains('done'),false);
    Object.assign(app.state.jobs[0],{renderSignature:'current-script',guideJobId:'newguide',narrationId:'voice'});
    w.WorkspaceUX.decorateCues();
    assert.equal(w.document.getElementById('workflowSteps').lastElementChild.classList.contains('done'),true);
    app.state.project.narrations[0].timelineRevision=3;
    w.WorkspaceUX.decorateCues();
    assert.equal(w.document.getElementById('workflowSteps').lastElementChild.classList.contains('done'),false);
  }finally{await app.close();}
});
