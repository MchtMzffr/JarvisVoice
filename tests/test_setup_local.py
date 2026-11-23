"""Prerequisite orchestration with fake HTTP/installers; never installs software."""
import io
import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jarvis import setup_local as setup


class SetupTests(unittest.TestCase):
    def test_existing_model_is_reused_without_install_or_download(self):
        with patch.object(setup, "webview2_available", return_value=True), \
             patch.object(setup, "ensure_service", return_value=["gpt-oss:20b"]), \
             patch.object(setup, "install_package") as install, \
             patch.object(setup, "pull_model") as pull:
            setup.setup(install_missing=True, progress=Mock())
        install.assert_not_called()
        pull.assert_not_called()

    def test_normal_start_cannot_install_or_pull_a_missing_model(self):
        with patch.object(setup, "webview2_available", return_value=True), \
             patch.object(setup, "ensure_service", return_value=[]), \
             patch.object(setup, "install_package") as install, \
             patch.object(setup, "pull_model") as pull:
            with self.assertRaises(setup.SetupError):
                setup.setup(progress=Mock())
        install.assert_not_called()
        pull.assert_not_called()

    def test_explicit_setup_pulls_only_when_missing_and_verifies_result(self):
        with patch.object(setup, "webview2_available", return_value=True), \
             patch.object(setup, "ensure_service", return_value=[]), \
             patch.object(setup, "pull_model") as pull, \
             patch.object(setup, "installed_models", return_value=["gpt-oss:20b"]):
            setup.setup(install_missing=True, progress=Mock())
        pull.assert_called_once()

    def test_existing_service_never_starts_another_process(self):
        with patch.object(setup, "installed_models", return_value=["gpt-oss:20b"]), \
             patch.object(setup.subprocess, "Popen") as spawn:
            self.assertEqual(setup.ensure_service(progress=Mock()), ["gpt-oss:20b"])
        spawn.assert_not_called()

    def test_missing_executable_without_setup_does_not_install(self):
        with patch.object(setup, "installed_models", side_effect=setup.ServiceUnavailable("not ready")), \
             patch.object(setup, "ollama_executable", return_value=None), \
             patch.object(setup, "install_package") as install:
            with self.assertRaises(setup.SetupError):
                setup.ensure_service(progress=Mock())
        install.assert_not_called()

    def test_installer_accepts_only_two_fixed_package_ids(self):
        with patch.object(setup.subprocess, "run") as run:
            with self.assertRaises(setup.SetupError):
                setup.install_package("UserProvided.Unknown")
        run.assert_not_called()

    def test_installer_uses_no_shell_and_fixed_source(self):
        with patch.object(setup.sys, "platform", "win32"), \
             patch.object(setup.shutil, "which", return_value=r"C:\Tools\winget.exe"), \
             patch.object(setup.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            setup.install_package("Ollama.Ollama")
        args, kwargs = run.call_args
        self.assertEqual(args[0][1:7], ["install", "--id", "Ollama.Ollama", "--exact", "--source", "winget"])
        self.assertIs(kwargs["shell"], False)

    def test_external_model_service_is_rejected_before_network(self):
        with patch.object(setup, "SETTINGS", replace(setup.SETTINGS, ollama_url="https://example.invalid")), \
             patch.object(setup.http.client, "HTTPConnection") as connection:
            with self.assertRaises(setup.SetupError):
                setup._connection()
        connection.assert_not_called()

    def test_model_list_is_bounded_and_validated(self):
        response = Mock(status=200)
        response.read.return_value = b'{"models":[{"name":"gpt-oss:20b"}]}'
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(setup, "_connection", return_value=connection):
            self.assertEqual(setup.installed_models(), ["gpt-oss:20b"])
        connection.close.assert_called_once()
        response.read.assert_called_once_with(setup.SETTINGS.setup_http_max_bytes + 1)

    def test_download_requires_complete_success_and_does_not_echo_remote_error(self):
        for payload in (b'{"completed":1,"total":2}\n', b'{"error":"private path or token"}\n'):
            response = io.BytesIO(payload)
            response.status = 200
            connection = Mock()
            connection.getresponse.return_value = response
            with patch.object(setup, "_connection", return_value=connection):
                with self.assertRaises(setup.SetupError) as raised:
                    setup.pull_model(progress=Mock())
            self.assertNotIn("private", str(raised.exception))
            connection.close.assert_called_once()

    def test_download_submits_fixed_model_and_validates_success(self):
        response = io.BytesIO(b'{"completed":2,"total":2}\n{"status":"success"}\n')
        response.status = 200
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(setup, "_connection", return_value=connection):
            setup.pull_model(progress=Mock())
        args = connection.request.call_args.args
        self.assertEqual(args[:2], ("POST", "/api/pull"))
        self.assertEqual(json.loads(args[2]), {"model": "gpt-oss:20b", "stream": True})


if __name__ == "__main__":
    unittest.main()
