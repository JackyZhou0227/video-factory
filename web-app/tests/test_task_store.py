from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services import settings_store, task_store
from tests.pg_test_utils import ensure_test_user, index_names, table_names


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output_root = self.root / "output"
        self.output_root.mkdir()
        settings_store.init_db()
        for user_id, username in (("user-a", "user_a"), ("user-b", "user_b")):
            ensure_test_user(user_id, username=username, display_name=username.title())

    def tearDown(self):
        self.temp_dir.cleanup()

    def user(self, user_id: str = "user-a") -> dict[str, str]:
        return {"id": user_id, "username": user_id.replace("-", "_"), "display_name": "User A"}

    def test_schema_is_idempotent_and_has_indexes(self):
        settings_store.init_db()
        self.assertIn("generation_tasks", table_names())
        indexes = {
            name
            for name in index_names("generation_tasks")
            if name.startswith("idx_generation_tasks_")
        }
        self.assertGreaterEqual(len(indexes), 3)

    def test_task_round_trip_snapshots_owner_and_uses_utc_date_directory(self):
        created_at = "2026-08-07T23:30:00+08:00"
        task = task_store.create_task(
            user=self.user(),
            task_type=task_store.TASK_TYPE_VOICE,
            generation_type="voice",
            requested_count=1,
            created_at=created_at,
            output_root=self.output_root,
            extra_info={"provider": "edge-tts", "nested": {"enabled": True}},
        )
        self.assertEqual(task["created_at"], "2026-08-07T15:30:00+00:00")
        self.assertEqual(
            Path(task["storage_path"]),
            self.output_root / "tasks" / "2026" / "08" / "07" / "voice_generation" / task["id"],
        )
        loaded = task_store.get_task(task["id"], "user-a")
        self.assertEqual(loaded["creator_username"], "user_a")
        self.assertEqual(loaded["extra_info"]["nested"]["enabled"], True)
        with self.assertRaises(task_store.TaskNotFoundError):
            task_store.get_task(task["id"], "user-b")

    def test_artifact_counts_and_public_payload_hide_server_path(self):
        task = task_store.create_task(
            user=self.user(),
            task_type=task_store.TASK_TYPE_POSTER,
            generation_type="image",
            requested_count=2,
            output_root=self.output_root,
        )
        first = Path(task["storage_path"]) / "first.jpg"
        first.write_bytes(b"first")
        task_store.add_artifact(task["id"], path=first, kind="image", artifact_id="artifact-one")
        second = Path(task["storage_path"]) / "second.jpg"
        task_store.add_artifact(
            task["id"],
            path=second,
            kind="image",
            status="failed",
            artifact_id="artifact-two",
        )
        loaded = task_store.get_task(task["id"], "user-a")
        public = task_store.public_task(loaded)
        self.assertEqual((loaded["success_count"], loaded["failed_count"]), (1, 1))
        self.assertNotIn("storage_path", public)
        self.assertNotIn("path", public["artifacts"][0])

    def test_sensitive_extra_info_and_path_escape_are_rejected(self):
        for sensitive_key in (
            "runninghub_api_key",
            "runninghubApiKey",
            "apiKey",
            "token",
            "accessToken",
            "privateKey",
            "clientSecret",
        ):
            with self.subTest(sensitive_key=sensitive_key), self.assertRaises(ValueError):
                task_store.create_task(
                    user=self.user(),
                    task_type=task_store.TASK_TYPE_DIGITAL_HUMAN,
                    generation_type="video",
                    requested_count=1,
                    output_root=self.output_root,
                    extra_info={sensitive_key: "secret"},
                )
        task = task_store.create_task(
            user=self.user(),
            task_type=task_store.TASK_TYPE_VOICE,
            generation_type="voice",
            requested_count=1,
            output_root=self.output_root,
        )
        with self.assertRaises(ValueError):
            task_store.add_artifact(task["id"], path=self.root / "outside.wav")

    def test_missing_artifact_is_reported_and_download_selection_skips_it(self):
        task = task_store.create_task(
            user=self.user(),
            task_type=task_store.TASK_TYPE_VOICE,
            generation_type="voice",
            requested_count=1,
            output_root=self.output_root,
        )
        path = Path(task["storage_path"]) / "gone.wav"
        path.write_bytes(b"audio")
        task_store.add_artifact(task["id"], path=path, kind="audio", artifact_id="gone")
        path.unlink()
        public = task_store.public_task(task_store.get_task(task["id"], "user-a"))
        self.assertEqual(public["artifacts"][0]["status"], "missing")
        self.assertIsNone(task_store.select_task_download(task_store.get_task(task["id"], "user-a")))

    def test_restart_marks_unfinished_tasks_failed_with_remaining_count(self):
        task = task_store.create_task(
            user=self.user(),
            task_type=task_store.TASK_TYPE_TEMPLATE,
            generation_type="video",
            requested_count=3,
            output_root=self.output_root,
        )
        task_store.update_task(task["id"], status="running", success_count=1, started=True)
        task_store.mark_incomplete_tasks_failed()
        loaded = task_store.get_task(task["id"], "user-a")
        self.assertEqual(loaded["status"], "failed")
        self.assertEqual(loaded["failed_count"], 2)
        self.assertIsNotNone(loaded["finished_at"])


if __name__ == "__main__":
    unittest.main()
