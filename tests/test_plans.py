"""Plan parsing, data boundaries and explicit persistence; no model required."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jarvis import plans


def model_plan(title="Akşam öğrenme planı"):
    return {
        "title": title,
        "steps": [
            {"text": "Önce bugünkü hedefini seç.", "minutes": 5},
            {"text": "Seçtiğin konuda küçük bir örnek uygula.", "minutes": 25},
            {"text": "Neyi öğrendiğini kısa bir notla özetle.", "minutes": None},
        ],
        "assumptions": ["Bu akşam yaklaşık yarım saat ayırabileceğini varsaydım."],
    }


class PlanCommandTests(unittest.TestCase):
    def test_direct_creation_preserves_turkish_goal(self):
        examples = {
            "plan oluştur: İşten sonra İngilizce çalışacağım": "İşten sonra İngilizce çalışacağım",
            "Bana bir plan hazırla: Türkçe konuşma pratiği.": "Türkçe konuşma pratiği",
            "İşten sonra İngilizce öğrenmek için bir plan hazırla.": "İşten sonra İngilizce öğrenmek",
            "Bana resim çizmek için bir plan oluştur": "resim çizmek",
            "Bana bir plan oluştur": "",
            "Plan yap.": "",
        }
        for text, goal in examples.items():
            with self.subTest(text=text):
                self.assertEqual(plans.plan_command(text), ("create", goal))

    def test_durable_and_read_commands_are_separate(self):
        for text, kind in (
            ("Planı kaydet.", "save"), ("Bu planı kaydet", "save"),
            ("Planımı göster", "show"), ("Planımı oku!", "show"),
            ("Kayıtlı planımı sil", "delete"),
            ("Plan taslağını iptal et", "discard"),
        ):
            with self.subTest(text=text):
                self.assertEqual(plans.plan_command(text), (kind, ""))

    def test_quotes_negation_and_embedded_instructions_are_not_commands(self):
        for text in (
            '"Planı kaydet"', "‘Kayıtlı planımı sil’", "`planı kaydet`",
            'Sayfada "planı kaydet" yazıyor.', "Bana planı kaydet de",
            "Planı kaydetme", "Kayıtlı planımı silme", "Plan oluşturma",
            "Planı kaydet ve not defterini aç", "Planı kaydetmek istemiyorum",
            "Planı kaydettim", "Bir plan oluşturabilir misin diye sordu",
            "Hayır, planı kaydet", "Planı\nkaydet", "Planı kaydet\u200b",
            "Planı kaydet: şimdi", "Planı kaydet;",
        ):
            with self.subTest(text=text):
                self.assertIsNone(plans.plan_command(text))

    def test_non_text_and_oversized_input_is_not_a_command(self):
        for text in (None, 123, [], "plan oluştur: " + "x" * plans.SETTINGS.max_text_chars):
            self.assertIsNone(plans.plan_command(text))


class PlanDataTests(unittest.TestCase):
    def test_server_owned_identity_timestamp_and_immutable_collections(self):
        first = plans.draft_from_model(model_plan())
        second = plans.draft_from_model(model_plan())
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(first.id), 32)
        self.assertEqual(datetime.fromisoformat(first.created_at).utcoffset(), timezone.utc.utcoffset(None))
        self.assertIsInstance(first.steps, tuple)
        self.assertIsInstance(first.assumptions, tuple)
        with self.assertRaises(FrozenInstanceError):
            first.title = "Başka"
        with self.assertRaises(FrozenInstanceError):
            first.steps[0].minutes = 42
        self.assertEqual(plans.PlanDraft.from_dict(first.to_dict()), first)

    def test_model_cannot_supply_identity_or_execution_fields(self):
        for extra in ("id", "schema_version", "created_at", "command", "path", "tool_calls"):
            value = model_plan()
            value[extra] = "arbitrary"
            with self.subTest(extra=extra), self.assertRaises(plans.PlanError):
                plans.draft_from_model(value)
        value = model_plan()
        value["steps"][0]["command"] = "do something"
        with self.assertRaises(plans.PlanError):
            plans.draft_from_model(value)

    def test_model_requires_exact_fields_and_lists(self):
        for key in ("title", "steps", "assumptions"):
            value = model_plan()
            del value[key]
            with self.subTest(key=key), self.assertRaises(plans.PlanError):
                plans.draft_from_model(value)
        for field in ("steps", "assumptions"):
            for wrong in (None, "wrong", {}, tuple()):
                value = model_plan()
                value[field] = wrong
                with self.subTest(field=field, wrong=wrong), self.assertRaises(plans.PlanError):
                    plans.draft_from_model(value)
        value = model_plan()
        del value["steps"][0]["minutes"]
        with self.assertRaises(plans.PlanError):
            plans.draft_from_model(value)

    def test_minutes_reject_bool_fraction_nan_zero_and_over_limit(self):
        for minutes in (True, False, 1.5, float("nan"), float("inf"), "25", 0, -1, plans.SETTINGS.plan_max_minutes + 1):
            value = model_plan()
            value["steps"][0]["minutes"] = minutes
            with self.subTest(minutes=minutes), self.assertRaises(plans.PlanError):
                plans.draft_from_model(value)

    def test_strings_and_collection_limits_are_enforced_without_truncation(self):
        for field, maximum in (
            ("title", plans.SETTINGS.plan_title_max_chars),
            ("step", plans.SETTINGS.plan_step_max_chars),
            ("assumption", plans.SETTINGS.plan_assumption_max_chars),
        ):
            for wrong in (None, 42, "", " leading", "trailing ", "a\nb", "a\x00b", "x" * (maximum + 1)):
                value = model_plan()
                if field == "title":
                    value["title"] = wrong
                elif field == "step":
                    value["steps"][0]["text"] = wrong
                else:
                    value["assumptions"] = [wrong]
                with self.subTest(field=field, wrong=repr(wrong)[:30]), self.assertRaises(plans.PlanError):
                    plans.draft_from_model(value)
        for field, value in (
            ("steps", []),
            ("steps", [{"text": "Adım", "minutes": None}] * (plans.SETTINGS.plan_max_steps + 1)),
            ("assumptions", ["Varsayım"] * (plans.SETTINGS.plan_max_assumptions + 1)),
        ):
            payload = model_plan()
            payload[field] = value
            with self.subTest(field=field), self.assertRaises(plans.PlanError):
                plans.draft_from_model(payload)

    def test_persisted_schema_metadata_and_unknown_fields_are_strict(self):
        original = plans.draft_from_model(model_plan()).to_dict()
        for field, value in (
            ("schema_version", 2), ("schema_version", True),
            ("id", "../../example"), ("id", "0" * 31),
            ("created_at", "2026-11-23T10:00:00"),
            ("created_at", "2026-11-23T10:00:00+03:00"),
            ("created_at", "bad"), ("created_at", None),
        ):
            payload = copy.deepcopy(original)
            payload[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(plans.PlanError):
                plans.PlanDraft.from_dict(payload)
        original["command"] = "ignored?"
        with self.assertRaises(plans.PlanError):
            plans.PlanDraft.from_dict(original)

    def test_json_schema_and_validation_share_settings_limits(self):
        settings = replace(plans.SETTINGS, plan_max_steps=1, plan_title_max_chars=8, plan_max_minutes=7)
        with patch.object(plans, "SETTINGS", settings):
            schema = plans.plan_json_schema()
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(schema["properties"]["title"]["maxLength"], 8)
            self.assertEqual(schema["properties"]["steps"]["maxItems"], 1)
            self.assertEqual(schema["properties"]["steps"]["items"]["properties"]["minutes"]["maximum"], 7)
            with self.assertRaises(plans.PlanError):
                plans.draft_from_model(model_plan())

    def test_spoken_plan_labels_time_estimates_and_assumptions(self):
        draft = plans.draft_from_model(model_plan())
        spoken = draft.spoken()
        self.assertIn("1. adım:", spoken)
        self.assertIn("Tahmini 25 dakika.", spoken)
        self.assertIn("Varsayımlar:", spoken)
        self.assertNotIn("None", spoken)
        self.assertNotIn(draft.id, spoken)


class PlanStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / "data" / "plan.json"
        self.store = plans.PlanStore(self.path)

    def tearDown(self):
        self.temporary.cleanup()

    def test_load_and_draft_creation_do_not_persist(self):
        self.assertIsNone(self.store.load())
        plans.draft_from_model(model_plan())
        self.store.delete()
        self.assertFalse(self.path.parent.exists())

    def test_explicit_save_survives_new_store_and_preserves_identity(self):
        first = plans.draft_from_model(model_plan())
        self.store.save(first)
        self.assertEqual(plans.PlanStore(self.path).load(), first)
        second = plans.draft_from_model(model_plan("Yeni hedef"))
        self.store.save(second)
        self.assertEqual(self.store.load(), second)
        self.store.delete()
        self.assertIsNone(self.store.load())

    def test_unknown_corrupt_and_duplicate_fields_are_never_overwritten_or_deleted(self):
        draft = plans.draft_from_model(model_plan())
        future = draft.to_dict()
        future["schema_version"] = 99
        duplicate = json.dumps(draft.to_dict(), ensure_ascii=False)
        duplicate = duplicate[:-1] + ', "schema_version": 1}'
        self.path.parent.mkdir()
        for raw in (b"not json", json.dumps(future).encode(), duplicate.encode(),
                    b"{\"minutes\": NaN}", b"[" * 1200 + b"0" + b"]" * 1200):
            self.path.write_bytes(raw)
            for action in (self.store.load, lambda: self.store.save(draft), self.store.delete):
                with self.subTest(raw=raw[:30], action=action), self.assertRaises(plans.PlanError):
                    action()
                self.assertEqual(self.path.read_bytes(), raw)

    def test_oversized_existing_file_is_preserved(self):
        self.path.parent.mkdir()
        raw = b"x" * (plans.SETTINGS.plan_file_max_bytes + 1)
        self.path.write_bytes(raw)
        with self.assertRaises(plans.PlanError):
            self.store.load()
        with self.assertRaises(plans.PlanError):
            self.store.save(plans.draft_from_model(model_plan()))
        self.assertEqual(self.path.read_bytes(), raw)

    def test_failed_replace_preserves_old_plan_and_removes_temporary(self):
        old = plans.draft_from_model(model_plan())
        self.store.save(old)
        original = self.path.read_bytes()
        with patch.object(plans.os, "replace", side_effect=OSError("private/path/secret")):
            with self.assertRaises(plans.PlanError) as raised:
                self.store.save(plans.draft_from_model(model_plan("Başka hedef")))
        self.assertNotIn("secret", str(raised.exception))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob(".plan-*.tmp")), [])

    def test_save_does_not_overwrite_an_observed_concurrent_change(self):
        self.store.save(plans.draft_from_model(model_plan()))
        external = plans.draft_from_model(model_plan("Başka süreç tarafından eklenen daha uzun hedef"))
        raw = json.dumps(external.to_dict(), ensure_ascii=False).encode("utf-8")
        def concurrent_write(_):
            self.path.write_bytes(raw)
        with patch.object(plans.os, "fsync", side_effect=concurrent_write):
            with self.assertRaises(plans.PlanError):
                self.store.save(plans.draft_from_model(model_plan("Bu değişmemeli")))
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(list(self.path.parent.glob(".plan-*.tmp")), [])

    def test_links_and_dangling_links_are_not_read_saved_or_deleted(self):
        self.path.parent.mkdir()
        target = self.root / "other.json"
        target.write_text(json.dumps(plans.draft_from_model(model_plan()).to_dict()), encoding="utf-8")
        try:
            self.path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links are not available in this environment")
        for dangling in (False, True):
            if dangling:
                target.unlink()
            for action in (self.store.load, lambda: self.store.save(plans.draft_from_model(model_plan())), self.store.delete):
                with self.subTest(dangling=dangling), self.assertRaises(plans.PlanError):
                    action()
                self.assertTrue(self.path.is_symlink())

    def test_linked_parent_directory_is_rejected(self):
        target = self.root / "other"
        target.mkdir()
        try:
            self.path.parent.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links are not available in this environment")
        with self.assertRaises(plans.PlanError):
            self.store.load()
        with self.assertRaises(plans.PlanError):
            self.store.save(plans.draft_from_model(model_plan()))
        self.assertEqual(list(target.iterdir()), [])

    def test_windows_reparse_attribute_is_rejected_without_following(self):
        fake = SimpleNamespace(st_mode=0o100600, st_file_attributes=0x400)
        with patch.object(plans.Path, "lstat", return_value=fake):
            with self.assertRaises(plans.PlanError):
                self.store.load()


if __name__ == "__main__":
    unittest.main()
