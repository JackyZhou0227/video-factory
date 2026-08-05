from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import digital_human
from app.api.auth import require_current_user


class DigitalHumanApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temp_dir.name) / "output"
        self.output_root.mkdir()
        digital_human._tasks.clear()

        app = FastAPI()
        app.include_router(digital_human.router, prefix="/api")
        app.dependency_overrides[require_current_user] = self._current_user
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        digital_human._tasks.clear()
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
        task_dir = self.output_root / task_id
        self.assertEqual((task_dir / "character.png").read_bytes(), b"image")
        self.assertEqual((task_dir / "input_audio.mp3").read_bytes(), b"audio")

        submit.assert_awaited_once()
        self.assertEqual(submit.await_args.kwargs["audio_path"], task_dir / "input_audio.mp3")
        self.assertEqual(submit.await_args.kwargs["workflow_id"], "workflow-id")


if __name__ == "__main__":
    unittest.main()
