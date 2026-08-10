from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import digital_human
from app.api.auth import require_current_user
from app.services import settings_store, task_store


class DigitalHumanApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temp_dir.name) / "output"
        self.output_root.mkdir()
        self.original_db_path = settings_store._db_path
        settings_store._db_path = lambda: Path(self.temp_dir.name) / "settings.db"
        settings_store.init_db()
        now = settings_store._now_iso()
        with settings_store._connect() as conn:
            conn.execute(
                "INSERT INTO users (id, username, display_name, is_default, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
                ("user-a", "user_a", "User A", now, now),
            )
        digital_human._tasks.clear()

        app = FastAPI()
        app.include_router(digital_human.router, prefix="/api")
        app.dependency_overrides[require_current_user] = self._current_user
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        digital_human._tasks.clear()
        settings_store._db_path = self.original_db_path
        self.temp_dir.cleanup()

    @staticmethod
    def _current_user():
        return {"id": "user-a", "username": "user-a", "display_name": "User A"}

    def test_generate_video_requires_an_uploaded_audio_file(self):
        response = self.client.post(
            "/api/generate-video",
            files={"image": ("character.png", b"image", "image/png")},
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_generate_video_saves_uploaded_audio_and_creates_runninghub_task(self):
        submit = AsyncMock()
        with patch.object(
            digital_human,
            "_get_config",
            return_value={"server": {"output_dir": str(self.output_root)}},
        ), patch.object(
            digital_human,
            "_resolve_runninghub_inputs",
            return_value=("test-key", "workflow-id", None),
        ), patch.object(digital_human, "_run_video_generation", submit):
            response = self.client.post(
                "/api/generate-video",
                files={
                    "image": ("character.png", b"image", "image/png"),
                    "audio": ("speech.mp3", b"audio", "audio/mpeg"),
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]
        task_dir = next((self.output_root / "tasks").rglob(task_id))
        self.assertEqual((task_dir / "character.png").read_bytes(), b"image")
        self.assertEqual((task_dir / "input_audio.mp3").read_bytes(), b"audio")

        submit.assert_awaited_once()
        self.assertEqual(submit.await_args.kwargs["audio_path"], task_dir / "input_audio.mp3")
        self.assertEqual(submit.await_args.kwargs["workflow_id"], "workflow-id")

    def test_runninghub_task_id_is_persisted_in_extra_info_only(self):
        task_id = uuid.uuid4().hex
        task = task_store.create_task(
            user=self._current_user(),
            task_type=task_store.TASK_TYPE_DIGITAL_HUMAN,
            generation_type="video",
            requested_count=1,
            task_id=task_id,
            output_root=self.output_root,
        )
        task_dir = Path(task["storage_path"])
        image_path = task_dir / "character.png"
        audio_path = task_dir / "input_audio.mp3"
        image_path.write_bytes(b"image")
        audio_path.write_bytes(b"audio")

        with patch.object(
            digital_human.runninghub,
            "submit_digital_human",
            AsyncMock(return_value="runninghub-123"),
        ):
            asyncio.run(
                digital_human._run_video_generation(
                    task_id,
                    task_dir,
                    image_path,
                    audio_path,
                    "test-key",
                    "workflow-id",
                    "plus",
                )
            )

        persisted = task_store.get_task(task_id, "user-a")
        self.assertEqual(persisted["status"], "completed")
        self.assertEqual(persisted["extra_info"]["runninghub_task_id"], "runninghub-123")
        with settings_store._connect() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(generation_tasks)").fetchall()}
            raw_json = conn.execute(
                "SELECT extra_info_json FROM generation_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()[0]
        self.assertNotIn("runninghub_task_id", columns)
        self.assertEqual(json.loads(raw_json)["runninghub_task_id"], "runninghub-123")


if __name__ == "__main__":
    unittest.main()
