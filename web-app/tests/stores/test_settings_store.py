from __future__ import annotations

import unittest

from app.services import settings_store
from tests.pg_test_utils import ensure_test_user


class SettingsStoreTests(unittest.TestCase):
    def setUp(self):
        settings_store.init_db(
            {
                "llm": {"base_url": "https://seed.example/v1", "api_key": "seed-key", "model": "seed-model"},
            }
        )

    def tearDown(self):
        pass

    def test_llm_settings_update_preserves_and_clears_secret(self):
        initial = settings_store.get_llm_settings()
        self.assertEqual(initial["api_key"], "seed-key")

        updated = settings_store.update_llm_settings(model="next-model")
        self.assertEqual(updated["api_key"], "seed-key")
        self.assertEqual(updated["model"], "next-model")

        public = settings_store.public_llm_settings(updated)
        self.assertTrue(public["api_key_configured"])
        self.assertNotIn("seed-key", public["api_key_masked"])

        cleared = settings_store.update_llm_settings(clear_api_key=True)
        self.assertEqual(cleared["api_key"], "")
        self.assertFalse(settings_store.public_llm_settings(cleared)["api_key_configured"])

    def test_llm_settings_are_isolated_by_user(self):
        ensure_test_user("user-2", username="user2", display_name="User 2")
        settings_store.update_llm_settings(user_id="user-2", base_url="https://other.example/v1", model="other")
        self.assertEqual(settings_store.get_llm_settings("user-2")["model"], "other")
        self.assertEqual(settings_store.get_llm_settings()["model"], "seed-model")

    def test_runninghub_defaults_to_48g_and_preserves_24g_selection(self):
        self.assertEqual(
            settings_store.get_runninghub_settings()["instance_type"],
            settings_store.DEFAULT_RUNNINGHUB_INSTANCE_TYPE,
        )

        updated = settings_store.update_runninghub_settings(instance_type="")
        self.assertEqual(updated["instance_type"], "")
        self.assertEqual(settings_store.get_runninghub_settings()["instance_type"], "")

    def test_subtitle_replacements_support_user_scoped_crud_and_validation(self):
        user_id = "local-default"
        created = settings_store.create_subtitle_replacement(user_id=user_id, source="医生", replacement="yi生")
        self.assertEqual(created["source"], "医生")
        self.assertEqual(created["replacement"], "yi生")
        self.assertEqual(len(settings_store.list_subtitle_replacements(user_id)), 1)

        updated = settings_store.update_subtitle_replacement(
            created["id"],
            user_id=user_id,
            source="名医",
            replacement="ming yi",
        )
        self.assertEqual(updated["source"], "名医")
        self.assertEqual(updated["replacement"], "ming yi")

        with self.assertRaises(settings_store.SubtitleReplacementConflictError):
            settings_store.create_subtitle_replacement(user_id=user_id, source="名医", replacement="other")
        with self.assertRaises(ValueError):
            settings_store.create_subtitle_replacement(user_id=user_id, source="same", replacement="same")
        with self.assertRaises(ValueError):
            settings_store.create_subtitle_replacement(user_id=user_id, source="line\nbreak", replacement="safe")

        settings_store.delete_subtitle_replacement(created["id"], user_id)
        self.assertEqual(settings_store.list_subtitle_replacements(user_id), [])
        with self.assertRaises(settings_store.SubtitleReplacementNotFoundError):
            settings_store.delete_subtitle_replacement(created["id"], user_id)

    def test_subtitle_replacements_are_isolated_and_have_no_legacy_limit(self):
        ensure_test_user("user-a")
        ensure_test_user("user-b")
        for index in range(31):
            settings_store.create_subtitle_replacement(
                user_id="user-a", source=f"source-{index}", replacement=f"target-{index}"
            )
        other = settings_store.create_subtitle_replacement(
            user_id="user-b", source="source-0", replacement="other"
        )
        self.assertEqual(len(settings_store.list_subtitle_replacements("user-a")), 31)
        self.assertEqual(settings_store.list_subtitle_replacements("user-b"), [other])
        with self.assertRaises(settings_store.SubtitleReplacementNotFoundError):
            settings_store.update_subtitle_replacement(
                other["id"], user_id="user-a", source="cross", replacement="user"
            )


if __name__ == "__main__":
    unittest.main()
