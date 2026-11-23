(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const ui = {
    connection: $("connection"), connectionLabel: $("connection-label"),
    title: $("voice-title"), subtitle: $("voice-subtitle"), orb: $("orb"),
    voiceToggle: $("voice-toggle"), voiceLabel: $("voice-toggle-label"),
    interrupt: $("interrupt"), micIndicator: $("mic-indicator"),
    notice: $("notice"), noticeText: $("notice-text"),
    transcriptSwitch: $("show-transcript"), transcriptPanel: $("transcript-panel"),
    messages: $("transcript-messages"), transcriptEmpty: $("transcript-empty"),
    clearTranscript: $("clear-transcript"), sourcesPanel: $("sources-panel"),
    sourceList: $("source-list"), webEnabled: $("web-enabled"), bargeIn: $("barge-in"),
    apiKey: $("api-key"), keyStatus: $("api-key-status"),
    textInput: $("text-input"), sendText: $("send-text"),
    memoryPanel: $("memory-panel"), memoryList: $("memory-list"),
    latency: $("last-latency"), footerHint: $("footer-hint"),
    brandName: $("brand-name"), profileDetails: $("profile-details"),
    profileSummary: $("profile-summary"), profileForm: $("profile-form"),
    userName: $("profile-user-name"), assistantName: $("profile-assistant-name"),
    profileStyle: $("profile-style"), profileVerbosity: $("profile-verbosity"),
    profilePause: $("profile-pause"), profileOutput: $("profile-output"),
    saveProfile: $("save-profile"), profileStatus: $("profile-status"),
    onboardingStart: $("onboarding-start"), calibrationStart: $("calibration-start"),
    guidedPanel: $("guided-panel"), guidedBadge: $("guided-badge"),
    guidedTitle: $("guided-title"), guidedMessage: $("guided-message"),
    guidedHint: $("guided-hint"), guidedCancel: $("guided-cancel"),
    calibrationResult: $("calibration-result"), calibrationMessage: $("calibration-result-message"),
    calibrationMeasurements: $("calibration-measurements"), calibrationPhrase: $("calibration-phrase"),
    calibrationReference: $("calibration-reference"), calibrationHeard: $("calibration-heard"),
    calibrationApply: $("calibration-apply"),
    metricsDetails: $("metrics-details"), timings: $("timing-measurements"),
    timingContext: $("timing-context"), acousticEnabled: $("acoustic-enabled"),
    acousticsDetails: $("acoustics-details"), acousticsStatus: $("acoustics-status"),
    acousticsMeasurements: $("acoustics-measurements"), captureMeasurements: $("capture-measurements"),
    acousticsLimitations: $("acoustics-limitations"),
  };

  const hash = new URLSearchParams(window.location.hash.slice(1));
  // This launch credential is tab-scoped. API keys and conversation content are
  // never placed in browser storage.
  const tokenStorageKey = "jarvis_voice_launch_token";
  let storedToken = "";
  try { storedToken = window.sessionStorage.getItem(tokenStorageKey) || ""; } catch (_) { /* Storage can be disabled. */ }
  const launchToken = hash.get("token") || storedToken;
  if (hash.get("token")) {
    try { window.sessionStorage.setItem(tokenStorageKey, launchToken); } catch (_) { /* In-memory use still works. */ }
  }
  if (window.location.hash) {
    history.replaceState(null, "", window.location.pathname + window.location.search);
  }

  const state = {
    socket: null, connected: false, ready: false, closing: false,
    sessionId: null, epoch: -1, blockAudioUntilEpoch: true, playbackAllowed: false,
    pendingEpochRequest: null, controlSerial: 0,
    micActive: false, starting: false, phase: "connecting", serverSpeaking: false,
    context: null, workletLoaded: false, stream: null, inputNode: null,
    worklet: null, silentGain: null, captureEnabled: false,
    playbacks: new Map(), seenSegments: new Set(), nextPlaybackTime: 0,
    tailUntil: 0, gateTimer: null, reconnectTimer: null, reconnectCount: 0,
    startRequest: 0, lastMessage: null, keyPending: false,
    profile: { schema_version: 1, assistant_name: "Jarvis", user_name: "", style: "friendly", verbosity: "short", pause: "balanced", output: "speakers", onboarding_complete: false },
    profileDirty: false, profilePending: false,
    onboarding: { active: false, stage: "", message: "" },
    calibration: { active: false, stage: "", message: "" },
    guidedPending: null,
    calibrationCanApply: false,
    captureInfo: null,
  };

  const MAX_AUDIO_BYTES = 4 * 1024 * 1024;
  const MAX_SOCKET_BUFFER = 64 * 1024;
  const OUTPUT_TAIL_MS = 350;

  function showNotice(message) {
    ui.noticeText.textContent = String(message || "Bir sorun oluştu. Yeniden deneyebilirsin.");
    ui.notice.hidden = false;
  }

  function dismissNotice() { ui.notice.hidden = true; }

  function send(message) {
    if (!state.connected || !state.socket || state.socket.readyState !== WebSocket.OPEN) return false;
    state.socket.send(JSON.stringify(message));
    return true;
  }

  function sendEpochControl(type, fields = {}) {
    const requestId = `${state.sessionId || "session"}:${++state.controlSerial}`;
    state.pendingEpochRequest = requestId;
    state.blockAudioUntilEpoch = true;
    return send({ type, ...fields, request_id: requestId });
  }

  function canCapture() {
    if (!state.micActive || !state.connected || !state.ready) return false;
    if (ui.bargeIn.checked) return true;
    return !state.serverSpeaking && state.playbacks.size === 0 && performance.now() >= state.tailUntil;
  }

  function syncCaptureGate() {
    const enabled = canCapture();
    if (state.worklet && enabled !== state.captureEnabled) {
      state.worklet.port.postMessage({ type: "capture", enabled, reset: true });
    }
    state.captureEnabled = enabled;
    if (!enabled) ui.orb.style.setProperty("--level", "0");
    window.clearTimeout(state.gateTimer);
    if (state.micActive && !ui.bargeIn.checked && state.tailUntil > performance.now()) {
      state.gateTimer = window.setTimeout(syncCaptureGate, Math.max(1, state.tailUntil - performance.now() + 5));
    }
    render();
  }

  function render() {
    let connectionLabel = "Bağlanıyor";
    let connectionState = "connecting";
    if (state.connected) {
      connectionLabel = state.ready ? "Hazır" : "Hazırlanıyor";
      connectionState = state.ready ? "ready" : "connecting";
    } else if (state.phase === "disconnected" || state.phase === "error") {
      connectionLabel = "Bağlantı yok";
      connectionState = "error";
    }
    ui.connectionLabel.textContent = connectionLabel;
    ui.connection.dataset.state = connectionState;
    ui.voiceToggle.disabled = !state.connected || !state.ready;
    ui.voiceToggle.setAttribute("aria-pressed", String(state.micActive));
    ui.voiceLabel.textContent = state.starting ? "Açmayı iptal et" : state.micActive ? "Mikrofonu kapat" : "Konuşmaya başla";
    ui.interrupt.disabled = !state.connected;
    ui.sendText.disabled = !state.connected || !state.ready;
    ui.onboardingStart.disabled = !state.connected || !state.ready || state.starting;
    ui.calibrationStart.disabled = !state.connected || !state.ready || state.starting;
    ui.saveProfile.disabled = !state.connected || !state.ready || state.profilePending;
    ui.guidedCancel.disabled = !state.connected;
    ui.calibrationApply.disabled = !state.connected || !state.ready || !state.calibrationCanApply;
    ui.onboardingStart.textContent = state.profile.onboarding_complete ? "Sesli tanışmayı yenile" : "Sesli tanışmayı başlat";

    const playing = state.playbacks.size > 0;
    let title = "Seni dinlemeye hazırım.";
    let subtitle = "Bir kez başlat, sonra doğal şekilde konuş.";
    let mode = "idle";
    if (!state.connected) {
      title = state.phase === "connecting" ? "Birazdan hazır." : "Bağlantı bekleniyor.";
      subtitle = state.phase === "connecting" ? "Konuşma alanın hazırlanıyor." : "Bağlantı kurulduğunda yeniden başlayabilirsin.";
    } else if (!state.ready) {
      title = "Birazdan hazır.";
      subtitle = `${state.profile.assistant_name} konuşmaya hazırlanıyor.`;
      mode = "thinking";
    } else if (state.starting) {
      title = "Mikrofonunu açalım.";
      subtitle = "Tarayıcı sorarsa mikrofon iznini ver.";
    } else if (playing) {
      title = "Seninle konuşuyor.";
      subtitle = ui.bargeIn.checked ? "Araya girebilir veya sesi kesebilirsin." : "İstersen “Sesi kes” düğmesiyle araya gir.";
      mode = "speaking";
    } else if (["thinking", "generating", "responding", "processing"].includes(state.phase)) {
      title = "Yanıtını hazırlıyor.";
      subtitle = "Konuşma birazdan devam edecek.";
      mode = "thinking";
    } else if (["searching", "web_search", "researching"].includes(state.phase)) {
      title = "Güncel kaynaklara bakıyor.";
      subtitle = "Bulduğu bilgileri senin için bir araya getiriyor.";
      mode = "thinking";
    } else if (["transcribing", "recognizing", "asr"].includes(state.phase)) {
      title = "Söylediklerini anlıyor.";
      subtitle = "Birazdan yanıt verecek.";
      mode = "thinking";
    } else if (state.micActive) {
      title = state.calibration.active && state.calibration.stage === "noise" ? "Ortamını dinliyor." : "Seni dinliyor.";
      subtitle = state.calibration.active ? state.calibration.message : state.onboarding.active ? "Soruyu yanıtlayarak tanışmaya devam edebilirsin." : "Aklından ne geçiyorsa söyle.";
      mode = "listening";
    } else if (!state.profile.onboarding_complete && !state.onboarding.active) {
      title = "Önce tanışalım mı?";
      subtitle = "Konuşmaya başla; isimlerimizi ve sohbet tarzımızı birlikte seçelim.";
    }
    ui.title.textContent = title;
    ui.subtitle.textContent = subtitle;
    ui.orb.dataset.mode = mode;
    ui.micIndicator.dataset.active = String(state.micActive);
    ui.micIndicator.replaceChildren();
    const dot = document.createElement("span");
    dot.setAttribute("aria-hidden", "true");
    ui.micIndicator.append(dot, document.createTextNode(state.micActive ? (state.captureEnabled ? "Mikrofon açık" : "Yanıtı dinliyorsun") : "Mikrofon kapalı"));
    ui.footerHint.textContent = state.micActive ? "Dilediğinde mikrofonu kapatabilirsin." : "Başlamak için mikrofon izni gerekir.";
    renderGuided();
  }

  async function ensureAudioContext() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error("Bu tarayıcı sesli sohbeti desteklemiyor. Güncel Chrome veya Edge ile açabilirsin.");
    if (!state.context || state.context.state === "closed") {
      state.context = new AudioContextClass({ latencyHint: "interactive" });
      state.workletLoaded = false;
      state.nextPlaybackTime = 0;
    }
    if (state.context.state === "suspended") await state.context.resume();
    return state.context;
  }

  function microphoneError(error) {
    if (error && ["NotAllowedError", "PermissionDeniedError"].includes(error.name)) {
      return "Mikrofon izni verilmedi. Adres çubuğundaki site izinlerinden mikrofonu açıp tekrar deneyebilirsin.";
    }
    if (error && ["NotFoundError", "DevicesNotFoundError"].includes(error.name)) {
      return "Mikrofon bulunamadı. Mikrofonunu bağla ve Windows ses giriş ayarını kontrol et.";
    }
    if (error && ["NotReadableError", "TrackStartError"].includes(error.name)) {
      return "Mikrofon açılamadı. Başka bir uygulama kullanıyorsa kapatıp yeniden dene; Windows mikrofon iznini de kontrol edebilirsin.";
    }
    return error && error.message ? error.message : "Mikrofon açılamadı. Güncel Chrome veya Edge ile tekrar deneyebilirsin.";
  }

  function releaseMicrophone() {
    const hadCapture = state.micActive || state.stream !== null || state.captureInfo !== null;
    state.micActive = false;
    state.captureEnabled = false;
    if (state.worklet) {
      state.worklet.port.postMessage({ type: "capture", enabled: false, reset: true });
      state.worklet.port.onmessage = null;
      try { state.worklet.disconnect(); } catch (_) { /* Already disconnected. */ }
    }
    if (state.inputNode) { try { state.inputNode.disconnect(); } catch (_) { /* Already disconnected. */ } }
    if (state.silentGain) { try { state.silentGain.disconnect(); } catch (_) { /* Already disconnected. */ } }
    if (state.stream) state.stream.getTracks().forEach((track) => track.stop());
    state.stream = null;
    state.worklet = null;
    state.inputNode = null;
    state.silentGain = null;
    window.clearTimeout(state.gateTimer);
    ui.orb.style.setProperty("--level", "0");
    state.captureInfo = null;
    clearAcoustics();
    if (hadCapture) reportCaptureInfo(null);
  }

  async function startMicrophone(initialControl = "start") {
    if (state.starting || state.micActive || !state.ready || !state.connected) return;
    const request = ++state.startRequest;
    state.starting = true;
    dismissNotice();
    render();
    let stream = null;
    try {
      const context = await ensureAudioContext();
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !context.audioWorklet) {
        throw new Error("Bu pencerede mikrofona erişilemiyor. Uygulamayı başlatıcısından, güncel Chrome veya Edge ile aç.");
      }
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: { ideal: 1 }, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      });
      if (request !== state.startRequest || !state.connected) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      if (!state.workletLoaded) {
        await context.audioWorklet.addModule("/static/capture-worklet.js?v=0.2.0");
        state.workletLoaded = true;
      }
      if (request !== state.startRequest || !state.connected) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      state.stream = stream;
      state.inputNode = context.createMediaStreamSource(stream);
      state.worklet = new AudioWorkletNode(context, "jarvis-capture", {
        numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
        processorOptions: { targetSampleRate: 16000, frameSize: 512 },
      });
      state.silentGain = context.createGain();
      state.silentGain.gain.value = 0;
      state.inputNode.connect(state.worklet);
      state.worklet.connect(state.silentGain);
      state.silentGain.connect(context.destination);
      state.worklet.port.onmessage = (event) => {
        if (!canCapture()) return;
        const message = event.data || {};
        if (message.type === "level") {
          const level = Math.min(1, Math.max(0, Number(message.rms) || 0) * 8);
          ui.orb.style.setProperty("--level", String(level));
        } else if (message.type === "audio" && message.buffer instanceof ArrayBuffer && message.buffer.byteLength === 1024) {
          if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return;
          if (state.socket.bufferedAmount > MAX_SOCKET_BUFFER) {
            showNotice("Ses bağlantısı yavaşladı. Bağlantı yeniden kurulduğunda konuşmayı tekrar başlatabilirsin.");
            stopSession(false);
            state.socket.close(4001, "audio_backpressure");
            return;
          }
          state.socket.send(message.buffer);
        }
      };
      for (const track of stream.getAudioTracks()) {
        track.addEventListener("ended", () => {
          if (state.stream === stream && state.micActive) {
            stopSession();
            showNotice("Mikrofon bağlantısı kesildi. Mikrofonunu kontrol edip yeniden başlatabilirsin.");
          }
        });
      }
      state.micActive = true;
      state.playbackAllowed = true;
      state.phase = "listening";
      reportCaptureInfo(stream.getAudioTracks()[0] || null);
      sendSettings();
      sendEpochControl(initialControl);
      syncCaptureGate();
    } catch (error) {
      if (stream) stream.getTracks().forEach((track) => track.stop());
      releaseMicrophone();
      showNotice(microphoneError(error));
    } finally {
      if (request === state.startRequest) state.starting = false;
      if (!state.micActive) state.guidedPending = null;
      render();
    }
  }

  function stopAllAudio(withTail = true) {
    const hadAudio = state.playbacks.size > 0 || state.serverSpeaking;
    for (const playback of state.playbacks.values()) {
      playback.cancelled = true;
      try { playback.source.stop(); } catch (_) { /* It may have already ended. */ }
      try { playback.source.disconnect(); } catch (_) { /* It may have already ended. */ }
    }
    state.playbacks.clear();
    state.nextPlaybackTime = state.context ? state.context.currentTime : 0;
    state.serverSpeaking = false;
    // A new speech epoch also arrives at the start of the user's sentence.
    // Do not silence that sentence unless there actually was output to clear.
    if (withTail && hadAudio) state.tailUntil = performance.now() + OUTPUT_TAIL_MS;
    syncCaptureGate();
  }

  function stopSession(notifyServer = true) {
    state.startRequest += 1;
    state.starting = false;
    state.playbackAllowed = false;
    state.blockAudioUntilEpoch = true;
    releaseMicrophone();
    stopAllAudio(false);
    state.phase = "muted";
    state.guidedPending = null;
    if (state.calibration.active) {
      state.calibration = { active: false, stage: "cancelled", message: "Mikrofon kontrolü durduruldu." };
    }
    if (notifyServer) sendEpochControl("stop");
    render();
  }

  function interruptResponse() {
    if (!state.connected) return;
    state.blockAudioUntilEpoch = true;
    stopAllAudio(true);
    state.phase = state.micActive ? "listening" : "ready";
    sendEpochControl("interrupt");
    render();
  }

  function receiveEpoch(epoch, requestId) {
    if (!Number.isInteger(epoch) || epoch < state.epoch) return;
    const changed = epoch !== state.epoch;
    if (changed || state.blockAudioUntilEpoch) stopAllAudio(true);
    state.epoch = epoch;
    if (state.pendingEpochRequest !== null && requestId === state.pendingEpochRequest) {
      state.pendingEpochRequest = null;
    }
    // An unsolicited epoch already in flight must never acknowledge a newer
    // local cancellation. Only the matching control response opens playback.
    state.blockAudioUntilEpoch = state.pendingEpochRequest !== null;
    if (changed) state.seenSegments.clear();
    syncCaptureGate();
  }

  function receiveAudio(message) {
    if (!state.connected || !state.playbackAllowed || state.blockAudioUntilEpoch || message.epoch !== state.epoch) return;
    const sampleRate = Number(message.sample_rate);
    if (!Number.isFinite(sampleRate) || sampleRate < 8000 || sampleRate > 96000 || typeof message.pcm !== "string") return;
    if (message.segment_id === undefined || message.segment_id === null) return;
    const key = `${message.epoch}:${String(message.segment_id)}`;
    if (state.seenSegments.has(key)) return;
    if (state.playbacks.size >= 3) {
      showNotice("Ses yanıtı birikti. Konuşmayı yeniden deneyebilirsin.");
      interruptResponse();
      return;
    }
    if (!state.context || state.context.state !== "running") {
      showNotice("Sesi açmak için “Konuşmaya başla” düğmesine basabilirsin.");
      return;
    }
    if (message.pcm.length > Math.ceil(MAX_AUDIO_BYTES * 4 / 3) + 4) {
      showNotice("Ses yanıtı oynatılamadı. Daha kısa bir yanıt isteyebilirsin.");
      interruptResponse();
      return;
    }
    try {
      const decoded = atob(message.pcm);
      if (!decoded.length || decoded.length % 2 !== 0 || decoded.length > MAX_AUDIO_BYTES) throw new Error("invalid_audio");
      const bytes = new Uint8Array(decoded.length);
      for (let i = 0; i < decoded.length; i += 1) bytes[i] = decoded.charCodeAt(i);
      const view = new DataView(bytes.buffer);
      const count = bytes.length / 2;
      if (count / sampleRate > 60) throw new Error("audio_too_long");
      const buffer = state.context.createBuffer(1, count, sampleRate);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < count; i += 1) channel[i] = view.getInt16(i * 2, true) / 32768;
      if (message.epoch !== state.epoch || state.blockAudioUntilEpoch) return;
      const source = state.context.createBufferSource();
      source.buffer = buffer;
      source.connect(state.context.destination);
      const playback = { source, cancelled: false, epoch: message.epoch, segmentId: message.segment_id };
      state.playbacks.set(key, playback);
      state.seenSegments.add(key);
      const startAt = Math.max(state.context.currentTime + 0.025, state.nextPlaybackTime);
      state.nextPlaybackTime = startAt + buffer.duration;
      source.onended = () => {
        try { source.disconnect(); } catch (_) { /* Already disconnected. */ }
        if (state.playbacks.get(key) === playback) state.playbacks.delete(key);
        if (!playback.cancelled && playback.epoch === state.epoch && !state.blockAudioUntilEpoch) {
          send({ type: "played", epoch: playback.epoch, segment_id: playback.segmentId });
        }
        if (state.playbacks.size === 0 && !playback.cancelled) {
          state.tailUntil = performance.now() + OUTPUT_TAIL_MS;
          if (!state.serverSpeaking) state.phase = state.micActive ? "listening" : "ready";
        }
        syncCaptureGate();
      };
      source.start(startAt);
      syncCaptureGate();
    } catch (_) {
      showNotice("Ses yanıtı oynatılamadı. Konuşmayı yeniden deneyebilirsin.");
      interruptResponse();
    }
  }

  function receiveTranscript(message) {
    if (!["user", "assistant"].includes(message.role) || typeof message.text !== "string" || !message.text.trim()) return;
    if (Number.isInteger(message.epoch) && message.epoch < state.epoch) return;
    const text = message.text.slice(0, 30000);
    const nearBottom = ui.transcriptPanel.scrollHeight - ui.transcriptPanel.clientHeight - ui.transcriptPanel.scrollTop < 60;
    const last = state.lastMessage;
    if (last && last.role === message.role && last.epoch === message.epoch && last.element.isConnected && message.role === "assistant") {
      if (text.startsWith(last.text)) last.text = text;
      else if (!last.text.startsWith(text)) last.text += (last.text.endsWith(" ") || text.startsWith(" ") ? "" : " ") + text;
      last.body.textContent = last.text;
    } else {
      const element = document.createElement("article");
      element.className = "transcript-message";
      element.dataset.role = message.role;
      const author = document.createElement("span");
      author.className = "message-author";
      author.textContent = message.role === "user" ? "SEN" : state.profile.assistant_name.toLocaleUpperCase("tr-TR");
      const body = document.createElement("p");
      body.textContent = text;
      element.append(author, body);
      ui.messages.appendChild(element);
      state.lastMessage = { role: message.role, epoch: message.epoch, text, element, body };
      while (ui.messages.children.length > 80) ui.messages.firstElementChild.remove();
    }
    ui.transcriptEmpty.hidden = true;
    if (nearBottom) ui.transcriptPanel.scrollTop = ui.transcriptPanel.scrollHeight;
  }

  function receiveSources(message) {
    if (Number.isInteger(message.epoch) && message.epoch !== state.epoch) return;
    ui.sourceList.replaceChildren();
    const items = Array.isArray(message.items) ? message.items.slice(0, 12) : [];
    for (const item of items) {
      try {
        const url = new URL(item.url);
        if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) continue;
        const link = document.createElement("a");
        link.className = "source-link";
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.referrerPolicy = "no-referrer";
        link.textContent = String(item.title || url.hostname).slice(0, 160);
        ui.sourceList.appendChild(link);
      } catch (_) { /* Ignore malformed source URLs. */ }
    }
    ui.sourcesPanel.hidden = ui.sourceList.childElementCount === 0;
  }

  function receiveMemories(message) {
    ui.memoryList.replaceChildren();
    const items = Array.isArray(message.items) ? message.items.slice(0, 100) : [];
    for (const item of items) {
      if (typeof item.text !== "string") continue;
      const row = document.createElement("li");
      row.textContent = item.text.slice(0, 2000);
      ui.memoryList.appendChild(row);
    }
    ui.memoryPanel.hidden = ui.memoryList.childElementCount === 0;
  }

  const PROFILE_LABELS = {
    style: { friendly: "samimi", balanced: "dengeli", formal: "resmî" },
    verbosity: { short: "kısa yanıtlar", medium: "orta uzunlukta yanıtlar", detailed: "ayrıntılı yanıtlar" },
    pause: { quick: "kısa duraklama", balanced: "dengeli duraklama", relaxed: "rahat duraklama" },
    output: { speakers: "hoparlör", headphones: "kulaklık" },
  };

  function renderGuided() {
    const calibration = state.calibration.active || state.guidedPending === "calibration_start";
    const onboarding = state.onboarding.active || state.guidedPending === "onboarding_start";
    ui.guidedPanel.hidden = !calibration && !onboarding;
    if (ui.guidedPanel.hidden) return;
    ui.guidedBadge.textContent = calibration ? "Mikrofon kontrolü" : "Sesli tanışma";
    ui.guidedTitle.textContent = calibration ? "Sesini birlikte ayarlayalım." : "Birbirimizi tanıyalım.";
    const current = calibration ? state.calibration : state.onboarding;
    ui.guidedMessage.textContent = current.message || "Mikrofon açıldığında başlayacağız.";
    ui.guidedHint.textContent = !state.micActive && !state.starting
      ? "Mikrofon kapalı. Devam etmek için “Konuşmaya başla” düğmesine basabilirsin."
      : calibration
        ? "Yönlendirmeyi dinle; istendiğinde sessiz kal veya örnek cümleyi söyle."
        : "Yanıtını söyleyebilirsin. Sonunda onay verdiğinde tercihlerin kaydedilir.";
  }

  function receiveProfile(message) {
    const incoming = message.profile;
    if (!incoming || typeof incoming !== "object" || incoming.schema_version !== 1) return;
    const profile = { ...state.profile };
    for (const key of ["assistant_name", "user_name"]) {
      if (typeof incoming[key] === "string") profile[key] = incoming[key].trim().slice(0, 40);
    }
    if (!profile.assistant_name) profile.assistant_name = "Jarvis";
    for (const key of Object.keys(PROFILE_LABELS)) {
      if (Object.prototype.hasOwnProperty.call(PROFILE_LABELS[key], incoming[key])) profile[key] = incoming[key];
    }
    profile.onboarding_complete = incoming.onboarding_complete === true;
    state.profile = profile;
    ui.brandName.textContent = profile.assistant_name;
    $("brand-link").setAttribute("aria-label", `${profile.assistant_name} sesli sohbet`);
    document.title = `${profile.assistant_name} · Sesli sohbet`;
    $("transcript-hint").textContent = `Söylediklerin ve ${profile.assistant_name} yanıtları bu pencerede görünür.`;
    ui.profileSummary.textContent = profile.onboarding_complete
      ? `${profile.assistant_name}${profile.user_name ? ` · ${profile.user_name}` : ""} · ${PROFILE_LABELS.style[profile.style]} sohbet · ${PROFILE_LABELS.verbosity[profile.verbosity]}.`
      : "İlk konuşmada adını, bana vereceğin ismi ve sohbet tarzını birlikte seçebiliriz.";
    if (!state.profileDirty || state.profilePending) {
      ui.userName.value = profile.user_name;
      ui.assistantName.value = profile.assistant_name;
      ui.profileStyle.value = profile.style;
      ui.profileVerbosity.value = profile.verbosity;
      ui.profilePause.value = profile.pause;
      ui.profileOutput.value = profile.output;
      if (state.profilePending) ui.profileStatus.textContent = "Tercihlerin kaydedildi.";
      state.profileDirty = false;
    }
    state.profilePending = false;
    if (message.onboarding && typeof message.onboarding === "object") {
      receiveOnboarding({ ...message.onboarding, type: "onboarding" });
    }
  }

  function receiveOnboarding(message) {
    if (Number.isInteger(message.epoch) && message.epoch !== state.epoch) return;
    if (state.pendingEpochRequest !== null && message.active === true) return;
    state.onboarding = {
      active: message.active === true,
      stage: typeof message.stage === "string" ? message.stage : "",
      message: typeof message.message === "string" ? message.message.slice(0, 1600) : state.onboarding.message,
    };
    state.guidedPending = null;
    if (state.onboarding.active) state.calibration.active = false;
  }

  function addMeasurement(container, label, value) {
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value;
    container.append(term, description);
  }

  function numberText(value, digits = 1) {
    return value.toLocaleString("tr-TR", { maximumFractionDigits: digits });
  }

  function finiteNumber(value) { return typeof value === "number" && Number.isFinite(value); }

  function receiveCalibration(message) {
    if (Number.isInteger(message.epoch) && message.epoch !== state.epoch) return;
    if (state.pendingEpochRequest !== null) return;
    if (typeof message.stage !== "string") return;
    const active = ["prompt", "noise", "phrase"].includes(message.stage);
    state.calibration = { active, stage: message.stage, message: typeof message.message === "string" ? message.message.slice(0, 1600) : "" };
    state.guidedPending = null;
    if (active) {
      state.onboarding.active = false;
      state.calibrationCanApply = false;
      ui.calibrationApply.hidden = true;
    }
    if (["result", "error", "cancelled", "applied"].includes(message.stage)) {
      ui.profileDetails.open = true;
      ui.calibrationResult.hidden = false;
      ui.calibrationMessage.textContent = state.calibration.message;
      state.calibrationCanApply = false;
      ui.calibrationApply.hidden = true;
    }
    const measurements = message.measurements;
    if (!measurements || typeof measurements !== "object") return;
    ui.calibrationMeasurements.replaceChildren();
    const rows = [
      ["noise_dbfs", "Ortam seviyesi", " dBFS"],
      ["noise_peak_dbfs", "Ortam tepe seviyesi", " dBFS"],
      ["voiced_dbfs", "Konuşma seviyesi", " dBFS"],
      ["snr_db", "Konuşma / ortam farkı", " dB"],
      ["clipping_pct", "Kırpılan örnekler", "%"],
    ];
    for (const [key, label, unit] of rows) {
      if (finiteNumber(measurements[key])) addMeasurement(ui.calibrationMeasurements, label, numberText(measurements[key]) + unit);
    }
    if (finiteNumber(measurements.word_error_rate) && measurements.word_error_rate >= 0) {
      addMeasurement(ui.calibrationMeasurements, "Bu cümlede kelime farkı", numberText(measurements.word_error_rate * 100) + "%");
    }
    const reference = typeof measurements.reference_text === "string" ? measurements.reference_text.slice(0, 1000) : "";
    const heard = typeof measurements.phrase_text === "string" ? measurements.phrase_text.slice(0, 1000) : "";
    ui.calibrationPhrase.hidden = !reference && !heard;
    ui.calibrationReference.textContent = reference;
    ui.calibrationHeard.textContent = heard || "Konuşma çözümlenemedi.";
    state.calibrationCanApply = message.stage === "result" && measurements.can_apply === true && finiteNumber(measurements.suggested_vad_threshold);
    ui.calibrationApply.hidden = !state.calibrationCanApply;
  }

  function receiveMetrics(message) {
    if (state.pendingEpochRequest !== null || (Number.isInteger(message.epoch) && message.epoch !== state.epoch)) return;
    const readyMs = finiteNumber(message.server_audio_ready_ms) ? message.server_audio_ready_ms : message.first_audio_ms;
    if (finiteNumber(readyMs) && readyMs >= 0) {
      ui.latency.textContent = `İlk ses hazır: ${numberText(readyMs / 1000)} sn`;
      ui.latency.hidden = false;
    }
    ui.timings.replaceChildren();
    ui.timingContext.textContent = message.measurement_kind === "guided"
      ? "Tanışma veya mikrofon yönergesi: bu yanıtta dil modeli kullanılmadı."
      : "Son sohbet yanıtının hazırlık aşamaları.";
    const rows = [
      ["endpoint_ms", "Sözün bitmesini bekleme"],
      ["asr_ms", "Sesi metne çevirme"],
      ["llm_first_ms", "İlk yanıt metnini hazırlama"],
      ["tts_first_ms", "İlk ses parçasını üretme"],
      ["ollama_load_ms", "Ollama modelini yükleme"],
      ["prompt_eval_ms", "Modelin girdiyi işlemesi"],
      ["eval_ms", "Modelin yanıtı üretmesi"],
    ];
    for (const [key, label] of rows) {
      if (finiteNumber(message[key]) && message[key] >= 0) addMeasurement(ui.timings, label, numberText(message[key] / 1000, 2) + " sn");
    }
    if (finiteNumber(readyMs) && readyMs >= 0) addMeasurement(ui.timings, "İlk ses hazır · toplam", numberText(readyMs / 1000, 2) + " sn");
    if (finiteNumber(message.tts_rtf) && message.tts_rtf >= 0) addMeasurement(ui.timings, "Ses üretimi / ses uzunluğu", numberText(message.tts_rtf, 2) + "×");
    ui.metricsDetails.hidden = ui.timings.childElementCount === 0;
  }

  function captureInfo(settings) {
    const source = settings && typeof settings === "object" ? settings : {};
    const positive = (value) => finiteNumber(value) && value > 0 ? value : null;
    const boolean = (value) => typeof value === "boolean" ? value : null;
    return {
      sample_rate: positive(source.sample_rate),
      channel_count: positive(source.channel_count),
      echo_cancellation: boolean(source.echo_cancellation),
      noise_suppression: boolean(source.noise_suppression),
      auto_gain_control: boolean(source.auto_gain_control),
    };
  }

  function reportCaptureInfo(track) {
    let actual = {};
    if (track && typeof track.getSettings === "function") {
      try { actual = track.getSettings() || {}; } catch (_) { /* Unknown is preferable to guessing browser settings. */ }
    }
    const info = captureInfo({
      sample_rate: actual.sampleRate, channel_count: actual.channelCount,
      echo_cancellation: actual.echoCancellation, noise_suppression: actual.noiseSuppression,
      auto_gain_control: actual.autoGainControl,
    });
    state.captureInfo = track ? info : null;
    // Only measured settings are reported; deviceId, groupId and labels are
    // deliberately excluded, even if getSettings() exposes them.
    send({ type: "capture_info", ...info });
  }

  function clearAcoustics() {
    ui.acousticsDetails.hidden = true;
    ui.acousticsStatus.textContent = "";
    ui.acousticsMeasurements.replaceChildren();
    ui.captureMeasurements.replaceChildren();
    ui.acousticsLimitations.replaceChildren();
  }

  function receiveAcoustics(message) {
    if (!ui.acousticEnabled.checked || !state.connected || !state.micActive || state.pendingEpochRequest !== null) return;
    if (!Number.isInteger(message.epoch) || message.epoch !== state.epoch) return;
    const observation = message.observation;
    if (!observation || typeof observation !== "object" || observation.schema_version !== 1) return;
    ui.acousticsMeasurements.replaceChildren();
    ui.captureMeasurements.replaceChildren();
    ui.acousticsLimitations.replaceChildren();
    ui.acousticsStatus.textContent = observation.signal_valid === true
      ? "Son konuşmanın ölçülebilen ses özellikleri."
      : "Bu örnekte güvenilir ölçüm için yeterli geçerli ses bulunamadı.";
    const rows = [
      ["duration_s", "İncelenen ses", " sn", 1],
      ["rms_dbfs", "Ortalama ses seviyesi", " dBFS", 1],
      ["peak_dbfs", "Tepe ses seviyesi", " dBFS", 1],
      ["clipping_pct", "Kırpılan örnekler", "%", 2],
      ["words_per_minute", "Tanınan kelime temposu", " kelime/dk", 0],
      ["f0_median_hz", "Temel frekans · ortanca", " Hz", 1],
      ["f0_iqr_hz", "Temel frekans · çeyrekler arası fark", " Hz", 1],
      ["analysis_ms", "Ölçümün hesaplanması", " ms", 1],
    ];
    for (const [key, label, unit, digits] of rows) {
      if (finiteNumber(observation[key])) addMeasurement(ui.acousticsMeasurements, label, numberText(observation[key], digits) + unit);
    }
    for (const [key, label] of [["speech_fraction", "Konuşma olarak işaretlenen bölüm"], ["pause_fraction", "Duraklama olarak işaretlenen bölüm"], ["f0_coverage", "Temel frekans ölçülebilen bölüm"]]) {
      if (finiteNumber(observation[key]) && observation[key] >= 0 && observation[key] <= 1) addMeasurement(ui.acousticsMeasurements, label, numberText(observation[key] * 100) + "%");
    }
    const capture = captureInfo(observation.capture || state.captureInfo);
    addMeasurement(ui.captureMeasurements, "Mikrofon örneklemesi", capture.sample_rate === null ? "Bilinmiyor" : numberText(capture.sample_rate, 0) + " Hz");
    addMeasurement(ui.captureMeasurements, "Kanal sayısı", capture.channel_count === null ? "Bilinmiyor" : numberText(capture.channel_count, 0));
    for (const [key, label] of [["echo_cancellation", "Yankı azaltma"], ["noise_suppression", "Gürültü azaltma"], ["auto_gain_control", "Otomatik giriş seviyesi"]]) {
      addMeasurement(ui.captureMeasurements, label, capture[key] === null ? "Bilinmiyor" : capture[key] ? "Açık" : "Kapalı");
    }
    if (Array.isArray(observation.limitations)) {
      for (const limitation of observation.limitations.slice(0, 8)) {
        if (typeof limitation !== "string") continue;
        const row = document.createElement("li");
        row.textContent = limitation.slice(0, 400);
        ui.acousticsLimitations.appendChild(row);
      }
    }
    ui.acousticsDetails.hidden = false;
  }

  async function startGuided(type) {
    if (!state.connected || !state.ready || state.starting) return;
    state.guidedPending = type;
    if (!state.micActive) {
      void startMicrophone(type);
      return;
    }
    const request = state.startRequest;
    try {
      await ensureAudioContext();
      if (request !== state.startRequest || !state.micActive || !state.connected) return;
      state.playbackAllowed = true;
      state.blockAudioUntilEpoch = true;
      stopAllAudio(true);
      state.phase = "listening";
      sendEpochControl(type);
      dismissNotice();
      render();
    } catch (error) {
      state.guidedPending = null;
      showNotice(microphoneError(error));
      render();
    }
  }

  function cancelGuided() {
    if (state.starting) {
      stopSession();
      return;
    }
    if (!state.connected) return;
    const type = state.calibration.active || state.guidedPending === "calibration_start" ? "calibration_cancel" : "onboarding_cancel";
    state.blockAudioUntilEpoch = true;
    stopAllAudio(true);
    state.guidedPending = null;
    state.onboarding.active = false;
    state.calibration.active = false;
    sendEpochControl(type);
    state.phase = state.micActive ? "listening" : "ready";
    render();
  }

  function receiveStatus(message) {
    let phase = message.state || message.status || message.value || "";
    if (!phase && typeof message.message === "string") {
      const wording = message.message.toLocaleLowerCase("tr-TR");
      if (wording.includes("dinliyorum")) phase = "listening";
      else if (wording.includes("mikrofon kapalı")) phase = "muted";
      else if (wording.includes("çözüyorum") || wording.includes("yazıya")) phase = "transcribing";
      else if (wording.includes("bakıyorum") || wording.includes("arıyorum") || wording.includes("araştırıyorum")) phase = "searching";
      else if (wording.includes("hazırlıyorum") || wording.includes("düşünüyorum")) phase = "thinking";
    }
    if (typeof phase === "string" && phase) state.phase = phase.toLowerCase();
    if (state.phase === "speaking") state.serverSpeaking = true;
    if (["listening", "ready", "idle", "muted", "stopped", "error"].includes(state.phase)) state.serverSpeaking = false;
    if (typeof message.ready === "boolean") state.ready = message.ready;
    syncCaptureGate();
  }

  function onServerMessage(event) {
    if (typeof event.data !== "string") return;
    let message;
    try { message = JSON.parse(event.data); } catch (_) { return; }
    if (!message || typeof message !== "object") return;
    if (message.type !== "hello" && message.session_id && state.sessionId && message.session_id !== state.sessionId) return;
    switch (message.type) {
      case "hello":
        state.connected = true;
        state.sessionId = message.session_id;
        state.epoch = -1;
        state.pendingEpochRequest = null;
        state.ready = message.ready === true;
        state.reconnectCount = 0;
        state.phase = state.ready ? "ready" : "loading";
        receiveEpoch(message.epoch);
        sendSettings();
        break;
      case "ready":
        state.ready = message.ready !== false;
        state.phase = state.ready ? (state.micActive ? "listening" : "ready") : "loading";
        if (!state.ready && typeof message.message === "string" && !message.message.includes("açılıyor")) showNotice(message.message);
        syncCaptureGate();
        break;
      case "epoch": receiveEpoch(message.epoch, message.request_id); break;
      case "status": receiveStatus(message); break;
      case "audio": receiveAudio(message); break;
      case "audio_end":
        if (message.epoch === undefined || message.epoch === state.epoch) {
          state.serverSpeaking = false;
          if (!state.playbacks.size) state.phase = state.micActive ? "listening" : "ready";
          syncCaptureGate();
        }
        break;
      case "transcript": receiveTranscript(message); break;
      case "sources": receiveSources(message); break;
      case "memories": receiveMemories(message); break;
      case "profile": receiveProfile(message); break;
      case "onboarding": receiveOnboarding(message); break;
      case "calibration": receiveCalibration(message); break;
      case "acoustics": receiveAcoustics(message); break;
      case "capture_stop":
        stopSession(false);
        showNotice(message.message || "Konuşma durduruldu. Hazır olduğunda yeniden başlayabilirsin.");
        break;
      case "settings":
      case "settings_saved":
        if (typeof message.web_enabled === "boolean") ui.webEnabled.checked = message.web_enabled;
        if (typeof message.barge_in === "boolean") ui.bargeIn.checked = message.barge_in;
        if (typeof message.acoustic_enabled === "boolean") {
          ui.acousticEnabled.checked = message.acoustic_enabled;
          if (!message.acoustic_enabled) clearAcoustics();
        }
        if (typeof message.api_key_configured === "boolean" || typeof message.has_api_key === "boolean") {
          const configured = message.api_key_configured === true || message.has_api_key === true;
          ui.keyStatus.textContent = configured ? "Anahtar bu oturum için eklendi." : "İnternet araması için anahtar ekleyebilirsin.";
          ui.keyStatus.hidden = false;
          state.keyPending = false;
        }
        syncCaptureGate();
        break;
      case "error":
        state.profilePending = false;
        state.guidedPending = null;
        state.serverSpeaking = false;
        state.blockAudioUntilEpoch = true;
        state.phase = state.micActive ? "listening" : "ready";
        stopAllAudio(true);
        sendEpochControl("interrupt");
        showNotice(message.message);
        break;
      case "metrics":
        receiveMetrics(message); break;
      default: break;
    }
    render();
  }

  function sendSettings(apiKey) {
    const message = { type: "settings", web_enabled: ui.webEnabled.checked, barge_in: ui.bargeIn.checked, acoustic_enabled: ui.acousticEnabled.checked };
    if (apiKey !== undefined) message.api_key = apiKey;
    return send(message);
  }

  function connect() {
    if (state.closing || !launchToken) return;
    window.clearTimeout(state.reconnectTimer);
    state.phase = "connecting";
    render();
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws`);
    state.socket = socket;
    socket.onopen = () => {
      if (state.socket !== socket) return;
      socket.send(JSON.stringify({ type: "hello", token: launchToken, protocol: 2 }));
    };
    socket.onmessage = (event) => { if (state.socket === socket) onServerMessage(event); };
    socket.onerror = () => { /* onclose performs cleanup and the bounded retry. */ };
    socket.onclose = (event) => {
      if (state.socket !== socket) return;
      state.connected = false;
      state.ready = false;
      state.sessionId = null;
      state.profilePending = false;
      state.onboarding.active = false;
      state.calibration.active = false;
      state.calibrationCanApply = false;
      ui.calibrationApply.hidden = true;
      ui.acousticEnabled.checked = false;
      clearAcoustics();
      state.socket = null;
      stopSession(false);
      state.phase = "disconnected";
      render();
      if (state.closing) return;
      if ([1008, 4003, 4401, 4403].includes(event.code)) {
        if (!ui.noticeText.textContent.includes("başka bir sekmede")) {
          try { window.sessionStorage.removeItem(tokenStorageKey); } catch (_) { /* Storage can be disabled. */ }
          showNotice("Bu pencerenin oturumu açılamadı. Uygulamanın başlatıcısından yeni bir pencere açabilirsin.");
        }
        return;
      }
      if (state.reconnectCount < 4) {
        const delay = Math.min(8000, 1000 * (2 ** state.reconnectCount));
        state.reconnectCount += 1;
        state.reconnectTimer = window.setTimeout(connect, delay);
      } else {
        showNotice("Jarvis’e ulaşılamıyor. Uygulamanın açık olduğundan emin olup başlatıcısından yeniden açabilirsin.");
      }
    };
  }

  ui.voiceToggle.addEventListener("click", () => {
    if (state.micActive || state.starting) stopSession();
    else void startMicrophone();
  });
  ui.interrupt.addEventListener("click", interruptResponse);
  ui.onboardingStart.addEventListener("click", () => { void startGuided("onboarding_start"); });
  ui.calibrationStart.addEventListener("click", () => { void startGuided("calibration_start"); });
  ui.guidedCancel.addEventListener("click", cancelGuided);
  ui.calibrationApply.addEventListener("click", () => {
    if (!state.connected || !state.ready || !state.calibrationCanApply) return;
    state.blockAudioUntilEpoch = true;
    stopAllAudio(true);
    state.calibrationCanApply = false;
    ui.calibrationApply.hidden = true;
    sendEpochControl("calibration_apply");
    render();
  });
  ui.profileForm.addEventListener("input", () => {
    state.profileDirty = true;
    ui.profileStatus.textContent = "Henüz kaydedilmedi.";
  });
  ui.profileForm.addEventListener("change", () => {
    state.profileDirty = true;
    ui.profileStatus.textContent = "Henüz kaydedilmedi.";
  });
  ui.profileForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.connected || !state.ready || state.profilePending) return;
    const profile = {
      schema_version: 1,
      user_name: ui.userName.value.trim(),
      assistant_name: ui.assistantName.value.trim(),
      style: ui.profileStyle.value, verbosity: ui.profileVerbosity.value,
      pause: ui.profilePause.value, output: ui.profileOutput.value,
      onboarding_complete: true,
    };
    if (!profile.assistant_name) { ui.assistantName.focus(); return; }
    state.profilePending = true;
    state.blockAudioUntilEpoch = true;
    stopAllAudio(true);
    sendEpochControl("profile_save", { profile });
    ui.profileStatus.textContent = "Tercihlerin kaydediliyor…";
    render();
  });
  $("dismiss-notice").addEventListener("click", dismissNotice);
  $("brand-link").addEventListener("click", (event) => { event.preventDefault(); window.scrollTo({ top: 0, behavior: "smooth" }); });
  ui.transcriptSwitch.addEventListener("change", () => {
    ui.transcriptPanel.hidden = !ui.transcriptSwitch.checked;
    ui.clearTranscript.hidden = !ui.transcriptSwitch.checked;
    if (ui.transcriptSwitch.checked) ui.transcriptPanel.scrollTop = ui.transcriptPanel.scrollHeight;
  });
  ui.clearTranscript.addEventListener("click", () => {
    ui.messages.replaceChildren();
    ui.sourceList.replaceChildren();
    ui.sourcesPanel.hidden = true;
    ui.transcriptEmpty.hidden = false;
    state.lastMessage = null;
  });
  ui.webEnabled.addEventListener("change", () => sendSettings());
  ui.bargeIn.addEventListener("change", () => { sendSettings(); syncCaptureGate(); });
  ui.acousticEnabled.addEventListener("change", () => {
    clearAcoustics();
    sendSettings();
  });
  $("api-key-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.connected) { showNotice("Önce Jarvis bağlantısının kurulmasını bekle."); return; }
    const key = ui.apiKey.value.trim();
    if (!key) { ui.apiKey.focus(); return; }
    if (sendSettings(key)) {
      ui.apiKey.value = "";
      state.keyPending = true;
      ui.keyStatus.textContent = "Anahtar bu oturum için gönderildi.";
      ui.keyStatus.hidden = false;
    }
  });
  $("text-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = ui.textInput.value.trim();
    if (!text || !state.connected || !state.ready) return;
    try {
      await ensureAudioContext();
      state.playbackAllowed = true;
      // The server advances its authoritative epoch for a new text turn.
      state.blockAudioUntilEpoch = true;
      stopAllAudio(true);
      sendEpochControl("text", { text });
      ui.textInput.value = "";
      ui.transcriptSwitch.checked = true;
      ui.transcriptPanel.hidden = false;
      ui.clearTranscript.hidden = false;
      state.phase = "thinking";
      dismissNotice();
      render();
    } catch (error) { showNotice(microphoneError(error)); }
  });
  ui.textInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("text-form").requestSubmit();
    }
  });
  window.addEventListener("pagehide", () => {
    state.closing = true;
    window.clearTimeout(state.reconnectTimer);
    stopSession();
    if (state.socket) state.socket.close(1000, "page_closed");
    if (state.context && state.context.state !== "closed") void state.context.close();
  });

  if (!launchToken) {
    state.phase = "error";
    showNotice("Bu pencereyi uygulamanın başlatıcısından açmalısın. Açık bir pencereyi yenilediysen başlatıcıyı yeniden çalıştırabilirsin.");
    render();
  } else {
    connect();
  }
})();
