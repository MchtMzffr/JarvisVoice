"""Windows WebView2 shell and an owned, loopback-only server lifecycle.

No application Python API is exposed to JavaScript. Native navigation hooks
are pinned to pywebview 6.2.1's documented ``window.native.webview`` object.
The platform-specific default popup handler is replaced before use so a page
cannot send arbitrary URI schemes to the operating system.
"""
import asyncio
import logging
import socket
import sys
import tempfile
import threading
from urllib.parse import urlsplit
import webbrowser

from .config import SETTINGS


class DesktopError(RuntimeError):
    """Only fixed, safe user-facing text may be placed in this exception."""


def _build_server(demo):
    # Keep launcher/unit checks free of the heavy application dependencies.
    import uvicorn
    from .server import Runtime, create_app
    runtime = Runtime(demo=demo)
    server = uvicorn.Server(uvicorn.Config(
        create_app(runtime), host=SETTINGS.host, port=SETTINGS.port,
        log_level="critical", log_config=None, access_log=False,
        ws_max_size=65536, workers=1,
        timeout_graceful_shutdown=SETTINGS.desktop_shutdown_timeout_s,
    ))
    return server, runtime


class LocalServer:
    """Own the listener; readiness means uvicorn has actually started."""
    def __init__(self, demo=False, *, server_factory=None, socket_factory=None):
        self.demo = demo
        self.factory = server_factory or _build_server
        self.socket_factory = socket_factory or socket.socket
        self.server = self.runtime = self.loop = self.listener = None
        self.thread = None
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.stopping = threading.Event()
        self.error = None

    @property
    def url(self):
        if self.runtime is None or not self.ready.is_set() or self.error:
            raise DesktopError("Yerel arayüz henüz hazır değil.")
        return f"http://{SETTINGS.host}:{SETTINGS.port}/#token={self.runtime.token}"

    def start(self):
        if self.thread is not None:
            raise DesktopError("Yerel arayüz zaten başlatıldı.")
        try:
            if SETTINGS.host != "127.0.0.1":
                raise OSError("Loopback required")
            self.listener = self.socket_factory(socket.AF_INET, socket.SOCK_STREAM)
            if sys.platform == "win32":
                exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
                if exclusive is None:
                    raise OSError("Exclusive socket unavailable")
                self.listener.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            self.listener.bind((SETTINGS.host, SETTINGS.port))
        except OSError:
            self._close_listener()
            raise DesktopError("Jarvis için 8765 portu açılamadı. Açık Jarvis penceresini kapatıp yeniden dene.") from None
        self.thread = threading.Thread(target=self._thread_main, name="jarvis-local-server", daemon=True)
        self.thread.start()
        if not self.ready.wait(SETTINGS.desktop_startup_timeout_s):
            self.stop()
            raise DesktopError("Yerel arayüz zamanında başlatılamadı. Jarvis'i yeniden başlat.")
        if self.error or self.finished.is_set():
            self.stop()
            raise DesktopError(self.error or "Yerel arayüz başlatılamadı.")

    def _thread_main(self):
        try:
            asyncio.run(self._serve())
        except BaseException:
            # uvicorn can raise SystemExit during startup. No background
            # traceback may expose a token, path or raw third-party exception.
            self.error = "Yerel arayüz sunucusu çalıştırılamadı. Jarvis'i yeniden başlat."
        finally:
            self._close_listener()
            self.finished.set()
            self.ready.set()

    def _close_listener(self):
        if self.listener is not None:
            try:
                self.listener.close()
            except OSError:
                pass

    async def _serve(self):
        self.loop = asyncio.get_running_loop()
        self.loop.set_exception_handler(self._loop_failure)
        try:
            self.server, self.runtime = self.factory(self.demo)
        except BaseException:
            self.error = "Yerel arayüz sunucusu çalıştırılamadı. Jarvis'i yeniden başlat."
            return
        if self.stopping.is_set():
            self.server.should_exit = True

        async def serve_guarded():
            try:
                await self.server.serve(sockets=[self.listener])
            except asyncio.CancelledError:
                raise
            except BaseException:
                # Catch SystemExit inside the task: catching it only outside
                # asyncio.run leaves a delayed, un-retrieved task traceback.
                self.error = "Yerel arayüz sunucusu çalıştırılamadı. Jarvis'i yeniden başlat."
        task = asyncio.create_task(serve_guarded())
        try:
            while not self.server.started and not task.done():
                if self.stopping.is_set():
                    self.server.should_exit = True
                await asyncio.sleep(0.02)
            if self.server.started and not task.done() and not self.stopping.is_set():
                self.ready.set()
            await task
            if not self.stopping.is_set() and self.error is None:
                self.error = "Yerel arayüz sunucusu beklenmedik biçimde kapandı. Jarvis'i yeniden başlat."
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    def _loop_failure(self, loop, context):
        # asyncio's default handler prints arbitrary exception/context values.
        # Preserve a useful bounded failure and shut down only our server.
        self.error = "Yerel arayüz işlemi tamamlanamadı. Jarvis'i yeniden başlat."
        if self.server is not None:
            self.server.should_exit = True
        self.ready.set()

    def request_stop(self):
        if self.stopping.is_set():
            return
        self.stopping.set()
        loop = self.loop
        if loop is None or loop.is_closed():
            return

        def stop_on_owner_loop():
            if self.server is not None:
                self.server.should_exit = True
            session = getattr(self.runtime, "session", None)
            if session is not None and not getattr(session, "closed", False):
                task = loop.create_task(session.close())
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            loop.call_soon_threadsafe(stop_on_owner_loop)
        except RuntimeError:
            pass

    def stop(self):
        self.request_stop()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(SETTINGS.desktop_shutdown_timeout_s)
            if self.thread.is_alive():
                # A running native CPU call cannot safely be killed as a
                # Python thread. Its slot stays owned until it really ends.
                return False
        return True


class NavigationGuard:
    def __init__(self, window, token, on_failure, *, open_external=None):
        self.window, self.token, self.on_failure = window, token, on_failure
        self.open_external = open_external or webbrowser.open
        self.core = None
        self.failed = False

    def _local(self, uri):
        try:
            value = urlsplit(uri)
            return (value.scheme == "http" and value.netloc == f"{SETTINGS.host}:{SETTINGS.port}"
                    and value.path in ("", "/") and not value.query)
        except (ValueError, TypeError):
            return False

    def _external(self, uri):
        if not isinstance(uri, str) or self.token in uri or len(uri) > 4096:
            return False
        if any(ord(char) < 32 or char == "\\" for char in uri):
            return False
        try:
            value = urlsplit(uri)
            return (value.scheme in {"http", "https"} and bool(value.hostname)
                    and value.username is None and value.password is None
                    and value.port != 0 and not self._local(uri))
        except ValueError:
            return False

    def _fail(self):
        if self.failed:
            return
        self.failed = True
        self.on_failure("Masaüstü pencere güvenlik ayarları uygulanamadı. KUR.cmd ile kurulum kontrolünü yeniden çalıştır.")
        # before_show blocks the UI; destroy waits for shown. A separate
        # thread avoids deadlocking the UI if native hooks cannot be installed.
        def close_after_show():
            try:
                self.window.destroy()
            except Exception:
                pass
        threading.Thread(target=close_after_show, name="jarvis-window-close", daemon=True).start()

    def before_show(self):
        try:
            view = self.window.native.webview
            view.NavigationStarting += self.on_navigation
            view.CoreWebView2InitializationCompleted += self.on_initialized
            if view.CoreWebView2 is not None:
                self._configure(view.CoreWebView2)
        except Exception:
            self._fail()

    def on_initialized(self, sender, args):
        try:
            if not args.IsSuccess:
                self._fail()
                return
            self._configure(sender.CoreWebView2)
        except Exception:
            self._fail()

    def _configure(self, core):
        # pywebview 6.2.1's first handler otherwise forwards arbitrary URI
        # schemes to webbrowser.open or load_url. Replace, do not stack on it.
        # Repeat removal on initialization: the native object may have been
        # visible before pywebview's initialization callback attached handlers.
        core.NewWindowRequested -= self.window.native.browser.on_new_window_request
        if self.core is not None:
            core.NewWindowRequested -= self.on_popup
            core.DownloadStarting -= self.on_download
        core.NewWindowRequested += self.on_popup
        core.DownloadStarting += self.on_download
        core.Settings.AreDevToolsEnabled = False
        core.Settings.AreDefaultContextMenusEnabled = False
        core.Settings.AreBrowserAcceleratorKeysEnabled = False
        self.core = core

    def _open(self, uri):
        if self._external(uri):
            try:
                self.open_external(uri)
            except Exception:
                pass

    def on_navigation(self, sender, args):
        uri = str(args.Uri)
        if self.failed or not self._local(uri):
            args.Cancel = True
            if not self.failed and bool(args.IsUserInitiated) and not bool(args.IsRedirected):
                self._open(uri)

    def on_popup(self, sender, args):
        args.Handled = True
        if not self.failed and bool(args.IsUserInitiated):
            self._open(str(args.Uri))

    @staticmethod
    def on_download(sender, args):
        args.Cancel = True


def run_desktop(demo=False, *, webview_module=None, host_factory=None):
    if sys.platform != "win32":
        raise DesktopError("Masaüstü penceresi bu sürümde Windows içindir. Bu sistemde --browser veya --no-browser kullanabilirsin.")
    if threading.current_thread() is not threading.main_thread():
        raise DesktopError("Masaüstü penceresi ana uygulama iş parçacığında başlatılmalı.")
    if webview_module is None:
        try:
            import webview as webview_module
        except (Exception, SystemExit):
            raise DesktopError("Masaüstü bileşenleri açılamadı. KUR.cmd ile kurulumu tamamla.") from None
    host = (host_factory or LocalServer)(demo=demo)
    failure = []
    logger = logging.getLogger("pywebview")
    previous_level = logger.level
    logger.setLevel(logging.CRITICAL)

    def fail(message):
        if not failure:
            failure.append(message)
        host.request_stop()

    try:
        host.start()
        webview_module.settings.update({
            "ALLOW_DOWNLOADS": False, "ALLOW_FILE_URLS": False,
            "OPEN_EXTERNAL_LINKS_IN_BROWSER": False,
            "IGNORE_SSL_ERRORS": False, "REMOTE_DEBUGGING_PORT": None,
            "OPEN_DEVTOOLS_IN_DEBUG": False, "SHOW_DEFAULT_MENUS": False,
        })
        window = webview_module.create_window(
            "Jarvis Voice", url=host.url, js_api=None,
            width=SETTINGS.desktop_window_width, height=SETTINGS.desktop_window_height,
            min_size=(720, 600), text_select=True, background_color="#101419",
            confirm_close=False,
        )
        guard = NavigationGuard(window, host.runtime.token, fail)

        def initialized(renderer):
            if renderer != "edgechromium":
                fail("WebView2 başlatılamadı. Microsoft Edge WebView2 Runtime kurulumunu kontrol et.")
                return False
            return None

        window.events.initialized += initialized
        window.events.before_show += guard.before_show
        window.events.closed += host.request_stop

        def monitor_server():
            host.finished.wait()
            if not host.stopping.is_set():
                fail(host.error or "Yerel arayüz sunucusu kapandı. Jarvis'i yeniden başlat.")
                try:
                    window.destroy()
                except Exception:
                    pass
        threading.Thread(target=monitor_server, name="jarvis-window-monitor", daemon=True).start()
        with tempfile.TemporaryDirectory(prefix="jarvis-webview-", ignore_cleanup_errors=True) as cache:
            webview_module.start(gui="edgechromium", debug=False, http_server=False,
                                 private_mode=True, storage_path=cache)
        if failure:
            raise DesktopError(failure[0])
    except DesktopError:
        raise
    except (Exception, SystemExit):
        raise DesktopError("Jarvis penceresi açılamadı. KUR.cmd ve Microsoft Edge WebView2 Runtime kurulumunu kontrol et.") from None
    finally:
        unwinding = sys.exc_info()[0] is not None
        stopped = host.stop()
        logger.setLevel(previous_level)
        if not stopped and not failure and not unwinding:
            raise DesktopError("Pencere kapandı; başlamış yerel işlem hâlâ tamamlanıyor. İşlem bitince Jarvis kapanacak.")


def run_browser(demo=False, no_browser=False):
    """Explicit alternative/developer mode; never print the launch token."""
    host = LocalServer(demo=demo)
    try:
        host.start()
        if not no_browser and not webbrowser.open(host.url):
            raise DesktopError("Tarayıcı açılamadı. Jarvis'i yeniden başlat.")
        if sys.stdout is not None:
            print("Jarvis Voice çalışıyor. Kapatmak için Ctrl+C kullan.", flush=True)
        while not host.finished.wait(0.2):
            pass
        if host.error:
            raise DesktopError(host.error)
    finally:
        host.stop()


def report_error(message):
    if sys.stderr is not None:
        print(message, file=sys.stderr, flush=True)
    elif sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Jarvis Voice", 0x10)
        except Exception:
            pass
