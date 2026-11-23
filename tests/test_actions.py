import dataclasses
import unittest
from unittest.mock import Mock, patch

from jarvis import actions


class ApplicationCommandTests(unittest.TestCase):
    def test_direct_turkish_variations_match_only_catalog_ids(self):
        examples = {
            "Hesap makinesini aç": "calculator",
            "Hesap   makinesini aç": "calculator",
            "JARVİS, hesap makinesini açar mısın?": "calculator",
            "Lütfen not defterini aç.": "notepad",
            "Jarvis, not defterini açar mısın?": "notepad",
            "Dosya gezginini açabilir misin?": "explorer",
            "Paint'i aç lütfen!": "paint",
            "Paint’i başlatır mısın?": "paint",
            "Notepad'i çalıştır": "notepad",
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(actions.application_command(text), expected)
        self.assertEqual(actions.application_command("Atlas, hesap makinesini aç", "Atlas"), "calculator")

    def test_unknown_explicit_app_is_not_guessed(self):
        self.assertEqual(actions.application_command("Chrome'u aç"), "unsupported")
        self.assertEqual(actions.application_command("Spotify'ı açar mısın?"), "unsupported")

    def test_quoted_negated_chained_and_ambiguous_text_never_launches(self):
        examples = [
            '"Hesap makinesini aç"', "“Hesap makinesini aç”", "'Not defterini aç'",
            "Hesap makinesini açma", "Sakın hesap makinesini aç", "Belki hesap makinesini aç",
            "Hesap makinesini aç ve not defterini aç", "Hesap makinesini açınca haber ver",
            "Hesap makinesini açtım", "Hesap makinesini aç demişti", "Hesap makinesini aç diyorsun",
            "Sayfada hesap makinesini aç yazıyor", "Onu aç", "Bunu aç", "Uygulamayı aç",
            "Not defterini aç; calc", "Not defterini aç\n", "Not\tdefterini aç",
            "C:\\Windows\\System32\\calc.exe aç", "https://example.com aç", "`calc` aç",
            "$(calc) aç", "notepad & calc aç", "Hesap makinesini\u200b aç",
        ]
        for text in examples:
            with self.subTest(text=text):
                self.assertIsNone(actions.application_command(text))

    def test_contracts_are_immutable_and_inputs_are_bounded(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            actions.APP_SPECS[0].id = "anything"
        result = actions.LaunchResult("calculator", "Hesap Makinesi", "requested", "İstek gönderildi.")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.status = "failed"
        self.assertIsNone(actions.application_command(None))
        self.assertIsNone(actions.application_command("x" * (actions.SETTINGS.max_text_chars + 1)))


class ApplicationLaunchTests(unittest.TestCase):
    def setUp(self):
        self.old_children = list(actions._children)
        actions._children.clear()

    def tearDown(self):
        actions._children[:] = self.old_children

    def test_catalog_lists_only_fixed_apps_without_launching(self):
        with patch.object(actions, "_is_windows", return_value=True), \
             patch.object(actions, "_windows_directory", return_value=r"C:\Windows"), \
             patch.object(actions.os.path, "isfile", side_effect=lambda p: p.endswith("calc.exe")), \
             patch.object(actions.subprocess, "Popen") as popen:
            catalog = actions.apps_catalog()
        self.assertEqual([row["id"] for row in catalog], ["calculator", "notepad", "explorer", "paint"])
        self.assertEqual([row["available"] for row in catalog], [True, False, False, False])
        self.assertTrue(all(set(row) == {"id", "label", "available"} for row in catalog))
        popen.assert_not_called()

    def test_launch_uses_fixed_absolute_path_no_shell_and_no_caller_arguments(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(actions, "_is_windows", return_value=True), \
             patch.object(actions, "_windows_directory", return_value=r"D:\Windows"), \
             patch.object(actions.os.path, "isfile", return_value=True), \
             patch.dict(actions.os.environ, {"PATH": r"C:\evil", "SystemRoot": r"C:\evil"}), \
             patch.object(actions.subprocess, "Popen", return_value=process) as popen:
            result = actions.launch_application("notepad")
        popen.assert_called_once_with(
            [r"D:\Windows\System32\notepad.exe"], shell=False,
            cwd=r"D:\Windows\System32", stdin=actions.subprocess.DEVNULL,
            stdout=actions.subprocess.DEVNULL, stderr=actions.subprocess.DEVNULL, close_fds=True,
        )
        self.assertEqual(result.status, "requested")
        self.assertIn("başlatma isteği gönderildi", result.message)
        self.assertNotIn("açıldı", result.message)
        process.wait.assert_not_called()
        process.terminate.assert_not_called()

    def test_unknown_ids_and_platform_never_launch(self):
        with patch.object(actions, "_is_windows", return_value=False), \
             patch.object(actions.subprocess, "Popen") as popen:
            self.assertEqual(actions.launch_application("calculator").status, "unsupported_platform")
            for app_id in ("cmd", r"C:\Windows\System32\calc.exe", "notepad --help", None, ["paint"]):
                result = actions.launch_application(app_id)
                self.assertEqual(result.status, "unavailable")
                self.assertEqual(result.app_id, "")
            self.assertTrue(all(not row["available"] for row in actions.apps_catalog()))
        popen.assert_not_called()

    def test_invalid_root_and_missing_executable_fail_closed(self):
        with patch.object(actions, "_is_windows", return_value=True), \
             patch.object(actions.subprocess, "Popen") as popen:
            for root in ("Windows", r"C:Windows", r"\\server\Windows", r"\\?\C:\Windows", "C:\0Windows"):
                with self.subTest(root=root), patch.object(actions, "_windows_directory", return_value=root):
                    self.assertEqual(actions.launch_application("calculator").status, "failed")
            with patch.object(actions, "_windows_directory", return_value=r"C:\Windows"), \
                 patch.object(actions.os.path, "isfile", return_value=False):
                self.assertEqual(actions.launch_application("calculator").status, "unavailable")
        popen.assert_not_called()

    def test_launch_error_does_not_echo_private_os_message(self):
        with patch.object(actions, "_is_windows", return_value=True), \
             patch.object(actions, "_windows_directory", return_value=r"C:\Windows"), \
             patch.object(actions.os.path, "isfile", return_value=True), \
             patch.object(actions.subprocess, "Popen", side_effect=OSError("secret path/token")):
            result = actions.launch_application("paint")
        self.assertEqual(result.status, "failed")
        self.assertNotIn("secret", result.message)
        self.assertNotIn("token", result.message)
        self.assertFalse(actions._children)

    def test_completed_children_are_polled_and_capacity_is_bounded(self):
        complete, live = Mock(), Mock()
        complete.poll.return_value = 0
        live.poll.return_value = None
        actions._children[:] = [complete, live]
        settings = dataclasses.replace(actions.SETTINGS, desktop_max_tracked_processes=1)
        with patch.object(actions, "SETTINGS", settings), \
             patch.object(actions, "_is_windows", return_value=True), \
             patch.object(actions.subprocess, "Popen") as popen:
            self.assertEqual(actions.launch_application("paint").status, "failed")
        self.assertEqual(actions._children, [live])
        popen.assert_not_called()
        complete.wait.assert_not_called()
        live.terminate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
