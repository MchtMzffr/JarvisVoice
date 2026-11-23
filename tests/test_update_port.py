"""Port-gate regressions with OS socket fakes, not a Windows runtime test."""
from contextlib import contextmanager
import errno
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

import update_jarvis as updater


def os_error(code, *, winerror=None, private="private-token-and-path"):
    error = OSError(code, private)
    if winerror is not None:
        error.winerror = winerror
    return error


class ProbeSocket:
    def __init__(self, *, option_error=None, bind_error=None, close_error=None):
        self.option_error = option_error
        self.bind_error = bind_error
        self.close_error = close_error
        self.events = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def setsockopt(self, level, option, value):
        self.events.append(("setsockopt", level, option, value))
        if self.option_error:
            raise self.option_error

    def bind(self, address):
        self.events.append(("bind", address))
        if self.bind_error:
            raise self.bind_error

    def close(self):
        self.closed = True
        self.events.append(("close",))
        if self.close_error:
            raise self.close_error

    def connect(self, *args):
        raise AssertionError("The Windows availability probe must not connect")

    def listen(self, *args):
        raise AssertionError("The availability probe must not become a server")

    def accept(self, *args):
        raise AssertionError("The availability probe must not accept traffic")


@contextmanager
def windows_probe(*probes, factory_error=None, exclusive=-5):
    with (
        patch.object(updater.sys, "platform", "win32"),
        patch.object(updater.socket, "SO_EXCLUSIVEADDRUSE", exclusive, create=True),
        patch.object(updater.socket, "create_connection", side_effect=AssertionError("No TCP connect on Windows")),
        patch.object(updater.socket, "socket", side_effect=factory_error or list(probes)) as factory,
    ):
        yield factory


class WindowsPortTests(unittest.TestCase):
    def test_free_port_is_exclusively_bound_without_listening_then_closed(self):
        probe = ProbeSocket()
        with windows_probe(probe) as factory:
            self.assertFalse(updater.jarvis_port_in_use())
        factory.assert_called_once_with(updater.socket.AF_INET, updater.socket.SOCK_STREAM)
        self.assertEqual(probe.events, [
            ("setsockopt", updater.socket.SOL_SOCKET, -5, 1),
            ("bind", ("0.0.0.0", 8765)),
            ("close",),
        ])
        self.assertTrue(probe.closed)

    def test_only_bind_address_in_use_is_busy_and_still_closes(self):
        for error in (
            os_error(errno.EADDRINUSE),
            os_error(errno.EINVAL, winerror=10048),
        ):
            with self.subTest(errno=error.errno, winerror=getattr(error, "winerror", None)):
                probe = ProbeSocket(bind_error=error)
                with windows_probe(probe):
                    self.assertTrue(updater.jarvis_port_in_use())
                self.assertTrue(probe.closed)

    def test_permission_error_is_unknown_not_free_or_proven_running(self):
        probe = ProbeSocket(bind_error=os_error(errno.EACCES, winerror=10013))
        with windows_probe(probe):
            with self.assertRaises(updater.UpdateError) as raised:
                updater.jarvis_port_in_use()
        message = str(raised.exception)
        self.assertIn("bind", message)
        self.assertIn("winerror=10013", message)
        self.assertIn("errno=13", message)
        self.assertNotIn("private-token-and-path", message)
        self.assertTrue(probe.closed)

    def test_unknown_error_retains_numeric_codes_but_not_free_form_os_text(self):
        error = os_error(errno.ENETDOWN, winerror=10050)
        probe = ProbeSocket(bind_error=error)
        with windows_probe(probe):
            with self.assertRaises(updater.UpdateError) as raised:
                updater.jarvis_port_in_use()
        message = str(raised.exception)
        self.assertIn(type(error).__name__, message)
        self.assertIn("winerror=10050", message)
        self.assertNotIn("private-token-and-path", message)
        self.assertTrue(probe.closed)

    def test_pre_bind_failures_cannot_be_mistaken_for_busy(self):
        error = os_error(errno.EADDRINUSE, winerror=10048)
        with windows_probe(factory_error=error):
            with self.assertRaises(updater.UpdateError) as raised:
                updater.jarvis_port_in_use()
        self.assertIn("(socket;", str(raised.exception))
        probe = ProbeSocket(option_error=error)
        with windows_probe(probe):
            with self.assertRaises(updater.UpdateError) as raised:
                updater.jarvis_port_in_use()
        self.assertIn("(setsockopt;", str(raised.exception))
        self.assertFalse(any(event[0] == "bind" for event in probe.events))
        self.assertTrue(probe.closed)

    def test_cleanup_error_is_unknown_even_after_successful_bind(self):
        probe = ProbeSocket(close_error=os_error(errno.EIO))
        with windows_probe(probe):
            with self.assertRaises(updater.UpdateError) as raised:
                updater.jarvis_port_in_use()
        self.assertIn("(close;", str(raised.exception))
        self.assertTrue(probe.closed)

    def test_missing_exclusive_option_does_not_downgrade_to_reuse_or_connect(self):
        with windows_probe(exclusive=None) as factory:
            with self.assertRaisesRegex(updater.UpdateError, "SO_EXCLUSIVEADDRUSE"):
                updater.jarvis_port_in_use()
        factory.assert_not_called()


class NonWindowsPortTests(unittest.TestCase):
    def test_connection_success_is_busy_and_closed(self):
        probe = ProbeSocket()
        with (
            patch.object(updater.sys, "platform", "linux"),
            patch.object(updater.socket, "create_connection", return_value=probe),
        ):
            self.assertTrue(updater.jarvis_port_in_use())
        self.assertTrue(probe.closed)

    def test_connection_refused_is_free(self):
        with (
            patch.object(updater.sys, "platform", "linux"),
            patch.object(updater.socket, "create_connection", side_effect=ConnectionRefusedError(errno.ECONNREFUSED, "private-token-and-path")),
        ):
            self.assertFalse(updater.jarvis_port_in_use())

    def test_timeout_remains_unknown_and_diagnostic_is_redacted(self):
        with (
            patch.object(updater.sys, "platform", "linux"),
            patch.object(updater.socket, "create_connection", side_effect=TimeoutError("private-token-and-path")),
        ):
            with self.assertRaises(updater.UpdateError) as raised:
                updater.jarvis_port_in_use()
        message = str(raised.exception)
        self.assertIn("connect", message)
        self.assertIn("TimeoutError", message)
        self.assertIn("errno=yok", message)
        self.assertNotIn("private-token-and-path", message)


@unittest.skipUnless(sys.platform == "win32", "Requires real Windows socket semantics")
class RealWindowsPortTests(unittest.TestCase):
    """OS integration cases use ephemeral ports, never the user's 8765 port."""
    def test_free_ephemeral_ipv4_port_is_available(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind(("0.0.0.0", 0))
            port = reservation.getsockname()[1]
        with patch.object(updater, "UPDATER_PORT", port):
            self.assertFalse(updater.jarvis_port_in_use())

    def assert_listener_blocks(self, address):
        # Keep default Windows bind options. In particular, this tests a
        # wildcard listener owned by the same account without exclusive use.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind((address, 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            with patch.object(updater, "UPDATER_PORT", port):
                try:
                    occupied = updater.jarvis_port_in_use()
                except updater.UpdateError as exc:
                    # Windows may report a conflicting exclusive bind as
                    # WSAEACCES. This remains unknown/blocked, never 'free'.
                    message = str(exc)
                    self.assertIn("(bind;", message)
                    self.assertIn("winerror=10013", message)
                else:
                    self.assertTrue(occupied)
            self.assertEqual(listener.getsockname()[1], port)

    def test_loopback_listener_blocks_update(self):
        self.assert_listener_blocks("127.0.0.1")

    def test_wildcard_listener_blocks_update(self):
        self.assert_listener_blocks("0.0.0.0")


def make_installation_pair(root):
    """Minimal source/installed trees for the real updater write gate."""
    source, target = root / "source", root / "installed"
    source.mkdir()
    target.mkdir()
    for name in updater.RELEASE_FILES:
        (source / name).write_text("release bytes", encoding="utf-8")
    for name in updater.RELEASE_DIRS:
        (source / name).mkdir()
    project = '[project]\nname="jarvis-voice-local"\nversion="{version}"\nrequires-python=">=3.11,<3.12"\ndependencies=[]\n'
    for directory, version in ((source, updater.RELEASE_VERSION), (target, "0.1.0")):
        (directory / "jarvis").mkdir(exist_ok=True)
        (directory / "jarvis" / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
        (directory / "pyproject.toml").write_text(project.format(version=version), encoding="utf-8")
    for relative, value in {
        "BASLAT.cmd": b"old launcher",
        ".venv/Scripts/python.exe": b"old python",
        "data/prepared.json": b"{}",
        "data/memories.sqlite3": b"keep user data",
    }.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    return source, target


def installed_bytes(target):
    return {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*")
            if p.is_file() and "backups" not in p.relative_to(target).parts}


class PortWriteGateTests(unittest.TestCase):
    def test_verified_free_port_allows_update_and_preserves_user_data(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = make_installation_pair(Path(directory))
            first, second = ProbeSocket(), ProbeSocket()
            with windows_probe(first, second):
                result = updater.update(source, target)
            self.assertEqual(result["to_version"], updater.RELEASE_VERSION)
            self.assertEqual((target / "data/memories.sqlite3").read_bytes(), b"keep user data")
            self.assertTrue(first.closed and second.closed)

    def test_busy_or_unknown_first_probe_rejects_without_code_or_backup_writes(self):
        for error in (os_error(errno.EADDRINUSE, winerror=10048), os_error(errno.EACCES, winerror=10013)):
            with self.subTest(code=error.winerror), tempfile.TemporaryDirectory() as directory:
                source, target = make_installation_pair(Path(directory))
                before = installed_bytes(target)
                probe = ProbeSocket(bind_error=error)
                with windows_probe(probe):
                    with self.assertRaises(updater.UpdateError):
                        updater.update(source, target)
                self.assertEqual(installed_bytes(target), before)
                self.assertFalse((target / "backups").exists())
                self.assertFalse((target / ".jarvis-update.lock").exists())
                self.assertTrue(probe.closed)

    def test_second_probe_catches_a_port_that_became_busy_before_code_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = make_installation_pair(Path(directory))
            before = installed_bytes(target)
            first = ProbeSocket()
            second = ProbeSocket(bind_error=os_error(errno.EADDRINUSE, winerror=10048))
            with windows_probe(first, second):
                with self.assertRaises(updater.UpdateError):
                    updater.update(source, target)
            self.assertEqual(installed_bytes(target), before)
            self.assertTrue((target / "backups").is_dir())
            self.assertFalse((target / ".jarvis-update.lock").exists())
            self.assertTrue(first.closed and second.closed)


if __name__ == "__main__":
    unittest.main()
