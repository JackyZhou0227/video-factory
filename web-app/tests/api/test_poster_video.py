from __future__ import annotations

import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import poster_video as poster_api
from app.api.auth import require_current_user
from app.services import settings_store, task_store
from tests.pg_test_utils import ensure_test_user


class PosterVideoApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output_root = self.root / "output"
        self.output_root.mkdir()
        settings_store.init_db()
        ensure_test_user("user-a", username="user_a", display_name="User A")
        poster_api._tasks.clear()

        app = FastAPI()
        app.include_router(poster_api.router, prefix="/api")
        app.dependency_overrides[require_current_user] = lambda: {
            "id": "user-a",
            "username": "user_a",
            "display_name": "User A",
        }
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        poster_api._tasks.clear()
        self.temp_dir.cleanup()

    def test_create_image_batch_records_requested_count_and_date_path(self):
        with patch.object(poster_api, "resolve_output_dir", return_value=self.output_root), patch.object(
            poster_api.poster_video,
            "create_overlay",
            side_effect=lambda _template, path: path.write_bytes(b"overlay"),
        ), patch.object(poster_api, "_run_batch"):
            response = self.client.post(
                "/api/poster-videos/generate",
                data={"media_type": "image", "template": '{"blocks": []}'},
                files=[
                    ("assets", ("first.jpg", b"first", "image/jpeg")),
                    ("assets", ("second.png", b"second", "image/png")),
                ],
            )
        self.assertEqual(response.status_code, 200, response.text)
        task = task_store.get_task(response.json()["task_id"], "user-a")
        self.assertEqual(task["task_type"], task_store.TASK_TYPE_POSTER)
        self.assertEqual(task["generation_type"], "image")
        self.assertEqual(task["requested_count"], 2)
        self.assertIn(str(Path("tasks") / task["created_at"][:4] / task["created_at"][5:7]), task["storage_path"])

    def run_batch_case(self, outcomes: list[bool]) -> dict:
        task_id = uuid.uuid4().hex
        record = task_store.create_task(
            user={"id": "user-a", "username": "user_a", "display_name": "User A"},
            task_type=task_store.TASK_TYPE_POSTER,
            generation_type="image",
            requested_count=len(outcomes),
            task_id=task_id,
            output_root=self.output_root,
        )
        task_dir = Path(record["storage_path"])
        files = []
        for index in range(len(outcomes)):
            input_path = task_dir / f"input-{index}.jpg"
            input_path.write_bytes(b"input")
            files.append({
                "id": f"item-{index}",
                "filename": f"input-{index}.jpg",
                "input_path": input_path,
                "output_path": task_dir / f"output-{index}.jpg",
            })
        poster_api._tasks[task_id] = poster_api._new_task("user-a", task_dir, files, "image")

        outcome_iter = iter(outcomes)

        def process_image(_input_path, _overlay_path, output_path):
            if not next(outcome_iter):
                raise RuntimeError("render failed")
            output_path.write_bytes(b"result")

        overlay = task_dir / "overlay.png"
        overlay.write_bytes(b"overlay")
        with patch.object(poster_api.poster_video, "process_image", side_effect=process_image):
            asyncio.run(poster_api._run_batch(task_id, files, overlay, task_dir, "image"))
        return task_store.get_task(task_id, "user-a")

    def test_batch_statuses_cover_success_partial_and_failure(self):
        completed = self.run_batch_case([True, True])
        partial = self.run_batch_case([True, False])
        failed = self.run_batch_case([False, False])

        self.assertEqual((completed["status"], completed["success_count"], completed["failed_count"]), ("completed", 2, 0))
        self.assertEqual((partial["status"], partial["success_count"], partial["failed_count"]), ("partial_failed", 1, 1))
        self.assertEqual((failed["status"], failed["success_count"], failed["failed_count"]), ("failed", 0, 2))
        self.assertTrue(any(item["kind"] == "archive" for item in completed["artifacts"]))
        self.assertTrue(any(item["kind"] == "archive" for item in partial["artifacts"]))
        self.assertFalse(any(item["kind"] == "archive" for item in failed["artifacts"]))


if __name__ == "__main__":
    unittest.main()
