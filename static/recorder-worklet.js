/* Only the microphone enters this processor. Its output is silent. */
class BreathworkPCM extends AudioWorkletProcessor {
  constructor() {
    super();
    this.token = null;
    this.pending = null;
    this.buffer = new Uint8Array(Math.round(sampleRate) * 3);
    this.used = 0; this.bytes = 0; this.levelFrames = 0; this.squares = 0; this.peak = 0;
    this.port.onmessage = ({data}) => {
      if (data.type === 'start') this.pending = data.token;
      if (data.type === 'stop') {
        this.flush();
        this.port.postMessage({type:'stopped',token:this.token || this.pending,bytes:this.bytes});
        this.token = null; this.pending = null;
      }
    };
  }
  flush() {
    if (!this.used) return;
    const pcm = this.buffer.slice(0,this.used).buffer;
    this.port.postMessage({type:'pcm',token:this.token,offset:this.bytes,pcm},[pcm]);
    this.bytes += this.used; this.used = 0;
  }
  process(inputs,outputs) {
    for (const output of outputs) for (const channel of output) channel.fill(0);
    if (this.pending) {
      this.token = this.pending; this.pending = null; this.bytes = 0; this.used = 0;
      this.port.postMessage({type:'started',token:this.token,frame:currentFrame});
    }
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (let i=0;i<input.length;i++) {
      const sample = input[i];
      this.peak = Math.max(this.peak,Math.abs(sample)); this.squares += sample * sample; this.levelFrames++;
      if (this.token) {
        const value = Math.round(Math.max(-1,Math.min(1,sample)) * (sample < 0 ? 8388608 : 8388607));
        this.buffer[this.used++] = value & 255;
        this.buffer[this.used++] = (value >> 8) & 255;
        this.buffer[this.used++] = (value >> 16) & 255;
        if (this.used === this.buffer.length) this.flush();
      }
    }
    if (this.levelFrames >= sampleRate/10) {
      this.port.postMessage({type:'level',peak:this.peak,rms:Math.sqrt(this.squares/this.levelFrames)});
      this.levelFrames = 0; this.squares = 0; this.peak = 0;
    }
    return true;
  }
}
registerProcessor('breathwork-pcm',BreathworkPCM);

