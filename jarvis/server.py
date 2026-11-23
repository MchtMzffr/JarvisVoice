"""Loopback-only application server. One microphone session, bounded CPU work."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from collections import deque, OrderedDict
import hmac
import os
import secrets
import time
import uuid
from dataclasses import replace
from pathlib import Path
import numpy as np
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import SETTINGS, DATA_ROOT, ASR_PATH, TTS_CACHE
from .contracts import EpochGate, Segmenter, event
from .memory import MemoryStore, memory_command
from .text import SentenceBuffer, clean_spoken
from .profile import Profile, ProfileStore, ProfileError, Onboarding
from .calibration import (CalibrationStore, CalibrationError, NoiseMeter,
                          NOISE_PROMPT, PHRASE_PROMPT, evaluate, segment_settings, words)
from .audio_analysis import analyze, sanitize_capture
from .actions import application_command, apps_catalog, launch_application
from .plans import PlanError, PlanStore, plan_command
from . import llm, __version__


class SerialCPU:
    """Cancellation cannot release the slot before an already-running call ends."""
    def __init__(self, name):
        self.lock = asyncio.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)

    async def call(self, function, *args):
        async with self.lock:
            future = asyncio.get_running_loop().run_in_executor(self.pool, function, *args)
            cancelled = False
            while True:
                try:
                    result = await asyncio.shield(future)
                    break
                except asyncio.CancelledError:
                    # Repeated stop/disconnect signals still cannot release a
                    # model's slot before its non-cancellable CPU work finishes.
                    if future.cancelled():
                        raise
                    cancelled = True
                except Exception:
                    if cancelled:
                        raise asyncio.CancelledError from None
                    raise
            if cancelled:
                raise asyncio.CancelledError
            return result

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)


class Runtime:
    def __init__(self, demo=False):
        self.token = secrets.token_urlsafe(32)
        self.ready = False
        self.loading = True
        self.message = "Ses bileşenleri açılıyor…"
        self.session = None
        self.demo = demo
        self.transcriber = self.speaker = None
        self.vad_factory = None
        self.profile = Profile()
        self.profile_store = ProfileStore(DATA_ROOT / "profile.json")
        self.calibration_store = CalibrationStore(DATA_ROOT / "audio_calibration.json")
        self.plan_store = PlanStore(DATA_ROOT / "plan.json")
        self.vad_threshold = SETTINGS.vad_threshold
        self.ollama_client = None
        self.prompt_cache = OrderedDict()
        self.prompt_cache_bytes = 0
        self.asr_cpu = SerialCPU("jarvis-asr")
        self.tts_cpu = SerialCPU("jarvis-tts")
        self.analysis_cpu = SerialCPU("jarvis-analysis")

    async def synthesize_guidance(self, text):
        """Small RAM-only cache for repeated local guidance, never normal chat."""
        if text in self.prompt_cache:
            self.prompt_cache.move_to_end(text)
            return self.prompt_cache[text]
        samples, rate = await self.tts_cpu.call(self.speaker.synthesize, text)
        if samples.nbytes <= SETTINGS.prompt_cache_max_bytes:
            while self.prompt_cache and (len(self.prompt_cache) >= SETTINGS.prompt_cache_entries or self.prompt_cache_bytes + samples.nbytes > SETTINGS.prompt_cache_max_bytes):
                _, (old, _) = self.prompt_cache.popitem(last=False)
                self.prompt_cache_bytes -= old.nbytes
            samples.setflags(write=False)
            self.prompt_cache[text] = (samples, rate)
            self.prompt_cache_bytes += samples.nbytes
        return samples, rate

    async def initialize(self):
        warmer = None
        try:
            self.profile = self.profile_store.load()
            self.vad_threshold = self.calibration_store.load_threshold()
            if self.demo:
                self.ready, self.loading, self.message = True, False, "Görsel test modu — gerçek ses modelleri bağlı değil."
                return
            if not (DATA_ROOT / "prepared.json").is_file():
                raise RuntimeError("İlk kurulumu tamamlamak için KUR.cmd dosyasını çalıştır.")
            self.ollama_client = httpx.AsyncClient(timeout=SETTINGS.ollama_timeout_s, trust_env=False)
            response = await self.ollama_client.get(SETTINGS.ollama_url + "/api/tags", timeout=10)
            response.raise_for_status()
            names = [m.get("name") for m in response.json().get("models", [])]
            if SETTINGS.model not in names:
                raise RuntimeError("gpt-oss:20b bulunamadı. Önce Ollama'da modelin kurulu olduğunu kontrol et.")
            warmer = asyncio.create_task(asyncio.wait_for(llm.warmup(self.ollama_client), SETTINGS.warmup_timeout_s))
            # This process never downloads speech weights at runtime.
            os.environ["HF_HOME"] = str(TTS_CACHE)
            os.environ["HF_HUB_CACHE"] = str(TTS_CACHE / "hub")
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
            from .asr import Transcriber, VoiceActivityDetector
            from .tts import Speaker
            self.transcriber, self.speaker = await asyncio.gather(
                self.asr_cpu.call(Transcriber, str(ASR_PATH), SETTINGS.asr_threads),
                self.tts_cpu.call(Speaker, TTS_CACHE, SETTINGS.tts_threads),
            )
            self.vad_factory = VoiceActivityDetector
            # Pay the first synthesis cost before inviting microphone input.
            first_prompt = Onboarding(self.profile).start().text
            for piece in SentenceBuffer(SETTINGS.max_sentence_chars).push(first_prompt, final=True):
                await self.synthesize_guidance(clean_spoken(piece))
            warm_message = ""
            try:
                await warmer
            except (llm.ModelUnavailable, asyncio.TimeoutError):
                warm_message = " İlk model yanıtı hazırlanırken biraz bekleyebilirsin."
            self.ready, self.message = True, "Hazır. Konuşmaya başlayabiliriz."
            self.message += warm_message
        except (ProfileError, CalibrationError) as exc:
            self.message = str(exc)
        except (httpx.HTTPError, OSError):
            self.message = "Ollama veya ses dosyaları açılamadı. Ollama'yı aç; gerekirse KUR.cmd dosyasını yeniden çalıştır."
        except Exception as exc:
            # Only our setup errors are shown; third-party exceptions may contain paths/URLs.
            self.message = str(exc) if isinstance(exc, RuntimeError) else "Ses bileşenleri başlatılamadı. KUR.cmd ile kurulum kontrolünü yeniden çalıştır."
        finally:
            if warmer:
                if not warmer.done():
                    warmer.cancel()
                await asyncio.gather(warmer, return_exceptions=True)
            self.loading = False
            if self.session:
                self.session.use_profile(self.profile)
                await self.session.send_profile()
                await self.session.send(event("ready", ready=self.ready, message=self.message))


class Session:
    def __init__(self, websocket: WebSocket, runtime: Runtime):
        self.ws, self.runtime = websocket, runtime
        self.id = uuid.uuid4().hex
        self.gate = EpochGate()
        self.profile = getattr(runtime, "profile", Profile())
        self.onboarding = Onboarding(self.profile)
        self.skip_onboarding = False
        self.segmenter = Segmenter(segment_settings(self.profile, getattr(runtime, "vad_threshold", SETTINGS.vad_threshold)))
        self.calibration = None
        self.calibration_result = None
        self.calibration_timer = None
        self.vad = None
        self.send_lock = asyncio.Lock()
        self.job = None
        self.history = []
        self.turns = deque()
        self.memory = MemoryStore(DATA_ROOT / "memories.sqlite3")
        self.api_key = ""
        self.web_enabled = False
        self.barge_in = False
        self.acoustic_enabled = False
        self.desktop_enabled = False
        self.speech_enabled = True
        self.plan_store = getattr(runtime, "plan_store", PlanStore(DATA_ROOT / "plan.json"))
        self.plan_draft = None
        self.plan_draft_deadline = 0.0
        self.application_times = deque()
        self.effect_epochs = deque(maxlen=SETTINGS.control_id_cache_size)
        self.control_ids = OrderedDict()
        self.capture_info = sanitize_capture(None)
        self.pending = {}
        self.closed = False
        self.tasks = set()

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        def finished(done):
            self.tasks.discard(done)
            if not done.cancelled():
                done.exception()  # retrieve failures; user-facing errors are handled below
        task.add_done_callback(finished)
        return task

    async def send(self, data):
        if self.closed:
            return
        async with self.send_lock:
            if not self.closed:
                await self.ws.send_json({"session_id": self.id, **data})

    async def status(self, message):
        await self.send(event("status", message=message))

    def use_profile(self, profile):
        self.profile = profile
        self.runtime.profile = profile
        self.segmenter = Segmenter(segment_settings(profile, getattr(self.runtime, "vad_threshold", SETTINGS.vad_threshold)))
        if self.vad:
            self.vad.reset()

    async def send_profile(self):
        await self.send(event("profile", profile=self.profile.to_dict(), onboarding={"active": self.onboarding.active, "stage": self.onboarding.stage}))

    def current_draft(self):
        if self.plan_draft is not None and time.monotonic() >= self.plan_draft_deadline:
            self.plan_draft = None
        return self.plan_draft

    async def send_plan_state(self, epoch=None):
        epoch = self.gate.epoch if epoch is None else epoch
        saved = self.plan_store.load()
        draft = self.current_draft()
        if not self.closed and self.gate.epoch == epoch:
            await self.send(event("plan", epoch=epoch, draft=draft.to_dict() if draft else None,
                                  saved=saved.to_dict() if saved else None))

    def saved_plan_for_context(self):
        try:
            return self.plan_store.load()
        except PlanError:
            # A bad plan is never reset or silently replaced. Normal chat can
            # still run without it; plan_get reports the actionable error.
            return None

    def apply_plan(self, kind, epoch, identifier=None):
        """Commit only explicit current-user actions, without an intervening await."""
        if self.closed or self.gate.epoch != epoch:
            raise asyncio.CancelledError
        if kind in {"save", "discard"}:
            draft = self.current_draft()
            if draft is None or (identifier is not None and identifier != draft.id):
                raise PlanError("Güncel bir plan taslağı yok veya taslağın süresi doldu. Yeniden plan oluştur.")
            if kind == "save":
                self.plan_store.save(draft)
                message = "Planını bu bilgisayara kaydettim. Planımı göster diyerek yeniden açabilirsin."
            else:
                message = "Plan taslağını kaldırdım. Kayıtlı planın korundu."
            self.plan_draft = None
            return message
        saved = self.plan_store.load()
        if identifier is not None and (saved is None or identifier != saved.id):
            raise PlanError("Kayıtlı plan değişmiş. Güncel planı açıp yeniden dene.")
        self.plan_store.delete()
        return "Kayıtlı planını sildim." if saved else "Kayıtlı bir planın yok."

    async def local_command(self, text, epoch, history):
        """This router receives direct user input only, never model/web content."""
        app_id = application_command(text, self.profile.assistant_name)
        if app_id is not None:
            if not self.gate.accepts(epoch) or self.closed:
                raise asyncio.CancelledError
            if app_id == "unsupported":
                return "Şimdilik Hesap Makinesi, Not Defteri, Dosya Gezgini ve Paint için açma komutunu destekliyorum."
            if not self.desktop_enabled:
                return "Uygulama açma izni kapalı. Ayarlardan Bilgisayarda uygulama açma seçeneğini açabilirsin."
            if self.runtime.demo:
                return "Görsel test modunda uygulama başlatılmaz."
            now = time.monotonic()
            while self.application_times and self.application_times[0] <= now - 60:
                self.application_times.popleft()
            if epoch in self.effect_epochs:
                return "Bu açma isteğini zaten işledim."
            if (len(self.application_times) >= SETTINGS.desktop_limit_per_minute
                    or (self.application_times and now - self.application_times[-1] < SETTINGS.desktop_min_interval_s)):
                return "Uygulama açma istekleri çok sık geldi. Biraz bekleyip yeniden söyle."
            # No await between authority checks, consumption and Popen. Stop
            # cannot undo a process already launched; it cancels future work.
            self.effect_epochs.append(epoch)
            self.application_times.append(now)
            result = launch_application(app_id)
            await self.send(event("application", epoch=epoch, app_id=result.app_id, label=result.label,
                                  status=result.status, message=result.message))
            return result.message
        command = plan_command(text)
        if command is None:
            return None
        if not self.gate.accepts(epoch) or self.closed:
            raise asyncio.CancelledError
        kind, goal = command
        if kind == "create":
            if not goal:
                return "Hangi hedef için plan hazırlayayım? Örneğin Plan oluştur: her akşam yarım saat Python öğrenmek istiyorum diyebilirsin."
            if self.runtime.demo:
                return "Görsel test modunda model bağlı değil; gerçek plan üretimi normal başlatmada çalışır."
            self.plan_draft = None
            await self.send_plan_state(epoch)
            await self.status("Tercihlerin ve kaydettiğin notlarla plan taslağını hazırlıyorum…")
            if not self.gate.accepts(epoch):
                raise asyncio.CancelledError
            draft = await llm.make_plan(goal, history, self.memory.list(), profile=self.profile,
                                       client=getattr(self.runtime, "ollama_client", None))
            if not self.gate.accepts(epoch) or self.closed:
                raise asyncio.CancelledError
            self.plan_draft = draft
            self.plan_draft_deadline = time.monotonic() + SETTINGS.plan_draft_ttl_s
            await self.send_plan_state(epoch)
            return draft.spoken() + " Kaydetmemi istersen planı kaydet diyebilirsin."
        if kind == "show":
            draft = self.current_draft()
            saved = self.plan_store.load()
            await self.send_plan_state(epoch)
            if draft:
                return "Henüz kaydedilmemiş taslağın: " + draft.spoken()
            return saved.spoken() if saved else "Henüz kayıtlı bir planın yok. Plan oluştur diyerek hedefini söyleyebilirsin."
        message = self.apply_plan(kind, epoch)
        await self.send_plan_state(epoch)
        return message

    async def send_onboarding(self, reply):
        await self.send(event("onboarding", epoch=self.gate.epoch, active=self.onboarding.active,
                              stage=reply.stage, message=reply.text))

    async def accept_onboarding(self, text):
        reply = self.onboarding.reply(text)
        if reply.completed_profile is not None:
            try:
                self.runtime.profile_store.save(reply.completed_profile)
            except ProfileError:
                # A disk error must not leave a completed-looking wizard with
                # unsaved preferences. Keep the draft at explicit confirmation.
                self.onboarding.stage, self.onboarding.active = "confirmation", True
                raise
            self.use_profile(reply.completed_profile)
            self.onboarding = Onboarding(self.profile)
            self.skip_onboarding = False
            await self.send_profile()
        elif reply.cancelled:
            self.skip_onboarding = True
        await self.send_onboarding(reply)
        return reply.text

    async def begin_onboarding(self, request_id=None):
        self.cancel_calibration()
        self.gate.active = True
        await self.interrupt(request_id)
        self.onboarding = Onboarding(self.profile)
        self.skip_onboarding = False
        reply = self.onboarding.start()
        self.segmenter.reset()
        if self.vad:
            self.vad.reset()
        await self.send_onboarding(reply)
        self.job = self.spawn(self.handle_turn(self.gate.epoch, canned=reply.text, guided=True))

    def cancel_calibration(self):
        self.calibration = None
        if self.calibration_timer and self.calibration_timer is not asyncio.current_task():
            self.calibration_timer.cancel()
        self.calibration_timer = None

    async def calibration_deadline(self, marker):
        await asyncio.sleep(SETTINGS.calibration_timeout_s)
        if self.calibration is marker:
            self.cancel_calibration()
            self.segmenter.reset()
            await self.interrupt()
            await self.send(event("calibration", stage="error", epoch=self.gate.epoch,
                                  message="Mikrofon kontrolü zaman aşımına uğradı. Mikrofon iznini ve seçili giriş aygıtını kontrol edip yeniden başlat."))

    async def calibration_prompt(self, epoch, marker, next_stage, text):
        ok = await self.handle_turn(epoch, canned=text, guided=True, wait_playback=True)
        if self.calibration is not marker or not self.gate.accepts(epoch):
            return
        if not ok:
            self.cancel_calibration()
            await self.send(event("calibration", stage="error", epoch=epoch, message="Kontrolün sesli yönergesi tamamlanamadı. Yeniden başlat."))
            return
        self.segmenter.reset()
        if self.vad:
            self.vad.reset()
        marker["stage"] = next_stage
        if self.calibration_timer:
            self.calibration_timer.cancel()
        self.calibration_timer = self.spawn(self.calibration_deadline(marker))
        await self.send(event("calibration", stage=next_stage, epoch=epoch,
                              message="Üç saniye sessiz kal; ortamı ölçüyorum." if next_stage == "noise" else PHRASE_PROMPT))

    async def begin_calibration(self, request_id=None):
        self.cancel_calibration()
        self.calibration_result = None
        if self.onboarding.active:
            self.onboarding = Onboarding(self.profile)
            await self.send(event("onboarding", active=False, stage="cancelled", message="Tanışma durduruldu; mevcut profil korundu."))
        self.gate.active = True
        await self.interrupt(request_id)
        marker = self.calibration = {"stage": "prompt", "meter": NoiseMeter()}
        await self.send(event("calibration", stage="prompt", epoch=self.gate.epoch, message=NOISE_PROMPT))
        self.job = self.spawn(self.calibration_prompt(self.gate.epoch, marker, "noise", NOISE_PROMPT))

    async def interrupt(self, request_id=None):
        epoch = self.gate.advance()
        if self.job and self.job is not asyncio.current_task() and not self.job.done() and not self.job.cancelling():
            self.job.cancel()
        self.job = None
        for item in self.pending.values():
            if not item["ack"].done():
                item["ack"].cancel()
        self.pending.clear()
        await self.send(event("epoch", epoch=epoch, request_id=request_id))
        return epoch

    def allowed_turn(self):
        now = time.monotonic()
        while self.turns and self.turns[0] < now - 60:
            self.turns.popleft()
        if len(self.turns) >= SETTINGS.turn_limit_per_minute:
            return False
        self.turns.append(now)
        return True

    async def receive_audio(self, raw):
        if not self.gate.active or not self.runtime.ready or self.runtime.demo:
            return
        if len(raw) != SETTINGS.frame_samples * 2:
            raise ValueError("Ses paketi biçimi uyumsuz.")
        if self.vad is None:
            self.vad = self.runtime.vad_factory()
        audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        if self.calibration and self.calibration["stage"] in {"prompt", "processing"}:
            # Headset barge-in is deliberately ignored while reading a measured
            # calibration instruction, so synthesized audio cannot be its sample.
            return
        probability = self.vad.probability(audio)
        if self.calibration and self.calibration["stage"] == "noise":
            marker = self.calibration
            meter = marker["meter"]
            meter.add(audio, probability)
            if meter.done:
                marker["noise"] = meter.result()
                marker["stage"] = "prompt"
                if self.calibration_timer:
                    self.calibration_timer.cancel()
                await self.interrupt()
                await self.send(event("calibration", stage="prompt", epoch=self.gate.epoch,
                                      message=PHRASE_PROMPT, measurements=marker["noise"]))
                self.job = self.spawn(self.calibration_prompt(self.gate.epoch, marker, "phrase", PHRASE_PROMPT))
            return
        started, utterance = self.segmenter.feed(audio, probability)
        if utterance and utterance.forced_end:
            # A forced boundary is not the user's completed thought. Stop
            # explicitly instead of answering a prefix that the next onset
            # would immediately cancel or silently losing the earlier audio.
            self.gate.active = False
            self.cancel_calibration()
            self.segmenter.reset()
            self.vad.reset()
            await self.interrupt()
            await self.send(event(
                "capture_stop", epoch=self.gate.epoch,
                message="Tek seferde en fazla 30 saniye konuşabilirsin. Daha kısa bir cümleyle yeniden başla.",
            ))
            return
        if started:
            await self.interrupt()
            await self.status("Seni dinliyorum…")
        if utterance:
            if not self.allowed_turn():
                await self.send(event("error", message="Çok sık konuşma başlangıcı algılandı. Mikrofonu ve hoparlör yankısını kontrol et; biraz sonra yeniden dene."))
                return
            if self.calibration and self.calibration["stage"] == "phrase":
                self.calibration["stage"] = "processing"
                if self.calibration_timer:
                    self.calibration_timer.cancel()
            self.job = self.spawn(self.handle_turn(self.gate.epoch, utterance=utterance))

    async def control(self, data):
        kind = data.get("type")
        request_id = data.get("request_id")
        if not isinstance(request_id, str) or len(request_id) > 96:
            request_id = None
        if kind in {"text", "plan_save", "plan_discard", "plan_delete"} and request_id:
            key = (kind, request_id)
            if key in self.control_ids:
                await self.send(event("epoch", epoch=self.gate.epoch, request_id=request_id))
                return
            self.control_ids[key] = True
            while len(self.control_ids) > SETTINGS.control_id_cache_size:
                self.control_ids.popitem(last=False)
        if kind == "start":
            self.cancel_calibration()
            if not self.runtime.ready:
                await self.send(event("error", message=self.runtime.message))
                return
            self.gate.active = True
            self.segmenter.reset()
            if self.vad:
                self.vad.reset()
            if self.onboarding.active:
                await self.interrupt(request_id)
                reply = self.onboarding.repeat()
                await self.send_onboarding(reply)
                self.job = self.spawn(self.handle_turn(self.gate.epoch, canned=reply.text, guided=True))
                return
            if not self.profile.onboarding_complete and not self.skip_onboarding:
                await self.begin_onboarding(request_id)
                return
            await self.interrupt(request_id)
            await self.status("Seni dinliyorum…")
        elif kind in ("stop", "mute"):
            self.gate.active = False
            was_calibrating = bool(self.calibration)
            self.cancel_calibration()
            self.segmenter.reset()
            if self.vad:
                self.vad.reset()
            await self.interrupt(request_id)
            if was_calibrating:
                await self.send(event("calibration", stage="cancelled", epoch=self.gate.epoch, message="Mikrofon kontrolü durduruldu. Ayar değiştirilmedi."))
            await self.status("Mikrofon kapalı.")
        elif kind == "interrupt":
            was_calibrating = bool(self.calibration)
            self.cancel_calibration()
            self.segmenter.reset()
            if self.vad:
                self.vad.reset()
            await self.interrupt(request_id)
            if was_calibrating:
                await self.send(event("calibration", stage="cancelled", epoch=self.gate.epoch, message="Mikrofon kontrolü durduruldu. Ayar değiştirilmedi."))
            await self.status("Seni dinliyorum…" if self.gate.active else "Mikrofon kapalı.")
        elif kind in {"onboarding_start", "calibration_start"}:
            if not self.runtime.ready:
                await self.interrupt(request_id)
                await self.send(event("error", message=self.runtime.message))
                return
            if kind == "onboarding_start":
                await self.begin_onboarding(request_id)
            else:
                await self.begin_calibration(request_id)
        elif kind == "onboarding_cancel":
            self.cancel_calibration()
            reply = self.onboarding.reply("iptal") if self.onboarding.active else None
            self.onboarding = Onboarding(self.profile)
            self.skip_onboarding = True
            await self.interrupt(request_id)
            await self.send(event("onboarding", active=False, stage="cancelled", epoch=self.gate.epoch,
                                  message=reply.text if reply else "Tanışma durduruldu; mevcut profil korundu."))
            await self.status("Seni dinliyorum…" if self.gate.active else "Mikrofon kapalı.")
        elif kind == "calibration_cancel":
            self.cancel_calibration()
            self.segmenter.reset()
            if self.vad:
                self.vad.reset()
            await self.interrupt(request_id)
            await self.send(event("calibration", stage="cancelled", epoch=self.gate.epoch, message="Mikrofon kontrolü durduruldu. Ayar değiştirilmedi."))
            await self.status("Seni dinliyorum…" if self.gate.active else "Mikrofon kapalı.")
        elif kind == "calibration_apply":
            self.cancel_calibration()
            await self.interrupt(request_id)
            try:
                self.runtime.calibration_store.save(self.calibration_result or {})
                self.runtime.vad_threshold = self.runtime.calibration_store.load_threshold()
                self.use_profile(self.profile)
                await self.send(event("calibration", stage="applied", epoch=self.gate.epoch,
                                      message="Mikrofon ayarın kaydedildi. Mikrofon veya ortam değişirse yeniden ölç."))
            except CalibrationError as exc:
                await self.send(event("error", message=str(exc)))
        elif kind == "profile_save":
            self.cancel_calibration()
            await self.interrupt(request_id)
            try:
                profile = Profile.from_dict(data.get("profile"))
                if not profile.onboarding_complete:
                    raise ProfileError("Profil kaydı için isim ve tercihlerini onayla.")
                self.runtime.profile_store.save(profile)
                self.use_profile(profile)
                self.onboarding = Onboarding(profile)
                self.skip_onboarding = False
                await self.send_profile()
                await self.send(event("onboarding", active=False, stage="complete", epoch=self.gate.epoch, message="Tercihlerin kaydedildi."))
                await self.status("Tercihlerin kaydedildi.")
            except ProfileError as exc:
                await self.send(event("error", message=str(exc)))
        elif kind == "settings":
            was_analyzing = self.acoustic_enabled
            was_speaking = self.speech_enabled
            if "speech_enabled" in data:
                self.speech_enabled = data["speech_enabled"] is True
            if was_speaking != self.speech_enabled and not self.onboarding.active and not self.calibration:
                await self.interrupt()
            if "acoustic_enabled" in data:
                self.acoustic_enabled = data["acoustic_enabled"] is True
            if was_analyzing and not self.acoustic_enabled and not self.onboarding.active and not self.calibration:
                # Guided flows never consume acoustic observations. Interrupting
                # a calibration prompt here would strand its measurement phase.
                await self.interrupt()
            if "api_key" in data:
                key = str(data["api_key"]).strip()
                if len(key) > 512 or any(ord(c) < 32 for c in key):
                    await self.send(event("error", message="API anahtarı biçimi geçersiz."))
                    return
                self.api_key = key
            self.web_enabled = bool(data.get("web_enabled", self.web_enabled)) and bool(self.api_key)
            self.barge_in = bool(data.get("barge_in", self.barge_in))
            if "desktop_enabled" in data:
                self.desktop_enabled = data["desktop_enabled"] is True
            await self.send(event("settings", web_enabled=self.web_enabled, has_api_key=bool(self.api_key), api_key_configured=bool(self.api_key), barge_in=self.barge_in, acoustic_enabled=self.acoustic_enabled, desktop_enabled=self.desktop_enabled, speech_enabled=self.speech_enabled))
            await self.status("Ayarlar uygulandı." if not self.web_enabled else "İnternet araştırması açık. Arama sorguları Ollama'ya gönderilir.")
        elif kind == "capture_info":
            self.capture_info = sanitize_capture(data)
        elif kind == "text":
            text = str(data.get("text", "")).strip()
            if not self.runtime.ready or not text or len(text) > SETTINGS.max_text_chars:
                await self.send(event("error", message="Mesaj boş, çok uzun veya ses modelleri henüz hazır değil."))
                return
            if not self.allowed_turn():
                await self.send(event("error", message="Biraz bekleyip yeniden dene."))
                return
            if self.calibration:
                # A typed sentence cannot count as microphone recognition.
                await self.interrupt(request_id)
                self.cancel_calibration()
                await self.send(event("calibration", stage="cancelled", epoch=self.gate.epoch,
                                      message="Yazılı mesaja geçildi; mikrofon kontrolü iptal edildi."))
            self.gate.active = True
            await self.interrupt(request_id)
            self.job = self.spawn(self.handle_turn(self.gate.epoch, text=text))
        elif kind == "played":
            if data.get("epoch") != self.gate.epoch:
                return
            item = self.pending.pop(str(data.get("segment_id", "")), None)
            if item and not item["ack"].done():
                # Acknowledgement represents a fully played sentence.
                item["history"]["content"] += (" " if item["history"]["content"] else "") + item["text"]
                item["ack"].set_result(True)
        elif kind == "memories":
            await self.send(event("memories", items=self.memory.list()))
        elif kind in {"plan_get", "apps_get"}:
            try:
                if kind == "plan_get":
                    await self.send_plan_state()
                else:
                    await self.send(event("apps", items=apps_catalog()))
            except PlanError as exc:
                await self.send(event("error", message=str(exc)))
        elif kind in {"plan_save", "plan_discard", "plan_delete"}:
            if not request_id:
                await self.send(event("error", message="Plan işlemi kimliği eksik. Uygulama penceresini yeniden aç."))
                return
            self.cancel_calibration()
            epoch = await self.interrupt(request_id)
            if not self.allowed_turn():
                await self.send(event("error", message="Biraz bekleyip yeniden dene."))
                return
            identifier = data.get("plan_id" if kind == "plan_delete" else "draft_id")
            try:
                if not isinstance(identifier, str) or len(identifier) != 32:
                    raise PlanError("Plan kimliği eksik veya geçersiz.")
                message = self.apply_plan(kind.removeprefix("plan_"), epoch, identifier)
                await self.send_plan_state(epoch)
                await self.status(message)
            except PlanError as exc:
                await self.send(event("error", message=str(exc)))
        elif kind == "delete_memories":
            self.memory.delete_all()
            await self.send(event("memories", items=[]))
            await self.status("Kaydettiğin hatıralar silindi.")
        elif kind == "ping":
            await self.send(event("pong"))

    async def handle_turn(self, epoch, utterance=None, text=None, canned=None, guided=False, wait_playback=False):
        started = utterance.ended_at if utterance else time.perf_counter()
        endpoint_ms = round((time.perf_counter() - started) * 1000) if utterance else 0
        turn_id = uuid.uuid4().hex
        speech_task = None
        producer_task = None
        analysis_task = None
        acoustic_observation = None
        try:
            asr_ms = 0
            if utterance:
                if self.acoustic_enabled and not self.onboarding.active and not self.calibration:
                    analysis_task = self.spawn(self.runtime.analysis_cpu.call(
                        analyze, utterance.audio, "", utterance.speech_fraction, dict(self.capture_info)
                    ))
                await self.status("Söylediğini çözüyorum…")
                before = time.perf_counter()
                text = await self.runtime.asr_cpu.call(self.runtime.transcriber.transcribe, utterance.audio)
                asr_ms = round((time.perf_counter() - before) * 1000)
            if not self.gate.accepts(epoch):
                return False
            text = (text or "").strip()
            if analysis_task is not None:
                try:
                    measured = await analysis_task
                    if self.acoustic_enabled and self.gate.accepts(epoch):
                        tempo = round(60 * len(words(text)) / measured.duration_s, 1) if text and measured.signal_valid and measured.speech_fraction != 0 and measured.duration_s > 0 else None
                        acoustic_observation = replace(measured, words_per_minute=tempo)
                        await self.send(event("acoustics", epoch=epoch, observation=acoustic_observation.to_dict()))
                except (ValueError, RuntimeError):
                    # Speech can still be answered if this optional measurement
                    # was unusable. Do not fabricate an emotion or a valid score.
                    acoustic_observation = None
            if not text and canned is None and not self.calibration:
                await self.status("Seni dinliyorum…")
                return False
            if text:
                await self.send(event("transcript", role="user", text=text, epoch=epoch))
            if not self.gate.accepts(epoch):
                return False
            if text.casefold().strip(".! ") in {"dur", "sus", "sesi kes", "konuşmayı durdur"}:
                if self.calibration:
                    self.cancel_calibration()
                    await self.send(event("calibration", stage="cancelled", epoch=epoch, message="Mikrofon kontrolü durduruldu."))
                await self.status("Seni dinliyorum…")
                return True
            if canned is None and self.calibration and utterance is not None:
                marker = self.calibration
                if text.casefold().strip(".! ") in {"iptal", "vazgeç"}:
                    canned = "Mikrofon kontrolünü iptal ettim. Ayar değiştirilmedi."
                    self.cancel_calibration()
                    await self.send(event("calibration", stage="cancelled", epoch=epoch, message=canned))
                else:
                    result, canned = evaluate(marker["noise"], utterance.audio, text)
                    self.calibration_result = result
                    self.cancel_calibration()
                    await self.send(event("calibration", stage="result", epoch=epoch, message=canned, measurements=result))
                guided = True
            elif canned is None and self.onboarding.active:
                canned = await self.accept_onboarding(text)
                guided = True
            elif canned is None:
                command_text = text.replace("İ", "i").replace("I", "ı").lower().strip(".!? ")
                if command_text in {"mikrofonu ölç", "mikrofon kalibrasyonu", "mikrofonu kalibre et"}:
                    await self.begin_calibration()
                    return True
                if command_text in {"yeniden tanışalım", "tanışmayı başlat", "sesli tanışmayı başlat"}:
                    await self.begin_onboarding()
                    return True
                if command_text == "mikrofon ayarını uygula":
                    await self.control({"type": "calibration_apply"})
                    return True
            history_before = [{"role": m["role"], "content": m["content"]} for m in self.history if m["content"]]
            assistant_entry = {"role": "assistant", "content": ""}
            if not guided:
                self.history.append({"role": "user", "content": text})
                self.history.append(assistant_entry)
                self.history = self.history[-20:]
            if canned is None:
                canned = await self.local_command(text, epoch, history_before)
            if not self.gate.accepts(epoch):
                return False
            command = memory_command(text) if canned is None else None
            if command:
                action, value = command
                if action == "add":
                    self.memory.add(value, turn_id)
                    canned = "Bunu hatırlayacağım: " + value
                elif action == "empty":
                    canned = "Neyi hatırlamamı istiyorsun? Bunu hatırla diyerek kaydetmemi istediğin bilgiyi söyle."
                elif action == "delete_all":
                    self.memory.delete_all()
                    canned = "Kaydettiğin hatıraları sildim."
                else:
                    notes = self.memory.list()
                    canned = "Henüz kalıcı bir not kaydetmedin." if not notes else "Şunları hatırlıyorum: " + "; ".join(n["text"] for n in notes[:5])
                await self.send(event("memories", items=self.memory.list()))
            queue = asyncio.Queue(maxsize=SETTINGS.max_pending_audio)
            timings = {"endpoint_ms": endpoint_ms, "asr_ms": asr_ms, "llm_first_ms": None,
                       "first_audio_ms": None, "tts_first_ms": None, "tts_rtf": None,
                       "measurement_kind": "guided" if guided else "conversation"}
            if acoustic_observation is not None:
                timings["analysis_ms"] = acoustic_observation.analysis_ms

            async def speak():
                number = 0
                while True:
                    piece = await queue.get()
                    if piece is None:
                        return
                    if not self.gate.accepts(epoch):
                        return
                    if not self.speech_enabled and not guided:
                        continue
                    spoken = clean_spoken(piece)
                    if not spoken:
                        continue
                    tts_start = time.perf_counter()
                    if self.runtime.demo:
                        pcm, rate = np.zeros(2400, dtype=np.float32), 24000
                    elif guided and hasattr(self.runtime, "synthesize_guidance"):
                        pcm, rate = await self.runtime.synthesize_guidance(spoken)
                    else:
                        pcm, rate = await self.runtime.tts_cpu.call(self.runtime.speaker.synthesize, spoken)
                    tts_seconds = time.perf_counter() - tts_start
                    if not self.gate.accepts(epoch):
                        return
                    if pcm.size == 0:
                        continue
                    while len(self.pending) >= SETTINGS.max_pending_audio:
                        first = next(iter(self.pending.values()))["ack"]
                        await asyncio.wait_for(asyncio.shield(first), SETTINGS.playback_ack_timeout_s)
                    number += 1
                    sid = f"{turn_id}-{number}"
                    ack = asyncio.get_running_loop().create_future()
                    self.pending[sid] = {"ack": ack, "history": assistant_entry, "text": piece}
                    pcm16 = (np.clip(pcm, -1, 1) * 32767).astype("<i2")
                    if timings["first_audio_ms"] is None:
                        timings["first_audio_ms"] = round((time.perf_counter() - started) * 1000)
                        timings["server_audio_ready_ms"] = timings["first_audio_ms"]
                        timings["tts_first_ms"] = round(tts_seconds * 1000)
                        timings["tts_rtf"] = round(tts_seconds / (pcm.size / rate), 4)
                        await self.send(event("metrics", epoch=epoch, turn_id=turn_id, **timings))
                    await self.send(event("audio", epoch=epoch, turn_id=turn_id, segment_id=sid, sample_rate=rate, pcm=base64.b64encode(pcm16.tobytes()).decode("ascii"), text=piece, guided=guided))

            speech_task = self.spawn(speak())
            generated = ""
            llm_start = time.perf_counter()

            async def status(message):
                if self.gate.accepts(epoch):
                    await self.status(message)

            async def sources(items):
                if self.gate.accepts(epoch):
                    await self.send(event("sources", epoch=epoch, items=items))

            async def model_metrics(values):
                timings.update(values)
                if self.gate.accepts(epoch):
                    await self.send(event("metrics", epoch=epoch, turn_id=turn_id, **timings))

            async def pieces():
                if canned:
                    yield canned
                elif self.runtime.demo:
                    yield "Bu görsel test ekranı. Gerçek konuşma için normal başlatıcıyı kullan."
                else:
                    async for delta in llm.answer(text, history_before, self.memory.list(), self.api_key, self.web_enabled, sources, status,
                                                  profile=self.profile, client=getattr(self.runtime, "ollama_client", None), metrics_callback=model_metrics,
                                                  acoustic=acoustic_observation if self.acoustic_enabled else None,
                                                  desktop_enabled=self.desktop_enabled, saved_plan=self.saved_plan_for_context()):
                        yield delta

            async def produce():
                nonlocal generated
                buffer = SentenceBuffer(SETTINGS.max_sentence_chars)
                async for delta in pieces():
                    if not self.gate.accepts(epoch):
                        raise asyncio.CancelledError
                    if canned is None and len(generated) + len(delta) > SETTINGS.reply_max_chars:
                        raise llm.ModelUnavailable("Yanıt metin sınırını aştı ve tamamlanmış sayılmadı. Daha kısa bir bölüm iste.")
                    if canned is None and timings["llm_first_ms"] is None:
                        timings["llm_first_ms"] = round((time.perf_counter() - llm_start) * 1000)
                    generated += delta
                    for piece in buffer.push(delta):
                        await queue.put(piece)
                for piece in buffer.push("", final=True):
                    await queue.put(piece)
                await queue.put(None)

            producer_task = self.spawn(produce())
            try:
                # Observe both tasks for their entire lifetime, including
                # periods when the producer is waiting on an LLM HTTP chunk.
                # A TTS/ACK error must not wait for another token or queue.put.
                await asyncio.gather(producer_task, speech_task)
            finally:
                for task in (producer_task, speech_task):
                    if not task.done() and not task.cancelling():
                        task.cancel()
            if wait_playback and self.gate.accepts(epoch):
                acknowledgements = [item["ack"] for key, item in self.pending.items() if key.startswith(turn_id + "-")]
                for acknowledgement in acknowledgements:
                    await asyncio.wait_for(asyncio.shield(acknowledgement), SETTINGS.playback_ack_timeout_s)
            if self.gate.accepts(epoch):
                await self.send(event("transcript", role="assistant", text=generated, epoch=epoch))
                if not self.speech_enabled and not guided and self.gate.accepts(epoch):
                    assistant_entry["content"] = generated
                await self.send(event("audio_end", epoch=epoch))
                return True
        except asyncio.CancelledError:
            raise
        except llm.ModelUnavailable as exc:
            if self.gate.accepts(epoch):
                await self.send(event("error", message=str(exc)))
        except (ProfileError, CalibrationError, PlanError) as exc:
            if self.gate.accepts(epoch):
                await self.send(event("error", message=str(exc)))
        except Exception:
            if self.gate.accepts(epoch):
                await self.send(event("error", message="Sesli yanıt tamamlanamadı. Sesi kesip tekrar konuşmayı dene; sürerse pencereyi yeniden aç."))
        finally:
            for task in (producer_task, speech_task, analysis_task):
                if task and not task.done() and not task.cancelling():
                    task.cancel()
            if self.gate.accepts(epoch):
                await self.send(event("audio_end", epoch=epoch))
        return False

    async def close(self):
        if self.closed and self.memory is None:
            return
        self.closed = True
        self.cancel_calibration()
        self.gate.active = False
        self.api_key = ""
        self.acoustic_enabled = False
        self.desktop_enabled = False
        self.plan_draft = None
        self.capture_info = sanitize_capture(None)
        await self.interrupt()
        for task in list(self.tasks):
            if not task.done() and not task.cancelling():
                task.cancel()
        if self.memory is not None:
            self.memory.close()
            self.memory = None
        if self.tasks:
            await asyncio.wait(list(self.tasks), timeout=3)


def create_app(runtime: Runtime | None = None):
    runtime = runtime or Runtime()

    @asynccontextmanager
    async def lifespan(app):
        initializer = asyncio.create_task(runtime.initialize())
        yield
        if runtime.session:
            await runtime.session.close()
        initializer.cancel()
        await asyncio.gather(initializer, return_exceptions=True)
        if runtime.ollama_client:
            await runtime.ollama_client.aclose()
        runtime.prompt_cache.clear()
        runtime.asr_cpu.close()
        runtime.tts_cpu.close()
        runtime.analysis_cpu.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runtime = runtime
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    async def index():
        return FileResponse(static / "index.html", headers={"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; media-src 'self' blob:; worker-src 'self'; object-src 'none'; frame-ancestors 'none'", "Referrer-Policy": "no-referrer"})

    @app.get("/health")
    async def health():
        return {"version": __version__, "ready": runtime.ready, "loading": runtime.loading, "message": runtime.message, "demo": runtime.demo}

    @app.websocket("/ws")
    async def socket(ws: WebSocket):
        origin = ws.headers.get("origin", "")
        if origin not in {f"http://127.0.0.1:{SETTINGS.port}", f"http://localhost:{SETTINGS.port}"}:
            await ws.close(code=1008)
            return
        await ws.accept()
        session = None
        try:
            hello = await asyncio.wait_for(ws.receive_json(), 5)
            if hello.get("type") != "hello" or hello.get("protocol") != SETTINGS.protocol_version or not hmac.compare_digest(str(hello.get("token", "")), runtime.token):
                await ws.close(code=1008)
                return
            if runtime.session is not None:
                await ws.send_json(event("error", message="Jarvis başka bir pencerede açık. Önce o pencereyi kapat."))
                await ws.close(code=1008)
                return
            session = runtime.session = Session(ws, runtime)
            await session.send(event("hello", epoch=0, ready=runtime.ready, message=runtime.message, version=__version__, demo=runtime.demo,
                                     model=SETTINGS.model, endpoint="local"))
            await session.send(event("ready", ready=runtime.ready, message=runtime.message))
            await session.send_profile()
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await session.receive_audio(message["bytes"])
                elif message.get("text") is not None:
                    if len(message["text"]) > 8192:
                        raise ValueError("Mesaj boyutu aşıldı")
                    import json
                    data = json.loads(message["text"])
                    if not isinstance(data, dict):
                        raise ValueError("Mesaj biçimi geçersiz")
                    await session.control(data)
        except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, RuntimeError):
            pass
        finally:
            if session:
                session.closed = True
                await session.close()
                if runtime.session is session:
                    runtime.session = None

    return app
