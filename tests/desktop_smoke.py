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

Listener lifecycle uses the actual owned socket/server and the Windows TCP
LISTEN table, with a positive baseline before shutdown. API/layout contracts:
https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable
https://learn.microsoft.com/en-us/windows/win32/api/tcpmib/ns-tcpmib-mib_tcprow_owner_pid
https://learn.microsoft.com/en-us/windows/win32/api/tcpmib/ns-tcpmib-mib_tcptable_owner_pid
https://learn.microsoft.com/en-us/windows/win32/api/iprtrmib/ne-iprtrmib-tcp_table_class
"""
from __future__ import annotations

import ctypes
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


class _TcpRowOwnerPid(ctypes.Structure):
    # DWORD is 32 bits on both Windows architectures; do not use host c_ulong.
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "dwState", "dwLocalAddr", "dwLocalPort", "dwRemoteAddr",
        "dwRemotePort", "dwOwningPid",
    )]


class _TcpTableOwnerPid(ctypes.Structure):
    _fields_ = [("dwNumEntries", ctypes.c_uint32), ("table", _TcpRowOwnerPid * 1)]


def windows_listener_state(port, return_codes):
    """Return (any IPv4 listener, this process's listener); never expose rows.

    An unknown/error response fails the smoke. Buffer growth is bounded, and
    native structure offsets/strides account for the documented ABI padding.
    Only numeric Win32 return codes are retained as diagnostics.
    """
    try:
        get_table = ctypes.WinDLL("iphlpapi.dll", use_last_error=True).GetExtendedTcpTable
        get_table.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int32,
            ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32,
        ]
        get_table.restype = ctypes.c_uint32
    except (AttributeError, OSError):
        raise SmokeFailure("tcp_table_api_unavailable") from None

    insufficient_buffer = 122
    listener_table_class = 3  # TCP_TABLE_OWNER_PID_LISTENER
    listening_state = 2      # MIB_TCP_STATE_LISTEN
    row_offset = _TcpTableOwnerPid.table.offset
    row_size = ctypes.sizeof(_TcpRowOwnerPid)
    max_bytes = 1024 * 1024
    size = ctypes.c_uint32(0)
    code = int(get_table(None, ctypes.byref(size), False, socket.AF_INET, listener_table_class, 0))
    return_codes.append(code)
    if code != insufficient_buffer:
        raise SmokeFailure("tcp_table_size_query_failed")

    for _ in range(4):
        capacity = int(size.value)
        if not row_offset <= capacity <= max_bytes:
            raise SmokeFailure("tcp_table_buffer_bound")
        buffer = ctypes.create_string_buffer(capacity)
        code = int(get_table(buffer, ctypes.byref(size), False, socket.AF_INET, listener_table_class, 0))
        return_codes.append(code)
        if code == insufficient_buffer:
            continue
        if code != 0:
            raise SmokeFailure("tcp_table_query_failed")
        if not row_offset <= size.value <= capacity:
            raise SmokeFailure("tcp_table_size_invalid")
        count = ctypes.c_uint32.from_buffer(buffer).value
        if count > (int(size.value) - row_offset) // row_size:
            raise SmokeFailure("tcp_table_row_bound")
        any_listener = False
        owned_listener = False
        own_pid = os.getpid()
        for index in range(count):
            row = _TcpRowOwnerPid.from_buffer(buffer, row_offset + index * row_size)
            if row.dwState != listening_state:
                continue  # TIME_WAIT, CLOSED and established sockets are not listeners.
            local_port = socket.ntohs(row.dwLocalPort & 0xFFFF)
            if local_port == port:
                any_listener = True
                owned_listener = owned_listener or row.dwOwningPid == own_pid
        return any_listener, owned_listener
    raise SmokeFailure("tcp_table_growth_limit")


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
            from jarvis.desktop import LocalServer, run_desktop
            from jarvis.config import SETTINGS

            original_create = webview.create_window
            owned_hosts = []

            def host_factory(**kwargs):
                host = LocalServer(**kwargs)
                owned_hosts.append(host)
                return host

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

                    report["stage"] = "listener_positive_baseline"
                    if len(owned_hosts) != 1:
                        raise SmokeFailure("owned_server_missing")
                    host = owned_hosts[0]
                    report["checks"]["owned_listener_open_before_close"] = (
                        host.listener is not None and host.listener.fileno() >= 0
                    )
                    servers = getattr(host.server, "servers", None)
                    report["checks"]["uvicorn_listening_before_close"] = bool(servers) and all(
                        server.is_serving() for server in servers
                    )
                    report["tcp_table_startup_rcs"] = []
                    present, owned = windows_listener_state(SETTINGS.port, report["tcp_table_startup_rcs"])
                    report["checks"]["os_listener_seen_before_close"] = present and owned
                    if not all(report["checks"].values()):
                        raise SmokeFailure("listener_positive_baseline_failed")

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
                run_desktop(demo=True, host_factory=host_factory)
            except BaseException:
                fail("desktop_start_or_lifecycle_failed")
            finally:
                webview.create_window = original_create

            if not callback_finished.is_set():
                fail("loaded_callback_incomplete")
            if not failure:
                report["stage"] = "listener_release"
                host = owned_hosts[0]
                report["checks"]["owned_listener_closed"] = host.listener is not None and host.listener.fileno() == -1
                report["checks"]["owned_server_finished"] = host.finished.is_set()
                report["checks"]["server_thread_stopped"] = host.thread is not None and not host.thread.is_alive()
                servers = getattr(host.server, "servers", None)
                report["checks"]["uvicorn_servers_stopped"] = bool(servers) and all(
                    not server.is_serving() for server in servers
                )
                report["tcp_table_shutdown_rcs"] = []
                present, _ = windows_listener_state(SETTINGS.port, report["tcp_table_shutdown_rcs"])
                report["checks"]["os_listener_absent_after_close"] = not present
                report["checks"]["listener_released"] = all(report["checks"][key] for key in (
                    "owned_listener_closed", "owned_server_finished", "server_thread_stopped",
                    "uvicorn_servers_stopped", "os_listener_absent_after_close",
                ))
                if not report["checks"]["listener_released"]:
                    fail("server_shutdown_incomplete")
            if failure:
                report["error_code"] = failure[0]
            else:
                report["status"] = "passed"
                report["stage"] = "complete"
    except SmokeFailure as exc:
        report["error_code"] = str(exc)
    except BaseException:
        report["error_code"] = "smoke_setup_or_cleanup_failed"
    finally:
        finished.set()
    emit_report(report)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
