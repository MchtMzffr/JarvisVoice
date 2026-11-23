"""Code-only updater tests on temporary Windows-shaped directories.

These tests do not execute CMD, PowerShell, or Windows binaries. They verify
the portable filesystem transaction and its containment/rollback contracts.
"""
from pathlib import Path
import json
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import update_jarvis as updater


PROJECT = '''[project]
name = "jarvis-voice-local"
version = "{version}"
requires-python = ">=3.11,<3.12"
dependencies = ["httpx==0.28.1"]
'''


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        # Windows TEMP may use an 8.3 alias. Canonicalize the fixture once so
        # injected write failures target the same path as the updater's roots.
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "new package"
        self.target = self.root / "installed Jarvis"
        self.source.mkdir()
        self.target.mkdir()
        for name in updater.RELEASE_FILES:
            (self.source / name).write_bytes(("new " + name).encode())
        for name in updater.RELEASE_DIRS:
            (self.source / name).mkdir()
        (self.source / "jarvis" / "__init__.py").write_text(f'__version__ = "{updater.RELEASE_VERSION}"\n', encoding="utf-8")
        (self.source / "jarvis" / "server.py").write_bytes(b"new server")
        (self.source / "jarvis" / "profile.py").write_bytes(b"new profile code")
        (self.source / "docs" / "guide.md").write_bytes(b"new guide")
        (self.source / "tests" / "test_sample.py").write_bytes(b"new test")
        (self.source / "pyproject.toml").write_text(PROJECT.format(version=updater.RELEASE_VERSION), encoding="utf-8")
        (self.target / "jarvis").mkdir()
        (self.target / "jarvis" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        (self.target / "jarvis" / "server.py").write_bytes(b"old server")
        (self.target / "BASLAT.cmd").write_bytes(b"old launcher")
        (self.target / "pyproject.toml").write_text(PROJECT.format(version="0.1.0"), encoding="utf-8")
        for relative, content in {
            ".venv/Scripts/python.exe": b"existing python",
            ".runtime/python/runtime.bin": b"existing managed python",
            "data/prepared.json": b'{"version":"0.1.0"}',
            "data/profile.json": b'{"user_name":"existing person"}',
            "data/memories.sqlite3": b"existing memories",
            "data/models/ema.pt": b"existing model",
            "custom-user-file.txt": b"keep unknown file",
        }.items():
            path = self.target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        # Foreign data in the extracted package must never be deployed.
        (self.source / "data").mkdir()
        (self.source / "data" / "profile.json").write_bytes(b"must never copy")
        (self.source / ".env").write_bytes(b"must never copy")

    def tearDown(self):
        self.temporary.cleanup()

    def snapshot(self, root=None):
        root = root or self.target
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
                if p.is_file() and "backups" not in p.relative_to(root).parts}

    def run_update(self, **kwargs):
        return updater.update(self.source, self.target, port_check=kwargs.get("port_check", lambda: False))

    def test_upgrade_preserves_data_environment_and_unknown_files(self):
        before = self.snapshot()
        result = self.run_update()
        after = self.snapshot()
        for path in before:
            if path.startswith(("data/", ".venv/", ".runtime/")) or path == "custom-user-file.txt":
                self.assertEqual(after[path], before[path], path)
        self.assertEqual(after["jarvis/server.py"], b"new server")
        self.assertEqual(after["jarvis/profile.py"], b"new profile code")
        self.assertNotIn(".env", after)
        self.assertNotIn(".jarvis-update.lock", after)
        self.assertEqual(result["from_version"], "0.1.0")
        self.assertEqual(result["to_version"], updater.RELEASE_VERSION)

    def test_backup_manifest_and_original_bytes_are_verified(self):
        before = self.snapshot()
        result = self.run_update()
        backup = Path(result["backup"])
        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(len(manifest["applied"]), result["changed_files"])
        for entry in manifest["files"]:
            rel = entry["path"]
            self.assertEqual(updater.digest((self.target / rel).read_bytes()), entry["new_sha256"])
            if entry["old_sha256"] is not None and entry["changed"]:
                saved = (backup / "files" / rel).read_bytes()
                self.assertEqual(saved, before[rel])
                self.assertEqual(updater.digest(saved), entry["old_sha256"])
        self.assertFalse((backup / "files" / "data").exists())
        self.assertFalse((backup / "files" / ".venv").exists())

    def test_write_failure_rolls_back_overwrites_and_new_files(self):
        before = self.snapshot()
        actual = updater._atomic_write
        failed = False

        def fail_once(path, data, root):
            nonlocal failed
            if path == self.target / "jarvis" / "server.py" and not failed:
                failed = True
                raise OSError("simulated write failure")
            return actual(path, data, root)

        with patch.object(updater, "_atomic_write", side_effect=fail_once):
            with self.assertRaisesRegex(updater.UpdateError, "geri alındı"):
                self.run_update()
        self.assertTrue(failed)
        self.assertEqual(self.snapshot(), before)
        manifests = list((self.target / "backups").glob("*/manifest.json"))
        self.assertEqual(len(manifests), 1)
        self.assertEqual(json.loads(manifests[0].read_text(encoding="utf-8"))["status"], "rolled_back")

    def test_unknown_target_version_is_rejected(self):
        (self.target / "jarvis" / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
        before = self.snapshot()
        with self.assertRaisesRegex(updater.UpdateError, "0.1.0/0.2.0"):
            self.run_update()
        self.assertEqual(self.snapshot(), before)

    def test_dependency_change_cannot_trigger_implicit_install(self):
        file = self.source / "pyproject.toml"
        file.write_text(file.read_text().replace("httpx==0.28.1", "httpx==9.0.0"))
        before = self.snapshot()
        with self.assertRaisesRegex(updater.UpdateError, "Bağımlılıklar farklı"):
            self.run_update()
        self.assertEqual(self.snapshot(), before)

    def test_approved_desktop_extra_is_copied_without_touching_python_environment(self):
        file = self.source / "pyproject.toml"
        extra = '''\n[project.optional-dependencies]\ndesktop = ["pywebview==6.2.1 ; sys_platform == 'win32'", "pythonnet==3.2.1 ; sys_platform == 'win32'"]\n'''
        file.write_text(file.read_text(encoding="utf-8") + extra, encoding="utf-8")
        before = self.snapshot()
        self.run_update()
        after = self.snapshot()
        self.assertIn(b"pywebview==6.2.1", after["pyproject.toml"])
        for name in before:
            if name.startswith((".venv/", ".runtime/", "data/")):
                self.assertEqual(before[name], after[name])

    def test_unapproved_optional_dependency_is_rejected_without_writes(self):
        file = self.source / "pyproject.toml"
        file.write_text(file.read_text(encoding="utf-8") + '\n[project.optional-dependencies]\nunknown = ["unreviewed-package==1.0"]\n', encoding="utf-8")
        before = self.snapshot()
        with self.assertRaisesRegex(updater.UpdateError, "İsteğe bağlı paketler"):
            self.run_update()
        self.assertEqual(self.snapshot(), before)

    def test_open_application_blocks_update_without_killing_it(self):
        before = self.snapshot()
        with self.assertRaisesRegex(updater.UpdateError, "8765"):
            self.run_update(port_check=lambda: True)
        self.assertEqual(self.snapshot(), before)

    def test_nested_or_same_roots_are_rejected(self):
        nested = self.source / "nested"
        nested.mkdir()
        for source, target in ((self.source, self.source), (self.source, nested), (nested, self.source)):
            with self.subTest(source=source, target=target):
                with self.assertRaisesRegex(updater.UpdateError, "ayrı klasörlerde"):
                    updater.update(source, target, port_check=lambda: False)

    def test_relative_manifest_paths_cannot_escape_or_touch_runtime(self):
        for value in ("../outside", "/outside", "C:/outside", "jarvis/../../data/profile.json",
                      "jarvis\\server.py", "data/profile.json", ".venv/Scripts/python.exe",
                      "jarvis/data/profile.json", "jarvis//server.py", "jarvis/./server.py"):
            with self.subTest(path=value):
                with self.assertRaises(updater.UpdateError):
                    updater.allowed_relative(value)

    def test_source_symlink_is_rejected(self):
        outside = self.root / "outside.py"
        outside.write_bytes(b"not release data")
        link = self.source / "jarvis" / "linked.py"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("Symlink fixture unsupported by this test host")
        before = self.snapshot()
        with self.assertRaisesRegex(updater.UpdateError, "Bağlantı/junction"):
            self.run_update()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(outside.read_bytes(), b"not release data")

    def test_target_symlink_and_backup_escape_are_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.target / "backups"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink fixture unsupported by this test host")
        with self.assertRaisesRegex(updater.UpdateError, "Bağlantı/junction"):
            self.run_update()
        self.assertEqual(list(outside.iterdir()), [])

    def test_parallel_update_lock_is_preserved(self):
        lock = self.target / ".jarvis-update.lock"
        lock.write_bytes(b"other updater")
        with self.assertRaisesRegex(updater.UpdateError, "güncelleme kilidi"):
            self.run_update()
        self.assertEqual(lock.read_bytes(), b"other updater")

    def test_windows_reparse_attribute_is_rejected(self):
        candidate = self.target / "jarvis"
        real_lstat = Path.lstat

        def lstat(path, *args, **kwargs):
            if path == candidate:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=updater.REPARSE_FLAG)
            return real_lstat(path, *args, **kwargs)

        with patch.object(Path, "lstat", new=lstat):
            with self.assertRaisesRegex(updater.UpdateError, "Bağlantı/junction"):
                updater._plain_components(candidate)


if __name__ == "__main__":
    unittest.main()
