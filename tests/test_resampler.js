/* Run with Node 20+: node --test tests/test_resampler.js
 * Exercises the actual AudioWorklet algorithm with synthetic PCM; no browser,
 * microphone, audio driver, speech model, or hardware latency is measured.
 */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "..", "jarvis", "static", "capture-worklet.js"), "utf8");

function processor(rate) {
  let Processor;
  const messages = [];
  class Base {
    constructor() { this.port = { onmessage: null, postMessage: (message) => messages.push(message) }; }
  }
  vm.runInNewContext(script, {
    AudioWorkletProcessor: Base, sampleRate: rate,
    registerProcessor: (name, implementation) => { assert.equal(name, "jarvis-capture"); Processor = implementation; },
  }, { filename: "capture-worklet.js" });
  const worklet = new Processor({ processorOptions: { targetSampleRate: 16000, frameSize: 512 } });
  worklet.port.onmessage({ data: { type: "capture", enabled: true, reset: true } });
  return { worklet, messages };
}

function feed(worklet, rate, seconds, frequency = 440) {
  const total = rate * seconds;
  for (let offset = 0; offset < total; offset += 128) {
    const length = Math.min(128, total - offset);
    const input = Float32Array.from({ length }, (_, i) => 0.2 * Math.sin(2 * Math.PI * frequency * (offset + i) / rate));
    const output = new Float32Array(length).fill(1);
    assert.equal(worklet.process([[input]], [[output]]), true);
    assert(output.every((value) => value === 0), "capture graph must not echo microphone input");
  }
}

for (const rate of [16000, 44100, 48000]) {
  test(`${rate} Hz input yields exact PCM16LE frames and continuous 16 kHz duration`, () => {
    const { worklet, messages } = processor(rate);
    feed(worklet, rate, 10);
    const frames = messages.filter((item) => item.type === "audio");
    assert(frames.every((frame) => frame.buffer.byteLength === 1024));
    assert.equal(frames.length * 512 + worklet.framePosition, 160000);
    let energy = 0;
    let count = 0;
    for (const frame of frames) {
      const view = new DataView(frame.buffer);
      for (let n = 0; n < 512; n++) {
        const sample = view.getInt16(n * 2, true) / 32768;
        energy += sample * sample;
        count += 1;
      }
    }
    assert(Math.abs(Math.sqrt(energy / count) - 0.2 / Math.sqrt(2)) < 0.002);
    worklet.port.onmessage({ data: { type: "capture", enabled: false, reset: true } });
    const prior = messages.length;
    feed(worklet, rate, 1);
    assert.equal(messages.length, prior);
    assert.equal(worklet.framePosition, 0);
    worklet.port.onmessage({ data: { type: "capture", enabled: true, reset: true } });
    feed(worklet, rate, 1);
    assert.equal((messages.filter((item) => item.type === "audio").length - frames.length) * 512 + worklet.framePosition, 16000);
  });
}

test("48 kHz downsampling suppresses an above-Nyquist 12 kHz tone", () => {
  const { worklet, messages } = processor(48000);
  feed(worklet, 48000, 1, 12000);
  const frames = messages.filter((item) => item.type === "audio");
  let peak = 0;
  // Skip the filter's startup transient.
  for (const frame of frames.slice(1)) {
    const view = new DataView(frame.buffer);
    for (let n = 0; n < 512; n++) peak = Math.max(peak, Math.abs(view.getInt16(n * 2, true) / 32768));
  }
  assert(peak < 0.005, `aliased peak ${peak} exceeds bound`);
});
