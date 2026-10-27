'use strict';
const Teleprompter = (() => {
  const green='#00ba38', red='#ff3030', yellow='#ffff00';
  function clock(milliseconds, roundUp=false) {
    let seconds=Math.max(0,roundUp?Math.ceil(milliseconds/1000):Math.floor(milliseconds/1000));
    const hours=Math.floor(seconds/3600); seconds%=3600;
    return (hours?String(hours).padStart(2,'0')+':':'')+String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');
  }
  function snapshot(project, atMs, durationMs) {
    durationMs=Math.max(1,Math.trunc(durationMs));atMs=Math.max(0,Math.min(durationMs,Math.trunc(atMs)));
    const cues=project.segments,offset=project.cueOffsetMs||0,shifted=atMs-offset;
    let low=0,high=cues.length-1,before=-1;
    while(low<=high){const middle=(low+high)>>1;if(cues[middle].startMs<=shifted){before=middle;low=middle+1;}else high=middle-1;}
    const current=atMs<durationMs&&before>=0&&cues[before].endMs>shifted?before:-1;
    const previous=current>=0?current-1:before,following=current>=0?current+1:before+1,next=following<cues.length?following:-1;
    let targetMs,countdownLabel;
    if(current>=0){targetMs=Math.min(durationMs,cues[current].endMs+offset);countdownLabel='DO KONCA TEXTU';}
    else if(next>=0){targetMs=cues[next].startMs+offset;countdownLabel='ĎALŠÍ TEXT O';}
    else{targetMs=durationMs;countdownLabel='DO KONCA HUDBY';}
    return {previous,current,next,elapsed:clock(atMs),remaining:clock(durationMs-atMs,true),countdown:Math.max(0,Math.ceil((targetMs-atMs)/1000)),countdownLabel,targetMs};
  }
  function wrap(ctx,text,width) {
    const lines=[];
    for(const paragraph of text.split('\n')){
      if(!paragraph.trim()){lines.push('');continue;}
      let line='';
      for(const word of paragraph.trim().split(/\s+/)){
        const candidate=(line+' '+word).trim();
        if(ctx.measureText(candidate).width<=width){line=candidate;continue;}
        if(line){lines.push(line);line='';}
        for(const letter of word){if(line&&ctx.measureText(line+letter).width>width){lines.push(line);line='';}line+=letter;}
      }
      if(line)lines.push(line);
    }
    return lines.length?lines:[''];
  }
  function secondary(style) {
    const rgb=value=>[1,3,5].map(i=>parseInt(value.slice(i,i+2),16));
    const a=rgb(style.color),b=rgb(style.background);
    return `rgb(${a.map((value,i)=>Math.round(value*.56+b[i]*.44)).join(',')})`;
  }
  function text(ctx,value,x,y,size,color,bold=false,align='center') {
    ctx.font=`${bold?600:400} ${size}px Inter`;ctx.fillStyle=color;ctx.textAlign=align;ctx.textBaseline='top';ctx.fillText(value,x,y);
  }
  function box(ctx,value,x,y,width,height,size,color,bold=false) {
    if(!value)return;
    let lines,lineHeight;size=Math.max(14,Math.round(size));
    do{
      ctx.font=`${bold?600:400} ${size}px Inter`;lines=wrap(ctx,value,width);lineHeight=Math.round(size*1.3);
      if(lines.length*lineHeight<=height||size<=14)break;size--;
    }while(true);
    ctx.fillStyle=color;ctx.textAlign='center';ctx.textBaseline='top';
    if(lines.length*lineHeight>height){text(ctx,'Text je príliš dlhý. Rozdeľ tento úsek.',x+width/2,y,14,red);return;}
    const top=y+(height-lines.length*lineHeight)/2;
    lines.forEach((line,index)=>ctx.fillText(line,x+width/2,top+index*lineHeight));
  }
  function draw(canvas,project,state) {
    const style=project.style,w=style.width,h=style.height,scale=w/1920;
    if(canvas.width!==w)canvas.width=w;if(canvas.height!==h)canvas.height=h;
    const ctx=canvas.getContext('2d'),muted=secondary(style);
    const brightness=[1,3,5].map(i=>parseInt(style.background.slice(i,i+2),16)).reduce((sum,value,i)=>sum+value*[.2126,.7152,.0722][i],0);
    const [green,red,yellow]=brightness>150?['#007b2b','#c71d27','#806600']:['#00ba38','#ff3030','#ffff00'];
    ctx.fillStyle=style.background;ctx.fillRect(0,0,w,h);
    text(ctx,'UPLYNULO',w*.07,h*.025,Math.round(18*scale),green,true,'left');
    text(ctx,'DO KONCA',w*.93,h*.025,Math.round(18*scale),red,true,'right');
    box(ctx,project.name||'',w*.29,h*.025,w*.42,h*.1,29*scale,yellow,true);
    text(ctx,state.elapsed,w*.07,h*.06,Math.round(65*scale),green,true,'left');
    text(ctx,state.remaining,w*.93,h*.06,Math.round(65*scale),red,true,'right');
    for(const [key,labelY,top,height,caption] of [['previous',.19,.22,.12,'PREDCHÁDZAJÚCI TEXT'],['current',.375,.405,.26,'TERAZ'],['next',.72,.75,.13,'NASLEDUJÚCI TEXT']]){
      const index=state[key];
      if(index<0){if(key==='current')text(ctx,'PAUZA',w/2,h*.51,Math.round(27*scale),muted);continue;}
      const active=key==='current';
      text(ctx,caption,w/2,h*labelY,Math.round(18*scale),active?yellow:muted,true);
      box(ctx,project.segments[index].text,w*.07,h*top,w*.86,h*height,style.fontSize*scale*(active?1:.64),active?style.color:muted,active);
    }
    const footerY=Math.round(h*.91);
    text(ctx,state.countdownLabel,w/2,footerY,Math.round(17*scale),yellow,true);
    text(ctx,String(state.countdown),w/2,footerY+Math.round(h*.025),Math.round(54*scale),yellow,true);
  }
  return {snapshot,draw};
})();
if(typeof module!=='undefined')module.exports=Teleprompter;
