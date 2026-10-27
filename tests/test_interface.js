'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const root=require('node:path').resolve(__dirname,'..');
const read=name=>fs.readFileSync(root+'/static/'+name,'utf8');

async function editor({empty=false,language}={}){
  const dom=new JSDOM(read('index.html'),{url:'https://studio.example',runScripts:'outside-only'});
  const w=dom.window, calls=[];
  if(language)w.localStorage.setItem('breathwork-language',language);
  w.document.fonts={ready:Promise.resolve()};
  w.setTimeout=w.setInterval=()=>1;w.clearTimeout=()=>{};
  let mediaLoads=0;
  w.HTMLMediaElement.prototype.load=()=>mediaLoads++;
  w.HTMLMediaElement.prototype.pause=()=>{};
  w.Teleprompter={snapshot:()=>({previous:-1,current:0,next:1}),draw:()=>{}};
  w.HTMLElement.prototype.scrollIntoView=()=>{};
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  const project={id:'example',name:'Sign in',revision:5,sourceId:null,cueOffsetMs:0,
    style:{width:1920,height:1080,fontSize:64,background:'#000000',color:'#ffffff',layout:'teleprompter'},
    segments:[{id:'one',startMs:0,endMs:3000,text:'Save now'},{id:'two',startMs:4000,endMs:7000,text:'Sign in'}],
    reference:{name:'English',segments:[{startMs:0,endMs:3000,text:'English'}]},
    music:{id:'music',name:'English',durationMs:8000,channels:2,sampleRate:44100,bytes:100000}};
  const summary={id:'example',name:project.name,count:2,endMs:7000,musicId:'music'};
  w.fetch=async(path,options={})=>{
    calls.push({path,options});let data;
    if(path==='/api/auth/me')data={username:'Sign in',role:'owner',remote:true,csrf:'test'};
    else if(path==='/api/projects')data=empty?[]:[summary];
    else if(path==='/api/catalog')data=[{id:1,name:'English',count:2,displayLanguage:'en'}];
    else if(path==='/api/health')data={ready:true};
    else if(path==='/api/projects/example')data=options.method==='PUT'?{...JSON.parse(options.body),revision:6}:project;
    else if(path.startsWith('/api/jobs'))data=[{id:'job',status:'complete',stage:'Ready to download',revision:5,progress:100,createdAt:'2026-10-27T13:27:00Z'}];
    else if(path==='/api/admin/users')data=[{id:'person',username:'Sign in',role:'editor',enabled:true}];
    else if(path==='/api/admin/workers')data=[{id:'mac',name:'English',enabled:true}];
    else if(path==='/api/services')data={elevenlabs:{configured:false},deepl:{configured:true}};
    else if(path==='/api/drafts')data=[];
    else throw new Error('Unexpected request '+path);
    return {ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(data))};
  };
  w.eval(read('i18n.js')+'\n'+read('app.js').replace(/start\(\);\s*$/,'window.started=start();')+
    '\nwindow.studio={state,flushSave,loadJobs,refreshAdmin,openServices};window.i18n=I18n;');
  await w.started;
  return {dom,w,calls,get mediaLoads(){return mediaLoads;}};
}

test('Slovak is default; static labels, accessible names and dynamic exports translate',async()=>{
  const {dom,w}=await editor();
  try{
    assert.equal(w.document.documentElement.lang,'sk');
    assert.equal(w.document.querySelector('.panel-title h2').textContent,'Slovenský text');
    assert.equal(w.document.getElementById('saveProject').textContent,'Uložiť');
    assert.equal(w.document.querySelector('[data-field=startMs]').getAttribute('aria-label'),'Text 1 – začiatok');
    assert.equal(w.document.getElementById('cueSearch').placeholder,'Hľadať v texte…');
    assert.match(w.document.getElementById('jobList').textContent,/Pripravené na stiahnutie/);
    assert.match(w.document.getElementById('jobList').textContent,/Uložená verzia 5/);
    assert.match(w.document.getElementById('jobList').textContent,/Stiahnuť MP4/);
    assert.equal(w.document.getElementById('remainingTime').textContent,'00:08');
    assert.equal(w.i18n.t('Cues 3 and 4 overlap. Adjust their times.'),'Texty 3 a 4 sa prekrývajú. Upravte ich časy.');
    assert.equal(w.i18n.t('That file could not be read as audio.'),'Súbor sa nepodarilo prečítať ako zvuk.');
  }finally{dom.window.close();}
});

test('SK/EN switching preserves user text, invalid time edits, selection and playback source',async()=>{
  const app=await editor(),{dom,w,calls}=app;
  try{
    const field=w.document.querySelector('textarea.cue-text');
    field.focus();field.value='Uvoľni ramená. Ľahký nádych.';
    field.dispatchEvent(new w.Event('input',{bubbles:true}));
    const time=w.document.querySelector('[data-field=startMs]');
    time.value='unfinished';time.dispatchEvent(new w.Event('input',{bubbles:true}));
    const before=JSON.stringify(w.studio.state.project),loads=app.mediaLoads;
    for(const language of ['en','sk','en']){
      w.document.querySelector('[data-language='+language+']').click();
      await new Promise(resolve=>setImmediate(resolve));
      assert.equal(w.document.documentElement.lang,language);
      assert.equal(w.document.querySelector('.panel-title h2').textContent,language==='sk'?'Slovenský text':'Slovak script');
      assert.equal(w.document.getElementById('saveProject').textContent,language==='sk'?'Uložiť':'Save now');
      assert.equal(w.document.getElementById('projectName').value,'Sign in');
      assert.equal(w.document.querySelector('.project-name').textContent,'Sign in');
      assert.equal(w.document.querySelector('.reference-text').textContent,'English');
      assert.equal(w.document.getElementById('musicName').textContent,'English');
      assert.equal(w.document.getElementById('workspaceLabel').textContent,'Sign in');
      assert.equal(field.value,'Uvoľni ramená. Ľahký nádych.');
      assert.equal(time.value,'unfinished');
      assert.equal(JSON.stringify(w.studio.state.project),before);
      assert.equal(app.mediaLoads,loads);
      assert.equal(w.studio.state.selected,'one');
    }
    assert.equal(w.localStorage.getItem('breathwork-language'),'en');
    assert.equal(calls.filter(call=>call.options.method).length,0);
    time.value='00:00:00.000';time.dispatchEvent(new w.Event('input',{bubbles:true}));
    await w.studio.flushSave();
    const saved=JSON.parse(calls.find(call=>call.options.method==='PUT').options.body);
    assert.equal(saved.segments[0].text,'Uvoľni ramená. Ľahký nádych.');
  }finally{dom.window.close();}
});

test('dialogs translate without translating usernames, renderer names or secrets',async()=>{
  const {dom,w}=await editor();
  try{
    await w.studio.refreshAdmin();await w.studio.openServices();
    assert.match(w.document.getElementById('usersList').textContent,/Sign in/);
    assert.match(w.document.getElementById('usersList').textContent,/Deaktivovať/);
    assert.match(w.document.getElementById('workersList').textContent,/English/);
    assert.match(w.document.getElementById('workersList').textContent,/Zatiaľ nepripojený/);
    const key=w.document.getElementById('elevenlabsKey');key.value='test-private-value';
    w.i18n.setLanguage('en');
    assert.equal(key.value,'test-private-value');
    assert.match(w.document.getElementById('servicesDialog').textContent,/Transcription & translation/);
    assert.match(w.document.getElementById('elevenlabsState').textContent,/No key configured/);
  }finally{dom.window.close();}
});

test('English preference and language switch work in an empty workspace',async()=>{
  const {dom,w}=await editor({empty:true,language:'en'});
  try{
    assert.equal(w.document.documentElement.lang,'en');
    const button=w.document.querySelector('[data-language=sk]');
    assert.equal(button.disabled,false);button.click();
    assert.equal(w.document.documentElement.lang,'sk');
    assert.equal(w.document.getElementById('importSubtitles').textContent,'↓ Importovať');
  }finally{dom.window.close();}
});

test('sign-in and first-time setup use the same language preference and errors',async()=>{
  for(const setup of [false,true]){
    const dom=new JSDOM(read('login.html'),{url:'https://studio.example/login',runScripts:'outside-only'}),w=dom.window;
    try{
      w.fetch=async(path)=>({ok:!path.endsWith('/login'),json:async()=>path.endsWith('/state')?{remote:true,needsSetup:setup}:{error:'Incorrect username or password.'}});
      w.eval(read('i18n.js')+'\n'+read('login.js')+'\nwindow.i18n=I18n;');
      await new Promise(resolve=>setImmediate(resolve));
      assert.equal(w.document.getElementById('loginHeading').textContent,setup?'Vytvorte účet vlastníka':'Prihlásiť sa');
      w.i18n.setLanguage('en');
      assert.equal(w.document.getElementById('loginHeading').textContent,setup?'Create your owner account':'Sign in');
      w.i18n.setLanguage('sk');
      if(!setup){
        await w.document.getElementById('loginForm').onsubmit({preventDefault(){}});
        assert.equal(w.document.getElementById('loginError').textContent,'Nesprávne používateľské meno alebo heslo.');
      }
    }finally{dom.window.close();}
  }
});

test('all static interface copy has a Slovak translation; favicon and 1080p controls exist',()=>{
  for(const name of ['index.html','login.html']){
    const dom=new JSDOM(read(name),{url:'https://studio.example',runScripts:'outside-only'}),w=dom.window;
    try{
      w.eval(read('i18n.js')+'\nwindow.i18n=I18n;');
      const exempt=/^(?:Breathwork Studio|BREATHWORK STUDIO|Breathwork|Studio|SK|EN|VTT ↗|Full HD · 1080p|[\d\W]+)$/u;
      const walker=w.document.createTreeWalker(w.document,w.NodeFilter.SHOW_TEXT);let node;
      const missing=[];
      while((node=walker.nextNode())){
        const text=node.textContent.trim();
        if(!text||node.parentElement?.closest('script,style')||exempt.test(text))continue;
        // A translated value or controlled metadata must replace every English label.
        if(Object.hasOwn(w.i18n.dictionary,text)&&w.i18n.dictionary[text]!==text)missing.push(text);
      }
      assert.deepEqual(missing,[]);
      assert.ok(w.document.querySelector('link[rel=icon][href="/favicon.svg"]'));
      if(name==='index.html')assert.deepEqual([...w.document.querySelectorAll('#resolution option')].map(option=>option.value),['1920']);
    }finally{dom.window.close();}
  }
});
