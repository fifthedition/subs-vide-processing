'use strict';
window.BreathworkAudio = (() => {
  function wavHeader(rate,bytes) {
    const buffer=new ArrayBuffer(44),view=new DataView(buffer);
    const text=(offset,value)=>[...value].forEach((letter,index)=>view.setUint8(offset+index,letter.charCodeAt(0)));
    text(0,'RIFF');view.setUint32(4,bytes+36,true);text(8,'WAVE');text(12,'fmt ');
    view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);
    view.setUint32(24,rate,true);view.setUint32(28,rate*3,true);view.setUint16(32,3,true);
    view.setUint16(34,24,true);text(36,'data');view.setUint32(40,bytes,true);
    return buffer;
  }
  function wav(chunks,rate) {
    const bytes=chunks.reduce((sum,chunk)=>sum+chunk.byteLength,0);
    return new Blob([wavHeader(rate,bytes),...chunks],{type:'audio/wav'});
  }
  class Microphone {
    constructor({level=()=>{},interrupted=()=>{},failure=()=>{}}={}) {
      this.level=level;this.interrupted=interrupted;this.failure=failure;this.active=false;
      this.stream=null;this.context=null;this.generation=0;this.closed=false;
    }
    async connect(deviceId='',gainDb=0) {
      if(this.active)throw new Error('Pause recording before changing microphone settings.');
      const closing=this.disconnect();
      if(!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode || !window.isSecureContext)
        throw new Error('Microphone recording needs HTTPS and a current version of Chrome, Safari or Firefox.');
      this.closed=false;
      const generation=++this.generation;
      let context,stream;
      try {
        const Context=window.AudioContext||window.webkitAudioContext;
        // Use the browser's native audio clock. The NAS resamples WAV takes to
        // 48 kHz when needed, avoiding cross-rate input issues in some browsers.
        context=new Context({latencyHint:'interactive'});
        this.pendingContext=context;
        // Resume synchronously from the button gesture, before permission or
        // storage awaits, so Safari does not lose its audio activation.
        const resumed=context.resume();resumed.catch(()=>{});
        const requested=navigator.mediaDevices.getUserMedia({audio:{deviceId:deviceId?{exact:deviceId}:undefined,
          channelCount:{ideal:1},sampleRate:{ideal:48000},echoCancellation:false,noiseSuppression:false,autoGainControl:false},video:false});
        requested.catch(()=>{});
        await closing;stream=await requested;
        if(generation!==this.generation){stream.getTracks().forEach(track=>track.stop());throw new Error('Microphone connection was cancelled.');}
        if(!context.audioWorklet)throw new Error('AudioWorklet recording is unavailable in this browser.');
        await resumed;await context.audioWorklet.addModule('/recorder-worklet.js');
        if(generation!==this.generation)throw new Error('Microphone connection was cancelled.');
        this.stream=stream;this.context=context;this.pendingContext=null;
        this.source=context.createMediaStreamSource(stream);this.gain=context.createGain();
        this.node=new AudioWorkletNode(context,'breathwork-pcm',{channelCount:1,channelCountMode:'explicit',outputChannelCount:[1]});
        this.setGain(gainDb);this.source.connect(this.gain);this.gain.connect(this.node);this.node.connect(context.destination);
        this.node.port.onmessage=event=>this.message(event.data);
        this.track=stream.getAudioTracks()[0];
        this.track.addEventListener('ended',()=>{if(!this.closed)this.interrupted('The microphone disconnected. The recording has been paused.');});
        this.track.addEventListener('mute',()=>{if(this.active)this.interrupted('The microphone was interrupted. The recording has been paused.');});
        context.onstatechange=()=>{if(this.active&&context.state!=='running')this.interrupted('Audio was interrupted. The recording has been paused.');};
        this.node.onprocessorerror=()=>this.interrupted('The audio recorder stopped. Recover the saved take before continuing.');
        return {rate:context.sampleRate,settings:this.track.getSettings(),label:this.track.label};
      } catch(error) {
        stream?.getTracks().forEach(track=>track.stop());await context?.close().catch(()=>{});
        if(generation===this.generation){this.stream=null;this.context=null;}
        if(this.pendingContext===context)this.pendingContext=null;
        throw error;
      }
    }
    setGain(db) { if(this.gain)this.gain.gain.value=10**(Number(db)/20); }
    async devices() {
      if(!navigator.mediaDevices?.enumerateDevices)return [];
      return (await navigator.mediaDevices.enumerateDevices()).filter(device=>device.kind==='audioinput');
    }
    message(data) {
      if(data.type==='level'){this.level(data);return;}
      if(data.token!==this.token)return;
      if(data.type==='started'){this.started?.({frame:data.frame,rate:this.context.sampleRate});this.started=null;}
      if(data.type==='pcm'){
        this.bytes=data.offset+data.pcm.byteLength;
        // Persist sequentially; recording never waits for a network round trip.
        this.persist=this.persist.then(()=>this.chunk(data)).catch(error=>{this.failure(error);});
      }
      if(data.type==='stopped'){this.bytes=data.bytes;this.stopped?.(data);this.stopped=null;}
    }
    async start(chunk) {
      if(this.active)throw new Error('A microphone recording is already active.');
      if(!this.context)throw new Error('Enable and check your microphone first.');
      await this.context.resume();
      this.active=true;this.token=crypto.randomUUID();this.chunk=chunk;this.bytes=0;this.persist=Promise.resolve();
      return new Promise((resolve,reject)=>{
        const timer=setTimeout(()=>{this.started=null;this.active=false;this.node.port.postMessage({type:'stop'});reject(new Error('The microphone did not start. Check its permission and try again.'));},5000);
        this.started=value=>{clearTimeout(timer);resolve(value);};
        this.node.port.postMessage({type:'start',token:this.token});
      });
    }
    async stop() {
      if(!this.active)return {bytes:this.bytes||0};
      this.active=false;
      const result=await new Promise(resolve=>{
        const timer=setTimeout(()=>{this.stopped=null;resolve({bytes:this.bytes||0,interrupted:true});},2000);
        this.stopped=value=>{clearTimeout(timer);resolve(value);};
        this.node?.port.postMessage({type:'stop'});
      });
      await this.persist;
      return result;
    }
    async disconnect() {
      this.generation++;this.closed=true;
      if(this.active)await this.stop();
      this.stream?.getTracks().forEach(track=>track.stop());
      this.source?.disconnect();this.gain?.disconnect();this.node?.disconnect();
      const context=this.context,pending=this.pendingContext;
      this.stream=null;this.context=null;this.track=null;this.pendingContext=null;
      await context?.close().catch(()=>{});
      if(pending&&pending!==context)await pending.close().catch(()=>{});
    }
  }
  class Spool {
    constructor(){this.database=null;this.memoryMeta=new Map();this.memoryChunks=new Map();}
    async open() {
      if(this.database)return this.database;
      if(!window.indexedDB)throw new Error('Enable browser storage to record narration safely.');
      this.database=await new Promise((resolve,reject)=>{
        const request=indexedDB.open('breathwork-recordings',1);
        request.onupgradeneeded=()=>{
          const db=request.result;
          db.createObjectStore('meta',{keyPath:'id'});
          db.createObjectStore('chunks',{keyPath:'id'}).createIndex('takeId','takeId');
        };
        request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
      });
      return this.database;
    }
    async transaction(stores,mode,action) {
      const db=await this.open();
      return new Promise((resolve,reject)=>{
        const tx=db.transaction(stores,mode);let value;
        try{value=action(tx);}catch(error){reject(error);return;}
        tx.oncomplete=()=>resolve(typeof value==='function'?value():value);
        tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||new Error('Browser storage was interrupted.'));
      });
    }
    async put(meta) {
      this.memoryMeta.set(meta.id,{...meta});
      try{await this.transaction(['meta'],'readwrite',tx=>tx.objectStore('meta').put({...meta}));}
      catch{ return false; }
      return true;
    }
    async all() {
      const saved=await this.transaction(['meta'],'readonly',tx=>{const request=tx.objectStore('meta').getAll();return ()=>request.result;});
      const values=new Map(saved.map(item=>[item.id,item]));
      for(const [id,meta] of this.memoryMeta)values.set(id,meta);
      return [...values.values()];
    }
    async append(meta,offset,pcm) {
      const id=meta.id+':'+String(offset).padStart(15,'0'),item={id,takeId:meta.id,offset,pcm};
      meta.bytes=Math.max(meta.bytes||0,offset+pcm.byteLength);this.memoryMeta.set(meta.id,{...meta});
      try {
        await this.transaction(['meta','chunks'],'readwrite',tx=>{tx.objectStore('meta').put({...meta});tx.objectStore('chunks').put(item);});
        return true;
      }catch{this.memoryChunks.set(id,item);return false;}
    }
    async chunks(id) {
      const saved=await this.transaction(['chunks'],'readonly',tx=>{const request=tx.objectStore('chunks').index('takeId').getAll(id);return ()=>request.result;});
      const values=new Map(saved.map(item=>[item.id,item]));
      for(const [key,item] of this.memoryChunks)if(item.takeId===id)values.set(key,item);
      return [...values.values()].sort((a,b)=>a.offset-b.offset);
    }
    async removeChunk(id) {
      await this.transaction(['chunks'],'readwrite',tx=>tx.objectStore('chunks').delete(id)).catch(()=>{});
      this.memoryChunks.delete(id);
    }
    async remove(id) {
      for(const chunk of await this.chunks(id))await this.removeChunk(chunk.id);
      await this.transaction(['meta'],'readwrite',tx=>tx.objectStore('meta').delete(id)).catch(()=>{});
      this.memoryMeta.delete(id);
    }
  }
  return {Microphone,Spool,wav,wavHeader};
})();

