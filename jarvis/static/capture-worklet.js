/* Microphone PCM adapter. No network or persistent storage in the worklet. */
class JarvisCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const settings = options.processorOptions || {};
    this.targetRate = settings.targetSampleRate || 16000;
    this.frameSize = settings.frameSize || 512;
    this.step = sampleRate / this.targetRate;
    this.enabled = false;
    this.taps = this.makeLowpass();
    this.filterHistory = new Float32Array(this.taps.length);
    this.frame = new Float32Array(this.frameSize);
    this.reset();
    this.port.onmessage = (event) => {
      const message = event.data || {};
      if (message.type === "capture") {
        this.enabled = message.enabled === true;
        if (message.reset !== false) this.reset();
      } else if (message.type === "reset") {
        this.reset();
      }
    };
  }

  makeLowpass() {
    if (sampleRate <= this.targetRate) return new Float64Array([1]);
    const count = 63;
    const cutoff = Math.min(this.targetRate * 0.45, sampleRate * 0.45) / sampleRate;
    const taps = new Float64Array(count);
    const center = (count - 1) / 2;
    let total = 0;
    for (let i = 0; i < count; i += 1) {
      const n = i - center;
      const sinc = n === 0 ? 2 * cutoff : Math.sin(2 * Math.PI * cutoff * n) / (Math.PI * n);
      const window = 0.54 - 0.46 * Math.cos((2 * Math.PI * i) / (count - 1));
      taps[i] = sinc * window;
      total += taps[i];
    }
    for (let i = 0; i < count; i += 1) taps[i] /= total;
    return taps;
  }

  reset() {
    this.filterHistory.fill(0);
    this.filterPosition = 0;
    this.sourcePosition = 0;
    this.nextOutputPosition = 0;
    this.previousSample = 0;
    this.framePosition = 0;
    this.energy = 0;
    this.meterFrames = 0;
  }

  lowpass(value) {
    if (this.taps.length === 1) return value;
    this.filterHistory[this.filterPosition] = value;
    let result = 0;
    let position = this.filterPosition;
    for (let i = 0; i < this.taps.length; i += 1) {
      result += this.taps[i] * this.filterHistory[position];
      position -= 1;
      if (position < 0) position = this.filterHistory.length - 1;
    }
    this.filterPosition = (this.filterPosition + 1) % this.filterHistory.length;
    return result;
  }

  emitSample(value) {
    const sample = Math.max(-1, Math.min(1, value));
    this.frame[this.framePosition] = sample;
    this.framePosition += 1;
    this.energy += sample * sample;
    if (this.framePosition !== this.frameSize) return;

    const buffer = new ArrayBuffer(this.frameSize * 2);
    const view = new DataView(buffer);
    for (let i = 0; i < this.frameSize; i += 1) {
      const v = this.frame[i];
      view.setInt16(i * 2, Math.round(v < 0 ? v * 32768 : v * 32767), true);
    }
    this.port.postMessage({ type: "audio", buffer }, [buffer]);
    this.meterFrames += 1;
    if (this.meterFrames >= 3) {
      this.port.postMessage({ type: "level", rms: Math.sqrt(this.energy / this.frameSize) });
      this.meterFrames = 0;
    }
    this.framePosition = 0;
    this.energy = 0;
  }

  process(inputs, outputs) {
    for (const output of outputs) for (const channel of output) channel.fill(0);
    const channels = inputs[0];
    if (!this.enabled || !channels || !channels.length || !channels[0].length) return true;

    const count = channels[0].length;
    for (let i = 0; i < count; i += 1) {
      let mono = 0;
      for (let c = 0; c < channels.length; c += 1) mono += channels[c][i] || 0;
      const value = this.lowpass(mono / channels.length);
      if (this.sourcePosition === 0) {
        this.emitSample(value);
        this.nextOutputPosition += this.step;
      } else {
        while (this.nextOutputPosition <= this.sourcePosition + 1e-8) {
          const fraction = this.nextOutputPosition - (this.sourcePosition - 1);
          this.emitSample(this.previousSample + (value - this.previousSample) * fraction);
          this.nextOutputPosition += this.step;
        }
      }
      this.previousSample = value;
      this.sourcePosition += 1;
    }
    return true;
  }
}

registerProcessor("jarvis-capture", JarvisCaptureProcessor);
