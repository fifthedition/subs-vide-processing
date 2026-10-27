'use strict';
window.WorkspaceUX=(()=>{
  const $=id=>document.getElementById(id),t=(key,v)=>I18n.t(key,v),esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let cfg,baseline=new Map(),scriptBaseline='',draftTimer,loadGeneration=0,versionGeneration=0,selectedVersion=null,recovery=null,cuePlayback=null;
  const cueSignature=cue=>JSON.stringify([cue.text,cue.startMs,cue.endMs]);
  const projectSignature=p=>JSON.stringify([p.segments,p.cueOffsetMs]);
  const draftSignature=p=>JSON.stringify(['name','segments','cueOffsetMs','style','sourceId','musicId','reviewed','workflowMode','favorite','archived'].map(key=>p[key]??null));
  const accountKey=id=>location.origin+':'+(cfg.state.auth?.id||cfg.state.auth?.username||'local')+':'+id;
  const setText=(node,message)=>{if(node.textContent!==message)node.textContent=message;};
  class Drafts{
    async database(){
      if(this.db)return this.db;if(!window.indexedDB)throw new Error('Local draft recovery is unavailable in this browser.');
      if(!this.opening)this.opening=new Promise((resolve,reject)=>{const request=indexedDB.open('breathwork-script-drafts',1);request.onupgradeneeded=()=>request.result.createObjectStore('drafts',{keyPath:'key'});request.onsuccess=()=>{this.db=request.result;resolve(this.db);};request.onerror=()=>reject(request.error);request.onblocked=()=>reject(new Error('Local draft recovery is unavailable in this browser.'));});
      return this.opening;
    }
    async transaction(mode,action){const db=await this.database();return new Promise((resolve,reject)=>{const transaction=db.transaction('drafts',mode),request=action(transaction.objectStore('drafts'));transaction.oncomplete=()=>resolve(request.result);transaction.onerror=()=>reject(transaction.error);transaction.onabort=()=>reject(transaction.error);});}
    get(key){return this.transaction('readonly',s=>s.get(key));}
    put(value){return this.transaction('readwrite',s=>s.put(value));}
    remove(key){return this.transaction('readwrite',s=>s.delete(key));}
  }
  const drafts=new Drafts();
  function feedback(key,error=false,container){
    const dialog=container||document.activeElement?.closest('dialog[open]')||[...document.querySelectorAll('dialog[open]')].at(-1);
    if(!dialog)return false;
    let box=dialog.querySelector('.dialog-feedback');if(!box){box=document.createElement('p');box.className='dialog-feedback';box.setAttribute('role','status');dialog.querySelector('.dialog-heading')?.after(box);}
    box.textContent=t(key);box.classList.toggle('error',error);box.hidden=false;return true;
  }
  const perform=async(action,container)=>{try{return await action();}catch(error){if(!feedback(error.message,true,container))cfg.toast(error.message,true);}};
  function projectVisible(p){const query=$('sessionFilter')?.value||'active';return query==='all'||query==='archived'?query==='all'||p.archived:!p.archived&&(query!=='favorites'||p.favorite)&&(query!=='ready'||p.scriptReady);}
  function hideCue(cue){const filter=$('reviewFilter')?.value||'all',reviewed=cfg.state.project?.reviewed?.includes(cue.id);return filter==='reviewed'?!reviewed:filter==='unreviewed'?reviewed:false;}
  function decorateCues(){
    if(!cfg?.state.project)return;
    const p=cfg.state.project,textareas=[];
    for(const row of $('cueList').querySelectorAll('.cue-row')){
      const cue=p.segments.find(c=>c.id===row.dataset.id);if(!cue)continue;
      for(const [action,icon,key] of [['seek','play','Preview this cue'],['split','split','Split at the text cursor'],['merge','merge','Merge with next cue'],['delete','delete','Remove cue (Undo available)']])StudioIcons.button(row.querySelector('[data-action='+action+']'),icon,t(key));
      let label=row.querySelector('.cue-reviewed');
      if(!label){label=document.createElement('label');label.className='cue-reviewed';const check=document.createElement('input');check.type='checkbox';check.dataset.review=cue.id;label.append(check,document.createElement('span'));row.querySelector('.cue-time').append(label);}
      label.querySelector('input').checked=(p.reviewed||[]).includes(cue.id);label.querySelector('span').textContent=t('Reviewed');
      row.classList.toggle('reviewed',label.querySelector('input').checked);
      const body=row.querySelector('.cue-body'),tools=row.querySelector('.row-tools');
      if(tools&&tools.parentElement!==body)body.append(tools);
      if(tools){
        tools.setAttribute('role','toolbar');tools.setAttribute('aria-label',t('Subtitle actions'));
        const buttons=[...tools.querySelectorAll('button')],focused=buttons.indexOf(document.activeElement);
        buttons.forEach((button,index)=>button.tabIndex=index===Math.max(0,focused)?0:-1);
        tools.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)||event.altKey)return;event.preventDefault();const current=buttons.indexOf(document.activeElement),index=event.key==='Home'?0:event.key==='End'?buttons.length-1:(current+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons.forEach((button,n)=>button.tabIndex=n===index?0:-1);buttons[index].focus();};
      }
      const text=row.querySelector('textarea');text.style.height='auto';textareas.push(text);
      if(!text.parentElement.classList.contains('translation-cell')){const cell=document.createElement('div');cell.className='translation-cell';const heading=document.createElement('span');heading.className='translation-label';cell.append(heading);text.before(cell);cell.append(text);}
      text.parentElement.querySelector('.translation-label').textContent=t('Slovak translation');
      const reference=row.querySelector('.reference-text');if(reference)reference.dataset.label=t('Original reference');
      row.classList.toggle('bilingual',!!row.querySelector('.reference-text'));
    }
    const heights=textareas.map(text=>Math.max($('cueDensity').value==='compact'?62:88,text.scrollHeight+2));
    textareas.forEach((text,index)=>{text.style.height=heights[index]+'px';});
    updateSummary();
  }
  function updateSummary(){
    if(!cfg?.state.project)return;
    const p=cfg.state.project,count=(p.reviewed||[]).length;
    $('reviewProgress').textContent=t('{reviewed} of {total} reviewed',{reviewed:count,total:p.segments.length});
    $('markScriptReady').disabled=cfg.state.dirty||!p.segments.length||count!==p.segments.length;
    $('markScriptReady').textContent=t(p.scriptReady?'Script ready':'Mark script ready');
    StudioIcons.button($('favoriteSession'),'star',t(p.favorite?'Remove favorite':'Favorite session'));$('favoriteSession').setAttribute('aria-pressed',String(!!p.favorite));
    StudioIcons.button($('archiveSession'),'archive',t(p.archived?'Restore session':'Archive session'));
    $('workflowMode').value=p.workflowMode||'live';
    const jobs=cfg.state.jobs||[],guide=jobs.find(j=>j.status==='complete'&&j.kind!=='final'),final=jobs.find(j=>j.status==='complete'&&j.kind==='final');
    const narration=p.narrations?.find(n=>n.guideJobId===guide?.id),outdated=!!guide&&(guide.renderSignature?guide.renderSignature!==p.renderSignature:guide.revision!==p.revision);
    const finalCurrent=!!final&&!outdated&&final.guideJobId===guide?.id&&final.narrationId===narration?.id&&final.narrationRevision===narration?.timelineRevision;
    const steps=[['Script',p.scriptReady],['Guide video',!!guide&&!outdated]];
    if(p.workflowMode==='narrated')steps.push(['Narration',!!narration?.hasVoice],['Enhancement',!!narration?.enhancedIsCurrent],['Final export',finalCurrent]);
    $('workflowSteps').innerHTML=steps.map(([name,done])=>'<li class="'+(done?'done':'')+'">'+(done?StudioIcons.svg('check'):'<span class="step-dot"></span>')+esc(t(name))+'</li>').join('');
    const queued=jobs.find(j=>j.status==='queued'),rendering=jobs.find(j=>j.status==='rendering');
    setText($('workflowMessage'),queued?t('Waiting for the Mac renderer. Start it when you are ready.'):rendering?t('Rendering…'):outdated?t('Script or appearance has changed. Export a new guide when ready.'):!p.scriptReady?t('Review the Slovak script, then mark it ready.'):!guide?t('Script ready. Send the guide for export.'):p.workflowMode==='narrated'&&!narration?.hasVoice?t('Guide ready. Open narration to record your voice.'):p.workflowMode==='narrated'&&!narration?.enhancedIsCurrent?t('Prepare the WAV, enhance it in Adobe Podcast, then upload it.'):p.workflowMode==='narrated'&&!finalCurrent?t('Check alignment and send the final mix for export.'):t('Your session is ready.'));
    setText($('narrationPrerequisite'),outdated?t('The guide uses an earlier script or appearance. Export a new guide to record your latest edits.'):guide?t('A completed guide is ready for recording.'):t('Render a guide video before recording narration.'));
    $('openLatestNarration').disabled=!guide;$('queueGuideFromNarration').hidden=!!guide&&!outdated;
    setText($('exportQueueHint'),queued?t('Waiting for the Mac renderer. Start it when you are ready.') : '');
    $('viewExports').dataset.count=String(jobs.filter(j=>j.status==='queued'||j.status==='rendering').length);
  }
  async function persistDraft(){
    if(!cfg.state.dirty||!cfg.state.project)return;
    const p=JSON.parse(JSON.stringify(cfg.state.project)),key=accountKey(p.id),generation=cfg.state.generation;
    delete p.music;delete p.narrations;
    const invalid=[...$('cueList').querySelectorAll('.invalid input[data-field]')].map(el=>({id:el.closest('.cue-row').dataset.id,field:el.dataset.field,value:el.value}));
    try{await drafts.put({key,project:p,invalid,generation,updatedAt:new Date().toISOString()});}
    catch{$('draftRecoveryBanner').hidden=false;$('draftRecoveryBanner').textContent=t('Local draft recovery is unavailable. Keep this page open until changes are saved.');}
  }
  function changed(){
    if(!cfg?.state.project)return;
    const p=cfg.state.project;
    p.reviewed=(p.reviewed||[]).filter(id=>{const c=p.segments.find(c=>c.id===id);return c&&baseline.get(id)===cueSignature(c);});
    if(projectSignature(p)!==scriptBaseline||p.reviewed.length!==p.segments.length)p.scriptReady=false;
    clearTimeout(draftTimer);draftTimer=setTimeout(persistDraft,200);updateSummary();
    for(const row of $('cueList').querySelectorAll('.cue-row')){const input=row.querySelector('[data-review]');if(input)input.checked=p.reviewed.includes(row.dataset.id);}
  }
  async function saved(result,generation){
    if(!cfg?.state.project||cfg.state.project.id!==result.id)return;
    if(generation===cfg.state.generation){
      for(const key of ['reviewed','scriptReady','readyRevision','readyBy','readySignature','renderSignature','favorite','archived','workflowMode'])if(result[key]!==undefined)cfg.state.project[key]=result[key];
      baseline=new Map(result.segments.map(c=>[c.id,cueSignature(c)]));scriptBaseline=projectSignature(result);
      const summary=cfg.state.projects.find(p=>p.id===result.id);if(summary)Object.assign(summary,{favorite:result.favorite,archived:result.archived,scriptReady:result.scriptReady});
      try{const key=accountKey(result.id),draft=await drafts.get(key);if(!cfg.state.dirty&&(!draft||draft.generation<=generation))await drafts.remove(key);}catch{}
      updateSummary();
    }
  }
  async function loaded({skipRecovery=false}={}){
    if(!cfg?.state.project)return;
    const p=cfg.state.project,generation=++loadGeneration;
    p.reviewed||=[];p.narrations||=[];baseline=new Map(p.segments.map(c=>[c.id,cueSignature(c)]));scriptBaseline=projectSignature(p);
    if(p.archived&&$('sessionFilter').value==='active'){$('sessionFilter').value='archived';cfg.renderProjects();}
    $('draftRecoveryBanner').hidden=true;$('musicDetails').open=!p.music;$('musicSummary').textContent=p.music?.name||t('Add your music-only track');decorateCues();updateSummary();
    if(skipRecovery)return;
    try{const draft=await drafts.get(accountKey(p.id));if(generation!==loadGeneration||!draft)return;
      if(draftSignature(draft.project)===draftSignature(p)&&!draft.invalid?.length){await drafts.remove(draft.key);return;}
      recovery=draft;
      const banner=$('draftRecoveryBanner');banner.hidden=false;banner.textContent=t('Unfinished subtitle edits were found in this browser.');
      const button=document.createElement('button');button.className='button outline';button.textContent=t('Review recovered draft');button.onclick=()=>openRecovery(draft);banner.append(' ',button);
    }catch{}
  }
  function setView(view){
    document.querySelector('main.workspace').dataset.view=view;
    for(const name of ['Script','Narration','Exports'])$('view'+name).setAttribute('aria-pressed',String(name.toLowerCase()===view));
    $('narrationWorkspace').hidden=view!=='narration';$('exportsWorkspace').hidden=view!=='exports';
    if(view!=='script'){cfg.audio.pause();$('referenceAudio').pause();}
  }
  function navigate(step){
    const p=cfg.state.project;if(!p)return;
    const index=p.segments.findIndex(c=>c.id===cfg.state.selected),next=p.segments[Math.max(0,Math.min(p.segments.length-1,index+step))];
    if(!next)return;cfg.selectCue(next.id,true);$('cueList').querySelector('[data-id="'+CSS.escape(next.id)+'"]')?.scrollIntoView({block:'nearest'});
  }
  async function review(id,checked){
    await cfg.flushSave();const p=cfg.state.project;
    if(!p.segments.some(c=>c.id===id))return;
    p.reviewed=[...new Set(checked?[...(p.reviewed||[]),id]:(p.reviewed||[]).filter(value=>value!==id))];
    cfg.markDirty();await cfg.flushSave();decorateCues();
  }
  function nudge(amount){
    const p=cfg.state.project,cue=p?.segments.find(c=>c.id===cfg.state.selected);if(!cue)return;
    const before=JSON.parse(JSON.stringify(p.segments));
    const old={...cue};cue.startMs+=amount;cue.endMs+=amount;
    if(cfg.validateDraft()||cue.startMs<0||(p.music&&cue.endMs+p.cueOffsetMs>p.music.durationMs)){Object.assign(cue,old);cfg.toast(t('This timing adjustment would overlap another subtitle or leave the music range.'),true);return;}
    cfg.pushUndo(before);cfg.markDirty();cfg.renderCues();cfg.selectCue(cue.id,true);
  }
  function playCue(cue){if(!cfg.state.project.music)return;cuePlayback={start:cue.startMs+cfg.state.project.cueOffsetMs,end:cue.endMs+cfg.state.project.cueOffsetMs};cfg.audio.play().catch(error=>cfg.toast(error.message,true));}
  function openRecovery(draft){recovery=draft;$('conflictMessage').textContent=t('Your local text is retained. Save it as a separate session, download it, or open the saved NAS version.');$('conflictError').hidden=true;$('conflictDialog').showModal();}
  async function conflict(project){await persistDraft();let draft;try{draft=await drafts.get(accountKey(project.id));}catch{}openRecovery(draft||{key:accountKey(project.id),project:JSON.parse(JSON.stringify(project))});}
  function downloadDraft(){const blob=new Blob([JSON.stringify({...recovery.project,recoveredInputs:recovery.invalid||[]},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='recovered-subtitles.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  async function openVersions(){
    await cfg.flushSave();selectedVersion=null;$('versionComparison').textContent='';$('restoreVersion').disabled=true;$('versionsError').hidden=true;$('versionsDialog').showModal();
    const list=await cfg.api('/api/projects/'+cfg.state.project.id+'/versions');
    $('versionList').innerHTML=list.map(v=>'<button class="version-choice" data-version="'+v.revision+'"><strong>'+esc(t('Revision {revision}',{revision:v.revision}))+'</strong><span>'+esc(new Date(v.created).toLocaleString(I18n.locale))+'</span><small data-user-text>'+esc(v.actor)+'</small><small>'+esc(t(v.label))+'</small></button>').join('');
  }
  async function previewVersion(revision){
    const generation=++versionGeneration,p=cfg.state.project,result=await cfg.api('/api/projects/'+p.id+'/versions/'+revision);if(cfg.state.project.id!==p.id||generation!==versionGeneration)return;selectedVersion=result;
    const old=new Map(result.segments.map(c=>[c.id,c])),current=new Map(p.segments.map(c=>[c.id,c]));
    let changed=[...new Set([...old.keys(),...current.keys()])].filter(id=>JSON.stringify(old.get(id))!==JSON.stringify(current.get(id)));
    const fields=['name','cueOffsetMs','style','musicId'];const settings=fields.some(key=>JSON.stringify(p[key])!==JSON.stringify(result[key]));
    $('versionComparison').innerHTML='<h3>'+esc(t('Revision {revision}',{revision}))+' · '+esc(t('Compare with current script'))+'</h3><p>'+esc(t('{count} subtitle differences',{count:changed.length}))+(settings?' · '+esc(t('Session settings also differ.')):'')+'</p>'+changed.map(id=>'<div class="version-difference"><div><strong>'+esc(t('Saved version'))+'</strong><p data-user-text>'+esc(old.get(id)?.text||'—')+'</p><small>'+(old.has(id)?esc(cfg.clock(old.get(id).startMs,true)+' – '+cfg.clock(old.get(id).endMs,true)):'')+'</small></div><div><strong>'+esc(t('Current version'))+'</strong><p data-user-text>'+esc(current.get(id)?.text||'—')+'</p><small>'+(current.has(id)?esc(cfg.clock(current.get(id).startMs,true)+' – '+cfg.clock(current.get(id).endMs,true)):'')+'</small></div></div>').join('');
    $('restoreVersion').disabled=revision===p.revision;
  }
  async function refreshNarrations(){const p=cfg.state.project;if(!p)return;try{const result=await cfg.api('/api/projects/'+p.id+'/narrations');if(cfg.state.project?.id===p.id){p.narrations=result;updateSummary();}}catch{}}
  function visibleJobs(jobs){if($('showAllExports')?.checked)return jobs;const guide=jobs.find(j=>j.kind!=='final'&&j.status==='complete'),final=jobs.find(j=>j.kind==='final'&&j.status==='complete');return jobs.filter(j=>j===guide||j===final||j.status!=='complete');}
  function jobLabel(job){const p=cfg.state.project,isOld=job.status==='complete'&&(job.renderSignature?job.renderSignature!==p.renderSignature:job.revision!==p.revision);return '<span class="export-kind">'+esc(t(job.kind==='final'?'Final mix':'Guide video'))+'</span>'+(isOld?'<span class="export-stale">'+esc(t('Script or appearance has changed'))+'</span>':'');}
  function init(options){
    cfg=options;
    cfg.audio.addEventListener('timeupdate',()=>{if(cuePlayback&&cfg.audio.currentTime*1000>=cuePlayback.end){cfg.audio.pause();cuePlayback=null;}});
    cfg.audio.addEventListener('seeking',()=>{if(cuePlayback&&(cfg.audio.currentTime*1000<cuePlayback.start-50||cfg.audio.currentTime*1000>cuePlayback.end+50))cuePlayback=null;});
    for(const [id,name,key] of [['previousCue','previous','Previous subtitle'],['nextCue','next','Next subtitle']])StudioIcons.button($(id),name,t(key));
    try{$('cueDensity').value=localStorage.getItem('breathwork-cue-density')||'comfortable';}catch{}
    document.querySelector('.editor-panel').dataset.density=$('cueDensity').value;
    $('cueDensity').onchange=()=>{document.querySelector('.editor-panel').dataset.density=$('cueDensity').value;try{localStorage.setItem('breathwork-cue-density',$('cueDensity').value);}catch{}decorateCues();};
    $('reviewFilter').onchange=cfg.renderCues;$('sessionFilter').onchange=cfg.renderProjects;
    $('previousCue').onclick=()=>navigate(-1);$('nextCue').onclick=()=>navigate(1);$('cueEarlier').onclick=()=>nudge(-100);$('cueLater').onclick=()=>nudge(100);
    $('jumpToCue').onclick=()=>{const p=cfg.state.project,value=$('jumpCue').value.trim();if(!p)return;perform(async()=>{let cue;if(/^\d+$/.test(value)){cue=p.segments[Number(value)-1];if(!cue)throw new Error('Choose an existing subtitle number or time.');cfg.selectCue(cue.id,true);}else{const at=cfg.parseClock(value);if(at>cfg.totalDuration())throw new Error('Choose an existing subtitle number or time.');cfg.seekTo(at);cue=p.segments.find(c=>c.endMs+p.cueOffsetMs>=at)||p.segments.at(-1);if(cue)cfg.selectCue(cue.id,false);}if(cue)$('cueList').querySelector('[data-id="'+CSS.escape(cue.id)+'"]')?.scrollIntoView({block:'nearest'});});};
    $('jumpCue').addEventListener('keydown',event=>{if(event.key==='Enter'){$('jumpToCue').click();event.preventDefault();}});
    for(const view of ['Script','Narration','Exports'])$('view'+view).onclick=()=>setView(view.toLowerCase());
    $('openLatestNarration').onclick=()=>perform(async()=>{const guide=cfg.state.jobs.find(j=>j.status==='complete'&&j.kind!=='final');if(guide)await window.NarrationStudio.open(guide.id);});
    $('queueGuideFromNarration').onclick=()=>$('exportVideo').click();
    $('favoriteSession').onclick=()=>perform(async()=>{cfg.state.project.favorite=!cfg.state.project.favorite;cfg.markDirty();await cfg.flushSave();cfg.renderProjects();updateSummary();});
    $('archiveSession').onclick=()=>perform(async()=>{cfg.state.project.archived=!cfg.state.project.archived;cfg.markDirty();await cfg.flushSave();cfg.renderProjects();updateSummary();});
    $('workflowMode').onchange=()=>{cfg.state.project.workflowMode=$('workflowMode').value;cfg.markDirty();updateSummary();};
    $('markScriptReady').onclick=()=>perform(async()=>{await cfg.flushSave();const p=cfg.state.project,result=await cfg.api('/api/projects/'+p.id+'/ready',{method:'POST',body:{revision:p.revision}});Object.assign(p,result);await saved(result,cfg.state.generation);cfg.renderProjects();updateSummary();});
    $('markShownReviewed').onclick=()=>perform(async()=>{await cfg.flushSave();const ids=[...$('cueList').querySelectorAll('.cue-row')].map(row=>row.dataset.id);if(!ids.length)return;if(!window.confirm(t('Mark the {count} shown subtitles as reviewed?',{count:ids.length})))return;cfg.state.project.reviewed=[...new Set([...(cfg.state.project.reviewed||[]),...ids])];cfg.markDirty();await cfg.flushSave();cfg.renderCues();});
    $('cueList').addEventListener('change',event=>{const id=event.target.dataset.review;if(id)perform(()=>review(id,event.target.checked));});
    $('cueList').addEventListener('input',event=>{if(event.target.matches('textarea')){event.target.style.height='auto';event.target.style.height=Math.max($('cueDensity').value==='compact'?62:88,event.target.scrollHeight+2)+'px';}});
    $('showAllExports').onchange=cfg.loadJobs;
    $('openVersions').onclick=()=>perform(openVersions,$('versionsDialog'));$('closeVersions').onclick=()=>$('versionsDialog').close();
    $('versionList').onclick=event=>{const button=event.target.closest('[data-version]');if(button)perform(()=>previewVersion(Number(button.dataset.version)),$('versionsDialog'));};
    $('restoreVersion').onclick=()=>perform(async()=>{if(!selectedVersion)return;if(!window.confirm(t('Restore this script as a new version? Your current script remains in history.')))return;const p=cfg.state.project;await cfg.api('/api/projects/'+p.id+'/restore',{method:'POST',body:{revision:p.revision,version:selectedVersion.revision}});$('versionsDialog').close();await cfg.loadProject(p.id,true);},$('versionsDialog'));
    $('closeConflict').onclick=()=>$('conflictDialog').close();$('downloadLocalDraft').onclick=downloadDraft;
    $('recoverDraftCopy').onclick=()=>perform(async()=>{const draft=recovery,p=draft.project,result=await cfg.api('/api/projects/'+p.id+'/recover',{method:'POST',body:{draft:p}});$('conflictDialog').close();cfg.state.projects=await cfg.api('/api/projects');await cfg.loadProject(result.id,true);for(const entry of draft.invalid||[]){if(!['startMs','endMs'].includes(entry.field))continue;const input=$('cueList').querySelector('[data-id="'+CSS.escape(entry.id)+'"] input[data-field="'+entry.field+'"]');if(input){input.value=entry.value;input.dispatchEvent(new Event('input',{bubbles:true}));}}if(draft.invalid?.length)cfg.markDirty();},$('conflictDialog'));
    $('reloadServerVersion').onclick=()=>perform(async()=>{if(!recovery)return;const id=recovery.project.id;$('conflictDialog').close();await cfg.loadProject(id,true);},$('conflictDialog'));
    $('openShortcuts').onclick=()=>$('shortcutsDialog').showModal();$('closeShortcuts').onclick=()=>$('shortcutsDialog').close();
    $('closeStorage').onclick=()=>$('storageDialog').close();$('openStorage').onclick=()=>perform(async()=>{
      $('storageDialog').showModal();$('storageContent').textContent=t('Loading…');const s=await cfg.api('/api/admin/storage'),size=value=>(value/1024**3).toLocaleString(I18n.locale,{maximumFractionDigits:2})+' GB';
      $('storageContent').innerHTML='<p>'+esc(t('{free} free of {total}',{free:size(s.freeBytes),total:size(s.totalBytes)}))+'</p><div class="storage-groups">'+s.groups.map(g=>'<div><strong>'+esc(t(({media:'Media files',exports:'Exports',recordings:'Original recording data','narration-masters':'Narration WAV masters',waveforms:'Waveform previews',uploads:'Audio uploads','render-uploads':'Video upload data'})[g.name]||g.name))+'</strong><span>'+esc(size(g.bytes))+' · '+g.files+'</span></div>').join('')+'</div><h3>'+esc(t('Media files'))+'</h3>'+s.assets.map(a=>'<div class="storage-asset"><strong data-user-text>'+esc(a.name)+'</strong><span>'+esc(size(a.bytes))+'</span><small data-user-text>'+esc(a.usedBy.join(', ')||t('Retained original or earlier version'))+'</small></div>').join('');
    },$('storageDialog'));
    document.addEventListener('keydown',event=>{
      if(document.querySelector('dialog[open]')||!cfg.state.project)return;
      if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();perform(()=>review(cfg.state.selected,true));return;}
      if(event.target.closest('input,textarea,select,[contenteditable=true]'))return;
      if(event.altKey&&['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();if(event.key==='ArrowUp')navigate(-1);if(event.key==='ArrowDown')navigate(1);if(event.key==='ArrowLeft')nudge(-100);if(event.key==='ArrowRight')nudge(100);}
    });
    document.addEventListener('languagechange',()=>{decorateCues();updateSummary();});
    window.addEventListener('pagehide',()=>{persistDraft();drafts.db?.close();drafts.db=null;drafts.opening=null;});
  }
  function accountReady(){if(cfg?.state.auth)$('openStorage').hidden=!cfg.state.auth.remote||cfg.state.auth.role!=='owner';}
  return {init,loaded,changed,saved,decorateCues,projectVisible,hideCue,visibleJobs,jobLabel,feedback,conflict,accountReady,playCue,jobsChanged:()=>{updateSummary();refreshNarrations();},_test:()=>({drafts,review,nudge,setView,persistDraft,previewVersion,get recovery(){return recovery;}})};
})();
