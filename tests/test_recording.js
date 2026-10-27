'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {JSDOM}=require('jsdom'),{IDBFactory}=require('fake-indexeddb');
const read=name=>fs.readFileSync(require('node:path').resolve(__dirname,'../static',name),'utf8');
const clone=value=>JSON.parse(JSON.stringify(value));
const delay=()=>new Promise(resolve=>setImmediate(resolve));
async function until(condition){for(let n=0;n<100;n++){if(condition())return;await delay();}assert.fail('Timed out waiting for recording state');}

function processor(rate=48000){
  let Class;
  const context={sampleRate:rate,currentFrame:0,AudioWorkletProcessor:class{constructor(){this.port={postMessage(){}};}},
    registerProcessor:(name,Constructor)=>{Class=Constructor;}};
  vm.createContext(context);vm.runInContext(read('recorder-worklet.js'),context);
  const node=new Class(),messages=[];
  node.port.postMessage=data=>messages.push(data);
  return {node,messages,context,pump(samples){
    const output=new Float32Array(samples.length).fill(1);
    node.process([[samples]],[[output]]);
    context.currentFrame+=samples.length;
    assert.ok(output.every(sample=>sample===0),'Microphone must never feed back to speakers');
  }};
}

test('AudioWorklet writes uncompressed mono 24-bit PCM, flushes on pause and ignores later samples',()=>{
  const p=processor();
  p.node.port.onmessage({data:{type:'start',token:'take'}});
  p.pump(new Float32Array([0,.5,-.5,1,-1,2,-2]));
  p.node.port.onmessage({data:{type:'stop'}});
  const chunk=p.messages.find(message=>message.type==='pcm'),data=Buffer.from(chunk.pcm);
  const sample=index=>data.readIntLE(index*3,3);
  assert.deepEqual(Array.from({length:7},(_,i)=>sample(i)),[0,4194304,-4194304,8388607,-8388608,8388607,-8388608]);
  assert.equal(p.messages.find(message=>message.type==='stopped').bytes,21);
  p.pump(new Float32Array(48000).fill(.1));
  assert.equal(p.messages.filter(message=>message.type==='pcm').length,1);
  assert.ok(p.messages.some(message=>message.type==='level'));
});

test('recording spool survives reload, removes acknowledged chunks and retains data on storage failure',async()=>{
  const dom=new JSDOM('',{url:'https://studio.example',runScripts:'outside-only'}),w=dom.window;
  w.indexedDB=new IDBFactory();w.eval(read('recorder.js'));
  const first=new w.BreathworkAudio.Spool(),second=new w.BreathworkAudio.Spool();
  try{
    const meta={id:'take',ownerId:'editor',bytes:0};
    assert.equal(await first.put(meta),true);
    await first.append(meta,0,new Uint8Array([1,2,3]).buffer);
    await first.append(meta,3,new Uint8Array([4,5,6]).buffer);
    assert.equal((await second.all())[0].bytes,6);
    assert.deepEqual(Array.from(await second.chunks('take'),item=>item.offset),[0,3]);
    const chunk=(await second.chunks('take'))[0];await second.removeChunk(chunk.id);
    assert.deepEqual(Array.from(await second.chunks('take'),item=>item.offset),[3]);
    const transaction=second.transaction.bind(second);
    second.transaction=async(stores,mode,action)=>{if(mode==='readwrite')throw new Error('Quota exceeded');return transaction(stores,mode,action);};
    assert.equal(await second.append(meta,6,new Uint8Array([7,8,9]).buffer),false);
    assert.deepEqual(Array.from(await second.chunks('take'),item=>item.offset),[3,6]);
    second.transaction=transaction;await second.remove('take');
    assert.deepEqual(Array.from(await second.all()),[]);
  }finally{first.database?.close();second.database?.close();dom.window.close();}
});

async function studio({deny=false,fallback=false}={}){
  const dom=new JSDOM(read('index.html'),{url:'https://studio.example',runScripts:'outside-only'}),w=dom.window;
  w.indexedDB=new IDBFactory();w.isSecureContext=true;
  w.setInterval=()=>0;w.clearInterval=()=>{};w.confirm=()=>true;
  w.URL.createObjectURL=()=> 'blob:test-recording';w.URL.revokeObjectURL=()=>{};
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
  const nodes=[],contexts=[],constraints=[],requests=[],errors=[];
  let stops=0,offline=false,offset=0,takeCount=0;
  const track=new w.EventTarget();track.label='External USB microphone';
  track.getSettings=()=>({sampleRate:fallback?44100:48000,echoCancellation:false,noiseSuppression:false,autoGainControl:false});
  track.stop=()=>stops++;
  w.navigator.mediaDevices={getUserMedia:async options=>{
    constraints.push(options);if(deny)throw new w.DOMException('Denied','NotAllowedError');
    return {getTracks:()=>[track],getAudioTracks:()=>[track]};
  },enumerateDevices:async()=>[{kind:'audioinput',deviceId:'usb',label:'External USB microphone'}],addEventListener(){}};
  class Context{
    constructor(options){if(fallback&&options?.sampleRate)throw new Error('Rate unavailable');this.sampleRate=fallback?44100:48000;this.currentTime=0;this.state='running';this.destination={};this.audioWorklet={addModule:async()=>{}};contexts.push(this);}
    async resume(){this.state='running';}
    async close(){this.state='closed';}
    createMediaStreamSource(){return {connect(){},disconnect(){}};}
    createGain(){return {gain:{value:1},connect(){},disconnect(){}};}
  }
  w.AudioContext=Context;
  w.AudioWorkletNode=class{
    constructor(context){
      this.context=context;this.bytes=0;this.port={onmessage:null,postMessage:data=>{
        if(data.type==='start'){this.token=data.token;this.bytes=0;queueMicrotask(()=>this.port.onmessage({data:{type:'started',token:this.token,frame:Math.round(context.currentTime*context.sampleRate)}}));}
        if(data.type==='stop')queueMicrotask(()=>this.port.onmessage({data:{type:'stopped',token:this.token,bytes:this.bytes}}));
      }};
      nodes.push(this);
    }
    emit(seconds=1){const pcm=new Uint8Array(Math.round(this.context.sampleRate*seconds)*3).buffer,offset=this.bytes;this.bytes+=pcm.byteLength;
      this.context.currentTime+=seconds;this.port.onmessage({data:{type:'pcm',token:this.token,offset,pcm}});}
    connect(){}disconnect(){}
  };
  for(const el of w.document.querySelectorAll('audio,video')){
    let paused=true,time=0;
    const state=el.media={readyState:4,duration:3,seeking:false,seeks:0,plays:0,loads:0,error:null,playError:null,holdSeek:false,deferPlay:false,pending:[]};
    Object.defineProperty(el,'paused',{get:()=>paused});
    Object.defineProperty(el,'readyState',{get:()=>state.readyState});
    Object.defineProperty(el,'duration',{get:()=>state.duration});
    Object.defineProperty(el,'seeking',{get:()=>state.seeking});
    Object.defineProperty(el,'error',{get:()=>state.error});
    el.finishSeek=()=>{state.seeking=false;el.dispatchEvent(new w.Event('seeked'));};
    Object.defineProperty(el,'currentTime',{get:()=>time,set:value=>{time=value;state.seeks++;state.seeking=true;
      el.dispatchEvent(new w.Event('seeking'));if(!state.holdSeek)queueMicrotask(el.finishSeek);}});
    el.advance=seconds=>{time+=seconds;el.dispatchEvent(new w.Event('timeupdate'));};
    el.play=()=>{state.plays++;if(state.playError)return Promise.reject(state.playError);
      paused=false;el.dispatchEvent(new w.Event('play'));
      return state.deferPlay?new Promise((resolve,reject)=>state.pending.push({resolve,reject})):Promise.resolve();};
    el.pause=()=>{if(!paused){paused=true;el.dispatchEvent(new w.Event('pause'));}};
    el.load=()=>{state.loads++;state.error=null;};
  }
  let session={id:'session',projectId:'project',guideJobId:'guide',name:'Sign in',guideRevision:5,durationMs:3000,sampleRate:48000,
    revision:1,timelineRevision:1,clips:[],cues:[{startMs:0,endMs:2500,text:'English'}],
    master:{status:'missing'},enhanced:null,enhancedMediaId:null,enhancedIsCurrent:false,canUndo:false,voiceOffsetMs:0,musicVolume:.25,voiceVolume:1,alignmentConfirmed:false};
  const pending=new Map();
  const api=async(path,options={})=>{
    requests.push({path,options});
    let match;
    if(path==='/api/narration/open'||path==='/api/narration/session')return clone(session);
    if(path.startsWith('/api/jobs'))return [];
    if(path.startsWith('/api/recordings?')||path==='/api/recordings')return [...pending.values()].map(clone);
    if(path==='/api/narration/session/take'){
      const id='take'+(++takeCount);offset=0;
      const take={id,sessionId:'session',startMs:options.body.startMs,endMs:options.body.endMs,sampleRate:options.body.sampleRate,offset:0,status:'recording'};
      pending.set(id,take);return clone(take);
    }
    if((match=path.match(/^\/api\/recordings\/(take\d+)$/)))return clone(pending.get(match[1]));
    if((match=path.match(/^\/api\/recordings\/(take\d+)\/chunk$/))){
      if(offline)throw new Error('Network disconnected');
      offset+=options.body.size;pending.get(match[1]).offset=offset;return {offset};
    }
    if((match=path.match(/^\/api\/recordings\/(take\d+)\/finish$/))){
      assert.equal(options.body.bytes,offset);assert.equal(options.body.revision,session.revision);
      const take=pending.get(match[1]);pending.delete(match[1]);session.revision++;session.timelineRevision++;
      session.clips.push({mediaId:match[1],startFrame:Math.round(take.startMs*48),endFrame:Math.round(take.startMs*48)+Math.round(offset/3*48000/take.sampleRate),sourceFrame:0});
      session.canUndo=true;return clone(session);
    }
    if(path.endsWith('/discard')){pending.delete(path.split('/')[3]);return {ok:true};}
    if(path==='/api/narration/session/mix'){session={...session,...options.body,revision:session.revision+1};return clone(session);}
    throw new Error('Unexpected request '+path);
  };
  w.eval(read('i18n.js')+'\n'+read('recorder.js')+'\n'+read('narration.js'));
  const clock=(ms,precise=false)=>{const s=Math.floor(ms/1000),m=Math.floor(s/60);return precise?'00:'+String(m).padStart(2,'0')+':'+String(s%60).padStart(2,'0')+'.'+String(ms%1000).padStart(3,'0'):String(m).padStart(2,'0')+':'+String(s%60).padStart(2,'0');};
  const parseClock=text=>{const [h,m,s]=text.split(':').map(Number);return Math.round(((h*60+m)*60+s)*1000);};
  w.NarrationStudio.init({api,uploadFile:async()=>({id:'enhanced'}),toast:message=>errors.push(message),clock,parseClock,
    auth:()=>({id:'editor'}),jobsChanged:async()=>{},pauseEditorAudio(){}});
  return {dom,w,nodes,contexts,constraints,requests,errors,pending,get stops(){return stops;},set offline(value){offline=value;},
    async close(){const state=w.NarrationStudio._test();if(state.mic.active)await state.mic.stop();await state.mic.disconnect();state.spool.database?.close();dom.window.close();}};
}

test('independent mic check handles permission denial and never starts narration',async()=>{
  const app=await studio({deny:true}),{w}=app;
  try{
    w.document.getElementById('openMicCheck').click();await delay();
    w.document.getElementById('micEnable').click();await until(()=>app.errors.length>0);
    assert.match(app.errors[0],/mikrofónu/);
    assert.equal(app.requests.length,0);assert.equal(app.nodes.length,0);
  }finally{await app.close();}
});

test('mic check can record and play a WAV test; fallback rate and device processing settings are exposed',async()=>{
  const app=await studio({fallback:true}),{w}=app;
  try{
    w.document.getElementById('openMicCheck').click();await delay();
    w.document.getElementById('micEnable').click();await until(()=>app.nodes.length===1);await delay();
    assert.match(w.document.getElementById('micSettings').textContent,/44100/);
    const audio=app.constraints[0].audio;
    assert.equal(audio.echoCancellation,false);assert.equal(audio.noiseSuppression,false);assert.equal(audio.autoGainControl,false);
    w.document.getElementById('micTest').click();await until(()=>w.NarrationStudio._test().mic.active);
    app.nodes[0].emit(.25);await delay();
    w.document.getElementById('micTest').click();await until(()=>!w.document.getElementById('micTestPlayback').hidden);
    assert.equal(app.requests.length,0);
    assert.equal(w.document.getElementById('micTestDownload').download,'microphone-test.wav');
    const header=w.BreathworkAudio.wavHeader(44100,33075),view=new w.DataView(header);
    assert.equal(view.getUint32(24,true),44100);assert.equal(view.getUint16(34,true),24);assert.equal(view.getUint16(22,true),1);
  }finally{await app.close();}
});

test('narration pause/resume saves separate takes and language switching leaves capture intact',async()=>{
  const app=await studio(),{w}=app;
  try{
    await w.NarrationStudio.open('guide');
    const state=w.NarrationStudio._test();
    await state.beginRecord(false);assert.equal(w.NarrationStudio.isRecording(),true);
    const id=app.pending.keys().next().value;
    w.document.querySelector('[data-language=en]').click();
    assert.equal(w.NarrationStudio.isRecording(),true);assert.ok(app.pending.has(id));
    app.nodes[0].emit(.5);await delay();
    // Update the fake media clock without simulating a user seek.
    await state.pauseTake();assert.equal(app.pending.size,0);
    assert.equal(state.session.clips.length,1);
    w.document.getElementById('guideVideo').currentTime=.5;await delay();
    await state.beginRecord(true);app.nodes[0].emit(.5);await delay();await state.pauseTake();
    assert.equal(state.session.clips.length,2);
    const starts=app.requests.filter(request=>request.path.endsWith('/take')).map(request=>request.options.body.startMs);
    assert.deepEqual(starts,[0,500]);
  }finally{await app.close();}
});

test('network failure pauses capture with durable chunks and retries without losing recorded bytes',async()=>{
  const app=await studio(),{w}=app;
  try{
    await w.NarrationStudio.open('guide');const state=w.NarrationStudio._test();
    await state.beginRecord();app.offline=true;app.nodes[0].emit(.5);
    await until(()=>!w.NarrationStudio.isRecording()&&w.document.getElementById('narrationRecovery').textContent.includes('Zopakovať'));
    const saved=await state.spool.all();assert.equal(saved.length,1);assert.equal(saved[0].bytes,72000);
    assert.equal((await state.spool.chunks(saved[0].id)).length,1);
    app.offline=false;await state.recover(saved[0].id);
    assert.equal((await state.spool.all()).length,0);assert.equal(app.pending.size,0);
    assert.equal(state.session.clips[0].endFrame,24000);
  }finally{await app.close();}
});

test('video buffering and playback-speed changes pause and save microphone capture',async()=>{
  const app=await studio(),{w}=app;
  try{
    await w.NarrationStudio.open('guide');const state=w.NarrationStudio._test(),video=w.document.getElementById('guideVideo');
    await state.beginRecord();app.nodes[0].emit(.5);video.advance(.5);await delay();
    assert.equal(w.NarrationStudio.isRecording(),true);
    video.dispatchEvent(new w.Event('waiting'));
    await until(()=>!w.NarrationStudio.isRecording()&&app.pending.size===0);
    assert.equal(state.session.clips.length,1);
    await state.beginRecord(true);app.nodes[0].emit(.5);video.advance(.5);await delay();
    video.playbackRate=1.5;video.dispatchEvent(new w.Event('ratechange'));
    await until(()=>!w.NarrationStudio.isRecording()&&app.pending.size===0);
    assert.equal(state.session.clips.length,2);
    assert.equal(state.mic.active,false);
  }finally{await app.close();}
});


async function preview(app,choice='raw'){
  const {w}=app,$=id=>w.document.getElementById(id);
  await w.NarrationStudio.open('guide');
  const session=w.NarrationStudio._test().session;
  session.master={status:'ready'};
  session.enhanced={id:'enhanced'};
  $('narrationListen').value=choice;$('narrationListen').dispatchEvent(new w.Event('change'));
  await delay();
  return {session,video:$('guideVideo'),voice:$('narrationVoice'),status:$('narrationPreviewStatus'),
    play:$('playNarrationPreview'),pause:$('pauseNarrationPreview'),$};
}

test('preview plays both tracks at selected levels and level/language updates do not seek again',async()=>{
  const app=await studio(),{w}=app;
  try{
    const {video,voice,play,pause,$}=await preview(app);
    video.currentTime=.5;await delay();
    const seeks=voice.media.seeks;
    $('mixMusic').value='25';$('mixMusic').dispatchEvent(new w.Event('input'));
    $('mixVoice').value='90';$('mixVoice').dispatchEvent(new w.Event('input'));
    w.document.querySelector('[data-language=en]').click();
    assert.equal(voice.media.seeks,seeks,'Settings and refreshes must not reset the decoder');
    play.click();await delay();
    assert.equal(video.paused,false);assert.equal(voice.paused,false);
    assert.equal(video.volume,.25);assert.equal(voice.volume,.9);
    assert.match(voice.getAttribute('src'),/master\?version=1&play=1$/);
    voice.advance(.2);video.advance(.2);await delay();
    assert.equal(voice.media.seeks,seeks);
    pause.click();assert.equal(video.paused,true);assert.equal(voice.paused,true);
  }finally{await app.close();}
});

test('slow WAV metadata, pending play and seeking are not restarted on every clock tick',async()=>{
  const app=await studio(),{w}=app;
  try{
    const {video,voice,play,status}=await preview(app);
    voice.media.readyState=0;voice.media.deferPlay=true;
    video.currentTime=.5;await delay();const seeks=voice.media.seeks;
    play.click();
    assert.equal(voice.media.plays,1);
    for(let n=0;n<5;n++)video.advance(.1);
    assert.equal(voice.media.seeks,seeks,'Do not seek before WAV metadata arrives');
    voice.media.readyState=1;voice.media.holdSeek=true;
    voice.dispatchEvent(new w.Event('loadedmetadata'));
    assert.equal(voice.media.seeks,seeks+1);
    for(let n=0;n<5;n++)video.advance(.1);
    assert.equal(voice.media.seeks,seeks+1,'Do not replace a pending network seek');
    assert.equal(voice.media.plays,1,'Keep one outstanding play promise');
    assert.match(status.textContent,/Načítava/);
    voice.media.readyState=4;voice.media.holdSeek=false;
    voice.finishSeek();voice.media.pending.shift().resolve();await delay();
    assert.equal(voice.paused,false);assert.equal(video.paused,false);
    assert.equal(voice.currentTime,video.currentTime,'Align once when delayed playback starts');
    assert.ok(voice.media.seeks<=seeks+2);
  }finally{await app.close();}
});

test('blocked secondary audio pauses music, reports inside the dialog and retries directly on click',async()=>{
  const app=await studio(),{w}=app;
  try{
    const {video,voice,play,status,$}=await preview(app);
    voice.media.playError=new w.DOMException('Autoplay blocked','NotAllowedError');
    await video.play();await delay();
    assert.equal(video.paused,true);assert.ok(status.classList.contains('preview-error'));
    assert.match(status.textContent,/zablokované/);
    const attempts=voice.media.plays;
    for(let n=0;n<5;n++)video.advance(.05);
    assert.equal(voice.media.plays,attempts,'Do not retry blocked playback in the timer');
    w.document.querySelector('[data-language=en]').click();
    assert.match(status.textContent,/blocked/);
    voice.media.playError=null;
    const original=voice.play;let inClick=false,calledInClick=false;
    voice.play=()=>{calledInClick=inClick;return original();};
    inClick=true;play.click();inClick=false;await delay();
    assert.equal(calledInClick,true);assert.equal(video.paused,false);assert.equal(voice.paused,false);
    assert.equal(status.classList.contains('preview-error'),false);
    $('closeNarration').click();await delay();assert.equal(voice.paused,true);
  }finally{await app.close();}
});

test('decode/network errors are visible in the studio and retry reloads the source',async()=>{
  const app=await studio(),{w}=app;
  try{
    const {video,voice,play,status}=await preview(app);
    play.click();await delay();
    voice.media.error={code:3};voice.dispatchEvent(new w.Event('error'));
    assert.equal(video.paused,true);assert.match(status.textContent,/dekódovať/);
    const loads=voice.media.loads;play.click();await delay();
    assert.equal(voice.media.loads,loads+1);assert.equal(voice.paused,false);
    voice.media.error={code:2};voice.dispatchEvent(new w.Event('error'));
    assert.equal(video.paused,true);assert.match(status.textContent,/pripojenie/);
  }finally{await app.close();}
});

test('switching sources ignores old play rejection and enhanced offset aligns without repeated seeks',async()=>{
  const app=await studio(),{w}=app;
  try{
    const {video,voice,play,status,$}=await preview(app);
    voice.media.deferPlay=true;play.click();
    const old=voice.media.pending.shift();
    $('narrationListen').value='enhanced';$('narrationListen').dispatchEvent(new w.Event('change'));
    assert.equal(voice.getAttribute('src'),'/media/enhanced');
    old.reject(new w.DOMException('Old source failed','NotSupportedError'));await delay();
    assert.equal(status.classList.contains('preview-error'),false);
    voice.media.deferPlay=false;voice.media.pending.shift().resolve();await delay();
    video.currentTime=1;await delay();
    $('narrationOffset').value='.1';$('narrationOffset').dispatchEvent(new w.Event('input'));await delay();
    assert.equal(voice.currentTime,.9);
    const seeks=voice.media.seeks;
    $('mixVoice').value='80';$('mixVoice').dispatchEvent(new w.Event('input'));await delay();
    assert.equal(voice.media.seeks,seeks);
    $('narrationOffset').value='2';$('narrationOffset').dispatchEvent(new w.Event('input'));
    assert.equal(voice.paused,true);
    video.currentTime=2.5;await delay();assert.equal(voice.currentTime,.5);assert.equal(voice.paused,false);
  }finally{await app.close();}
});

test('missing narration is explained inside the modal and never starts a music-only voice preview',async()=>{
  const app=await studio(),{w}=app;
  try{
    const {session,video,voice,play,status,$}=await preview(app);
    session.master={status:'missing'};
    $('narrationListen').dispatchEvent(new w.Event('change'));play.click();await delay();
    assert.equal(video.paused,true);assert.equal(voice.paused,true);assert.match(status.textContent,/WAV/);
    $('narrationListen').value='music';$('narrationListen').dispatchEvent(new w.Event('change'));
    play.click();await delay();assert.equal(video.paused,false);assert.equal(voice.paused,true);
  }finally{await app.close();}
});
