from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services import settings_store


class SettingsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = settings_store._db_path
        db_path = Path(self.temp_dir.name) / "settings.db"
        settings_store._db_path = lambda: db_path
        settings_store.init_db(
            {
                "runninghub": {},
                "llm": {"base_url": "https://seed.example/v1", "api_key": "seed-key", "model": "seed-model"},
            }
        )

    def tearDown(self):
        settings_store._db_path = self.original_db_path
        self.temp_dir.cleanup()

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
        with settings_store._connect() as conn:
            now = settings_store._now_iso()
            conn.execute(
                """
                INSERT INTO users (id, username, display_name, created_at, updated_at)
                VALUES ('user-2', 'user2', 'User 2', ?, ?)
                """,
                (now, now),
            )
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


if __name__ == "__main__":
    unittest.main()
