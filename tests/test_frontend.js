/* Run with Node 20+: node --test tests/test_frontend.js
 * Deterministic protocol tests, not browser/microphone/hardware validation.
 * No third-party packages, network, or real credentials are used.
 */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const staticDir = path.join(__dirname, "..", "jarvis", "static");
const html = fs.readFileSync(path.join(staticDir, "index.html"), "utf8");
const script = fs.readFileSync(path.join(staticDir, "app.js"), "utf8");
const flush = async () => { for (let n = 0; n < 6; n++) await Promise.resolve(); };

class Element {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.events = new Map();
    this.dataset = {};
    this.attributes = {};
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.value = "";
    this.textContent = "";
    this.isConnected = false;
    this.scrollHeight = this.clientHeight = this.scrollTop = 0;
    this.style = { setProperty() {} };
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, listener) {
    if (!this.events.has(name)) this.events.set(name, []);
    this.events.get(name).push(listener);
  }
  async fire(name, fields = {}) {
    const event = { preventDefault() {}, ...fields };
    await Promise.all((this.events.get(name) || []).map((listener) => listener(event)));
    await flush();
  }
  appendChild(child) {
    child.parent = this;
    child.isConnected = this.isConnected;
    this.children.push(child);
    return child;
  }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  replaceChildren(...children) {
    for (const child of this.children) child.isConnected = false;
    this.children = [];
    this.append(...children);
  }
  remove() {
    if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1);
    this.isConnected = false;
  }
  focus() {}
  requestSubmit() { return this.fire("submit"); }
  get childElementCount() { return this.children.length; }
  get firstElementChild() { return this.children[0]; }
}

function harness(t, options = {}) {
  const nodes = new Map();
  for (const match of html.matchAll(/<([a-z]+)[^>]*\sid="([^"]+)"[^>]*>/g)) {
    const element = new Element(match[1]);
    element.isConnected = true;
    element.hidden = /\bhidden(?:\s|>)/.test(match[0]);
    element.disabled = /\bdisabled(?:\s|>)/.test(match[0]);
    element.checked = /\bchecked(?:\s|>)/.test(match[0]);
    nodes.set(match[2], element);
  }
  const record = { controls: [], binary: [], sources: [], tracks: [], worklets: [], contexts: [], confirmations: [] };
  let now = 0;
  let nextTimer = 0;
  const timers = new Map();
  const clock = {
    now: () => now,
    setTimeout(fn, delay) { const id = ++nextTimer; timers.set(id, { fn, at: now + delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
    advance(milliseconds) {
      now += milliseconds;
      for (const [id, timer] of [...timers]) {
        if (timer.at <= now && timers.delete(id)) timer.fn();
      }
    },
  };
  const browserEvents = new Map();
  const storage = new Map();
  const location = new URL("http://127.0.0.1:8765/#token=test-launch-token");
  const history = { replaceState(_a, _b, url) { location.href = new URL(url, location).href; } };
  const noopNode = () => ({ connect() {}, disconnect() {} });

  class AudioContext {
    constructor() {
      record.contexts.push(this);
      this.state = "running";
      this.destination = {};
      this.audioWorklet = { addModule: async () => {} };
    }
    get currentTime() { return now / 1000; }
    async resume() { this.state = "running"; }
    async close() { this.state = "closed"; }
    createMediaStreamSource() { return noopNode(); }
    createGain() { return { ...noopNode(), gain: { value: 1 } }; }
    createBuffer(_channels, count, sampleRate) {
      const channel = new Float32Array(count);
      return { duration: count / sampleRate, getChannelData: () => channel };
    }
    createBufferSource() {
      const source = {
        ...noopNode(), onended: null, stopped: false, ended: false,
        start(at) { this.startedAt = at; record.sources.push(this); },
        stop() { this.stopped = true; this.finish(); },
        finish() { if (!this.ended) { this.ended = true; if (this.onended) this.onended(); } },
      };
      return source;
    }
  }
  class Worklet {
    constructor() {
      this.gates = [];
      this.port = { onmessage: null, postMessage: (message) => this.gates.push(message) };
      record.worklets.push(this);
    }
    connect() {}
    disconnect() {}
    get enabled() { return this.gates.length ? this.gates.at(-1).enabled : false; }
    emit(buffer) { if (this.port.onmessage) this.port.onmessage({ data: { type: "audio", buffer } }); }
  }
  const media = {
    getUserMedia: async () => {
      const track = { readyState: "live", stop() { this.readyState = "ended"; }, addEventListener() {} };
      record.tracks.push(track);
      return { getTracks: () => [track], getAudioTracks: () => [track] };
    },
  };

  let serverEpoch = 0;
  let socket;
  let configured = false;
  let speechEnabled = true;
  let planDraft = null;
  let planSaved = null;
  let confirmation = true;
  const defaultProfile = { schema_version: 1, assistant_name: "Jarvis", user_name: "", style: "friendly", verbosity: "short", pause: "balanced", output: "speakers", onboarding_complete: false };
  class WebSocket {
    static OPEN = 1;
    constructor() {
      socket = this;
      planDraft = null; // A reconnect creates a new server session, not a durable draft.
      this.readyState = 1;
      this.bufferedAmount = 0;
      this.deferredControls = [];
      this.deferEpochs = false;
      this.deferHello = false;
      queueMicrotask(() => { if (this.onopen) this.onopen(); });
    }
    deliver(message) {
      if (this.onmessage) this.onmessage({ data: JSON.stringify({ session_id: "test-session", ...message }) });
    }
    acknowledge(message) {
      serverEpoch += 1;
      this.deliver({ type: "epoch", epoch: serverEpoch, request_id: message.request_id });
      if (message.type === "text") {
        this.deliver({ type: "transcript", role: "user", epoch: serverEpoch, text: message.text });
        this.deliver({ type: "transcript", role: "assistant", epoch: serverEpoch, text: "Merhaba." });
        if (speechEnabled) this.audio("text-reply");
        this.deliver({ type: "audio_end", epoch: serverEpoch });
      } else if (message.type === "profile_save") {
        this.deliver({ type: "profile", profile: message.profile, onboarding: { active: false, stage: "done" } });
      } else if (["plan_save", "plan_discard", "plan_delete"].includes(message.type)) {
        if (message.type === "plan_save" && planDraft && message.draft_id === planDraft.id) {
          planSaved = planDraft;
          planDraft = null;
        } else if (message.type === "plan_discard" && planDraft && message.draft_id === planDraft.id) {
          planDraft = null;
        } else if (message.type === "plan_delete" && planSaved && message.plan_id === planSaved.id) {
          planSaved = null;
        }
        this.deliver({ type: "plan", epoch: serverEpoch, draft: planDraft, saved: planSaved });
      } else {
        this.deliver({ type: "status", message: message.type === "stop" ? "Mikrofon kapalı." : "Seni dinliyorum…" });
      }
    }
    audio(segmentId, epoch = serverEpoch) {
      this.deliver({ type: "audio", epoch, segment_id: segmentId, sample_rate: 24000, pcm: Buffer.alloc(4800).toString("base64"), text: "Merhaba." });
    }
    send(data) {
      if (data instanceof ArrayBuffer) { record.binary.push(data); return; }
      const message = JSON.parse(data);
      record.controls.push(message);
      queueMicrotask(() => {
        if (message.type === "hello") {
          if (this.deferHello) return;
          this.deliver({ type: "hello", epoch: serverEpoch, ready: options.ready !== false, model: "gpt-oss:20b", endpoint: "local" });
          this.deliver({ type: "ready", ready: options.ready !== false });
          this.deliver({ type: "profile", profile: defaultProfile, onboarding: { active: false, stage: "" } });
        } else if (message.type === "settings") {
          if (message.api_key !== undefined) configured = !!message.api_key;
          speechEnabled = message.speech_enabled === true;
          this.deliver({ type: "settings", web_enabled: message.web_enabled && configured, barge_in: message.barge_in, api_key_configured: configured, acoustic_enabled: message.acoustic_enabled, desktop_enabled: message.desktop_enabled, speech_enabled: speechEnabled });
        } else if (message.type === "plan_get") {
          this.deliver({ type: "plan", epoch: serverEpoch, draft: planDraft, saved: planSaved });
        } else if (message.type === "apps_get") {
          this.deliver({ type: "apps", items: [{ id: "calculator", label: "Hesap Makinesi", available: true }] });
        } else if (["start", "stop", "interrupt", "text", "onboarding_start", "onboarding_cancel", "calibration_start", "calibration_cancel", "calibration_apply", "profile_save", "plan_save", "plan_discard", "plan_delete"].includes(message.type)) {
          if (this.deferEpochs) this.deferredControls.push(message);
          else this.acknowledge(message);
        }
      });
    }
    close(code = 1000) { this.readyState = 3; if (this.onclose) this.onclose({ code }); }
  }

  const window = {
    location, AudioContext, setTimeout: clock.setTimeout, clearTimeout: clock.clearTimeout,
    sessionStorage: { getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) },
    // Any accidental persistent storage access fails the test immediately.
    get localStorage() { throw new Error("localStorage must not be used"); },
    addEventListener: (name, listener) => browserEvents.set(name, listener), scrollTo() {},
    confirm(message) { record.confirmations.push(message); return confirmation; },
  };
  const document = {
    getElementById: (id) => { assert(nodes.has(id), `missing HTML id: ${id}`); return nodes.get(id); },
    createElement: (tag) => new Element(tag),
    createTextNode: (text) => ({ textContent: text }),
  };
  const context = { window, document, history, navigator: { mediaDevices: media }, WebSocket,
    AudioWorkletNode: Worklet, performance: { now: clock.now }, URL, URLSearchParams,
    ArrayBuffer, DataView, Uint8Array, Float32Array, atob: (value) => Buffer.from(value, "base64").toString("binary") };
  vm.runInNewContext(script, context, { filename: "app.js" });
  t.after(async () => { if (browserEvents.has("pagehide")) browserEvents.get("pagehide")(); await flush(); });
  return {
    get socket() { return socket; }, get epoch() { return serverEpoch; }, record, storage, location,
    clock, media, el: (id) => nodes.get(id),
    confirm(value) { confirmation = value; },
    setPlans(draft, saved = null) {
      planDraft = draft;
      planSaved = saved;
      socket.deliver({ type: "plan", epoch: serverEpoch, draft, saved });
    },
    async start() { await flush(); await nodes.get("voice-toggle").fire("click"); await flush(); },
    unsolicitedEpoch() { serverEpoch += 1; socket.deliver({ type: "epoch", epoch: serverEpoch }); },
  };
}

test("authenticated startup removes the fragment; API key stays out of storage", async (t) => {
  const h = harness(t);
  await flush();
  assert.equal(h.location.hash, "");
  assert.equal(h.storage.get("jarvis_voice_launch_token"), "test-launch-token");
  assert.deepEqual(h.record.controls[0], { type: "hello", token: "test-launch-token", protocol: 3 });
  assert.equal(h.el("voice-toggle").disabled, false);
  h.el("api-key").value = "test-only-api-key";
  await h.el("api-key-form").fire("submit");
  assert.equal(h.el("api-key").value, "");
  assert.equal([...h.storage.values()].includes("test-only-api-key"), false);
  assert.match(h.el("api-key-status").textContent, /bu oturum/);
});

test("text response acknowledges only a completed playback", async (t) => {
  const h = harness(t);
  await flush();
  h.el("text-input").value = "Merhaba";
  await h.el("text-form").fire("submit");
  assert.equal(h.record.sources.length, 1);
  assert.equal(h.record.controls.filter((item) => item.type === "played").length, 0);
  h.record.sources[0].finish();
  assert.equal(h.record.controls.filter((item) => item.type === "played").length, 1);
  assert.equal(h.el("transcript-messages").children.length, 2);
});

test("interrupt rejects stale audio and unsolicited epochs until its own ACK", async (t) => {
  const h = harness(t);
  await h.start();
  h.socket.audio("playing");
  h.socket.audio("queued");
  const oldEpoch = h.epoch;
  assert.equal(h.record.sources.length, 2);
  h.socket.deferEpochs = true;
  await h.el("interrupt").fire("click");
  assert(h.record.sources.every((source) => source.stopped));
  assert.equal(h.record.controls.filter((item) => item.type === "played").length, 0);
  h.socket.audio("stale-before-ack", oldEpoch);
  h.unsolicitedEpoch();
  h.socket.audio("in-flight-other-turn");
  assert.equal(h.record.sources.length, 2);
  h.socket.acknowledge(h.socket.deferredControls.shift());
  h.socket.audio("stale-after-ack", oldEpoch);
  h.socket.audio("current-after-ack");
  assert.equal(h.record.sources.length, 3);
});

test("mic gate resets across playback and tail; a speech epoch does not clip input", async (t) => {
  const h = harness(t);
  await h.start();
  const worklet = h.record.worklets[0];
  assert.equal(worklet.enabled, true);
  worklet.emit(new ArrayBuffer(1024));
  worklet.emit(new ArrayBuffer(12));
  assert.equal(h.record.binary.length, 1);
  h.unsolicitedEpoch();
  assert.equal(worklet.enabled, true, "speech-onset epoch must not create an output tail");
  h.socket.audio("output");
  assert.equal(worklet.enabled, false);
  worklet.emit(new ArrayBuffer(1024));
  assert.equal(h.record.binary.length, 1, "main thread also checks the gate");
  h.socket.deliver({ type: "audio_end", epoch: h.epoch });
  h.record.sources[0].finish();
  assert.equal(h.record.tracks[0].readyState, "live", "audio_end must not end capture");
  assert.equal(worklet.enabled, false);
  h.clock.advance(360);
  assert.equal(worklet.enabled, true);
  assert(worklet.gates.every((gate) => gate.reset === true));
  h.el("barge-in").checked = true;
  await h.el("barge-in").fire("change");
  h.socket.audio("headphones-output");
  assert.equal(worklet.enabled, true, "headphone setting allows interruption by voice");
});

test("capture_stop closes the microphone and returns to an explicit start", async (t) => {
  const h = harness(t);
  await h.start();
  h.socket.audio("output");
  h.socket.deliver({ type: "capture_stop", message: "Tek seferde en fazla 30 saniye konuşabilirsin." });
  assert(h.record.tracks.every((track) => track.readyState === "ended"));
  assert(h.record.sources.every((source) => source.stopped));
  assert.equal(h.el("voice-toggle-label").textContent, "Konuşmaya başla");
  assert.equal(h.el("notice").hidden, false);
  assert.match(h.el("notice-text").textContent, /30 saniye/);
  h.socket.audio("late-after-capture-stop");
  assert.equal(h.record.sources.length, 1);
});

test("cancel during permission request stops a late-arriving microphone", async (t) => {
  const h = harness(t);
  await flush();
  let resolvePermission;
  const track = { readyState: "live", stop() { this.readyState = "ended"; } };
  h.media.getUserMedia = () => new Promise((resolve) => { resolvePermission = resolve; });
  await h.el("voice-toggle").fire("click");
  assert.equal(h.el("voice-toggle-label").textContent, "Açmayı iptal et");
  await h.el("voice-toggle").fire("click");
  resolvePermission({ getTracks: () => [track], getAudioTracks: () => [track] });
  await flush();
  assert.equal(track.readyState, "ended");
  assert.equal(h.record.worklets.length, 0);
  assert.equal(h.el("voice-toggle-label").textContent, "Konuşmaya başla");
});

test("source labels remain plain text and unsafe URLs are discarded", async (t) => {
  const h = harness(t);
  await flush();
  h.socket.deliver({ type: "sources", epoch: h.epoch, items: [
    { title: "bad", url: "javascript:alert(1)" },
    { title: "credentials", url: "https://user:pass@example.com/" },
    { title: "<img src=x onerror=alert(1)>", url: "https://example.com/article" },
  ] });
  const links = h.el("source-list").children;
  assert.equal(links.length, 1);
  assert.equal(links[0].textContent, "<img src=x onerror=alert(1)>");
  assert.equal(links[0].children.length, 0);
  assert.equal(links[0].rel, "noopener noreferrer");
});

test("profile and first onboarding prompt render as plain text without opening a microphone", async (t) => {
  const h = harness(t);
  await flush();
  assert.equal(h.el("voice-title").textContent, "Önce tanışalım mı?");
  h.socket.deliver({ type: "profile", profile: {
    schema_version: 1, assistant_name: "<svg onload=alert(1)>", user_name: "<b>Muzaffer</b>",
    style: "friendly", verbosity: "medium", pause: "relaxed", output: "headphones", onboarding_complete: true,
  } });
  assert.equal(h.el("brand-name").textContent, "<svg onload=alert(1)>");
  assert.equal(h.el("brand-name").children.length, 0);
  assert.equal(h.el("barge-in").checked, false, "headphones do not imply permission for barge-in");
  h.socket.deliver({ type: "onboarding", epoch: h.epoch, active: true, stage: "user_name", message: "Sana nasıl hitap edeyim?" });
  assert.equal(h.el("guided-panel").hidden, false);
  assert.equal(h.el("guided-message").textContent, "Sana nasıl hitap edeyim?");
  assert.equal(h.record.tracks.length, 0);
  assert.match(h.el("guided-hint").textContent, /Mikrofon kapalı/);
  assert.equal(h.record.controls.some((item) => item.type === "profile_save"), false);
});

test("profile edit is saved only by explicit submit and never enters browser storage", async (t) => {
  const h = harness(t);
  await flush();
  h.el("profile-user-name").value = "Muzaffer";
  h.el("profile-assistant-name").value = "Atlas";
  h.el("profile-style").value = "friendly";
  await h.el("profile-form").fire("input");
  assert.equal(h.record.controls.some((item) => item.type === "profile_save"), false);
  h.socket.deliver({ type: "profile", profile: { schema_version: 1, assistant_name: "Jarvis", user_name: "", style: "balanced", verbosity: "short", pause: "balanced", output: "speakers", onboarding_complete: false } });
  assert.equal(h.el("profile-assistant-name").value, "Atlas", "unrelated profile event does not overwrite an unsaved draft");
  await h.el("profile-form").fire("submit");
  const message = h.record.controls.find((item) => item.type === "profile_save");
  assert.equal(message.profile.assistant_name, "Atlas");
  assert.equal(message.profile.user_name, "Muzaffer");
  assert.equal(message.profile.onboarding_complete, true);
  assert.equal(typeof message.request_id, "string");
  assert.equal(h.el("brand-name").textContent, "Atlas");
  assert.equal(h.el("profile-status").textContent, "Tercihlerin kaydedildi.");
  assert.equal(h.record.tracks.length, 0);
  assert.deepEqual([...h.storage.keys()], ["jarvis_voice_launch_token"]);
});

test("guided controls wait for authentication and never infer microphone consent from server events", async (t) => {
  const h = harness(t);
  h.socket.deferHello = true;
  await flush();
  await h.el("onboarding-start").fire("click");
  await h.el("calibration-start").fire("click");
  await h.el("profile-form").fire("submit");
  assert.equal(h.record.tracks.length, 0);
  assert.deepEqual(h.record.controls.map((item) => item.type), ["hello"]);
  h.socket.deliver({ type: "calibration", stage: "noise", message: "Şimdi sessiz kal." });
  assert.equal(h.record.tracks.length, 0);
});

test("guided start requests one microphone and its own epoch without a redundant start", async (t) => {
  const h = harness(t);
  await flush();
  await h.el("onboarding-start").fire("click");
  await flush();
  assert.equal(h.record.tracks.length, 1);
  assert.equal(h.record.controls.filter((item) => item.type === "start").length, 0);
  assert.equal(h.record.controls.filter((item) => item.type === "onboarding_start").length, 1);
  h.socket.deliver({ type: "onboarding", active: true, stage: "user_name", message: "Adın ne?", epoch: h.epoch });
  h.socket.audio("onboarding-question");
  const oldEpoch = h.epoch;
  h.socket.deferEpochs = true;
  await h.el("guided-cancel").fire("click");
  const cancel = h.record.controls.find((item) => item.type === "onboarding_cancel");
  assert.equal(typeof cancel.request_id, "string");
  h.unsolicitedEpoch();
  h.socket.audio("old-guided-output");
  assert.equal(h.record.sources.length, 1);
  h.socket.acknowledge(h.socket.deferredControls.shift());
  h.socket.deliver({ type: "onboarding", epoch: oldEpoch, active: true, stage: "name", message: "Eski soru" });
  assert.equal(h.el("guided-panel").hidden, true);
  assert.equal(h.record.tracks[0].readyState, "live", "cancel introduction leaves mic under user's prior choice");
});

for (const control of ["onboarding-start", "calibration-start"]) {
  test(`cancel ${control} during permission closes a late microphone`, async (t) => {
    const h = harness(t);
    await flush();
    let resolvePermission;
    const track = { readyState: "live", stop() { this.readyState = "ended"; } };
    h.media.getUserMedia = () => new Promise((resolve) => { resolvePermission = resolve; });
    await h.el(control).fire("click");
    assert.equal(h.el("guided-panel").hidden, false);
    await h.el("guided-cancel").fire("click");
    resolvePermission({ getTracks: () => [track], getAudioTracks: () => [track] });
    await flush();
    assert.equal(track.readyState, "ended");
    assert.equal(h.record.worklets.length, 0);
    assert.equal(h.record.controls.filter((item) => item.type === control.replace("-", "_")).length, 0);
    assert.equal(h.el("guided-panel").hidden, true);
  });
}

test("calibration shows measurements honestly and applies only an explicit eligible result", async (t) => {
  const h = harness(t);
  await flush();
  h.socket.deliver({ type: "calibration", stage: "result", message: "Mikrofonun kontrol edildi.", measurements: {
    noise_dbfs: -55, noise_peak_dbfs: -45, voiced_dbfs: -24, snr_db: 31, clipping_pct: 0,
    word_error_rate: 0.125, reference_text: "Bir örnek cümle.", phrase_text: "<img src=x>",
    suggested_vad_threshold: 0.62, can_apply: false,
  } });
  assert.equal(h.el("calibration-result").hidden, false);
  assert.equal(h.el("calibration-apply").hidden, true);
  assert.equal(h.el("calibration-heard").textContent, "<img src=x>");
  assert.equal(h.el("calibration-heard").children.length, 0);
  const readings = h.el("calibration-measurements").children.map((item) => item.textContent);
  assert(readings.includes("12,5%"));
  await h.el("calibration-apply").fire("click");
  assert.equal(h.record.controls.some((item) => item.type === "calibration_apply"), false);
  h.socket.deliver({ type: "calibration", stage: "result", measurements: { can_apply: true, suggested_vad_threshold: 0.62 } });
  assert.equal(h.el("calibration-apply").hidden, false);
  assert.equal(h.record.controls.some((item) => item.type === "calibration_apply"), false);
  await h.el("calibration-apply").fire("click");
  const applied = h.record.controls.find((item) => item.type === "calibration_apply");
  assert.deepEqual(Object.keys(applied).sort(), ["request_id", "type"]);
  assert.equal(h.record.tracks.length, 0);
});

test("late calibration events cannot resume a stopped microphone", async (t) => {
  const h = harness(t);
  await flush();
  await h.el("calibration-start").fire("click");
  await flush();
  h.socket.deliver({ type: "calibration", stage: "noise", epoch: h.epoch, message: "Sessiz kal." });
  const previousEpoch = h.epoch;
  await h.el("voice-toggle").fire("click");
  assert(h.record.tracks.every((track) => track.readyState === "ended"));
  h.socket.deliver({ type: "calibration", stage: "phrase", epoch: previousEpoch, message: "Şimdi konuş." });
  h.clock.advance(1000);
  assert.equal(h.el("guided-panel").hidden, true);
  assert.equal(h.record.tracks.length, 1);
  assert(h.record.tracks.every((track) => track.readyState === "ended"));
});

test("timings label readiness rather than unmeasured loudspeaker latency", async (t) => {
  const h = harness(t);
  await flush();
  h.socket.deliver({ type: "metrics", asr_ms: 350, endpoint_ms: 800, llm_first_ms: 120,
    tts_first_ms: 80, first_audio_ms: 1400, server_audio_ready_ms: 1450, tts_rtf: 0.2 });
  assert.equal(h.el("metrics-details").hidden, false);
  assert.match(h.el("last-latency").textContent, /İlk ses hazır/);
  const readings = h.el("timing-measurements").children.map((item) => item.textContent);
  assert(readings.includes("1,45 sn"));
  assert(readings.includes("0,2×"));
  assert.equal(readings.some((text) => /duyma|hoparlör/.test(text)), false);
});

test("metrics reject stale epochs and pending controls; guided timings do not invent LLM latency", async (t) => {
  const h = harness(t);
  await h.start();
  h.socket.deliver({ type: "metrics", epoch: h.epoch, turn_id: "first", first_audio_ms: 500, measurement_kind: "conversation" });
  const previous = h.el("last-latency").textContent;
  h.socket.deferEpochs = true;
  await h.el("interrupt").fire("click");
  h.socket.deliver({ type: "metrics", epoch: h.epoch, turn_id: "old", first_audio_ms: 9999 });
  assert.equal(h.el("last-latency").textContent, previous);
  h.unsolicitedEpoch();
  h.socket.deliver({ type: "metrics", epoch: h.epoch, turn_id: "inflight", first_audio_ms: 8888 });
  assert.equal(h.el("last-latency").textContent, previous);
  h.socket.acknowledge(h.socket.deferredControls.shift());
  h.socket.deliver({ type: "metrics", epoch: h.epoch - 1, turn_id: "stale", first_audio_ms: 7777 });
  assert.equal(h.el("last-latency").textContent, previous);
  h.socket.deliver({ type: "metrics", epoch: h.epoch, turn_id: "guided", first_audio_ms: 100, llm_first_ms: null, tts_first_ms: 80, measurement_kind: "guided" });
  assert.match(h.el("timing-context").textContent, /dil modeli kullanılmadı/);
  const labels = h.el("timing-measurements").children.map((item) => item.textContent);
  assert(!labels.includes("İlk yanıt metnini hazırlama"));
});

test("microphone settings report actual whitelisted values and clear on stop", async (t) => {
  const h = harness(t);
  await flush();
  let reads = 0;
  const track = {
    label: "Do not transmit microphone label", readyState: "live",
    stop() { this.readyState = "ended"; }, addEventListener() {},
    getSettings() {
      reads += 1;
      return { sampleRate: 48000, channelCount: 1, echoCancellation: true, noiseSuppression: false, autoGainControl: true,
        deviceId: "private-device-id", groupId: "private-group", label: "private-label" };
    },
  };
  h.media.getUserMedia = async () => {
    h.record.tracks.push(track);
    return { getTracks: () => [track], getAudioTracks: () => [track] };
  };
  await h.start();
  const opened = h.record.controls.find((item) => item.type === "capture_info");
  assert.deepEqual(opened, { type: "capture_info", sample_rate: 48000, channel_count: 1,
    echo_cancellation: true, noise_suppression: false, auto_gain_control: true });
  assert.equal(reads, 1);
  assert(!JSON.stringify(h.record.controls).includes("private-"));
  assert(!JSON.stringify(h.record.controls).includes("microphone label"));
  await h.el("voice-toggle").fire("click");
  const closed = h.record.controls.filter((item) => item.type === "capture_info").at(-1);
  assert.deepEqual(closed, { type: "capture_info", sample_rate: null, channel_count: null,
    echo_cancellation: null, noise_suppression: null, auto_gain_control: null });
});

function acousticSample() {
  return { schema_version: 1, duration_s: 3.5, rms_dbfs: -25, peak_dbfs: -8, clipping_pct: 0,
    speech_fraction: 0.8, pause_fraction: 0.2, words_per_minute: 120, f0_median_hz: null,
    f0_iqr_hz: null, f0_coverage: 0, analysis_ms: 15, signal_valid: true,
    limitations: ["Tek bir örneğin ölçümüdür.", "<img src=x onerror=alert(1)>"],
    capture: { sample_rate: 48000, channel_count: 1, echo_cancellation: true,
      noise_suppression: true, auto_gain_control: false, deviceId: "must-not-appear" } };
}

test("acoustics require explicit opt-in and are displayed as numeric observations only", async (t) => {
  const h = harness(t);
  await flush();
  assert.equal(h.el("acoustic-enabled").checked, false);
  assert(h.record.controls.filter((item) => item.type === "settings").every((item) => item.acoustic_enabled === false));
  h.el("acoustic-enabled").checked = true;
  await h.el("acoustic-enabled").fire("change");
  assert.equal(h.record.tracks.length, 0, "analysis consent must not open a microphone");
  assert.equal(h.record.controls.filter((item) => item.type === "settings").at(-1).acoustic_enabled, true);
  await h.start();
  h.socket.deliver({ type: "acoustics", epoch: h.epoch, observation: acousticSample() });
  assert.equal(h.el("acoustics-details").hidden, false);
  assert.equal(h.el("acoustics-details").open, undefined, "measurement panel is not automatically expanded");
  const values = h.el("acoustics-measurements").children.map((item) => item.textContent);
  assert(values.includes("120 kelime/dk"));
  assert(values.includes("80%"));
  assert(!values.includes("Temel frekans · ortanca"), "missing F0 must not become a numeric claim");
  const limitations = h.el("acoustics-limitations").children;
  assert.equal(limitations[1].textContent, "<img src=x onerror=alert(1)>");
  assert.equal(limitations[1].children.length, 0);
  assert(!h.el("capture-measurements").children.some((item) => String(item.textContent).includes("must-not-appear")));
  assert.deepEqual([...h.storage.keys()], ["jarvis_voice_launch_token"]);
});

test("turning acoustic inspection off clears results and rejects late observations without stopping conversation", async (t) => {
  const h = harness(t);
  await h.start();
  h.socket.deliver({ type: "acoustics", epoch: h.epoch, observation: acousticSample() });
  assert.equal(h.el("acoustics-details").hidden, true);
  h.el("acoustic-enabled").checked = true;
  await h.el("acoustic-enabled").fire("change");
  h.socket.deliver({ type: "acoustics", epoch: h.epoch, observation: acousticSample() });
  assert.equal(h.el("acoustics-details").hidden, false);
  h.el("acoustic-enabled").checked = false;
  await h.el("acoustic-enabled").fire("change");
  h.socket.deliver({ type: "acoustics", epoch: h.epoch, observation: acousticSample() });
  assert.equal(h.el("acoustics-details").hidden, true);
  assert.equal(h.el("acoustics-measurements").children.length, 0);
  assert.equal(h.el("acoustics-limitations").children.length, 0);
  assert.equal(h.record.tracks[0].readyState, "live");
});

test("acoustic observations cannot survive stop, disconnect, or an outdated epoch", async (t) => {
  const h = harness(t);
  await h.start();
  h.el("acoustic-enabled").checked = true;
  await h.el("acoustic-enabled").fire("change");
  h.socket.deliver({ type: "acoustics", epoch: h.epoch - 1, observation: acousticSample() });
  assert.equal(h.el("acoustics-details").hidden, true);
  h.socket.deliver({ type: "acoustics", epoch: h.epoch, observation: acousticSample() });
  assert.equal(h.el("acoustics-details").hidden, false);
  await h.el("voice-toggle").fire("click");
  h.socket.deliver({ type: "acoustics", epoch: h.epoch, observation: acousticSample() });
  assert.equal(h.el("acoustics-details").hidden, true);
  assert.equal(h.record.tracks.length, 1);
  assert.equal(h.record.tracks[0].readyState, "ended");
  h.socket.close(1000);
  assert.equal(h.el("acoustic-enabled").checked, false);
  assert.equal(h.el("acoustics-details").hidden, true);
});

function planSample(id = "a".repeat(32), title = "Akşam çalışma planı") {
  return { schema_version: 1, id, title, created_at: "2026-11-23T12:00:00+00:00",
    steps: [{ text: "Çalışma alanını hazırla.", minutes: 10 }, { text: "İlk örneği dene.", minutes: null }],
    assumptions: ["Bu akşam yarım saat ayırabildiğini varsaydım."] };
}

test("visible chat waits for readiness and text-only mode needs no microphone or audio context", async (t) => {
  const h = harness(t, { ready: false });
  await flush();
  assert.equal(h.el("transcript-panel").hidden, false);
  assert.equal(h.el("show-transcript").checked, true);
  assert.match(h.el("model-label").textContent, /Yerel model · gpt-oss:20b/);
  assert.equal(h.el("send-text").disabled, true);
  assert.equal(h.el("voice-toggle").disabled, true);
  assert.equal(h.record.controls.filter((item) => item.type === "plan_get").length, 0);
  h.socket.deliver({ type: "ready", ready: true });
  await flush();
  h.socket.deliver({ type: "ready", ready: true });
  await flush();
  assert.equal(h.record.controls.filter((item) => item.type === "plan_get").length, 1);
  assert.equal(h.el("speech-enabled").checked, true);
  h.el("speech-enabled").checked = false;
  await h.el("speech-enabled").fire("change");
  h.el("text-input").value = "Yalnız yazarak sohbet edelim.";
  await h.el("text-form").fire("submit");
  assert.equal(h.record.controls.filter((item) => item.type === "text").at(-1).text, "Yalnız yazarak sohbet edelim.");
  assert.equal(h.record.contexts.length, 0);
  assert.equal(h.record.tracks.length, 0);
  assert.equal(h.record.sources.length, 0);
  assert.equal(h.el("transcript-messages").children.at(-1).children[1].textContent, "Merhaba.");
  assert.deepEqual([...h.storage.keys()], ["jarvis_voice_launch_token"]);
});

test("desktop consent is explicit and session-only; application output rejects pending and stale epochs", async (t) => {
  const h = harness(t);
  await flush();
  assert.equal(h.el("desktop-enabled").checked, false);
  assert(h.record.controls.filter((item) => item.type === "settings").every((item) => item.desktop_enabled === false));
  h.socket.deliver({ type: "settings", desktop_enabled: true });
  assert.equal(h.el("desktop-enabled").checked, false, "server ACK cannot supply user consent");
  h.el("desktop-enabled").checked = true;
  await h.el("desktop-enabled").fire("change");
  assert.equal(h.record.controls.filter((item) => item.type === "settings").at(-1).desktop_enabled, true);
  assert.equal(h.record.controls.filter((item) => item.type === "apps_get").length, 1);
  assert.equal(h.record.tracks.length, 0);
  h.socket.deliver({ type: "apps", items: [{ id: "calculator", label: "<img src=x onerror=alert(1)>", available: true }] });
  assert.equal(h.el("apps-list").children[0].textContent, "<img src=x onerror=alert(1)> · hazır");
  assert.equal(h.el("apps-list").children[0].children.length, 0);
  const result = { type: "application", epoch: h.epoch, app_id: "calculator", label: "Hesap Makinesi", status: "requested", message: "<b>Başlatma isteği gönderildi.</b>" };
  h.socket.deliver(result);
  assert.equal(h.el("application-result").textContent, result.message);
  assert.equal(h.el("application-result").children.length, 0);
  const previousEpoch = h.epoch;
  h.socket.deferEpochs = true;
  await h.el("interrupt").fire("click");
  h.socket.deliver({ ...result, message: "Pending result" });
  h.unsolicitedEpoch();
  h.socket.deliver({ ...result, epoch: h.epoch, message: "Unsolicited epoch result" });
  assert.equal(h.el("application-result").textContent, result.message);
  h.socket.acknowledge(h.socket.deferredControls.shift());
  h.socket.deliver({ ...result, epoch: previousEpoch, message: "Stale result" });
  assert.equal(h.el("application-result").textContent, result.message);
  h.el("desktop-enabled").checked = false;
  await h.el("desktop-enabled").fire("change");
  h.socket.deliver({ type: "settings", desktop_enabled: true });
  h.socket.deliver({ ...result, epoch: h.epoch });
  assert.equal(h.el("desktop-enabled").checked, false);
  assert.equal(h.el("application-result").hidden, true);
  assert.equal(h.el("apps-list").children.length, 0);
  assert.deepEqual([...h.storage.keys()], ["jarvis_voice_launch_token"]);
});

test("plan drafts and saved plans render as text and never save themselves", async (t) => {
  const h = harness(t);
  await flush();
  const draft = planSample("a".repeat(32), "<svg onload=alert(1)>");
  draft.steps[0].text = "<img src=x onerror=alert(1)>";
  draft.assumptions[0] = "<script>unsafe()</script>";
  const saved = planSample("b".repeat(32), "Kayıtlı çalışma planı");
  h.setPlans(draft, saved);
  assert.equal(h.el("plan-draft").hidden, false);
  assert.equal(h.el("plan-saved").hidden, false);
  assert.equal(h.el("plan-draft-title").textContent, draft.title);
  assert.equal(h.el("plan-draft-title").children.length, 0);
  assert.equal(h.el("plan-draft-steps").children[0].children[0].textContent, draft.steps[0].text);
  assert.equal(h.el("plan-draft-steps").children[0].children[0].children.length, 0);
  assert.equal(h.el("plan-draft-steps").children[0].children[1].textContent, "Yaklaşık 10 dakika");
  assert.equal(h.el("plan-draft-steps").children[1].children.length, 1, "unknown duration is not invented");
  assert.equal(h.el("plan-draft-assumptions").children[0].textContent, draft.assumptions[0]);
  assert.equal(h.el("plan-draft-assumptions").children[0].children.length, 0);
  assert.equal(h.el("plan-saved-title").textContent, saved.title);
  assert.equal(h.record.controls.some((item) => ["plan_save", "plan_discard", "plan_delete"].includes(item.type)), false);
  h.socket.deliver({ type: "plan", epoch: h.epoch, draft: { ...draft, schema_version: 99 }, saved: null });
  assert.equal(h.el("plan-saved-title").textContent, saved.title, "unknown schema cannot replace visible canonical state");
  assert.equal(h.record.tracks.length, 0);
  assert.deepEqual([...h.storage.keys()], ["jarvis_voice_launch_token"]);
});

test("plan mutations send current IDs once, await their own epoch ACK, and require explicit deletion", async (t) => {
  const h = harness(t);
  await flush();
  const draft = planSample();
  const saved = planSample("b".repeat(32), "Önceki plan");
  h.setPlans(draft, saved);
  h.socket.deferEpochs = true;
  await h.el("plan-save").fire("click");
  const save = h.record.controls.find((item) => item.type === "plan_save");
  assert.deepEqual(Object.keys(save).sort(), ["draft_id", "request_id", "type"]);
  assert.equal(save.draft_id, draft.id);
  assert.equal(typeof save.request_id, "string");
  assert.equal(h.el("plan-save").disabled, true);
  await h.el("plan-save").fire("click");
  assert.equal(h.record.controls.filter((item) => item.type === "plan_save").length, 1);
  h.socket.deliver({ type: "plan", epoch: h.epoch, draft: null, saved: null });
  h.unsolicitedEpoch();
  h.socket.deliver({ type: "plan", epoch: h.epoch, draft: null, saved: null });
  assert.equal(h.el("plan-draft").hidden, false);
  assert.equal(h.el("plan-saved-title").textContent, saved.title);
  h.socket.acknowledge(h.socket.deferredControls.shift());
  assert.equal(h.el("plan-draft").hidden, true);
  assert.equal(h.el("plan-saved-title").textContent, draft.title);
  h.socket.deferEpochs = false;
  const anotherDraft = planSample("c".repeat(32), "Başka taslak");
  h.setPlans(anotherDraft, draft);
  await h.el("plan-discard").fire("click");
  assert.equal(h.record.controls.find((item) => item.type === "plan_discard").draft_id, anotherDraft.id);
  assert.equal(h.el("plan-draft").hidden, true);
  assert.equal(h.el("plan-saved-title").textContent, draft.title);
  h.confirm(false);
  await h.el("plan-delete").fire("click");
  assert.equal(h.record.controls.some((item) => item.type === "plan_delete"), false);
  h.confirm(true);
  await h.el("plan-delete").fire("click");
  const deletion = h.record.controls.find((item) => item.type === "plan_delete");
  assert.deepEqual(Object.keys(deletion).sort(), ["plan_id", "request_id", "type"]);
  assert.equal(deletion.plan_id, draft.id);
  assert.equal(h.el("plan-saved").hidden, true);
  assert.equal(h.record.confirmations.length, 2);
  assert.equal(h.record.tracks.length, 0);
  assert.equal(h.record.contexts.length, 0);
});

test("stopping the microphone preserves plans; reconnect clears drafts and rereads saved state", async (t) => {
  const h = harness(t);
  await h.start();
  const draft = planSample();
  const saved = planSample("b".repeat(32), "Kalıcı plan");
  h.setPlans(draft, saved);
  const oldEpoch = h.epoch;
  await h.el("voice-toggle").fire("click");
  assert.equal(h.el("plan-draft").hidden, false);
  assert.equal(h.el("plan-saved-title").textContent, saved.title);
  h.socket.deliver({ type: "plan", epoch: oldEpoch, draft: null, saved: null });
  assert.equal(h.el("plan-draft").hidden, false);
  h.el("desktop-enabled").checked = true;
  await h.el("desktop-enabled").fire("change");
  const oldSocket = h.socket;
  oldSocket.close(1000);
  assert.equal(h.el("plan-draft").hidden, true);
  assert.equal(h.el("plan-saved").hidden, true);
  assert.equal(h.el("desktop-enabled").checked, false);
  oldSocket.deliver({ type: "plan", epoch: h.epoch, draft, saved });
  assert.equal(h.el("plan-draft").hidden, true);
  h.clock.advance(1000);
  await flush();
  assert.equal(h.record.controls.filter((item) => item.type === "plan_get").length, 2);
  assert.equal(h.el("plan-draft").hidden, true);
  assert.equal(h.el("plan-saved-title").textContent, saved.title);
  assert.equal(h.el("desktop-enabled").checked, false);
  assert.equal(h.record.controls.filter((item) => item.type === "settings").at(-1).desktop_enabled, false);
  assert.equal(h.record.tracks.length, 1, "reconnect must not reopen capture");
  assert.equal(h.record.tracks[0].readyState, "ended");
});

test("muting spoken replies stops late audio while explicitly started guidance can still speak", async (t) => {
  const h = harness(t);
  await h.start();
  h.socket.audio("normal-before-mute");
  const oldEpoch = h.epoch;
  h.socket.deferEpochs = true;
  h.el("speech-enabled").checked = false;
  await h.el("speech-enabled").fire("change");
  assert.equal(h.record.sources[0].stopped, true);
  assert.equal(h.record.tracks[0].readyState, "live", "speech preference does not change microphone consent");
  h.socket.audio("late-normal-before-ack", oldEpoch);
  h.unsolicitedEpoch();
  h.socket.audio("late-unsolicited-normal");
  assert.equal(h.record.sources.length, 1);
  h.socket.acknowledge(h.socket.deferredControls.shift());
  h.socket.deliver({ type: "settings", speech_enabled: true });
  assert.equal(h.el("speech-enabled").checked, false, "late ACK cannot restore a muted preference");
  h.socket.audio("normal-after-ack");
  assert.equal(h.record.sources.length, 1);
  h.socket.deferEpochs = false;
  await h.el("onboarding-start").fire("click");
  h.socket.deliver({ type: "onboarding", epoch: h.epoch, active: false, stage: "complete", message: "Tercihlerin hazır." });
  h.socket.deliver({ type: "audio", epoch: h.epoch, segment_id: "guided-completion", sample_rate: 24000,
    guided: true, pcm: Buffer.alloc(4800).toString("base64"), text: "Tercihlerin hazır." });
  assert.equal(h.record.sources.length, 2, "last guidance sentence can play after guided state becomes inactive");
  h.socket.audio("normal-after-guidance");
  assert.equal(h.record.sources.length, 2);
  h.el("speech-enabled").checked = true;
  await h.el("speech-enabled").fire("change");
  h.socket.audio("normal-after-unmuting");
  assert.equal(h.record.sources.length, 3, "unmuting an active microphone session restores spoken replies");
  assert.equal(h.record.tracks.length, 1);
});
