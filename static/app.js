'use strict';
const t = I18n.t;
const $ = id => document.getElementById(id);
const state = {auth: null, projects: [], catalog: [], project: null, reference: [], selected: null, dirty: false, generation: 0,
  savePromise: null, saveTimer: null, undo: [], invalid: new Set(), previewMs: 0, signature: '', jobs: [], presenter: false};
const audio = $('audio');
let toastTimer;
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clone = value => JSON.parse(JSON.stringify(value));

async function api(path, options = {}) {
  const headers={'X-CSRF-Token':state.auth?.csrf||'',...options.headers};
  const response = await fetch(path, options.body && !(options.body instanceof Blob) ? {...options, headers: {'Content-Type':'application/json', ...headers}, body: JSON.stringify(options.body)} : {...options,headers});
  const data = await response.json();
  if (!response.ok) throw new Error(t(data.error || 'The request could not be completed.'));
  return data;
}
function toast(message, error = false) {
  $('toast').textContent = t(message); $('toast').classList.toggle('error', error); $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, error ? 7500 : 3500);
}
function clock(ms, precise = false) {
  ms = Math.max(0, Math.round(ms));
  const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, s = Math.floor(ms / 1000) % 60;
  if (precise) return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}.${String(ms % 1000).padStart(3,'0')}`;
  return `${h ? String(h).padStart(2,'0') + ':' : ''}${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}
function parseClock(text) {
  const m = text.trim().match(/^(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?$/);
  if (!m || +m[2] > 59 || +m[3] > 59) throw new Error(t('Use HH:MM:SS.mmm for cue times.'));
  return ((+(m[1] || 0) * 60 + +m[2]) * 60 + +m[3]) * 1000 + +(m[4] || '').padEnd(3,'0');
}
function prettyName(name) {
  return name.replace(/^V\d+\s*/, '').replace(/\b\w+/g, word => word[0] + word.slice(1).toLowerCase());
}
function totalDuration() {
  return state.project?.music?.durationMs || Math.max(1, ...(state.project?.segments || []).map(s => s.endMs + state.project.cueOffsetMs));
}
function currentMs() { return state.project?.music && audio.readyState >= 1 ? (audio.ended ? totalDuration() : audio.currentTime * 1000) : state.previewMs; }
function showValidation(message) { $('validation').hidden = !message; $('validation').textContent = t(message || ''); }
function validateDraft() {
  if (state.invalid.size) return t('Correct the highlighted cue time before your changes can be saved.');
  const cues = [...state.project.segments].sort((a,b) => a.startMs - b.startMs);
  for (let i = 0; i < cues.length; i++) {
    if (cues[i].startMs < 0 || cues[i].endMs <= cues[i].startMs) return t('Cue {number} needs an end time later than its start.', {number:i+1});
    if (i && cues[i].startMs < cues[i-1].endMs) return t('Cues {first} and {second} overlap. Adjust their times.', {first:i,second:i+1});
  }
  return '';
}
function saveLabel(text, kind = '') { $('saveState').textContent = t(text); $('saveState').className = 'save-state ' + kind; }
function markDirty() {
  state.dirty = true; state.generation++; saveLabel(t('Unsaved changes'), 'dirty');
  const error = validateDraft(); showValidation(error);
  clearTimeout(state.saveTimer);
  if (!error) state.saveTimer = setTimeout(() => flushSave().catch(() => {}), 900);
}
async function flushSave() {
  clearTimeout(state.saveTimer);
  if (state.savePromise) { await state.savePromise; if (state.dirty) return flushSave(); return; }
  if (!state.project) return;
  const error = validateDraft();
  if (error) { showValidation(error); throw new Error(error); }
  if (!state.dirty) return;
  state.savePromise = (async () => {
    while (state.dirty) {
      const validation = validateDraft();
      if (validation) throw new Error(validation);
      const generation = state.generation, payload = clone(state.project);
      delete payload.music;
      saveLabel(t('Saving…'));
      try {
        const saved = await api('/api/projects/' + payload.id, {method:'PUT', body:payload});
        state.project.revision = saved.revision; state.project.updatedAt = saved.updatedAt;
        if (generation === state.generation) state.dirty = false;
        saveLabel(state.dirty ? t('Saving…') : t('Saved'));
        const summary = state.projects.find(p => p.id === saved.id);
        if (summary) Object.assign(summary, {name:saved.name, revision:saved.revision, count:saved.segments.length, musicId:saved.musicId});
      } catch (error) { saveLabel(t('Save needs attention'), 'error'); showValidation(error.message); throw error; }
    }
    renderProjects();
  })();
  try { await state.savePromise; } finally { state.savePromise = null; }
}
function pushUndo() { state.undo.push(clone(state.project.segments)); if (state.undo.length > 50) state.undo.shift(); $('undo').disabled = false; }
function backupDraft() {
  const blob = new Blob([JSON.stringify(state.project, null, 2)], {type:'application/json'});
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = (state.project.name || 'session') + '.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
function renderProjects() {
  const query = $('sessionSearch').value.toLowerCase();
  $('sessionCount').textContent = state.projects.length;
  $('projectList').innerHTML = state.projects.filter(p => p.name.toLowerCase().includes(query)).map(p => `<button class="project-item ${p.id === state.project?.id ? 'selected' : ''}" data-project="${p.id}"><span class="project-symbol" aria-hidden="true">${p.musicId ? '♫' : '◇'}</span><span><span class="project-name" data-user-text>${escapeHTML(p.name)}</span><span class="project-meta">${escapeHTML(t('{count} cues',{count:p.count}))} · ${clock(p.endMs)}${p.musicId ? ' · '+t('Music added') : ''}</span></span></button>`).join('') || '<p class="empty-list">No matching sessions.</p>';
  I18n.apply($('projectList'));
}
async function loadReference() {
  if (!state.project.sourceId) { state.reference = state.project.reference?.segments || []; return; }
  const doc = await api('/api/archive/' + state.project.sourceId);
  state.reference = doc.segments.map(s => ({startMs:parseClock(s.from_time), endMs:parseClock(s.to_time), text:s.text}));
}
async function loadProject(id) {
  if(window.NarrationStudio?.isRecording()){toast(t('Pause and save the current recording first.'),true);return;}
  try {
    await flushSave(); audio.pause(); $('referenceAudio').pause();
    state.project = await api('/api/projects/' + id); state.previewMs = 0; state.selected = state.project.segments[0]?.id;
    document.querySelectorAll('.workspace input,.workspace button,.workspace select').forEach(element=>element.disabled=false);
    state.project.style.layout ||= 'teleprompter';
    state.undo = []; state.invalid.clear(); state.signature = ''; state.dirty = false; $('undo').disabled = true;
    await loadReference();
    $('projectName').value = state.project.name;
    const meta = state.catalog.find(d => String(d.id) === String(state.project.archiveId));
    $('sessionDescription').textContent = state.project.reference ? t('Slovak draft · review each cue against the original before guiding live.') : meta ? t('From {name} · your own editable session',{name:meta.name}) : t('Slovak prompts. Your music. Your guidance.');
    $('sourceSelect').innerHTML = `<option value="" data-user-text>${escapeHTML(state.project.reference?.name || t('No reference'))}</option>` + state.catalog.map(d => `<option value="${d.id}" data-user-text>${escapeHTML(d.name)}</option>`).join('');
    $('sourceSelect').value = state.project.sourceId || '';
    $('showReference').checked = Boolean(state.project.reference);
    const sourceMedia = state.project.reference?.mediaId;
    $('sourceReview').hidden = !sourceMedia;
    if (sourceMedia) $('referenceAudio').src = '/media/' + sourceMedia; else $('referenceAudio').removeAttribute('src');
    $('fontSize').value = state.project.style.fontSize; $('fontSizeValue').textContent = state.project.style.fontSize;
    $('resolution').value = state.project.style.width; $('cueOffset').value = state.project.cueOffsetMs / 1000;
    $('videoLayout').value = state.project.style.layout;
    updateThemes(); configureMusic(); renderProjects(); renderCues(); showValidation(''); saveLabel(t('Saved'));
    try { localStorage.setItem('breathwork-last-project', id); } catch {}
    $('sidebar').classList.remove('open'); await loadJobs(); tick();
  } catch (error) { toast(error.message, true); }
}
function configureMusic(reload = true) {
  const music = state.project.music;
  $('musicName').textContent = music?.name || t('Add your music-only track');
  $('musicDescription').textContent = music ? `${clock(music.durationMs)} · ${music.channels === 2 ? t('Stereo') : t('{count} channel(s)',{count:music.channels})}${music.sampleRate ? ' · '+(music.sampleRate/1000)+' kHz' : ''} · ${Math.round(music.bytes/1024/1024*10)/10} MB` : t('Drop an MP3, WAV, or M4A here to bring this session to life.');
  $('chooseMusic').textContent = music ? t('Replace music') : t('Choose music ＋'); $('playPause').disabled = !music;
  if (!reload) return;
  if (music) { audio.src = '/media/' + music.id; audio.load(); $('timelineHint').textContent = t('Music and prompts share one timeline'); showWaveform(music.id); }
  else { audio.removeAttribute('src'); audio.load(); $('waveform').hidden = true; $('timelineHint').textContent = t('Preview prompts before adding music'); }
}
function showWaveform(id, retry = 0) {
  const image = $('waveform');
  image.onload = () => { if (state.project?.music?.id === id) image.hidden = false; };
  image.onerror = () => { image.hidden = true; if (retry < 8) setTimeout(() => { if (state.project?.music?.id === id) showWaveform(id, retry+1); }, 2000); };
  image.src = `/media/${id}/waveform.png?try=${retry}`;
}
function referenceFor(cue) {
  let found, best = 0;
  for (const source of state.reference) { const overlap = Math.max(0, Math.min(cue.endMs, source.endMs) - Math.max(cue.startMs, source.startMs)); if (overlap > best) { best = overlap; found = source; } }
  return found?.text || '';
}
function renderCues() {
  if (!state.project) return;
  const query = $('cueSearch').value.toLowerCase(), showReference = $('showReference').checked;
  $('cueCount').textContent = t('{count} cues',{count:state.project.segments.length});
  $('cueList').innerHTML = state.project.segments.map((cue,index) => {
    if (query && !cue.text.toLowerCase().includes(query)) return '';
    return `<article class="cue-row ${cue.id === state.selected ? 'selected' : ''}" data-id="${escapeHTML(cue.id)}"><div class="cue-time"><div class="cue-number"><span class="dot"></span>${String(index+1).padStart(2,'0')}<span class="editing-label">Editing</span></div><input data-field="startMs" aria-label="Cue ${index+1} start time" value="${clock(cue.startMs,true)}"><span class="time-divider">—</span><input data-field="endMs" aria-label="Cue ${index+1} end time" value="${clock(cue.endMs,true)}"></div><div class="cue-body">${showReference ? `<div class="reference-text" data-user-text>${escapeHTML(referenceFor(cue)) || t('No matching reference cue')}</div>` : ''}<textarea class="cue-text" aria-label="Cue ${index+1} Slovak text" spellcheck="true" lang="sk">${escapeHTML(cue.text)}</textarea></div><div class="row-tools"><button data-action="seek" title="Preview this cue" aria-label="Preview cue ${index+1}">▷</button><button data-action="split" title="Split at the text cursor" aria-label="Split cue ${index+1}">⋮</button><button data-action="merge" title="Merge with next cue" aria-label="Merge cue ${index+1} with next">⊕</button><button data-action="delete" title="Remove cue (Undo available)" aria-label="Remove cue ${index+1}">×</button></div></article>`;
  }).join('') || '<div class="empty-list">No prompts match your search.</div>';
  I18n.apply($('cueList')); tick();
}
function selectCue(id, seek = false) {
  state.selected = id;
  document.querySelectorAll('.cue-row').forEach(row => row.classList.toggle('selected', row.dataset.id === id));
  if (seek) {
    const cue = state.project.segments.find(s => s.id === id);
    seekTo(Math.max(0, cue.startMs + state.project.cueOffsetMs + 1));
  }
}
function seekTo(ms) {
  ms = Math.max(0, Math.min(totalDuration(), ms));
  if (state.project.music && audio.readyState >= 1) audio.currentTime = ms / 1000;
  else state.previewMs = ms;
  state.signature = ''; tick();
}
function cueAt(ms) {
  const shifted = ms - state.project.cueOffsetMs;
  const cues = state.project.segments;
  let lo = 0, hi = cues.length - 1, before = -1;
  while (lo <= hi) { const mid = (lo+hi)>>1; if (cues[mid].startMs <= shifted) { before = mid; lo = mid+1; } else hi = mid-1; }
  const index = before >= 0 && cues[before].endMs > shifted ? before : -1;
  return {index, next:index >= 0 ? index+1 : before+1, previous:index >= 0 ? index-1 : before};
}
function wrapCanvas(ctx, text, maxWidth) {
  const lines = [];
  for (const paragraph of text.split('\n')) {
    if (!paragraph.trim()) { lines.push(''); continue; }
    let line = '';
    for (const word of paragraph.trim().split(/\s+/)) {
      const candidate = (line + ' ' + word).trim();
      if (ctx.measureText(candidate).width <= maxWidth) { line = candidate; continue; }
      if (line) { lines.push(line); line = ''; }
      for (const letter of word) { if (line && ctx.measureText(line+letter).width > maxWidth) { lines.push(line); line=''; } line += letter; }
    }
    if (line) lines.push(line);
  }
  return lines.length ? lines : [''];
}
function drawPreview(text) {
  const canvas = $('previewCanvas'), ctx = canvas.getContext('2d'), style = state.project.style;
  canvas.width = style.width; canvas.height = style.height;
  ctx.fillStyle = style.background; ctx.fillRect(0,0,canvas.width,canvas.height);
  let size = Math.round(style.fontSize * canvas.width / 1920), lines, lineHeight;
  do { ctx.font = `400 ${size}px Inter`; lines = wrapCanvas(ctx,text,canvas.width*.82); lineHeight=Math.round(size*1.42); if(lines.length*lineHeight <= canvas.height*.76 || size <= 14) break; size--; } while(true);
  ctx.fillStyle = style.color; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
  const top = (canvas.height - lines.length * lineHeight)/2;
  lines.forEach((line,index) => ctx.fillText(line, canvas.width/2, top+index*lineHeight));
}
function tick() {
  if (!state.project) return;
  const ms = currentMs(), total = totalDuration(), {index,next} = cueAt(ms);
  const cue = state.project.segments[index], upcoming = state.project.segments[next];
  $('currentTime').textContent = clock(ms); $('totalTime').textContent = clock(total); $('remainingTime').textContent = clock(Math.ceil(Math.max(0,total-ms)/1000)*1000); $('seek').value = Math.round(ms/total*1000); $('seekFill').style.width = Math.min(100,ms/total*100)+'%';
  $('previewStatus').textContent = cue ? t('CURRENT PROMPT') : t('MUSIC · SPACE TO BREATHE');
  $('previewCueTime').textContent = cue ? `${clock(cue.startMs+state.project.cueOffsetMs)} — ${clock(cue.endMs+state.project.cueOffsetMs)}` : '';
  $('nextText').textContent = upcoming?.text || t('The final prompt. Let the music finish.');
  $('nextCountdown').textContent = upcoming ? t('in {seconds} sec',{seconds:Math.max(0,Math.ceil((upcoming.startMs+state.project.cueOffsetMs-ms)/1000))}) : '';
  const presenter=Teleprompter.snapshot(state.project,ms,total),teleprompter=state.project.style.layout==='teleprompter';
  const signature = JSON.stringify([state.project.style,state.project.name,teleprompter?presenter:null,
    teleprompter?[presenter.previous,presenter.current,presenter.next].map(i=>state.project.segments[i]?.text):cue?.text||'']);
  if (state.signature !== signature) { if(teleprompter)Teleprompter.draw($('previewCanvas'),state.project,presenter);else drawPreview(cue?.text||''); state.signature = signature; }
  document.querySelectorAll('.cue-row').forEach(row => row.classList.toggle('playing', row.dataset.id === cue?.id));
  $('playPause').textContent = audio.paused ? '▶' : 'Ⅱ'; $('playPause').setAttribute('aria-label', audio.paused ? t('Play music') : t('Pause music'));
}
function playLoop() { tick(); if (!audio.paused) requestAnimationFrame(playLoop); }
async function togglePlay() {
  if (!state.project?.music) { toast(t('Add your music-only track to play the session.')); return; }
  try { if (audio.paused) { $('referenceAudio').pause(); await audio.play(); } else audio.pause(); } catch { toast(t('This browser cannot play that audio format. Try an MP3 or M4A.'), true); }
}
async function uploadMusic(file) {
  if (!file || !state.project) return;
  const projectId = state.project.id;
  try {
    await flushSave(); $('chooseMusic').disabled = true; $('chooseMusic').textContent = t('Uploading…');
    const media = await uploadFile(file,'music',message=>$('chooseMusic').textContent=message);
    if (state.project.id !== projectId) { toast(t('Music uploaded. Select the original session before attaching it.'),true); return; }
    state.project.musicId = media.id; state.project.music = media; state.previewMs = 0; markDirty(); await flushSave(); configureMusic(); tick(); toast(t('Music added. Preview the timing before exporting.'));
  } catch(error) { toast(error.message,true); }
  finally { $('chooseMusic').disabled = false; $('chooseMusic').textContent = state.project?.music ? t('Replace music') : t('Choose music ＋'); }
}
function mutateCue(id, action) {
  const index = state.project.segments.findIndex(s => s.id === id), cue = state.project.segments[index]; if (!cue) return;
  if (action === 'seek') { selectCue(id,true); return; }
  if (action === 'split') {
    const textarea = document.querySelector(`.cue-row[data-id="${CSS.escape(id)}"] textarea`);
    let position = textarea.selectionStart;
    if (position <= 0 || position >= cue.text.length) { const middle=Math.floor(cue.text.length/2); const space=cue.text.indexOf(' ',middle); position=space<0?middle:space; }
    const left=cue.text.slice(0,position).trim(), right=cue.text.slice(position).trim();
    if (!left || !right || cue.endMs-cue.startMs < 200) { toast(t('Place the text cursor between words to split this prompt.')); return; }
    pushUndo(); const split=Math.round(cue.startMs+(cue.endMs-cue.startMs)*left.length/(left.length+right.length));
    const added={id:crypto.randomUUID().replaceAll('-',''),startMs:split,endMs:cue.endMs,text:right}; cue.endMs=split; cue.text=left; state.project.segments.splice(index+1,0,added);
  } else if (action === 'merge') {
    const next=state.project.segments[index+1]; if(!next){toast(t('There is no next cue to merge.'));return;}
    pushUndo(); cue.text=cue.text.trim()+' '+next.text.trim(); cue.endMs=next.endMs; state.project.segments.splice(index+1,1);
  } else if (action === 'delete') {
    pushUndo(); state.project.segments.splice(index,1); state.selected=state.project.segments[Math.min(index,state.project.segments.length-1)]?.id;
  }
  state.invalid.clear(); markDirty(); renderCues();
}
function updateThemes() {
  const map={midnight:['#101d22'],black:['#000000','#080a0b'],paper:['#f4f1e9']};
  document.querySelectorAll('[data-theme]').forEach(button => button.classList.toggle('selected',map[button.dataset.theme].includes(state.project.style.background)));
}
function renderArchive() {
  const query=$('archiveSearch').value.toLowerCase();
  $('archiveList').innerHTML=state.catalog.filter(d=>d.name.toLowerCase().includes(query)).map(d=>`<button class="archive-item" data-archive="${d.id}"><span><span data-user-text>${escapeHTML(d.name)}</span><small>Original document ${d.id} · ${d.count} cues</small></span><span class="pill">${d.displayLanguage==='en'?t('EN · English'):t('SK · Slovak')}</span></button>`).join('');
  I18n.apply($('archiveList'));
}
function updateCueTime(event, finished = false) {
  const row=event.target.closest('.cue-row');
  const fieldKey=row.dataset.id+':'+event.target.dataset.field;
  try {
    const value=parseClock(event.target.value);
    state.project.segments.find(s=>s.id===row.dataset.id)[event.target.dataset.field]=value;
    state.invalid.delete(fieldKey);
    row.classList.toggle('invalid',[...state.invalid].some(key=>key.startsWith(row.dataset.id+':')));
    state.project.segments.sort((a,b)=>a.startMs-b.startMs);
    markDirty();
    if(finished&&!validateDraft())renderCues();
  } catch(error) {
    state.invalid.add(fieldKey);row.classList.add('invalid');showValidation(error.message);saveLabel(t('Fix cue time'),'error');
  }
}
function formatExportTime(value) {
  const date=new Date(value);
  return Number.isNaN(date.getTime())?t('Unknown date'):date.toLocaleString(I18n.locale,{year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23',timeZoneName:'short'});
}
function exportDownloadUrl(id) {
  const zone=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
  return '/api/jobs/'+id+'/download?timezone='+encodeURIComponent(zone);
}
async function loadJobs() {
  if (!state.project) return;
  const projectId=state.project.id;
  try { const jobs=await api('/api/jobs?projectId='+projectId); if(state.project.id!==projectId)return; state.jobs=jobs;
    const visibleJobs=jobs.slice(0,5),latestGuide=jobs.find(job=>job.status==='complete'&&job.kind!=='final');
    if(latestGuide&&!visibleJobs.some(job=>job.id===latestGuide.id))visibleJobs.push(latestGuide);
    $('jobList').innerHTML=visibleJobs.length?visibleJobs.map(j=>{
      const completed=j.status==='complete',timestamp=completed?(j.completedAt||j.createdAt):j.createdAt;
      return `<div class="job"><div class="job-top"><strong>${escapeHTML(j.stage)}</strong><span>${completed?'✓':j.status==='failed'?'!':Math.round(j.progress)+'%'}</span></div><div class="job-meta"><small>${j.kind==='final'?'Final mix · ':''}Saved revision ${j.revision}</small><small>${completed?t('Exported'):t('Requested')} ${escapeHTML(formatExportTime(timestamp))}</small></div>${j.status==='queued'||j.status==='rendering'?`<div class="job-progress"><i style="width:${j.progress}%"></i></div>`:''}${completed?`<div class="export-actions"><button class="button outline" data-watch="${j.id}">Play video</button><a href="${exportDownloadUrl(j.id)}">Download MP4 ↗</a>${j.kind!=='final'?`<button class="button outline" data-narrate="${j.id}">Open narration studio</button>`:''}</div>`:''}${j.error?`<p class="job-error">${escapeHTML(j.error)}</p>`:''}</div>`;
    }).join(''):'<p class="empty-exports">Your finished videos will appear here.<br>Only your music and visible prompts are included.</p>';
    I18n.apply($('jobList'));
    const busy=jobs.some(j=>j.status==='queued'||j.status==='rendering'),queued=jobs.some(j=>j.status==='queued'); $('exportVideo').disabled=busy||!state.project; $('exportVideo').textContent=busy?(queued?t('Queued for export'):t('Rendering…')):(state.auth?.remote?t('↗ Send for export'):t('↗ Export MP4'));
    $('jobList').querySelectorAll('.job').forEach((element,index)=>{const job=visibleJobs[index];if(!job)return;const action=job.status==='failed'&&job.protocol?'retry':job.status==='queued'&&job.protocol?'cancel':null;if(action){const button=document.createElement('button');button.className='text-button';button.textContent=action==='retry'?t('Retry this export'):t('Cancel queued export');button.onclick=async()=>{try{await api('/api/jobs/'+job.id+'/'+action,{method:'POST',body:{}});await loadJobs();}catch(error){toast(error.message,true);}};element.append(button);}});
  } catch {}
}
async function openServices() {
  $('servicesForm').reset(); $('servicesError').hidden = true;
  try {
    const settings = await api('/api/services');
    for (const provider of ['elevenlabs','deepl']) {
      const info = settings[provider];
      $(provider+'State').textContent = info.fromEnvironment ? t('Configured through the server environment') : info.configured ? t('Configured · used when a draft starts') : t('No key configured');
    }
    const owner=state.auth?.role==='owner';$('servicesForm').querySelectorAll('input,button').forEach(element=>element.disabled=!owner);$('servicesDialog').showModal();
  } catch(error) { toast(error.message,true); }
}
function updateDraftForm() {
  const kind = $('draftKind').value;
  $('draftFileLabel').hidden = kind === 'current';
  $('draftFile').accept = kind === 'audio' ? 'audio/*,.mp4' : '.srt,.vtt,.json';
  $('draftServiceNote').textContent = kind === 'audio' ? t("The recording is sent to ElevenLabs for transcription. Its text is sent to DeepL for Slovak translation (unless the source is Slovak). These services may charge your account. Add your separate music-only track in the editor.") : t("The source text is sent to DeepL for Slovak translation, which may charge your account. A new session keeps the original text alongside your editable draft. Cue times stay unchanged. Choose Slovak above to copy a source without translation.");
  if(kind === 'current' && !$('draftName').value) $('draftName').value = state.project?.name || '';
}
async function loadDraftJobs() {
  if (!$('draftDialog').open) return;
  try {
    const jobs = await api('/api/drafts');
    $('draftJobs').innerHTML = jobs.length ? jobs.slice(0,12).map(job => `<div class="job"><div class="job-top"><strong data-user-text>${escapeHTML(job.name)}</strong><span>${job.status==='complete'?'✓':job.status==='failed'?'!':Math.round(job.progress)+'%'}</span></div><p class="draft-stage">${escapeHTML(job.stage)}</p>${job.status==='working'||job.status==='queued'?`<div class="job-progress"><i style="width:${job.progress}%"></i></div>`:''}${job.error?`<p class="job-error">${escapeHTML(job.error)}</p>`:''}<div class="draft-job-actions">${job.resultProjectId?`<button class="button outline" data-open-draft="${job.resultProjectId}">Open Slovak draft ↗</button>`:''}${job.canRetry?`<button class="button outline" data-retry-draft="${job.id}">Resume translation</button>`:''}${job.sourceReady?`<a href="/api/drafts/${job.id}/source" download="original-transcript.json">Save original transcript</a>`:''}</div></div>`).join('') : '<p class="empty-exports">Your new drafts will appear here.</p>';
    I18n.apply($('draftJobs'));
  } catch(error) { $('draftError').textContent=t(error.message); $('draftError').hidden=false; }
}
function bindDraftEvents() {
  $('newDraft').onclick=()=>{updateDraftForm();$('draftDialog').showModal();$('draftDialog').scrollTop=0;loadDraftJobs();};
  $('closeDraft').onclick=()=>$('draftDialog').close();
  $('draftKind').onchange=()=>{$('draftFile').value='';updateDraftForm();};
  $('draftFile').onchange=()=>{const file=$('draftFile').files[0];if(file)$('draftName').value=file.name.replace(/\.[^.]+$/,'');};
  $('openServices').onclick=openServices; $('draftServices').onclick=openServices;
  $('closeServices').onclick=()=>$('servicesDialog').close();
  $('servicesDialog').addEventListener('close',()=>$('servicesForm').reset());
  $('servicesForm').onsubmit=async event=>{
    event.preventDefault();$('saveServices').disabled=true;$('servicesError').hidden=true;
    try{await api('/api/services',{method:'POST',body:{elevenlabs:$('elevenlabsKey').value,deepl:$('deeplKey').value,remove_elevenlabs:$('removeElevenlabs').checked,remove_deepl:$('removeDeepl').checked}});$('servicesDialog').close();toast(t('Keys saved. Services are used when you start a draft.'));}
    catch(error){$('servicesError').textContent=t(error.message);$('servicesError').hidden=false;}
    finally{$('saveServices').disabled=false;}
  };
  $('draftForm').onsubmit=async event=>{
    event.preventDefault();$('startDraft').disabled=true;$('draftError').hidden=true;
    try{
      const kind=$('draftKind').value,payload={name:$('draftName').value,language:$('draftLanguage').value};
      const settings=await api('/api/services');
      if(kind==='audio'&&!settings.elevenlabs.configured)throw new Error(t('Set up your ElevenLabs API key first.'));
      if(payload.language!=='sk'&&!settings.deepl.configured)throw new Error(t('Set up your DeepL API key first, or choose Slovak for an already Slovak source.'));
      if(kind==='current'){await flushSave();payload.projectId=state.project.id;payload.revision=state.project.revision;}
      else{
        const file=$('draftFile').files[0];if(!file)throw new Error(t('Choose a source file.'));
        if(kind==='audio'){
          if(file.size>4*1024**3)throw new Error(t('Choose a source recording smaller than 4 GB.'));
          $('startDraft').textContent=t('Uploading source…');
          const media=await uploadFile(file,'reference',message=>$('startDraft').textContent=message);payload.mediaId=media.id;
        }else{
          if(file.size>25*1024*1024)throw new Error(t('Choose subtitles smaller than 25 MB.'));payload.subtitleText=await file.text();
        }
      }
      await api('/api/drafts',{method:'POST',body:payload});await loadDraftJobs();toast(t('Draft queued. You can keep editing while it is prepared.'));
    }catch(error){$('draftError').textContent=t(error.message);$('draftError').hidden=false;}
    finally{$('startDraft').disabled=false;$('startDraft').textContent=t('Create Slovak draft');}
  };
  $('draftJobs').onclick=async event=>{
    const open=event.target.closest('[data-open-draft]'),retry=event.target.closest('[data-retry-draft]');
    try{
      if(open){await flushSave();state.projects=await api('/api/projects');$('draftDialog').close();await loadProject(open.dataset.openDraft);}
      else if(retry){retry.disabled=true;await api('/api/drafts/'+retry.dataset.retryDraft+'/retry',{method:'POST',body:{}});await loadDraftJobs();}
    }catch(error){toast(error.message,true);if(retry)retry.disabled=false;}
  };
  $('referenceAudio').onplay=()=>audio.pause();
}
function bindEvents() {
  bindDraftEvents();bindAdminEvents();
  $('sessionSearch').oninput=renderProjects; $('cueSearch').oninput=renderCues;
  $('projectList').onclick=event=>{const button=event.target.closest('[data-project]');if(button)loadProject(button.dataset.project);};
  $('projectName').oninput=()=>{state.project.name=$('projectName').value;markDirty();tick();};
  $('saveProject').onclick=()=>flushSave().then(()=>toast(t('Session saved.'))).catch(error=>toast(error.message,true));
  $('cueList').addEventListener('focusin', event=>{const row=event.target.closest('.cue-row');if(row){selectCue(row.dataset.id);if(event.target.matches('textarea,input'))pushUndo();}});
  $('cueList').addEventListener('input', event=>{
    const row=event.target.closest('.cue-row');if(!row)return;
    if(event.target.matches('textarea')){state.project.segments.find(s=>s.id===row.dataset.id).text=event.target.value;markDirty();tick();}
    else if(event.target.matches('[data-field]'))updateCueTime(event);
  });
  $('cueList').addEventListener('change', event=>{
    if(event.target.matches('[data-field]'))updateCueTime(event,true);
  });
  $('cueList').onclick=event=>{const row=event.target.closest('.cue-row');if(!row)return;const action=event.target.closest('[data-action]');if(action)mutateCue(row.dataset.id,action.dataset.action);else if(!event.target.matches('textarea,input'))selectCue(row.dataset.id,true);};
  $('showReference').onchange=renderCues;
  $('sourceSelect').onchange=async()=>{state.project.sourceId=$('sourceSelect').value?+$('sourceSelect').value:null;await loadReference();markDirty();renderCues();};
  $('addCue').onclick=()=>{pushUndo();const start=state.project.segments.at(-1)?.endMs||0;const cue={id:crypto.randomUUID().replaceAll('-',''),startMs:start,endMs:start+5000,text:''};state.project.segments.push(cue);state.selected=cue.id;markDirty();renderCues();const row=$('cueList').lastElementChild;row?.scrollIntoView({block:'nearest'});row?.querySelector('textarea').focus();};
  $('undo').onclick=()=>{if(!state.undo.length)return;state.project.segments=state.undo.pop();state.invalid.clear();$('undo').disabled=!state.undo.length;markDirty();renderCues();};
  $('backupProject').onclick=backupDraft;
  $('chooseMusic').onclick=()=>$('musicFile').click();$('musicFile').onchange=event=>{uploadMusic(event.target.files[0]);event.target.value='';};
  $('musicDrop').ondragover=event=>{event.preventDefault();$('musicDrop').classList.add('dragover');};$('musicDrop').ondragleave=()=>$('musicDrop').classList.remove('dragover');$('musicDrop').ondrop=event=>{event.preventDefault();$('musicDrop').classList.remove('dragover');uploadMusic(event.dataTransfer.files[0]);};
  $('playPause').onclick=togglePlay;$('presenterPlay').onclick=togglePlay;$('rewind').onclick=()=>seekTo(currentMs()-5000);$('seek').oninput=()=>seekTo(+$('seek').value/1000*totalDuration());
  audio.onplay=()=>requestAnimationFrame(playLoop);audio.onpause=tick;audio.ontimeupdate=tick;audio.onended=tick;audio.onloadedmetadata=()=>{if(state.previewMs)audio.currentTime=state.previewMs/1000;tick();};
  audio.onerror=()=>{if(state.project?.music)toast(t('This browser could not play the music. MP3 and M4A have the widest support.'),true);};
  $('presenter').onclick=async()=>{try{await $('previewStage').requestFullscreen();}catch{toast(t('Fullscreen is unavailable in this browser.'),true);}};$('exitPresenter').onclick=()=>document.exitFullscreen();
  document.addEventListener('keydown', event=>{if(event.code==='Space'&&!event.target.matches('input,textarea,select,button')){event.preventDefault();togglePlay();}if(document.fullscreenElement&&event.code==='ArrowRight'){seekTo(currentMs()+5000);}if(document.fullscreenElement&&event.code==='ArrowLeft'){seekTo(currentMs()-5000);}});
  $('fontSize').oninput=()=>{state.project.style.fontSize=+$('fontSize').value;$('fontSizeValue').textContent=$('fontSize').value;markDirty();tick();};
  $('resolution').onchange=()=>{Object.assign(state.project.style,{width:1920,height:1080});markDirty();tick();};
  $('videoLayout').onchange=()=>{state.project.style.layout=$('videoLayout').value;markDirty();tick();};
  $('cueOffset').onchange=()=>{const value=+$('cueOffset').value;if(!Number.isFinite(value)){toast(t('Use a number for the prompt offset.'),true);return;}state.project.cueOffsetMs=Math.round(value*1000);markDirty();tick();};
  document.querySelectorAll('[data-theme]').forEach(button=>button.onclick=()=>{const map={midnight:['#101d22','#f7f5ed'],black:['#000000','#ffffff'],paper:['#f4f1e9','#2e4237']};const [background,color]=map[button.dataset.theme];Object.assign(state.project.style,{background,color});updateThemes();markDirty();tick();});
  $('newSession').onclick=()=>{renderArchive();$('archiveDialog').showModal();};$('closeArchive').onclick=()=>$('archiveDialog').close();$('archiveSearch').oninput=renderArchive;
  $('archiveList').onclick=async event=>{const button=event.target.closest('[data-archive]');if(!button)return;try{await flushSave();const project=await api('/api/projects',{method:'POST',body:{subtitleId:+button.dataset.archive}});state.projects=await api('/api/projects');$('archiveDialog').close();await loadProject(project.id);toast(t('Created an editable copy. The archived script is preserved.'));}catch(error){toast(error.message,true);}};
  $('duplicateProject').onclick=async()=>{try{await flushSave();const project=await api('/api/projects/'+state.project.id+'/duplicate',{method:'POST',body:{}});state.projects=await api('/api/projects');await loadProject(project.id);}catch(error){toast(error.message,true);}};
  $('importSubtitles').onclick=()=>$('subtitleFile').click();$('subtitleFile').onchange=async event=>{const file=event.target.files[0];if(!file)return;try{await flushSave();if(file.size>25*1024*1024)throw new Error(t('Choose a subtitle file smaller than 25 MB.'));const project=await api('/api/import',{method:'POST',body:{name:file.name.replace(/\.[^.]+$/,''),text:await file.text()}});state.projects=await api('/api/projects');await loadProject(project.id);toast(t('Imported into a new session.'));}catch(error){toast(error.message,true);}finally{event.target.value='';}};
  for(const [button,fmt] of [['downloadSrt','srt'],['downloadVtt','vtt']])$(button).onclick=async()=>{try{await flushSave();const link=document.createElement('a');link.href='/api/projects/'+state.project.id+'/subtitles.'+fmt;link.download='';link.click();}catch(error){toast(error.message,true);}};
  $('exportVideo').onclick=async()=>{try{await flushSave();const job=await api('/api/projects/'+state.project.id+'/render',{method:'POST',body:{revision:state.project.revision}});await loadJobs();toast(job.status==='queued'?(state.auth?.remote?t('Queued. The Mac renderer will pick it up when launched.'):t('Export queued. You can keep editing.')):t('Export started.'));}catch(error){toast(error.message,true);}};
  $('mobileNav').onclick=()=>$('sidebar').classList.toggle('open');
  window.addEventListener('beforeunload',event=>{if(state.dirty||state.invalid.size){event.preventDefault();event.returnValue='';}});
}
async function uploadFile(file,purpose,report=()=>{}) {
  if(!file.size||file.size>4*1024**3)throw new Error(t('Choose an audio file smaller than 4 GB.'));
  const sample=new Blob([file.slice(0,1024*1024),file.slice(Math.max(0,file.size-1024*1024))]);
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await sample.arrayBuffer())),byte=>byte.toString(16).padStart(2,'0')).join('');
  const key=hash+':'+file.size+':'+file.lastModified+':'+purpose;
  async function retry(action){let error;for(let n=0;n<3;n++){try{return await action();}catch(caught){error=caught;if(n<2)await new Promise(resolve=>setTimeout(resolve,1000*(n+1)));}}throw error;}
  const upload=await retry(()=>api('/api/uploads',{method:'POST',body:{name:file.name,bytes:file.size,purpose,key}}));
  if(upload.media)return upload.media;
  let offset=upload.offset;
  while(offset<file.size){
    const start=offset,chunk=file.slice(start,Math.min(file.size,start+upload.chunkBytes));
    const result=await retry(()=>api('/api/uploads/'+upload.id+'/chunk',{method:'POST',body:chunk,headers:{'Content-Type':'application/octet-stream','X-Upload-Offset':String(start)}}));
    offset=result.offset;report(t('Uploading… {percent}%',{percent:Math.round(offset/file.size*100)}));
  }
  report(t('Checking audio…'));
  return retry(()=>api('/api/uploads/'+upload.id+'/finish',{method:'POST',body:{}}));
}
async function refreshAdmin() {
  const [users,workers]=await Promise.all([api('/api/admin/users'),api('/api/admin/workers')]);
  $('usersList').innerHTML=users.map(user=>`<div class="admin-row"><span><span data-user-text>${escapeHTML(user.username)}</span> · ${escapeHTML(t(user.role))}${user.enabled?'':' · '+t('disabled')}</span>${user.role==='editor'&&user.enabled?`<button class="text-button" data-disable-user="${user.id}">Disable</button>`:''}</div>`).join('');
  $('workersList').innerHTML=workers.map(worker=>`<div class="admin-row"><span><span data-user-text>${escapeHTML(worker.name)}</span><small>${worker.enabled?(worker.last_seen?t('Last connected {date}',{date:new Date(worker.last_seen).toLocaleString(I18n.locale)}):t('Not connected yet')):t('Revoked')}</small></span>${worker.enabled?`<button class="text-button" data-revoke-worker="${worker.id}">Revoke</button>`:''}</div>`).join('')||'<p class="provider-note">No Mac renderers paired yet.</p>';
  I18n.apply($('usersList')); I18n.apply($('workersList'));
}
function bindAdminEvents() {
  async function perform(action){$('adminError').hidden=true;try{await action();await refreshAdmin();}catch(error){$('adminError').textContent=t(error.message);$('adminError').hidden=false;}}
  $('openAdmin').onclick=()=>{perform(refreshAdmin);$('adminDialog').showModal();};
  $('closeAdmin').onclick=()=>$('adminDialog').close();
  $('adminDialog').addEventListener('close',()=>{$('workerToken').value='';$('newWorkerToken').hidden=true;$('editorPassword').value='';});
  $('addEditorForm').onsubmit=event=>{event.preventDefault();const button=event.submitter;button.disabled=true;perform(async()=>{await api('/api/admin/users',{method:'POST',body:{username:$('editorUsername').value,password:$('editorPassword').value}});$('addEditorForm').reset();toast(t('Editor account created. Share the login details privately.'));}).finally(()=>button.disabled=false);};
  $('addWorkerForm').onsubmit=event=>{event.preventDefault();const button=event.submitter;button.disabled=true;perform(async()=>{const worker=await api('/api/admin/workers',{method:'POST',body:{name:$('workerName').value}});$('workerToken').value=worker.token;$('newWorkerToken').hidden=false;}).finally(()=>button.disabled=false);};
  $('copyWorkerToken').onclick=async()=>{try{await navigator.clipboard.writeText($('workerToken').value);toast(t('Token copied.'));}catch{$('workerToken').select();toast(t('Select and copy the token.'));}};
  $('usersList').onclick=event=>{const button=event.target.closest('[data-disable-user]');if(button)perform(()=>api('/api/admin/users/'+button.dataset.disableUser+'/disable',{method:'POST',body:{}}));};
  $('workersList').onclick=event=>{const button=event.target.closest('[data-revoke-worker]');if(button)perform(()=>api('/api/admin/workers/'+button.dataset.revokeWorker+'/revoke',{method:'POST',body:{}}));};
  $('signOut').onclick=async()=>{try{await flushSave();await api('/api/auth/logout',{method:'POST',body:{}});location.replace('/login');}catch(error){toast(error.message,true);}};
}
function updateAccountLabels() {
  if (!state.auth) return;
  $('workspaceLabel').textContent=state.auth.remote?state.auth.username:t('Local workspace');
  $('workspaceNote').textContent=state.auth.remote?t('Saved on your NAS · render on demand'):t('Editing and rendering on this computer');
}
function updateSessionDescription() {
  if (!state.project) return;
  const meta=state.catalog.find(d=>String(d.id)===String(state.project.archiveId));
  $('sessionDescription').textContent=state.project.reference?t('Slovak draft · review each cue against the original before guiding live.'):meta?t('From {name} · your own editable session',{name:meta.name}):t('Slovak prompts. Your music. Your guidance.');
  if (!state.project.reference) $('sourceSelect').options[0].textContent=t('No reference');
}
document.addEventListener('languagechange',()=>{
  updateAccountLabels(); renderProjects(); renderArchive(); updateDraftForm();
  if(state.project){updateSessionDescription();configureMusic(false);$('cueCount').textContent=t('{count} cues',{count:state.project.segments.length});tick();loadJobs();}
  if($('draftDialog').open)loadDraftJobs();
  if($('adminDialog').open)refreshAdmin().catch(error=>toast(error.message,true));
});
async function start() {
  for(const id of ['musicName','nextText','workspaceLabel','sessionDescription'])$(id).setAttribute('data-user-text','');
  bindEvents();
  window.NarrationStudio?.init({api,uploadFile,toast,clock,parseClock,auth:()=>state.auth,jobsChanged:loadJobs,
    pauseEditorAudio:()=>{audio.pause();$('referenceAudio').pause();}});
  try {
    const meResponse=await fetch('/api/auth/me');if(meResponse.status===401){location.replace('/login');return;}if(!meResponse.ok)throw new Error(t('Could not load your account.'));state.auth=await meResponse.json();
    window.NarrationStudio?.authReady();
    $('workspaceLabel').textContent=state.auth.remote?state.auth.username:t('Local workspace');$('workspaceNote').textContent=state.auth.remote?t('Saved on your NAS · render on demand'):t('Editing and rendering on this computer');$('openAdmin').hidden=!state.auth.remote||state.auth.role!=='owner';$('signOut').hidden=!state.auth.remote;
    const [projects,catalog,health]=await Promise.all([api('/api/projects'),api('/api/catalog'),api('/api/health')]);state.projects=projects;state.catalog=catalog;
    if(!health.ready)showValidation(t('FFmpeg is not available yet. Editing works; install FFmpeg before adding music or exporting.'));
    let previous;try{previous=localStorage.getItem('breathwork-last-project');}catch{}
    const selected=projects.find(p=>p.id===previous)||projects.find(p=>p.name.startsWith('V06'))||projects[0];
    if(selected)await loadProject(selected.id);else{renderProjects();saveLabel(t('Ready'));$('exportVideo').disabled=true;showValidation(t('Import subtitles to create your first session, or create a draft from audio.'));document.querySelectorAll('.workspace input,.workspace button,.workspace select').forEach(element=>element.disabled=true);$('importSubtitles').disabled=false;$('subtitleFile').disabled=false;$('mobileNav').disabled=false;$('projectName').value=t('Create your first session');document.querySelectorAll('[data-language]').forEach(element=>element.disabled=false);}
    await document.fonts.ready;state.signature='';tick();setInterval(loadJobs,2500);setInterval(loadDraftJobs,2500);
  }catch(error){showValidation('The app could not load. '+error.message);saveLabel(t('Connection problem'),'error');}
}
start();
