'use strict';
window.NarrationTimeline=(()=>{
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const range=(a,b,total)=>({start:Math.max(0,Math.min(total,Math.min(a,b))),end:Math.max(0,Math.min(total,Math.max(a,b)))});
  function waveform(peaks,start=0,end=1){
    if(!peaks?.length)return '';
    const first=Math.floor(Math.max(0,start)*peaks.length),last=Math.min(peaks.length,Math.ceil(end*peaks.length)),stride=Math.max(1,Math.ceil((last-first)/400));
    const selected=[];for(let n=first;n<last;n+=stride)selected.push(Math.max(0,...peaks.slice(n,Math.min(last,n+stride))));
    return '<svg viewBox="0 0 400 40" preserveAspectRatio="none" aria-hidden="true"><path d="'+selected.map((p,i)=>'M'+(i/Math.max(1,selected.length-1)*400).toFixed(2)+' '+(20-p*18).toFixed(2)+'V'+(20+p*18).toFixed(2)).join(' ')+'"/></svg>';
  }
  class Timeline{
    constructor(root,options){
      this.root=root;this.options=options;this.zoom=1;this.data=null;this.peaks=new Map();this.drag=null;
      root.innerHTML='<div class="timeline-controls"><strong>'+esc(I18n.t('Recording timeline'))+'</strong><label>'+esc(I18n.t('Zoom'))+' <select data-zoom><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option><option value="8">8×</option></select></label></div><div class="recording-timeline-scroll"><div class="recording-timeline-content"></div></div><p class="setting-help">'+esc(I18n.t('Click to seek. Drag empty space to select a range, or use the time fields.'))+'</p>';
      root.querySelector('[data-zoom]').onchange=event=>{this.zoom=Number(event.target.value);this.render();};
      root.addEventListener('click',event=>{const cue=event.target.closest('[data-timeline-cue]'),clip=event.target.closest('[data-timeline-clip]');if(cue)this.options.onCue(Number(cue.dataset.timelineCue));if(clip)this.options.onClip(Number(clip.dataset.timelineClip));});
      root.addEventListener('pointerdown',event=>{
        const track=event.target.closest('.timeline-track,.timeline-ruler');if(!track||event.target.closest('button')||this.disabled)return;
        const bounds=track.getBoundingClientRect(),at=Math.max(0,Math.min(this.data.durationMs,(event.clientX-bounds.left)/bounds.width*this.data.durationMs));
        this.drag={start:at,at,x:event.clientX,pointer:event.pointerId};track.setPointerCapture?.(event.pointerId);event.preventDefault();
      });
      root.addEventListener('pointermove',event=>{if(!this.drag)return;const track=event.target.closest('.timeline-track,.timeline-ruler')||root.querySelector('.timeline-ruler'),bounds=track.getBoundingClientRect();this.drag.at=Math.max(0,Math.min(this.data.durationMs,(event.clientX-bounds.left)/bounds.width*this.data.durationMs));this.setRange(this.drag.start,this.drag.at);});
      root.addEventListener('pointerup',event=>{if(!this.drag)return;const selected=this.drag;this.drag=null;if(Math.abs(event.clientX-selected.x)>4){const r=range(selected.start,selected.at,this.data.durationMs);if(r.end-r.start>=100)this.options.onRange(r.start,r.end);}else this.options.onSeek(selected.start);});
      root.addEventListener('pointercancel',()=>{this.drag=null;});
      root.addEventListener('keydown',event=>{if(!event.target.matches('.timeline-ruler')||this.disabled)return;const step=event.shiftKey?100:1000;let at=this.time||0;if(event.key==='ArrowLeft')at-=step;else if(event.key==='ArrowRight')at+=step;else if(event.key==='Home')at=0;else if(event.key==='End')at=this.data.durationMs;else return;event.preventDefault();this.options.onSeek(Math.max(0,Math.min(this.data.durationMs,at)));});
    }
    setData(data){const signature=JSON.stringify([data.id,data.durationMs,data.clips,data.cues,data.enhanced?.id,data.voiceOffsetMs]);this.data=data;if(signature!==this.signature){this.signature=signature;this.render();}}
    setPeaks(key,value){this.peaks.set(key,value);this.render();}
    render(){
      if(!this.data)return;
      const d=this.data,total=d.durationMs,percent=ms=>ms/total*100,clock=this.options.clock,content=this.root.querySelector('.recording-timeline-content');
      const lane=(name,inside)=>'<div class="timeline-lane"><strong>'+esc(I18n.t(name))+'</strong><div class="timeline-track">'+inside+'</div></div>';
      const ticks=Array.from({length:9},(_,i)=>'<span style="left:'+i*12.5+'%">'+esc(clock(total*i/8))+'</span>').join('');
      const cues=d.cues.map((cue,index)=>'<button class="timeline-cue" data-timeline-cue="'+index+'" style="left:'+percent(cue.startMs)+'%;width:'+Math.max(.1,percent(cue.endMs-cue.startMs))+'%" title="'+esc(cue.text)+'" '+(this.disabled?'disabled':'')+'><span data-user-text>'+esc(cue.text)+'</span></button>').join('');
      const clips=d.clips.map((clip,index)=>{const p=this.peaks.get(clip.mediaId),start=clip.startFrame/d.sampleRate*1000,end=clip.endFrame/d.sampleRate*1000,source=clip.sourceFrame/d.sampleRate*1000;return '<button class="timeline-voice" data-timeline-clip="'+index+'" style="left:'+percent(start)+'%;width:'+Math.max(.1,percent(end-start))+'%" aria-label="'+esc(I18n.t('Saved narration')+' '+clock(start,true)+' – '+clock(end,true))+'" '+(this.disabled?'disabled':'')+'>'+waveform(p?.peaks,source/(p?.durationMs||1),(source+end-start)/(p?.durationMs||1))+'<span>'+(index+1)+'</span></button>';}).join('');
      content.style.width=(this.zoom*100)+'%';
      content.innerHTML='<div class="timeline-ruler" tabindex="0" role="slider" aria-label="'+esc(I18n.t('Session position'))+'" aria-valuemin="0" aria-valuemax="'+total+'">'+ticks+'</div>'+lane('Music track',waveform(this.peaks.get('guide')?.peaks))+lane('Slovak script',cues)+lane('Saved narration',clips)+(d.enhanced?lane('Enhanced narration','<div class="timeline-enhanced" style="left:'+percent(d.voiceOffsetMs)+'%;width:'+percent(d.enhanced.durationMs)+'%">'+waveform(this.peaks.get(d.enhanced.id)?.peaks)+'</div>'):'')+'<div class="timeline-selection" aria-hidden="true"></div><div class="timeline-playhead" aria-hidden="true"></div>';
      this.setTime(this.time||0);if(this.selection)this.setRange(this.selection.start,this.selection.end);
    }
    setTime(ms){this.time=ms;if(!this.data)return;const line=this.root.querySelector('.timeline-playhead'),slider=this.root.querySelector('.timeline-ruler');if(line)line.style.left=(ms/this.data.durationMs*100)+'%';if(slider){slider.setAttribute('aria-valuenow',String(Math.round(ms)));slider.setAttribute('aria-valuetext',this.options.clock(ms,true));}}
    setRange(start,end){this.selection=range(start,end,this.data?.durationMs||1);const node=this.root.querySelector('.timeline-selection');if(node&&this.data){node.style.left=this.selection.start/this.data.durationMs*100+'%';node.style.width=(this.selection.end-this.selection.start)/this.data.durationMs*100+'%';}}
    setDisabled(disabled){if(this.disabled===disabled)return;this.disabled=disabled;this.render();}
  }
  return {Timeline,range,waveform};
})();
