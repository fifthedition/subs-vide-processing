'use strict';
window.StudioTools=(()=>{
  const $=id=>document.getElementById(id),t=(key,v)=>I18n.t(key,v),esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let cfg,timeline,sessionId=null,peaks=new Map(),peakQueue=[],peakActive=0,rangePlayback=null,preparation=null,frame=null;
  const mix={musicMuted:false,voiceMuted:false,solo:null};
  function range(){return {start:cfg.parse($('recordStart').value),end:cfg.parse($('recordEnd').value)};}
  function setRange(start,end){if(cfg.busy())return;$('recordStart').value=cfg.clock(start,true);$('recordEnd').value=cfg.clock(end,true);timeline.setRange(start,end);}
  function renderMix(){
    for(const [id,active] of [['mutePreviewMusic',mix.musicMuted],['mutePreviewVoice',mix.voiceMuted],['soloPreviewMusic',mix.solo==='music'],['soloPreviewVoice',mix.solo==='voice']])$(id).setAttribute('aria-pressed',String(active));
    cfg.video().muted=!cfg.busy()&&(mix.musicMuted||mix.solo==='voice');cfg.voice().muted=cfg.busy()||mix.voiceMuted||mix.solo==='music';
  }
  function changed(){renderMix();}
  async function drain(){
    while(peakActive<2&&peakQueue.length){const item=peakQueue.shift();peakActive++;(async()=>{try{
      let result;for(let n=0;n<120;n++){if(item.id!==sessionId)return;result=await cfg.request(item.path);if(result.status!=='building')break;await new Promise(resolve=>setTimeout(resolve,1500));}
      if(item.id===sessionId&&result?.status==='ready')timeline.setPeaks(item.key,result);
      else if(item.id===sessionId)$('waveformPreviewState').textContent=t('Waveform unavailable. Playback and numeric range controls still work.');
    }catch{if(item.id===sessionId)$('waveformPreviewState').textContent=t('Waveform unavailable. Playback and numeric range controls still work.');}finally{peakActive--;drain();if(!peakActive&&!peakQueue.length&&$('waveformPreviewState').textContent===t('Preparing waveforms…'))$('waveformPreviewState').textContent='';}})();}
  }
  function fetchPeak(key,path){if(peaks.has(key))return;peaks.set(key,true);if($('waveformPreviewState').textContent!==t('Preparing waveforms…'))$('waveformPreviewState').textContent=t('Preparing waveforms…');peakQueue.push({key,path,id:sessionId});drain();}
  function render(){
    const session=cfg.session();if(!session)return;
    if(sessionId!==session.id){sessionId=session.id;peaks.clear();peakQueue=[];timeline.peaks.clear();rangePlayback=null;mix.musicMuted=false;mix.voiceMuted=false;mix.solo=null;}
    let selected;try{selected=range();}catch{selected={start:0,end:session.durationMs};}
    timeline.setData({...session,voiceOffsetMs:(Number($('narrationOffset').value)||0)*1000});timeline.setRange(selected.start,selected.end);timeline.setDisabled(cfg.busy());renderMix();
    if($('studioTimelineDetails').open){
      fetchPeak('guide','/api/narration/'+session.id+'/guide-peaks');
      for(const clip of session.clips.slice(-12))fetchPeak(clip.mediaId,'/api/media/'+clip.mediaId+'/peaks');
      if(session.enhanced)fetchPeak(session.enhanced.id,'/api/media/'+session.enhanced.id+'/peaks');
    }
    $('playLastTake').disabled=cfg.busy()||!session.clips.length;
    $('focusRecording').textContent=t($('narrationDialog').classList.contains('recording-focus')?'Show all studio controls':'Focus recording view');
    $('studioSelectionState').textContent=t('Selected range: {start} – {end}',{start:cfg.clock(selected.start,true),end:cfg.clock(selected.end,true)});
    for(const id of ['recordCountIn','recordLeadIn','playNarrationRange','loopNarrationRange','mutePreviewMusic','mutePreviewVoice','soloPreviewMusic','soloPreviewVoice','checkAlignStart','checkAlignEnd'])$(id).disabled=cfg.busy();
    $('enhancedDurationCheck').textContent=session.enhanced&&Math.abs(session.enhanced.durationMs-session.durationMs)>100?
      t('Audio duration differs by {seconds} seconds. Check the beginning and end; a single offset cannot correct changing drift.',{seconds:((session.enhanced.durationMs-session.durationMs)/1000).toFixed(2)}):'';
  }
  function audition(index){
    if(cfg.busy())return;const session=cfg.session(),clip=session.clips[index];if(!clip)return;
    if($('studioTimelineDetails').open)fetchPeak(clip.mediaId,'/api/media/'+clip.mediaId+'/peaks');
    const start=clip.startFrame/session.sampleRate*1000,end=clip.endFrame/session.sampleRate*1000;
    cfg.selectClip(index);rangePlayback={start,end};cfg.video().currentTime=start/1000;cfg.playPreview();
  }
  function playRange(){if(cfg.busy())return;const selected=range();if(selected.end<=selected.start)return;if($('narrationListen').value==='take'){$('narrationListen').value='raw';$('narrationListen').dispatchEvent(new Event('change'));}rangePlayback=selected;cfg.video().currentTime=selected.start/1000;cfg.playPreview();}
  function tick(){
    if(!cfg.session())return;const ms=cfg.video().currentTime*1000;timeline.setTime(ms);
    if(rangePlayback&&!cfg.recording()&&!cfg.video().paused&&ms>=rangePlayback.end-5){
      if($('loopNarrationRange').checked){cfg.video().currentTime=rangePlayback.start/1000;cfg.syncVoice(true);}
      else{cfg.video().pause();cfg.voice().pause();rangePlayback=null;}
    }
    const pending=cfg.pendingBytes?.()||0;
    const uploadMessage=t(cfg.pending?.()?'Recording needs upload recovery.':cfg.recording()?pending>0?'Uploading recorded audio…':'Recording microphone only…':cfg.busy()?'Saving recorded audio…':'Saved takes are stored on your NAS.');
    $('narrationUploadState').setAttribute('aria-live',cfg.recording()?'off':'polite');
    if($('narrationUploadState').textContent!==uploadMessage)$('narrationUploadState').textContent=uploadMessage;
  }
  async function beforeRecord(start,seekGuide){
    rangePlayback=null;mix.musicMuted=false;mix.voiceMuted=false;mix.solo=null;renderMix();cfg.video().muted=false;cfg.voice().muted=false;
    const controller=new AbortController();preparation=controller;$('cancelCountIn').hidden=false;
    const wait=ms=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>{controller.signal.removeEventListener('abort',cancel);resolve();},ms);function cancel(){clearTimeout(timer);reject(new Error('Recording preparation cancelled.'));}controller.signal.addEventListener('abort',cancel,{once:true});});
    try{
      if($('recordCountIn').checked)for(let seconds=3;seconds>0;seconds--){cfg.status('Recording starts in {seconds}…',{seconds});await wait(1000);}
      const lead=Math.min(start/1000,Number($('recordLeadIn').value));
      if(lead>0){cfg.status('Listening to the lead-in. Recording has not started.');await seekGuide(start/1000-lead);await cfg.video().play();
        const deadline=performance.now()+Math.max(15000,lead*1000+5000);
        while(cfg.video().currentTime<start/1000){if(cfg.video().paused||performance.now()>deadline||document.hidden)throw new Error('Lead-in interrupted. Start recording again.');await wait(20);}
        cfg.video().pause();await seekGuide(start/1000);
      }
    }finally{if(preparation===controller)preparation=null;$('cancelCountIn').hidden=true;}
  }
  function close(){preparation?.abort();rangePlayback=null;sessionId=null;peakQueue=[];if(frame!=null)window.cancelAnimationFrame?.(frame);frame=null;cfg.video().muted=false;cfg.voice().muted=false;}
  function init(options){
    cfg=options;
    const root=document.createElement('section');root.className='studio-toolbox';root.innerHTML='<div class="studio-recording-options"><label class="check-row"><input id="recordCountIn" type="checkbox">'+esc(t('Three-second count-in'))+'</label><label>'+esc(t('Lead-in before recording'))+'<select id="recordLeadIn"><option value="0">'+esc(t('Off'))+'</option><option value="1">1 s</option><option value="2">2 s</option><option value="3">3 s</option><option value="5">5 s</option></select></label><button id="cancelCountIn" class="button outline" hidden>'+esc(t('Cancel preparation'))+'</button><button id="focusRecording" class="button outline">'+esc(t('Focus recording view'))+'</button><button id="playLastTake" class="button outline">'+StudioIcons.svg('play')+esc(t('Play last take'))+'</button></div><div id="recordingTimeline"></div><div class="studio-range-controls"><button id="playNarrationRange" class="button outline">'+StudioIcons.svg('play')+esc(t('Play selected range'))+'</button><label class="check-row"><input id="loopNarrationRange" type="checkbox">'+esc(t('Loop selected range'))+'</label><span id="studioSelectionState"></span></div>';
    const details=document.createElement('details');details.id='studioTimelineDetails';details.className='studio-timeline-details';const summary=document.createElement('summary');summary.textContent=t('Timeline and range playback');details.append(summary,root.querySelector('#recordingTimeline'),root.querySelector('.studio-range-controls'));root.append(details);details.addEventListener('toggle',()=>{if(details.open)render();});
    const loading=document.createElement('p');loading.id='waveformPreviewState';loading.className='setting-help';loading.setAttribute('role','status');details.append(loading);
    const uploadState=document.createElement('p');uploadState.id='narrationUploadState';uploadState.className='setting-help';uploadState.setAttribute('role','status');root.append(uploadState);
    $('narrationClips').closest('.narration-section').before(root);
    const previewControls=document.createElement('div');previewControls.className='preview-mix-controls';previewControls.innerHTML='<p>'+esc(t('Preview only — saved export levels stay unchanged.'))+'</p><div><strong>'+esc(t('Music'))+'</strong><button id="mutePreviewMusic" class="button outline" aria-pressed="false">'+esc(t('Mute music'))+'</button><button id="soloPreviewMusic" class="button outline" aria-pressed="false">'+esc(t('Solo music'))+'</button></div><div><strong>'+esc(t('Voice'))+'</strong><button id="mutePreviewVoice" class="button outline" aria-pressed="false">'+esc(t('Mute voice'))+'</button><button id="soloPreviewVoice" class="button outline" aria-pressed="false">'+esc(t('Solo voice'))+'</button></div>';
    $('narrationPreviewStatus').after(previewControls);
    const align=document.createElement('div');align.className='alignment-controls';align.innerHTML='<div><button data-offset="-.1" class="button outline">−0.1 s</button><button data-offset=".1" class="button outline">+0.1 s</button><button id="checkAlignStart" class="button outline">'+esc(t('Check beginning'))+'</button><button id="checkAlignEnd" class="button outline">'+esc(t('Check end'))+'</button></div><p id="enhancedDurationCheck" role="status"></p>';
    $('narrationOffset').closest('label').after(align);
    timeline=new NarrationTimeline.Timeline($('recordingTimeline'),{clock:cfg.clock,onSeek:ms=>{if(!cfg.busy())cfg.video().currentTime=ms/1000;},onRange:setRange,onCue:index=>{const cue=cfg.session().cues[index];if(cue&&!cfg.busy()){setRange(cue.startMs,cue.endMs);cfg.video().currentTime=cue.startMs/1000;}},onClip:index=>{const session=cfg.session(),clip=session.clips[index];if(clip&&!cfg.busy()){fetchPeak(clip.mediaId,'/api/media/'+clip.mediaId+'/peaks');setRange(clip.startFrame/session.sampleRate*1000,clip.endFrame/session.sampleRate*1000);cfg.video().currentTime=clip.startFrame/session.sampleRate;}}});
    $('playLastTake').onclick=()=>{const session=cfg.session(),index=session.clips.findIndex(c=>c.mediaId===session.lastTakeId);if(session.clips.length)audition(index<0?session.clips.length-1:index);};
    $('playNarrationRange').onclick=playRange;$('cancelCountIn').onclick=()=>preparation?.abort();
    $('narrationListen').addEventListener('change',()=>{rangePlayback=null;if($('narrationListen').value==='music'&&mix.solo==='voice'){mix.solo=null;mix.musicMuted=false;}renderMix();});
    $('focusRecording').onclick=()=>{$('narrationDialog').classList.toggle('recording-focus');$('focusRecording').textContent=t($('narrationDialog').classList.contains('recording-focus')?'Show all studio controls':'Focus recording view');};
    for(const [id,action] of [['mutePreviewMusic',()=>mix.musicMuted=!mix.musicMuted],['mutePreviewVoice',()=>mix.voiceMuted=!mix.voiceMuted],['soloPreviewMusic',()=>{mix.solo=mix.solo==='music'?null:'music';if(mix.solo)mix.musicMuted=false;}],['soloPreviewVoice',()=>{mix.solo=mix.solo==='voice'?null:'voice';if(mix.solo)mix.voiceMuted=false;}]])$(id).onclick=()=>{action();renderMix();};
    cfg.video().addEventListener('volumechange',()=>{
      if(cfg.busy()||!cfg.session())return;
      const expected=mix.musicMuted||mix.solo==='voice';
      if(cfg.video().muted!==expected){mix.musicMuted=cfg.video().muted;if(!mix.musicMuted&&mix.solo==='voice')mix.solo=null;renderMix();}
      if(Math.abs(cfg.video().volume-Number($('mixMusic').value)/100)>.005){$('mixMusic').value=Math.round(cfg.video().volume*100);$('mixMusic').dispatchEvent(new Event('input'));}
    });
    align.addEventListener('click',event=>{const button=event.target.closest('[data-offset]');if(button&&!cfg.busy()){$('narrationOffset').value=(Number($('narrationOffset').value)+Number(button.dataset.offset)).toFixed(2);$('narrationOffset').dispatchEvent(new Event('input'));}});
    $('checkAlignStart').onclick=()=>{if(!cfg.busy())cfg.video().currentTime=Math.max(0,(cfg.session().clips[0]?.startFrame||0)/cfg.session().sampleRate);};
    $('checkAlignEnd').onclick=()=>{if(!cfg.busy()){const session=cfg.session(),last=session.clips.at(-1);cfg.video().currentTime=Math.max(0,((last?.endFrame||session.durationMs*session.sampleRate/1000)/session.sampleRate)-8);}};
    for(const id of ['recordStart','recordEnd'])$(id).addEventListener('change',()=>{try{render();}catch{}});
    for(const event of ['loadedmetadata','seeked'])cfg.video().addEventListener(event,()=>{if(rangePlayback&&(cfg.video().currentTime*1000<rangePlayback.start-100||cfg.video().currentTime*1000>rangePlayback.end+100))rangePlayback=null;});
    cfg.video().addEventListener('play',()=>{if(frame!=null)return;const update=()=>{frame=null;if(!sessionId||cfg.video().paused)return;tick();frame=window.requestAnimationFrame?.(update);};frame=window.requestAnimationFrame?.(update);});
    cfg.video().addEventListener('pause',()=>{if(frame!=null)window.cancelAnimationFrame?.(frame);frame=null;});
    cfg.video().addEventListener('ended',()=>{if(rangePlayback&&$('loopNarrationRange').checked&&!cfg.busy()){cfg.video().currentTime=rangePlayback.start/1000;cfg.playPreview();}});
    document.addEventListener('languagechange',()=>{render();});
    StudioIcons.button($('playNarrationPreview'),'play',t('Play preview'));StudioIcons.button($('pauseNarrationPreview'),'pause',t('Pause preview'));
  }
  return {init,render,tick,changed,audition,beforeRecord,close,get timeline(){return timeline;},get rangePlayback(){return rangePlayback;},get mix(){return mix;}};
})();
