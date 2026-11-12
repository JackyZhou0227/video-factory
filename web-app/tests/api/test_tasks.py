from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import output as output_api
from app.api import tasks as tasks_api
from app.api.auth import require_current_user
from app.core.config import app_config
from app.services import settings_store, task_store
from tests.pg_test_utils import ensure_test_user, set_task_artifacts


class TasksApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output_root = self.root / "output"
        self.output_root.mkdir()
        settings_store.init_db()
        for user_id, username in (("user-a", "user_a"), ("user-b", "user_b")):
            ensure_test_user(user_id, username=username, display_name=username.title())

        self.user_id = "user-a"

        def current_user():
            return {
                "id": self.user_id,
                "username": self.user_id.replace("-", "_"),
                "display_name": self.user_id,
            }

        app = FastAPI()
        app.include_router(tasks_api.router, prefix="/api")
        app.include_router(output_api.router)
        app.dependency_overrides[require_current_user] = current_user
        self.client = TestClient(app)
        self.output_root_patch = patch.object(task_store, "_output_root", return_value=self.output_root.resolve())
        self.output_root_patch.start()

    def tearDown(self):
        self.client.close()
        self.output_root_patch.stop()
        self.temp_dir.cleanup()

    def user(self, user_id: str) -> dict[str, str]:
        return {
            "id": user_id,
            "username": user_id.replace("-", "_"),
            "display_name": user_id,
        }

    def cancel_task(self, task_id: str, *, runtime_available: bool = True, registered: bool = True):
        if not runtime_available:
            runtime_patch = patch.object(tasks_api, "get_task_runtime", side_effect=RuntimeError)
        else:
            runtime = Mock()
            runtime.can_cancel.return_value = registered
            runtime.cancel.return_value = True
            runtime_patch = patch.object(tasks_api, "get_task_runtime", return_value=runtime)
        with runtime_patch:
            return self.client.post(f"/api/tasks/{task_id}/cancel")

    def create_completed_voice_task(self, user_id: str = "user-a") -> tuple[dict, str, Path]:
        task = task_store.create_task(
            user=self.user(user_id),
            task_type=task_store.TASK_TYPE_VOICE,
            generation_type="voice",
            requested_count=1,
            output_root=self.output_root,
            extra_info={"provider": "edge-tts"},
        )
        artifact_id = "voice-artifact"
        path = Path(task["storage_path"]) / "preview.mp3"
        path.write_bytes(b"audio-data")
        task_store.add_artifact(
            task["id"],
            artifact_id=artifact_id,
            path=path,
            name="preview.mp3",
            kind="audio",
            mime_type="audio/mpeg",
        )
        task_store.update_task(
            task["id"],
            status="completed",
            progress=100,
            success_count=1,
            finished=True,
        )
        return task, artifact_id, path

    def test_list_filters_paginates_and_hides_server_paths(self):
        voice_task, _, _ = self.create_completed_voice_task()
        task_store.create_task(
            user=self.user("user-a"),
            task_type=task_store.TASK_TYPE_POSTER,
            generation_type="image",
            requested_count=2,
            output_root=self.output_root,
        )
        task_store.create_task(
            user=self.user("user-b"),
            task_type=task_store.TASK_TYPE_VOICE,
            generation_type="voice",
            requested_count=1,
            output_root=self.output_root,
        )

        response = self.client.get(
            "/api/tasks",
            params={"task_type": "voice_generation", "page": 1, "page_size": 1},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["id"], voice_task["id"])
        self.assertNotIn("storage_path", payload["items"][0])
        self.assertNotIn("path", payload["items"][0]["artifacts"][0])
        self.assertTrue(payload["items"][0]["artifacts"][0]["preview_url"].startswith("/api/tasks/"))

    def test_creator_names_follow_display_name_renames(self):
        task, _, _ = self.create_completed_voice_task()
        ensure_test_user("user-a", username="user_a", display_name="改名后的昵称")

        response = self.client.get("/api/tasks")
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["items"][0]
        self.assertEqual(item["creator_username"], "user_a")
        self.assertEqual(item["creator_display_name"], "改名后的昵称")

        detail = self.client.get(f"/api/tasks/{task['id']}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["creator_username"], "user_a")
        self.assertEqual(detail.json()["creator_display_name"], "改名后的昵称")

    def test_date_filter_boundaries_use_shanghai_calendar_days(self):
        self.assertEqual(
            tasks_api._date_boundary(date(2026, 8, 7)),
            "2026-08-06T16:00:00+00:00",
        )
        self.assertEqual(
            tasks_api._date_boundary(date(2026, 8, 7), end=True),
            "2026-08-07T15:59:59.999999+00:00",
        )

    def test_preview_download_and_task_download_are_authenticated(self):
        task, artifact_id, _ = self.create_completed_voice_task()
        preview = self.client.get(f"/api/tasks/{task['id']}/artifacts/{artifact_id}/preview")
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.content, b"audio-data")
        self.assertEqual(preview.headers["content-type"], "audio/mpeg")

        download = self.client.get(f"/api/tasks/{task['id']}/artifacts/{artifact_id}/download")
        self.assertEqual(download.status_code, 200, download.text)
        self.assertIn("attachment", download.headers["content-disposition"])
        task_download = self.client.get(f"/api/tasks/{task['id']}/download")
        self.assertEqual(task_download.status_code, 200, task_download.text)
        self.assertEqual(task_download.content, b"audio-data")

        self.user_id = "user-b"
        for path in (
            f"/api/tasks/{task['id']}",
            f"/api/tasks/{task['id']}/artifacts/{artifact_id}/preview",
            f"/api/tasks/{task['id']}/artifacts/{artifact_id}/download",
            f"/api/tasks/{task['id']}/download",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, response.text)

    def test_output_route_does_not_serve_voice_profile_files_directly(self):
        reference = self.output_root / "voice_profiles" / "user-a" / "voice-1" / "reference.wav"
        reference.parent.mkdir(parents=True)
        reference.write_bytes(b"private voice")

        response = self.client.get("/output/voice_profiles/user-a/voice-1/reference.wav")

        self.assertEqual(response.status_code, 404, response.text)

    def test_missing_and_malicious_artifact_paths_return_404_without_leaking_paths(self):
        task, artifact_id, path = self.create_completed_voice_task()
        path.unlink()
        detail = self.client.get(f"/api/tasks/{task['id']}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["artifacts"][0]["status"], "missing")
        self.assertEqual(
            self.client.get(f"/api/tasks/{task['id']}/artifacts/{artifact_id}/preview").status_code,
            404,
        )

        outside = self.root / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        malicious = [{
            "id": "malicious",
            "name": "outside.txt",
            "kind": "file",
            "mime_type": "text/plain",
            "path": str(outside),
            "status": "completed",
            "size": outside.stat().st_size,
            "created_at": settings_store._now_iso(),
            "is_primary": True,
        }]
        set_task_artifacts(task["id"], malicious)
        response = self.client.get(f"/api/tasks/{task['id']}/artifacts/malicious/download")
        self.assertEqual(response.status_code, 404, response.text)
        self.assertNotIn(str(outside), response.text)

    def test_user_can_cancel_owned_pending_task(self):
        task = task_store.create_task(
            user=self.user("user-a"),
            task_type=task_store.TASK_TYPE_VOICE,
            generation_type="voice",
            requested_count=1,
            output_root=self.output_root,
        )

        response = self.cancel_task(task["id"])

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "cancelled")
        self.assertEqual(payload["message"], "任务已取消")
        self.assertIsNotNone(payload["finished_at"])

    def test_user_can_request_cancellation_for_owned_running_task(self):
        task = task_store.create_task(
            user=self.user("user-a"),
            task_type=task_store.TASK_TYPE_VOICE,
            generation_type="voice",
            requested_count=1,
            output_root=self.output_root,
        )
        task_store.update_task(task["id"], status="running", started=True)

        response = self.cancel_task(task["id"])

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "cancelling")
        self.assertIsNone(response.json()["finished_at"])

    def test_foreign_task_returns_404_when_cancelling(self):
        task = task_store.create_task(
            user=self.user("user-b"),
            task_type=task_store.TASK_TYPE_VOICE,
            generation_type="voice",
            requested_count=1,
            output_root=self.output_root,
        )

        response = self.cancel_task(task["id"])

        self.assertEqual(response.status_code, 404, response.text)

    def test_completed_task_returns_409_when_cancelling(self):
        task, _, _ = self.create_completed_voice_task()

        response = self.cancel_task(task["id"])

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(task_store.get_task(task["id"])["status"], "completed")

    def test_repeating_cancel_is_idempotent(self):
        task = task_store.create_task(
            user=self.user("user-a"),
            task_type=task_store.TASK_TYPE_VOICE,
            generation_type="voice",
            requested_count=1,
            output_root=self.output_root,
        )

        first = self.cancel_task(task["id"])
        second = self.cancel_task(task["id"], registered=False)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["status"], "cancelled")
        self.assertEqual(second.json()["finished_at"], first.json()["finished_at"])

    def test_non_tts_active_task_remains_unchanged_and_cannot_be_cancelled(self):
        task = task_store.create_task(
            user=self.user("user-a"),
            task_type=task_store.TASK_TYPE_COMFYUI_WORKFLOW,
            generation_type="video",
            requested_count=1,
            output_root=self.output_root,
        )
        task_store.update_task(task["id"], status="running", started=True)

        response = self.cancel_task(task["id"])

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"], "RunningHub 工作流任务暂不支持取消")
        self.assertEqual(task_store.get_task(task["id"])["status"], "running")

    def test_selfhost_pending_comfyui_task_can_be_cancelled(self):
        task = task_store.create_task(
            user=self.user("user-a"),
            task_type=task_store.TASK_TYPE_COMFYUI_WORKFLOW,
            generation_type="image",
            requested_count=1,
            output_root=self.output_root,
            extra_info={"source": "selfhost"},
        )

        response = self.cancel_task(task["id"], registered=False)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "cancelled")

    def test_all_non_digital_human_task_types_can_be_cancelled(self):
        for task_type in (
            task_store.TASK_TYPE_POSTER,
            task_store.TASK_TYPE_TEMPLATE,
            task_store.TASK_TYPE_SMART_EDITING,
        ):
            with self.subTest(task_type=task_type):
                task = task_store.create_task(
                    user=self.user("user-a"),
                    task_type=task_type,
                    generation_type="video",
                    requested_count=1,
                    output_root=self.output_root,
                )
                task_store.update_task(task["id"], status="running", started=True)

                response = self.cancel_task(task["id"])

                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["status"], "cancelling")
                self.assertEqual(task_store.get_task(task["id"])["status"], "cancelling")
                task_store.update_task(task["id"], status="cancelled", finished=True)

    def test_pending_task_not_registered_with_runtime_is_cancelled(self):
        task = task_store.create_task(
            user=self.user("user-a"),
            task_type=task_store.TASK_TYPE_VOICE,
            generation_type="voice",
            requested_count=1,
            output_root=self.output_root,
        )

        response = self.cancel_task(task["id"], registered=False)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(task_store.get_task(task["id"])["status"], "cancelled")

    def test_missing_runtime_still_cancels_pending_task(self):
        task = task_store.create_task(
            user=self.user("user-a"),
            task_type=task_store.TASK_TYPE_VOICE,
            generation_type="voice",
            requested_count=1,
            output_root=self.output_root,
        )

        response = self.cancel_task(task["id"], runtime_available=False)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(task_store.get_task(task["id"])["status"], "cancelled")

    def test_task_summary_counts_pending_and_running_without_leaking_other_tasks(self):
        original_tasks_config = app_config.get("tasks")
        app_config["tasks"] = {
            "max_running_tasks_per_user": 3,
            "max_active_jobs": 6,
            "max_queued_jobs": 4,
        }
        try:
            current_pending = task_store.create_task(
                user=self.user("user-a"),
                task_type=task_store.TASK_TYPE_VOICE,
                generation_type="voice",
                requested_count=1,
                output_root=self.output_root,
            )
            current_running = task_store.create_task(
                user=self.user("user-a"),
                task_type=task_store.TASK_TYPE_POSTER,
                generation_type="image",
                requested_count=1,
                output_root=self.output_root,
            )
            task_store.update_task(current_running["id"], status="running", started=True)
            completed = task_store.create_task(
                user=self.user("user-a"),
                task_type=task_store.TASK_TYPE_TEMPLATE,
                generation_type="video",
                requested_count=1,
                output_root=self.output_root,
            )
            task_store.update_task(completed["id"], status="completed", finished=True)
            other_pending = task_store.create_task(
                user=self.user("user-b"),
                task_type=task_store.TASK_TYPE_VOICE,
                generation_type="voice",
                requested_count=1,
                output_root=self.output_root,
            )
            other_running = task_store.create_task(
                user=self.user("user-b"),
                task_type=task_store.TASK_TYPE_POSTER,
                generation_type="image",
                requested_count=1,
                output_root=self.output_root,
            )
            task_store.update_task(other_running["id"], status="running", started=True)

            response = self.client.get("/api/tasks/summary")
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertEqual(
                payload["user"],
                {"pending": 1, "running": 1, "cancelling": 0, "active": 2, "limit": 3},
            )
            self.assertEqual(
                payload["global"],
                {"pending": 2, "running": 2, "cancelling": 0, "active": 4, "limit": 10},
            )
            self.assertIsNone(payload["runtime"])
            self.assertNotIn(other_pending["id"], response.text)
        finally:
            if original_tasks_config is None:
                app_config.pop("tasks", None)
            else:
                app_config["tasks"] = original_tasks_config

    def test_task_summary_returns_null_limits_when_disabled(self):
        original_tasks_config = app_config.get("tasks")
        app_config["tasks"] = {
            "max_running_tasks_per_user": 0,
            "max_active_jobs": 1,
            "max_queued_jobs": 0,
        }
        try:
            response = self.client.get("/api/tasks/summary")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIsNone(response.json()["user"]["limit"])
            self.assertEqual(response.json()["global"]["limit"], 1)
        finally:
            if original_tasks_config is None:
                app_config.pop("tasks", None)
            else:
                app_config["tasks"] = original_tasks_config


if __name__ == "__main__":
    unittest.main()
