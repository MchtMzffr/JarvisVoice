import asyncio
import contextlib
import dataclasses
import gc
import io
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from jarvis import desktop
from jarvis import __main__ as entry


class Signal:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)
        return self

    def fire(self, *args):
        return [handler(*args) for handler in list(self.handlers)]


class FakeServer:
    started = False
    should_exit = False

    def __init__(self, fail=None, never_start=False):
        self.fail, self.never_start = fail, never_start
        self.sockets = None

    async def serve(self, sockets):
        self.sockets = sockets
        if self.fail is not None:
            raise self.fail
        self.started = not self.never_start
        while not self.should_exit:
            await asyncio.sleep(0.001)


class LocalServerTests(unittest.TestCase):
    def make_host(self, server):
        listener = Mock()
        runtime = SimpleNamespace(token="private-test-token", session=None)
        host = desktop.LocalServer(server_factory=lambda demo: (server, runtime), socket_factory=lambda *args: listener)
        return host, listener

    def test_ready_means_bound_own_listener_and_stop_releases_it(self):
        server = FakeServer()
        host, listener = self.make_host(server)
        try:
            host.start()
            listener.bind.assert_called_once_with(("127.0.0.1", 8765))
            self.assertEqual(server.sockets, [listener])
            self.assertIn("#token=private-test-token", host.url)
        finally:
            self.assertTrue(host.stop())
        self.assertTrue(host.finished.is_set())
        self.assertFalse(host.thread.is_alive())
        listener.close.assert_called_once()

    def test_port_failure_does_not_start_server_or_echo_os_error(self):
        listener = Mock()
        listener.bind.side_effect = OSError("private token and path")
        factory = Mock()
        host = desktop.LocalServer(server_factory=factory, socket_factory=lambda *args: listener)
        with self.assertRaises(desktop.DesktopError) as caught:
            host.start()
        self.assertNotIn("private", str(caught.exception))
        factory.assert_not_called()
        listener.close.assert_called_once()

    def test_background_system_exit_is_redacted_without_thread_traceback(self):
        host, _ = self.make_host(FakeServer(fail=SystemExit("private-test-token")))
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            with self.assertRaises(desktop.DesktopError) as caught:
                host.start()
            gc.collect()
        self.assertNotIn("private-test-token", str(caught.exception) + output.getvalue())
        self.assertFalse(host.thread.is_alive())

    def test_never_ready_times_out_and_stops_instead_of_hanging(self):
        host, _ = self.make_host(FakeServer(never_start=True))
        settings = dataclasses.replace(desktop.SETTINGS, desktop_startup_timeout_s=0.03, desktop_shutdown_timeout_s=1)
        started = time.monotonic()
        with patch.object(desktop, "SETTINGS", settings), self.assertRaises(desktop.DesktopError):
            host.start()
        self.assertLess(time.monotonic() - started, 1)
        self.assertFalse(host.thread.is_alive())


def fake_window():
    default_popup = Mock()
    core = SimpleNamespace(NewWindowRequested=Signal(), DownloadStarting=Signal(), Settings=SimpleNamespace())
    core.NewWindowRequested += default_popup
    native_view = SimpleNamespace(NavigationStarting=Signal(), CoreWebView2InitializationCompleted=Signal(), CoreWebView2=core)
    window = SimpleNamespace(
        native=SimpleNamespace(webview=native_view, browser=SimpleNamespace(on_new_window_request=default_popup)),
        events=SimpleNamespace(initialized=Signal(), before_show=Signal(), closed=Signal()), destroy=Mock(),
    )
    return window, core, default_popup


class NavigationTests(unittest.TestCase):
    def test_late_native_initialization_cannot_restore_default_popup_handler(self):
        window, core, default = fake_window()
        guard = desktop.NavigationGuard(window, "private-token", Mock())
        guard.before_show()
        core.NewWindowRequested += default
        guard.on_initialized(window.native.webview, SimpleNamespace(IsSuccess=True))
        self.assertNotIn(default, core.NewWindowRequested.handlers)
        self.assertEqual(core.NewWindowRequested.handlers.count(guard.on_popup), 1)
        self.assertEqual(core.DownloadStarting.handlers.count(guard.on_download), 1)

    def test_native_popup_handler_is_replaced_before_external_links(self):
        window, core, default = fake_window()
        opener, failure = Mock(), Mock()
        guard = desktop.NavigationGuard(window, "private-token", failure, open_external=opener)
        guard.before_show()
        self.assertNotIn(default, core.NewWindowRequested.handlers)
        self.assertIn(guard.on_popup, core.NewWindowRequested.handlers)
        for uri in ("file:///C:/secret", "javascript:alert(1)", "mailto:test@example.com", "https://name:secret@example.com", "https://example.com/private-token"):
            args = SimpleNamespace(Uri=uri, IsUserInitiated=True, Handled=False)
            core.NewWindowRequested.fire(None, args)
            self.assertTrue(args.Handled)
        opener.assert_not_called()
        args = SimpleNamespace(Uri="https://example.com/source", IsUserInitiated=True, Handled=False)
        core.NewWindowRequested.fire(None, args)
        opener.assert_called_once_with("https://example.com/source")
        failure.assert_not_called()

    def test_only_local_root_navigation_stays_inside_window(self):
        window, _, _ = fake_window()
        opener = Mock()
        guard = desktop.NavigationGuard(window, "private-token", Mock(), open_external=opener)
        for uri in ("http://127.0.0.1:8765/", "http://127.0.0.1:8765/#token=private-token"):
            args = SimpleNamespace(Uri=uri, IsUserInitiated=False, IsRedirected=False, Cancel=False)
            guard.on_navigation(None, args)
            self.assertFalse(args.Cancel)
        for uri in ("http://127.0.0.1:8766/", "http://127.0.0.1:8765.evil/", "file:///C:/secret", "https://example.com"):
            args = SimpleNamespace(Uri=uri, IsUserInitiated=False, IsRedirected=False, Cancel=False)
            guard.on_navigation(None, args)
            self.assertTrue(args.Cancel)
        opener.assert_not_called()
        args = SimpleNamespace(Uri="https://example.com", IsUserInitiated=True, IsRedirected=False, Cancel=False)
        guard.on_navigation(None, args)
        opener.assert_called_once_with("https://example.com")
        self.assertTrue(args.Cancel)

    def test_downloads_are_cancelled(self):
        args = SimpleNamespace(Cancel=False)
        desktop.NavigationGuard.on_download(None, args)
        self.assertTrue(args.Cancel)


class DesktopShellTests(unittest.TestCase):
    def test_private_window_has_no_application_bridge_and_stops_owned_server(self):
        window, _, _ = fake_window()
        host = Mock()
        host.url = "http://127.0.0.1:8765/#token=private-token"
        host.runtime = SimpleNamespace(token="private-token")
        host.finished = threading.Event()
        host.stopping = threading.Event()
        host.stop.return_value = True
        host.request_stop.side_effect = lambda: (host.stopping.set(), host.finished.set())
        view = SimpleNamespace(settings={}, create_window=Mock(return_value=window))
        def start(**kwargs):
            self.assertEqual(threading.current_thread(), threading.main_thread())
            self.assertEqual(kwargs["gui"], "edgechromium")
            self.assertTrue(kwargs["private_mode"])
            self.assertFalse(kwargs["debug"])
            window.events.initialized.fire("edgechromium")
            window.events.before_show.fire()
            window.events.closed.fire()
        view.start = Mock(side_effect=start)
        with patch.object(desktop.sys, "platform", "win32"):
            desktop.run_desktop(webview_module=view, host_factory=lambda **kwargs: host)
        self.assertIsNone(view.create_window.call_args.kwargs["js_api"])
        self.assertFalse(view.settings["ALLOW_FILE_URLS"])
        self.assertFalse(view.settings["ALLOW_DOWNLOADS"])
        self.assertIsNone(view.settings["REMOTE_DEBUGGING_PORT"])
        host.start.assert_called_once()
        host.request_stop.assert_called_once()
        host.stop.assert_called_once()

    def test_non_windows_explicit_desktop_fails_without_browser_fallback(self):
        with patch.object(desktop.sys, "platform", "linux"), patch.object(desktop.webbrowser, "open") as opener:
            with self.assertRaises(desktop.DesktopError):
                desktop.run_desktop()
        opener.assert_not_called()

    def test_cli_default_windows_desktop_and_explicit_modes(self):
        with patch.object(entry.sys, "platform", "win32"), \
             patch.object(entry, "run_desktop") as desktop_run, \
             patch.object(entry, "run_browser") as browser_run:
            self.assertEqual(entry.main([]), 0)
            desktop_run.assert_called_once_with(demo=False)
            self.assertEqual(entry.main(["--browser", "--demo"]), 0)
            browser_run.assert_called_with(demo=True, no_browser=False)
            self.assertEqual(entry.main(["--no-browser"]), 0)
            browser_run.assert_called_with(demo=False, no_browser=True)

    def test_unexpected_cli_error_is_sanitized(self):
        with patch.object(entry, "run_desktop", side_effect=RuntimeError("private-token C:/secret")), \
             patch.object(entry, "report_error") as report:
            self.assertEqual(entry.main(["--desktop"]), 1)
        self.assertNotIn("private-token", report.call_args.args[0])
        self.assertNotIn("C:/secret", report.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
