'use strict';
window.NarrationStudio = (() => {
  const $=id=>document.getElementById(id), t=(key,values)=>I18n.t(key,values);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let cfg,mic,spool,session=null,meta=null,recording=false,preparing=false,stopping=null,upload=null;
  let testMode=false,testTimer,testURL=null,testChunks=[],mixDirty=false,hasPending=false,clockTimer,pollTimer;
  let statusKey='Ready to record.',statusValues={},previewError=false,activeExport=false,guideJobs=[],guideSignature='';
  let voicePlay=null,nextVoiceCorrection=0,previewKey='Choose audio and press Play preview.';
  const video=()=>$('guideVideo'),voice=()=>$('narrationVoice');
  function status(key,values={}){statusKey=key;statusValues=values;$('narrationStatus').textContent=t(key,values);}
  function microphoneError(error){
    return ({NotAllowedError:'Microphone permission denied. Allow it in the browser and macOS Privacy settings.',
      NotFoundError:'No microphone was found. Connect one and refresh the device list.',
      NotReadableError:'The microphone is busy or unavailable. Close other recording apps and try again.',
      OverconstrainedError:'The selected microphone is unavailable. Choose another device.'})[error.name]||error.message;
  }
  async function safe(action){try{return await action();}catch(error){cfg.toast(t(microphoneError(error)),true);}}
  async function request(path,options={}){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
    try{return await cfg.api(path,{...options,signal:controller.signal});}
    catch(error){if(error.name==='AbortError')throw new Error('Connection timed out. The recording remains saved for retry.');throw error;}
    finally{clearTimeout(timer);}
  }
  function buttons(){
    if(!cfg)return;
    const busy=recording||preparing||!!stopping||testMode;
    for(const id of ['micDevice','micGain','micEnable','micRefresh'])$(id).disabled=busy;
    $('micDisable').disabled=!mic.context||busy;
    $('micTest').disabled=recording||preparing||!!stopping||!mic.context;
    $('micTest').textContent=t(testMode?'Stop test recording':'Record a 10-second test');
    for(const id of ['recordRange','resumeNarration'])$(id).disabled=!session||busy||hasPending;
    $('pauseNarration').disabled=!recording;
    for(const id of ['recordStart','recordEnd','narrationCue','narrationGuide','enhancedFile','enhancedBasisVersion',
      'enhancedVersionConfirm','narrationOffset','mixMusic','mixVoice','narrationAlignment','saveNarrationMix','narrationListen',
      'playNarrationPreview','pauseNarrationPreview'])$(id).disabled=busy||!session;
    $('undoNarration').disabled=busy||hasPending||!session?.canUndo;
    $('prepareNarrationMaster').disabled=busy||hasPending||!session?.clips.length||session?.master.status==='building';
    $('narrationAlignment').disabled=busy||!session?.enhancedIsCurrent;
    $('queueNarrationFinal').disabled=busy||hasPending||activeExport||!session?.enhancedIsCurrent||!$('narrationAlignment').checked;
    $('studioMicCheck').disabled=busy;
    $('closeNarration').disabled=preparing||!!stopping;
    video().controls=!recording;
  }
  function level({peak,rms}){
    const db=Math.max(-60,20*Math.log10(Math.max(rms,1e-9))),clipping=peak>=.98;
    for(const id of ['micLevelBar','studioMicLevelBar'])if($(id)){
      $(id).style.width=((db+60)/60*100)+'%';$(id).parentElement.classList.toggle('clipping',clipping);
      $(id).parentElement.setAttribute('aria-valuenow',String(Math.round(db)));
    }
    $('micLevelValue').textContent=Math.round(db)+' dBFS';
    const key=clipping?'Clipping detected — lower the input gain.':rms>.003?'Microphone signal detected.':'Speak to test the microphone.';
    $('micLevelState').textContent=t(key);if($('studioMicLevelState'))$('studioMicLevelState').textContent=t(key);
  }
  async function devices(){
    const selected=$('micDevice').value;
    const list=await mic.devices();
    $('micDevice').innerHTML='<option value="">'+escape(t('System default microphone'))+'</option>'+
      list.map((item,index)=>'<option data-user-text value="'+escape(item.deviceId)+'">'+escape(item.label||t('Microphone {number}',{number:index+1}))+'</option>').join('');
    if(list.some(item=>item.deviceId===selected))$('micDevice').value=selected;
  }
  function describeMic(){
    if(!mic.context){$('micConnection').textContent=t('Microphone is off.');$('micSettings').textContent='';return;}
    $('micConnection').textContent=t('Microphone is ready.');
    const settings=mic.track.getSettings(),value=key=>t(settings[key]===true?'On':settings[key]===false?'Off':'Not reported');
    $('micSettings').textContent=t('WAV capture: {rate} Hz · 24-bit mono. Echo cancellation: {echo}. Noise suppression: {noise}. Automatic gain: {gain}.',
      {rate:mic.context.sampleRate,echo:value('echoCancellation'),noise:value('noiseSuppression'),gain:value('autoGainControl')});
  }
  async function ensureMic(){
    if(!mic.context){await mic.connect($('micDevice').value,Number($('micGain').value));await devices();}
    else await mic.context.resume();
    describeMic();buttons();
  }
  async function micCheck(){
    if(recording)throw new Error('Pause recording before changing microphone settings.');
    $('micDialog').showModal();describeMic();await devices();buttons();
  }
  async function stopTest(){
    if(!testMode)return;
    clearTimeout(testTimer);await mic.stop();testMode=false;
    if(testURL)URL.revokeObjectURL(testURL);
    testURL=URL.createObjectURL(BreathworkAudio.wav(testChunks,mic.context.sampleRate));
    $('micTestPlayback').src=testURL;$('micTestPlayback').hidden=false;
    $('micTestDownload').href=testURL;$('micTestDownload').download='microphone-test.wav';$('micTestDownload').hidden=false;
    buttons();
  }
  async function startTest(){
    if(testMode)return stopTest();
    await ensureMic();cfg.pauseEditorAudio();video().pause();$('micTestPlayback').pause();testChunks=[];testMode=true;buttons();
    try{await mic.start(data=>{testChunks.push(data.pcm);});testTimer=setTimeout(()=>safe(stopTest),10000);}
    catch(error){testMode=false;buttons();throw error;}
  }
  async function closeMic(){
    await stopTest();$('micTestPlayback').pause();await mic.disconnect();describeMic();$('micDialog').close();buttons();
  }
  function parse(value){return cfg.parseClock(value);}
  async function seekGuide(seconds){
    if(video().readyState<1)await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{cleanup();reject(new Error('The guide video did not load. Check your connection and try again.'));},15000);
      const done=()=>{cleanup();resolve();},failed=()=>{cleanup();reject(new Error('The guide video could not play. Check your connection and reopen it.'));};
      function cleanup(){clearTimeout(timer);video().removeEventListener('loadedmetadata',done);video().removeEventListener('error',failed);}
      video().addEventListener('loadedmetadata',done);video().addEventListener('error',failed);
    });
    if(Math.abs(video().currentTime-seconds)<.001)return;
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{cleanup();reject(new Error('The video could not seek to the selected range. Try again.'));},15000);
      const done=()=>{cleanup();resolve();};
      function cleanup(){clearTimeout(timer);video().removeEventListener('seeked',done);}
      video().addEventListener('seeked',done);video().currentTime=seconds;
    });
  }
  function range(){
    const start=parse($('recordStart').value),end=parse($('recordEnd').value);
    if(start<0||end<=start||end>session.durationMs)throw new Error('Choose a recording range inside the guide video.');
    return {start,end};
  }
  function renderSession(force=false){
    if(!session)return;
    renderGuides();
    $('narrationVersion').innerHTML='<span data-user-text>'+escape(session.name)+'</span> · '+escape(t('Rendered revision {revision} · narration WAV version {version}',{revision:session.guideRevision,version:session.timelineRevision}));
    $('narrationClips').innerHTML=session.clips.length?session.clips.map((clip,index)=>{
      const start=clip.startFrame/session.sampleRate*1000,end=clip.endFrame/session.sampleRate*1000;
      return '<div class="narration-clip"><span>'+escape(cfg.clock(start,true))+' – '+escape(cfg.clock(end,true))+'</span><button class="text-button" data-rerecord="'+index+'">'+t('Re-record this range')+'</button></div>';
    }).join(''):'<p>'+t('No narration has been saved yet.')+'</p>';
    $('narrationMasterState').textContent=session.master.status==='ready'?
      t('WAV version {version} is ready.',{version:session.timelineRevision}):
      session.master.status==='building'?t('Preparing the full-length WAV…'):
      session.master.status==='failed'?t(session.master.error||'The WAV master could not be prepared.'):
      t('Prepare a WAV after recording and reviewing your takes.');
    $('downloadNarrationMaster').hidden=session.master.status!=='ready';
    $('downloadNarrationMaster').href='/api/narration/'+session.id+'/master?version='+session.timelineRevision;
    $('downloadNarrationMaster').download='narration-'+session.id.slice(0,8)+'-r'+session.timelineRevision+'.wav';
    $('enhancedName').textContent=session.enhanced?.name||'';
    $('enhancedState').textContent=session.enhanced?(session.enhancedIsCurrent?
      t('Enhanced audio: {duration}. Video: {video}. Check alignment before export.',{duration:cfg.clock(session.enhanced.durationMs,true),video:cfg.clock(session.durationMs,true)}):
      t('Narration changed after enhancement. Prepare and enhance the new WAV version.')):
      t('Upload the enhanced narration after processing the WAV in Adobe Podcast.');
    if(force||!mixDirty){
      $('mixMusic').value=Math.round(session.musicVolume*100);$('mixVoice').value=Math.round(session.voiceVolume*100);
      $('narrationOffset').value=session.voiceOffsetMs/1000;$('narrationAlignment').checked=session.alignmentConfirmed;
      $('enhancedBasisVersion').value=session.enhancedTimelineRevision||session.timelineRevision;
    }
    $('mixMusicValue').value=$('mixMusic').value+'%';$('mixVoiceValue').value=$('mixVoice').value+'%';
    I18n.apply($('narrationClips'));buttons();playback();
  }
  async function refreshSession(force=false){
    if(!session||recording||preparing||stopping||(!force&&mixDirty))return;
    const id=session.id,result=await request('/api/narration/'+id);
    if(session?.id===id){session=result;await refreshExportState();renderSession(force);}
  }
  async function refreshExportState(){
    if(!session)return;
    const id=session.id,jobs=await request('/api/jobs?projectId='+session.projectId);
    if(session?.id===id){activeExport=jobs.some(job=>job.status==='queued'||job.status==='rendering');guideJobs=jobs.filter(job=>job.status==='complete'&&job.kind!=='final');renderGuides();}
  }
  function renderGuides(){
    if(!session)return;
    const jobs=guideJobs.some(job=>job.id===session.guideJobId)?guideJobs:[{id:session.guideJobId,revision:session.guideRevision},...guideJobs];
    const signature=JSON.stringify([I18n.language,session.guideJobId,jobs.map(job=>[job.id,job.revision,job.completedAt,job.createdAt])]);
    if(signature===guideSignature){$('narrationGuide').value=session.guideJobId;return;}
    guideSignature=signature;
    $('narrationGuide').innerHTML=jobs.map(job=>'<option data-user-text value="'+escape(job.id)+'">'+escape(t('Rendered revision {revision}',{revision:job.revision})+
      (job.createdAt?' · '+new Date(job.completedAt||job.createdAt).toLocaleString(I18n.locale,{dateStyle:'medium',timeStyle:'medium'}):''))+'</option>').join('');
    $('narrationGuide').value=session.guideJobId;
  }
  async function flush(item){
    if(upload)return upload;
    upload=(async()=>{
      if(item.serverOffset==null){const server=await request('/api/recordings/'+item.id);item.serverOffset=server.offset;}
      for(const chunk of await spool.chunks(item.id)){
        const end=chunk.offset+chunk.pcm.byteLength;
        if(item.serverOffset>=end){await spool.removeChunk(chunk.id);continue;}
        if(item.serverOffset<chunk.offset)throw new Error('Some audio is still in the original browser. Reopen it or recover only the audio already received.');
        const cut=item.serverOffset-chunk.offset;
        const result=await request('/api/recordings/'+item.id+'/chunk',{method:'POST',body:new Blob([chunk.pcm.slice(cut)]),
          headers:{'Content-Type':'application/octet-stream','X-Upload-Offset':String(item.serverOffset)}});
        item.serverOffset=result.offset;await spool.removeChunk(chunk.id);
      }
      await spool.put(item);
    })().catch(error=>{item.serverOffset=null;throw error;}).finally(()=>{upload=null;});
    return upload;
  }
  async function finishItem(item){
    await flush(item);
    // Chunks can have arrived while an earlier flush was in flight.
    if((await spool.chunks(item.id)).length)await flush(item);
    if(item.serverOffset!==item.bytes)throw new Error('Some audio is still in the original browser. Reopen it or recover only the audio already received.');
    const result=await request('/api/recordings/'+item.id+'/finish',{method:'POST',
      body:{revision:item.revision,bytes:item.bytes,startMs:Math.round(item.startMs)}});
    await spool.remove(item.id);return result;
  }
  async function pauseTake(reason='Take saved. You can resume from the playhead.'){
    if(stopping)return stopping;
    if(!recording)return;
    recording=false;video().pause();voice().pause();status('Saving recorded audio…');buttons();
    stopping=(async()=>{
      const result=await mic.stop();
      meta.bytes=result.bytes;meta.done=true;await spool.put(meta);
      if(!meta.bytes){
        await request('/api/recordings/'+meta.id+'/discard',{method:'POST',body:{}});await spool.remove(meta.id);
        status('No audio was captured. Check your microphone and try again.');
      }else{
        session=await finishItem(meta);mixDirty=false;renderSession(true);
        status(result.interrupted?'The recording was interrupted. Review the saved take before continuing.':reason);
      }
      meta=null;hasPending=false;
    })().catch(error=>{
      hasPending=true;status('Recording paused. Retry uploading the saved take before continuing.');cfg.toast(t(error.message),true);
    }).finally(async()=>{stopping=null;buttons();await updateRecovery().catch(()=>{});await refreshRecoveryBadge().catch(()=>{});});
    buttons();return stopping;
  }
  async function beginRecord(resume=false){
    if(!session||recording||preparing||stopping||hasPending)return;
    const selected=range(),start=resume?Math.round(video().currentTime*1000):selected.start;
    if(start>=selected.end)throw new Error('Move the playhead inside the selected range before resuming.');
    preparing=true;status('Preparing microphone and video…');buttons();
    let created=null;
    try{
      await ensureMic();await spool.open();
      $('narrationListen').value='music';voice().pause();cfg.pauseEditorAudio();
      video().pause();video().playbackRate=1;await seekGuide(start/1000);playback();
      created=await request('/api/narration/'+session.id+'/take',{method:'POST',
        body:{revision:session.revision,startMs:start,endMs:selected.end,sampleRate:mic.context.sampleRate}});
      meta={id:created.id,sessionId:session.id,ownerId:cfg.auth().id,bytes:0,revision:session.revision,
        startMs:start,rate:mic.context.sampleRate,endMs:selected.end,serverOffset:0,done:false};
      if(!await spool.put(meta))throw new Error('Browser storage is unavailable. Free some space before recording.');
      try{await video().play();}catch{throw new Error('Press Play in the video player once, pause it, then start recording.');}
      const anchorVideo=video().currentTime*1000,anchorAudio=mic.context.currentTime;
      recording=true;
      const started=await mic.start(async data=>{
        const item=meta;
        if(!item)return;
        const durable=await spool.append(item,data.offset,data.pcm);
        if(!durable&&recording)safe(()=>pauseTake('Browser storage filled up. Review the saved take before continuing.'));
        flush(item).catch(()=>{if(recording)safe(()=>pauseTake('The connection was interrupted. Review the saved take before continuing.'));});
        if(item.bytes-(item.serverOffset||0)>8*1024*1024&&recording)safe(()=>pauseTake('Recording paused while waiting for uploads.'));
      });
      meta.firstAudioTime=started.frame/started.rate;
      meta.startMs=Math.max(0,Math.min(start+500,anchorVideo+(meta.firstAudioTime-anchorAudio)*1000));
      await spool.put(meta);status('Recording microphone only…');
    }catch(error){
      if(recording){await pauseTake();throw error;}
      video().pause();
      if(created){await request('/api/recordings/'+created.id+'/discard',{method:'POST',body:{}}).catch(()=>{});await spool.remove(created.id).catch(()=>{});}
      meta=null;throw error;
    }finally{preparing=false;buttons();if(!recording){await updateRecovery().catch(()=>{});await refreshRecoveryBadge().catch(()=>{});}}
  }
  function playback(){
    if(!session)return;
    video().volume=Number($('mixMusic').value)/100;voice().volume=Number($('mixVoice').value)/100;
    const choice=$('narrationListen').value;
    let source=choice==='raw'&&session.master.status==='ready'?'/api/narration/'+session.id+'/master?version='+session.timelineRevision+'&play=1':
      choice==='enhanced'&&session.enhanced?'/media/'+session.enhanced.id:'';
    if(recording)source='';
    if((voice().getAttribute('src')||'')!==source){
      voicePlay=null;nextVoiceCorrection=0;previewError=false;
      voice().pause();if(source)voice().src=source;else voice().removeAttribute('src');
      voice().load();
      previewStatus('Choose audio and press Play preview.');
    }
    if(!source&&choice!=='music')previewStatus(choice==='raw'?'Prepare the WAV master to preview saved narration.':
      'Upload enhanced narration to preview it.');
    // Updating levels or polling the session must not restart an audio seek.
    syncVoice();
  }
  function previewStatus(key,error=false){
    previewKey=key;const message=t(key);
    if($('narrationPreviewStatus').textContent!==message)$('narrationPreviewStatus').textContent=message;
    $('narrationPreviewStatus').classList.toggle('preview-error',error);
  }
  function previewFailed(error){
    if(error?.name==='AbortError')return; // Pause/seek/source changes can interrupt play().
    previewError=true;video().pause();voice().pause();
    previewStatus(error?.name==='NotAllowedError'?'Voice playback was blocked. Click Play preview to allow it.':
      error?.name==='NotSupportedError'||voice().error?.code===3||voice().error?.code===4?
      'The browser could not decode the narration. Download the WAV to check it, or try another browser.':
      'The narration could not load. Check your connection and click Play preview to retry.',true);
  }
  function playVoice(){
    if(voicePlay||!voice().paused||previewError)return;
    const operation={};voicePlay=operation;
    // Invoke play synchronously: the preview button supplies the user gesture
    // required by browsers that block a second media element's automatic audio.
    let promise;
    try{promise=voice().play();}catch(error){voicePlay=null;previewFailed(error);return;}
    Promise.resolve(promise).then(()=>{
      if(voicePlay!==operation)return;
      voicePlay=null;
      if(video().paused||recording||!$('narrationDialog').open)voice().pause();
      else{previewStatus('Playing narration and music.');syncVoice(true);}
    },error=>{
      if(voicePlay!==operation)return;
      voicePlay=null;previewFailed(error);
    });
  }
  function syncVoice(force=false,start=false){
    if(!session||!voice().getAttribute('src')||recording){voice().pause();return;}
    if(previewError)return;
    const offset=$('narrationListen').value==='enhanced'?Number($('narrationOffset').value)||0:0;
    const at=video().currentTime-offset;
    if(at<0||(voice().duration>0&&Number.isFinite(voice().duration)&&at>=voice().duration)){
      voice().pause();previewStatus('No narration at this position.');return;
    }
    const now=performance.now(),drift=Math.abs(voice().currentTime-at);
    // Wait for an in-flight seek/play to settle. Re-seeking a large WAV every
    // 200 ms can keep a network-backed decoder buffering indefinitely.
    if(voice().readyState>=1&&!voice().seeking&&!video().seeking&&drift>(force?.04:.35)&&
      (force||(!voicePlay&&voice().readyState>=3&&now>=nextVoiceCorrection))){
      try{voice().currentTime=Math.max(0,at);nextVoiceCorrection=now+2000;}catch{}
    }
    voice().playbackRate=video().playbackRate;
    if(video().paused&&!start)voice().pause();
    else{
      if(voice().readyState<3||voice().seeking)previewStatus('Loading narration…');
      else if(!voice().paused&&!voicePlay)previewStatus('Playing narration and music.');
      playVoice();
    }
  }
  function playPreview(){
    if(!session||recording||preparing||stopping||testMode)return;
    previewError=false;
    if(voice().error){voicePlay=null;voice().load();}
    playback();
    if($('narrationListen').value!=='music'&&!voice().getAttribute('src'))return;
    cfg.pauseEditorAudio();
    if(video().ended)video().currentTime=0;
    syncVoice(true,true);
    // Both play calls occur in this click handler, without an await between them.
    video().play().catch(()=>{
      voice().pause();previewStatus('The guide video could not play. Check your connection and reopen it.',true);
    });
    if($('narrationListen').value==='music')previewStatus('Playing music only.');
  }
  function tick(){
    if(!session||!$('narrationDialog').open)return;
    const ms=video().currentTime*1000;
    $('narrationElapsed').textContent=cfg.clock(ms);
    $('narrationRemaining').textContent=cfg.clock(Math.ceil(Math.max(0,session.durationMs-ms)/1000)*1000);
    syncVoice();
    if(recording&&meta){
      if(ms>=meta.endMs-5){safe(()=>pauseTake('Selected range recorded and saved.'));return;}
      if(meta.firstAudioTime!=null){
        const elapsed=mic.context.currentTime-meta.firstAudioTime;
        if(elapsed>=7200){safe(()=>pauseTake('Two-hour take saved. Resume to continue recording.'));return;}
        if(Math.abs(ms-(meta.startMs+elapsed*1000))>200)safe(()=>pauseTake('Playback timing changed. Review the saved take before continuing.'));
      }
    }
  }
  async function saveMix(extra={}){
    const payload={revision:session.revision,timelineRevision:session.timelineRevision,
      voiceOffsetMs:Math.round(Number($('narrationOffset').value)*1000),musicVolume:Number($('mixMusic').value)/100,
      voiceVolume:Number($('mixVoice').value)/100,alignmentConfirmed:$('narrationAlignment').checked,...extra};
    session=await request('/api/narration/'+session.id+'/mix',{method:'POST',body:payload});
    mixDirty=false;renderSession(true);return session;
  }
  async function enhance(file){
    if(!file)return;
    if(!$('enhancedVersionConfirm').checked)throw new Error('Confirm which WAV version was processed before uploading enhanced audio.');
    const basis=Number($('enhancedBasisVersion').value);
    if(basis!==session.timelineRevision)throw new Error('Use the current narration WAV version for enhancement.');
    preparing=true;$('narrationAlignment').checked=false;buttons();
    try{
      const media=await cfg.uploadFile(file,'enhanced',message=>status(message));
      await saveMix({enhancedMediaId:media.id,attachEnhanced:true,enhancedTimelineRevision:basis,alignmentConfirmed:false});
      $('enhancedVersionConfirm').checked=false;status('Enhanced audio attached. Preview the beginning and end, then confirm alignment.');
    }finally{preparing=false;$('enhancedFile').value='';buttons();}
  }
  async function updateRecovery(){
    if(!session)return;
    const id=session.id,items=await request('/api/recordings?sessionId='+id);
    if(session?.id!==id)return;
    hasPending=items.length>0;
    $('narrationRecovery').innerHTML=items.map(item=>'<div class="recording-recovery"><strong>'+escape(t('Unfinished take at {time}',{time:cfg.clock(item.startMs)}))+'</strong><div class="mic-actions"><button class="button outline" data-recover="'+item.id+'">'+t('Retry upload and save')+'</button><button class="text-button" data-partial="'+item.id+'">'+t('Recover received audio only')+'</button><button class="text-button" data-discard="'+item.id+'">'+t('Discard unfinished take')+'</button></div></div>').join('');
    buttons();
  }
  async function recover(id,partial=false){
    preparing=true;buttons();
    try{
      const take=await request('/api/recordings/'+id);
      if(take.status==='complete'){await spool.remove(id);session=await request('/api/narration/'+take.sessionId);mixDirty=false;renderSession(true);return;}
      const fresh=await request('/api/narration/'+take.sessionId);
      let item=(await spool.all()).find(value=>value.id===id);
      if(item&&item.revision!==fresh.revision&&!window.confirm(t('Narration changed in another window. Apply the recovered take to the current timeline?')))return;
      if(partial){
        if(!window.confirm(t('Save only audio already received by the NAS? Unsent audio from this take will not be included.')))return;
        item={id,sessionId:take.sessionId,ownerId:cfg.auth().id,bytes:take.offset,serverOffset:take.offset,startMs:item?.startMs??take.startMs,revision:fresh.revision,done:true};
        // Explicit partial recovery must not append still-pending local chunks.
        if(!item.bytes)throw new Error('No audio has reached the NAS yet. Retry from the original browser.');
        session=await request('/api/recordings/'+id+'/finish',{method:'POST',body:{revision:fresh.revision,bytes:item.bytes,startMs:Math.round(item.startMs)}});
        await spool.remove(id);
      }else{
        if(!item)throw new Error('Reopen the original browser to upload the remaining audio, or recover the received audio only.');
        item.revision=fresh.revision;item.serverOffset=null;item.done=true;await spool.put(item);
        session=await finishItem(item);
      }
      meta=null;mixDirty=false;renderSession(true);status('Recovered take saved. Review its timing before continuing.');
    }finally{preparing=false;await updateRecovery();await refreshRecoveryBadge();buttons();}
  }
  async function refreshRecoveryBadge(){
    if(!cfg.auth())return;
    const pending=await request('/api/recordings');$('openRecordingRecovery').hidden=!pending.length;
    return pending;
  }
  async function openRecovery(){
    $('recordingRecoveryDialog').showModal();const pending=await refreshRecoveryBadge();
    const sessions=new Map();
    for(const item of pending||[])if(!sessions.has(item.sessionId))sessions.set(item.sessionId,await request('/api/narration/'+item.sessionId));
    $('recordingRecoveryList').innerHTML=[...sessions.values()].map(item=>'<div class="admin-row"><span data-user-text>'+escape(item.name)+'</span><button class="button outline" data-recover-guide="'+item.guideJobId+'">'+t('Open matching video')+'</button></div>').join('')||'<p>'+t('No interrupted recordings were found.')+'</p>';
  }
  async function open(guideId){
    if(recording||preparing||stopping)throw new Error('Pause and save the current recording first.');
    preparing=true;buttons();cfg.pauseEditorAudio();
    voicePlay=null;previewError=false;video().pause();voice().pause();
    try{
      session=await request('/api/narration/open',{method:'POST',body:{guideJobId:guideId}});
      mixDirty=false;hasPending=false;meta=null;activeExport=false;guideJobs=[];
      $('recordStart').value=cfg.clock(0,true);$('recordEnd').value=cfg.clock(session.durationMs,true);
      $('narrationCue').innerHTML='<option value="">'+t('Choose a rendered subtitle…')+'</option>'+session.cues.map((cue,index)=>
        '<option data-user-text value="'+index+'">'+escape(cfg.clock(cue.startMs)+' · '+cue.text.slice(0,110))+'</option>').join('');
      $('enhancedVersionConfirm').checked=false;$('narrationListen').value='music';
      video().src='/api/jobs/'+guideId+'/play';video().currentTime=Math.min(session.lastPositionMs||0,session.durationMs)/1000;
      $('narrationDialog').showModal();status('Ready to record.');renderSession(true);
      previewStatus('Choose audio and press Play preview.');
      await updateRecovery();await refreshExportState();
      clearInterval(clockTimer);clockTimer=setInterval(tick,200);
      clearInterval(pollTimer);pollTimer=setInterval(()=>safe(()=>refreshSession()),3000);
    }finally{preparing=false;buttons();}
  }
  async function close(){
    if(recording)await pauseTake();
    if(preparing||stopping)return;
    voicePlay=null;video().pause();voice().pause();await mic.disconnect();describeMic();
    clearInterval(clockTimer);clearInterval(pollTimer);$('narrationDialog').close();
    video().removeAttribute('src');video().load();voice().removeAttribute('src');voice().load();
    await refreshRecoveryBadge().catch(()=>{});
  }
  async function watch(id){
    cfg.pauseEditorAudio();video().pause();voice().pause();
    $('watchVideo').src='/api/jobs/'+id+'/play';$('watchDialog').showModal();
  }
  function init(options){
    if(cfg)return;
    cfg=options;spool=new BreathworkAudio.Spool();
    mic=new BreathworkAudio.Microphone({level,interrupted:message=>{
      if(recording)safe(()=>pauseTake(message));if(testMode)safe(stopTest);describeMic();
    },failure:error=>{cfg.toast(t(error.message),true);if(recording)safe(()=>pauseTake());}});
    $('openMicCheck').onclick=()=>safe(micCheck);$('studioMicCheck').onclick=()=>safe(micCheck);
    $('closeMicCheck').onclick=()=>safe(closeMic);$('micDialog').addEventListener('cancel',event=>{event.preventDefault();safe(closeMic);});
    $('micEnable').onclick=()=>safe(async()=>{preparing=true;buttons();try{await mic.connect($('micDevice').value,Number($('micGain').value));await devices();describeMic();}finally{preparing=false;buttons();}});
    $('micDevice').onchange=()=>{if(mic.context)safe(async()=>{await mic.connect($('micDevice').value,Number($('micGain').value));describeMic();});};
    $('micRefresh').onclick=()=>safe(devices);$('micDisable').onclick=()=>safe(async()=>{await mic.disconnect();describeMic();buttons();});
    $('micGain').oninput=()=>{mic.setGain($('micGain').value);$('micGainValue').value=$('micGain').value+' dB';};
    $('micTest').onclick=()=>safe(startTest);
    navigator.mediaDevices?.addEventListener?.('devicechange',()=>{if($('micDialog').open&&!mic.active)safe(devices);});
    $('closeNarration').onclick=()=>safe(close);$('narrationDialog').addEventListener('cancel',event=>{event.preventDefault();safe(close);});
    $('recordRange').onclick=()=>safe(()=>beginRecord(false));$('resumeNarration').onclick=()=>safe(()=>beginRecord(true));
    $('pauseNarration').onclick=()=>safe(()=>pauseTake());
    $('narrationCue').onchange=()=>{
      if($('narrationCue').value==='')return;const cue=session.cues[Number($('narrationCue').value)];
      $('recordStart').value=cfg.clock(cue.startMs,true);$('recordEnd').value=cfg.clock(cue.endMs,true);video().currentTime=cue.startMs/1000;
    };
    $('narrationGuide').onchange=()=>safe(async()=>{
      const id=$('narrationGuide').value;
      if(mixDirty&&!window.confirm(t('Discard unsaved mix settings and switch guide videos?'))){renderGuides();return;}
      try{await open(id);}catch(error){renderGuides();throw error;}
    });
    $('narrationClips').onclick=event=>{const button=event.target.closest('[data-rerecord]');if(!button)return;
      const clip=session.clips[Number(button.dataset.rerecord)];
      $('recordStart').value=cfg.clock(clip.startFrame/session.sampleRate*1000,true);$('recordEnd').value=cfg.clock(clip.endFrame/session.sampleRate*1000,true);
      video().currentTime=clip.startFrame/session.sampleRate;
    };
    $('undoNarration').onclick=()=>safe(async()=>{session=await request('/api/narration/'+session.id+'/undo',{method:'POST',body:{revision:session.revision}});mixDirty=false;renderSession(true);status('Previous narration restored.');});
    $('prepareNarrationMaster').onclick=()=>safe(async()=>{session=await request('/api/narration/'+session.id+'/master',{method:'POST',body:{revision:session.revision}});renderSession();});
    $('downloadNarrationMaster').onclick=()=>{$('enhancedBasisVersion').value=session.timelineRevision;$('enhancedVersionConfirm').checked=false;};
    $('enhancedFile').onchange=()=>safe(()=>enhance($('enhancedFile').files[0]));
    $('enhancedBasisVersion').oninput=()=>{mixDirty=true;};
    for(const id of ['mixMusic','mixVoice','narrationOffset','narrationAlignment']){
      $(id).oninput=()=>{mixDirty=true;if(id==='narrationOffset')$('narrationAlignment').checked=false;$('mixMusicValue').value=$('mixMusic').value+'%';$('mixVoiceValue').value=$('mixVoice').value+'%';playback();if(id==='narrationOffset')syncVoice(true);buttons();};
    }
    $('narrationListen').onchange=()=>{
      playback();
    };
    $('playNarrationPreview').onclick=playPreview;
    $('pauseNarrationPreview').onclick=()=>{video().pause();voice().pause();if(!previewError)previewStatus('Preview paused.');};
    $('saveNarrationMix').onclick=()=>safe(async()=>{await saveMix();status('Mix settings saved.');});
    $('queueNarrationFinal').onclick=()=>safe(async()=>{await saveMix();await request('/api/narration/'+session.id+'/render',{method:'POST',body:{revision:session.revision}});activeExport=true;buttons();status('Final mix queued. Start the Mac renderer when ready.');await cfg.jobsChanged();});
    $('narrationRecovery').onclick=event=>safe(async()=>{
      const recoverButton=event.target.closest('[data-recover]'),partial=event.target.closest('[data-partial]'),discard=event.target.closest('[data-discard]');
      if(recoverButton)await recover(recoverButton.dataset.recover);
      if(partial)await recover(partial.dataset.partial,true);
      if(discard&&window.confirm(t('Discard this unfinished take? Existing saved narration will remain.'))){
        await request('/api/recordings/'+discard.dataset.discard+'/discard',{method:'POST',body:{}});await spool.remove(discard.dataset.discard);
        await updateRecovery();await refreshRecoveryBadge();
      }
    });
    $('openRecordingRecovery').onclick=()=>safe(openRecovery);$('closeRecordingRecovery').onclick=()=>$('recordingRecoveryDialog').close();
    $('recordingRecoveryList').onclick=event=>{const button=event.target.closest('[data-recover-guide]');if(button){$('recordingRecoveryDialog').close();safe(()=>open(button.dataset.recoverGuide));}};
    $('jobList').addEventListener('click',event=>{const narrate=event.target.closest('[data-narrate]'),play=event.target.closest('[data-watch]');if(narrate)safe(()=>open(narrate.dataset.narrate));if(play)safe(()=>watch(play.dataset.watch));});
    $('closeWatch').onclick=()=>{$('watchVideo').pause();$('watchVideo').removeAttribute('src');$('watchDialog').close();};
    $('watchDialog').addEventListener('close',()=>{$('watchVideo').pause();$('watchVideo').removeAttribute('src');$('watchVideo').load();});
    video().addEventListener('play',()=>{cfg.pauseEditorAudio();syncVoice(true);});
    video().addEventListener('pause',()=>{voice().pause();if(recording)safe(()=>pauseTake());});
    video().addEventListener('seeking',()=>{if(recording)safe(()=>pauseTake('Playback position changed. Review the saved take before continuing.'));else syncVoice(true);});
    video().addEventListener('seeked',()=>syncVoice(true));video().addEventListener('timeupdate',tick);
    for(const event of ['waiting','stalled'])video().addEventListener(event,()=>{if(recording)safe(()=>pauseTake('Video playback was interrupted. Review the saved take before continuing.'));});
    video().addEventListener('ratechange',()=>{if(recording&&video().playbackRate!==1)safe(()=>pauseTake('Playback speed changed. Recording has been paused.'));else syncVoice(true);});
    video().addEventListener('ended',()=>{if(recording)safe(()=>pauseTake('Selected range recorded and saved.'));});
    video().addEventListener('error',()=>{if(recording)safe(()=>pauseTake());cfg.toast(t('The guide video could not play. Check your connection and reopen it.'),true);});
    voice().addEventListener('loadedmetadata',()=>syncVoice(true));
    for(const event of ['canplay','seeked'])voice().addEventListener(event,()=>syncVoice());
    voice().addEventListener('waiting',()=>{if(!recording&&!video().paused&&!previewError)previewStatus('Loading narration…');});
    voice().addEventListener('error',()=>{if(session&&voice().getAttribute('src')&&!recording)previewFailed(voice().error);});
    document.addEventListener('visibilitychange',()=>{if(document.hidden&&recording)safe(()=>pauseTake('Recording paused because the video is no longer visible.'));});
    window.addEventListener('pagehide',()=>safe(async()=>{if(recording)await pauseTake();await mic.disconnect();}));
    window.addEventListener('beforeunload',event=>{if(recording||stopping||hasPending){event.preventDefault();event.returnValue='';}});
    document.addEventListener('languagechange',()=>{status(statusKey,statusValues);describeMic();renderSession();previewStatus(previewKey,previewError);buttons();});
    buttons();
  }
  return {init,open,watch,authReady:()=>safe(refreshRecoveryBadge),isRecording:()=>recording||preparing||!!stopping,
    _test:()=>({mic,spool,get session(){return session;},beginRecord,pauseTake,saveMix,recover})};
})();

