"""Explicit Windows/WebView2 smoke; excluded from unittest discovery.

Run from the repository root: ``python tests/desktop_smoke.py``.
Only a fresh temporary data directory and demo mode are used. No microphone,
speech model, Ollama call, application launch or real user profile is involved.

Optional artifacts:
  JARVIS_DESKTOP_SMOKE_SCREENSHOT: PNG path; capture must pass when requested.
  JARVIS_DESKTOP_SMOKE_REPORT: JSON path with booleans and fixed error codes.

The native ExecuteScriptAsync/Control.Invoke APIs keep the application's CSP
and empty Python bridge intact. Their contract is documented by Microsoft:
https://learn.microsoft.com/en-us/dotnet/api/microsoft.web.webview2.core.corewebview2.executescriptasync
https://learn.microsoft.com/en-us/dotnet/api/microsoft.web.webview2.core.corewebview2.capturepreviewasync
https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.control.invoke
"""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time


TIMEOUT_S = 45
DEMO_ANSWER = "Bu görsel test ekranı. Gerçek konuşma için normal başlatıcıyı kullan."


class SmokeFailure(Exception):
    """Messages are fixed diagnostic codes, never native exception text."""


def emit_report(report):
    destination = os.environ.get("JARVIS_DESKTOP_SMOKE_REPORT")
    if destination:
        try:
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        except OSError:
            report["status"] = "failed"
            report["error_code"] = "report_write_failed"
    print(json.dumps(report, ensure_ascii=True, sort_keys=True), flush=True)


def main():
    report = {"status": "failed", "demo_only": True, "checks": {}, "stage": "platform"}
    if sys.platform != "win32":
        report["error_code"] = "windows_required"
        emit_report(report)
        return 2

    # The script path is tests/, whereas imports belong to the repository.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    finished = threading.Event()
    callback_started = threading.Event()
    callback_finished = threading.Event()
    callback_lock = threading.Lock()
    failure = []
    started = time.monotonic()
    deadline = started + TIMEOUT_S

    def fail(code):
        if not failure:
            failure.append(code)

    def watchdog():
        if not finished.wait(TIMEOUT_S):
            report["status"] = "failed"
            report["error_code"] = "smoke_timeout"
            emit_report(report)
            # This is the isolated CI smoke process, never the product path.
            # A wedged native GUI must not leave a runner blocked indefinitely.
            os._exit(2)
    threading.Thread(target=watchdog, name="jarvis-smoke-watchdog", daemon=True).start()

    try:
        with tempfile.TemporaryDirectory(prefix="jarvis-smoke-data-", ignore_cleanup_errors=True) as data_dir:
            # Must precede every jarvis import so no personal data can be read.
            os.environ["JARVIS_DATA_DIR"] = data_dir
            os.environ["ORT_DISABLE_TELEMETRY"] = "1"
            os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
            report["stage"] = "imports"
            import webview
            from jarvis.desktop import run_desktop
            from jarvis.config import SETTINGS

            original_create = webview.create_window

            def loaded(window):
                with callback_lock:
                    if callback_started.is_set():
                        return
                    callback_started.set()
                try:
                    if threading.current_thread() is threading.main_thread():
                        raise SmokeFailure("loaded_callback_requires_worker")
                    # pywebview has initialized pythonnet and its assemblies by
                    # this point. Native tasks start on the UI thread; only the
                    # background callback waits for their completion.
                    from System import Action

                    def native_task(factory, *, result=False):
                        holder = {}

                        def begin():
                            try:
                                holder["task"] = factory(window.native.webview.CoreWebView2)
                            except BaseException:
                                holder["error"] = "native_task_start_failed"
                        try:
                            window.native.Invoke(Action(begin))
                        except BaseException:
                            raise SmokeFailure("native_ui_invoke_failed") from None
                        if "error" in holder or "task" not in holder:
                            raise SmokeFailure(holder.get("error", "native_task_missing"))
                        task = holder["task"]
                        task_deadline = min(deadline - 4, time.monotonic() + 6)
                        while not task.IsCompleted:
                            if time.monotonic() >= task_deadline:
                                raise SmokeFailure("native_task_timeout")
                            time.sleep(0.02)
                        if task.IsCanceled or task.IsFaulted:
                            raise SmokeFailure("native_task_failed")
                        if result:
                            try:
                                return json.loads(str(task.Result))
                            except BaseException:
                                raise SmokeFailure("native_script_result_invalid") from None
                        return None

                    def evaluate(script):
                        return native_task(lambda core: core.ExecuteScriptAsync(script), result=True)

                    probe_script = """(() => {
                      const input = document.getElementById('text-input');
                      const send = document.getElementById('send-text');
                      const connection = document.getElementById('connection');
                      const model = document.getElementById('model-label');
                      const speech = document.getElementById('speech-enabled');
                      const voice = document.getElementById('voice-toggle');
                      const rect = input ? input.getBoundingClientRect() : null;
                      const users = Array.from(document.querySelectorAll('#transcript-messages article[data-role="user"] p'));
                      const answers = Array.from(document.querySelectorAll('#transcript-messages article[data-role="assistant"] p'));
                      return {
                        chat_visible: !!rect && rect.width > 0 && rect.height > 0 && getComputedStyle(input).visibility === 'visible',
                        chat_ready: !!send && !send.disabled && !!connection && connection.dataset.state === 'ready',
                        model_header: !!model && model.textContent.includes('Yerel model') && model.textContent.includes('gpt-oss:20b'),
                        secure_context: window.isSecureContext === true,
                        media_api_available: !!navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === 'function',
                        audio_worklet_available: typeof window.AudioContext === 'function' && typeof window.AudioWorkletNode === 'function' && 'audioWorklet' in window.AudioContext.prototype,
                        token_fragment_removed: location.hash === '',
                        microphone_closed: !!voice && voice.getAttribute('aria-pressed') === 'false',
                        speech_muted: !!speech && !speech.checked,
                        user_turn: users.some(p => p.textContent === 'demo'),
                        assistant_demo: answers.some(p => p.textContent === __DEMO_ANSWER__)
                      };
                    })()""".replace("__DEMO_ANSWER__", json.dumps(DEMO_ANSWER, ensure_ascii=True))

                    def wait_for(keys, code):
                        while time.monotonic() < deadline - 5:
                            probe = evaluate(probe_script)
                            if isinstance(probe, dict):
                                for key in keys:
                                    report["checks"][key] = probe.get(key) is True
                                if all(probe.get(key) is True for key in keys):
                                    return probe
                            time.sleep(0.1)
                        raise SmokeFailure(code)

                    report["stage"] = "render_and_websocket"
                    probe = wait_for(("chat_visible", "chat_ready", "model_header", "token_fragment_removed"), "chat_not_ready")
                    for key in ("chat_visible", "chat_ready", "model_header", "token_fragment_removed",
                                "secure_context", "media_api_available", "audio_worklet_available", "microphone_closed"):
                        report["checks"][key] = probe.get(key) is True
                    if not all(report["checks"].values()):
                        raise SmokeFailure("native_browser_capability_missing")

                    report["stage"] = "silent_chat_roundtrip"
                    submitted = evaluate("""(() => {
                      const speech = document.getElementById('speech-enabled');
                      const input = document.getElementById('text-input');
                      const form = document.getElementById('text-form');
                      if (!speech || !input || !form) return false;
                      speech.checked = false;
                      speech.dispatchEvent(new Event('change', {bubbles: true}));
                      input.value = 'demo';
                      form.requestSubmit();
                      return true;
                    })()""")
                    if submitted is not True:
                        raise SmokeFailure("text_submit_failed")
                    probe = wait_for(("speech_muted", "user_turn", "assistant_demo", "microphone_closed"), "demo_roundtrip_failed")
                    for key in ("speech_muted", "user_turn", "assistant_demo", "microphone_closed"):
                        report["checks"][key] = probe.get(key) is True

                    screenshot = os.environ.get("JARVIS_DESKTOP_SMOKE_SCREENSHOT")
                    if screenshot:
                        report["stage"] = "screenshot"
                        from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
                        from System.IO import MemoryStream
                        stream = MemoryStream()
                        try:
                            native_task(lambda core: core.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, stream))
                            image = bytes(stream.ToArray())
                            if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                                raise SmokeFailure("screenshot_not_png")
                            target = Path(screenshot)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(image)
                            report["checks"]["screenshot_captured"] = True
                        except SmokeFailure:
                            raise
                        except BaseException:
                            raise SmokeFailure("screenshot_capture_failed") from None
                        finally:
                            stream.Dispose()
                    report["stage"] = "window_close"
                except SmokeFailure as exc:
                    fail(str(exc))
                except BaseException:
                    fail("native_callback_failed")
                finally:
                    callback_finished.set()
                    try:
                        window.destroy()
                    except BaseException:
                        fail("window_close_failed")

            def create_window(*args, **kwargs):
                window = original_create(*args, **kwargs)
                window.events.loaded += lambda: loaded(window)
                return window

            webview.create_window = create_window
            report["stage"] = "desktop_start"
            try:
                run_desktop(demo=True)
            except BaseException:
                fail("desktop_start_or_lifecycle_failed")
            finally:
                webview.create_window = original_create

            if not callback_finished.is_set():
                fail("loaded_callback_incomplete")
            if not failure:
                report["stage"] = "listener_release"
                released = False
                # A 200 ms nonblocking connect can time out on Windows before
                # Winsock reports a refused loopback connection. Require an
                # actual refusal, allow its result to arrive, and record only
                # bounded numeric diagnostics if the listener stays unknown.
                report["listener_probe_codes"] = []
                report["listener_probe_ms"] = []
                for attempt in range(4):
                    if time.monotonic() >= deadline - 3:
                        break
                    probe_started = time.monotonic()
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
                        probe_socket.settimeout(2.0)
                        code = probe_socket.connect_ex((SETTINGS.host, SETTINGS.port))
                    report["listener_probe_codes"].append(int(code))
                    report["listener_probe_ms"].append(round((time.monotonic() - probe_started) * 1000))
                    if code in {errno.ECONNREFUSED, 10061}:
                        released = True
                        break
                    time.sleep(0.1)
                report["checks"]["listener_released"] = released
                report["checks"]["server_thread_stopped"] = not any(
                    thread.name == "jarvis-local-server" and thread.is_alive() for thread in threading.enumerate()
                )
                if not released or not report["checks"]["server_thread_stopped"]:
                    fail("server_shutdown_incomplete")
            if failure:
                report["error_code"] = failure[0]
            else:
                report["status"] = "passed"
                report["stage"] = "complete"
    except BaseException:
        report["error_code"] = "smoke_setup_or_cleanup_failed"
    finally:
        finished.set()
    emit_report(report)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
