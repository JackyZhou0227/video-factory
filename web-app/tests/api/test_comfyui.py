from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import comfyui
from app.api.auth import require_current_user
from app.services import settings_store, task_store
from tests.pg_test_utils import column_names, ensure_test_user, task_extra_info_json


class ComfyUIApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temp_dir.name) / "output"
        self.output_root.mkdir()
        settings_store.init_db()
        ensure_test_user("user-a", username="user_a", display_name="User A")
        comfyui._tasks.clear()

        app = FastAPI()
        app.include_router(comfyui.router, prefix="/api")
        app.dependency_overrides[require_current_user] = self._current_user
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        comfyui._tasks.clear()
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
            comfyui,
            "_get_config",
            return_value={"server": {"output_dir": str(self.output_root)}},
        ), patch.object(
            comfyui,
            "_resolve_runninghub_inputs",
            return_value=("test-key", "workflow-id", None),
        ), patch.object(comfyui, "_run_video_generation", submit):
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
        self.assertEqual(submit.await_args.kwargs["image_path"], task_dir / "character.png")
        self.assertEqual(submit.await_args.kwargs["workflow_id"], "workflow-id")

    def test_workflow_catalog_returns_public_workflow_inputs(self):
        response = self.client.get("/api/workflows")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()[0]["key"], "digital-human-lipsync")
        self.assertEqual(
            [item["key"] for item in response.json()[0]["inputs"]],
            ["image", "audio"],
        )
        self.assertNotIn("workflow_id", response.json()[0])

    def test_workflow_submission_validates_uploaded_input_fields(self):
        missing_audio = self.client.post(
            "/api/workflows/digital-human-lipsync/generate",
            files={"image": ("character.png", b"image", "image/png")},
            data={"source": "runninghub"},
        )
        unknown_workflow = self.client.post(
            "/api/workflows/unknown/generate",
            files={
                "image": ("character.png", b"image", "image/png"),
                "audio": ("speech.mp3", b"audio", "audio/mpeg"),
            },
            data={"source": "runninghub"},
        )
        invalid_image = self.client.post(
            "/api/workflows/digital-human-lipsync/generate",
            files={
                "image": ("character.txt", b"image", "text/plain"),
                "audio": ("speech.mp3", b"audio", "audio/mpeg"),
            },
            data={"source": "runninghub"},
        )

        self.assertEqual(missing_audio.status_code, 422, missing_audio.text)
        self.assertEqual(unknown_workflow.status_code, 404, unknown_workflow.text)
        self.assertEqual(invalid_image.status_code, 422, invalid_image.text)

    def test_workflow_submission_creates_comfyui_task_and_uses_input_mapping(self):
        submit = AsyncMock()
        with patch.object(
            comfyui,
            "_get_config",
            return_value={"server": {"output_dir": str(self.output_root)}},
        ), patch.object(
            comfyui,
            "_resolve_runninghub_inputs",
            return_value=("test-key", "workflow-id", "plus"),
        ), patch.object(comfyui, "_run_workflow_generation", submit):
            response = self.client.post(
                "/api/workflows/digital-human-lipsync/generate",
                files={
                    "image": ("character.png", b"image", "image/png"),
                    "audio": ("speech.mp3", b"audio", "audio/mpeg"),
                },
                data={"source": "runninghub"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]
        task = task_store.get_task(task_id, "user-a")
        self.assertEqual(task["task_type"], task_store.TASK_TYPE_COMFYUI_WORKFLOW)
        task_dir = Path(task["storage_path"])
        self.assertEqual(task_dir.parent.name, "comfyui_workflow")
        self.assertEqual((task_dir / "input_image.png").read_bytes(), b"image")
        self.assertEqual((task_dir / "input_audio.mp3").read_bytes(), b"audio")

        submit.assert_awaited_once()
        self.assertEqual(
            submit.await_args.kwargs["workflow"]["workflow_id"],
            "workflow-id",
        )
        self.assertEqual(
            submit.await_args.kwargs["inputs"],
            {
                "videoimage": str(task_dir / "input_image.png"),
                "audio": str(task_dir / "input_audio.mp3"),
            },
        )

    def test_comfyui_error_message_surfaces_missing_models(self):
        response = httpx.Response(
            200,
            json={
                "error": {"message": "Prompt outputs failed validation"},
                "node_errors": {
                    "18:1": {
                        "class_type": "UNETLoader",
                        "errors": [
                            {
                                "type": "value_not_in_list",
                                "details": "unet_name: 'flux3.safetensors' not in []",
                            }
                        ],
                    }
                },
            },
        )

        message = comfyui._comfyui_error_message(response)

        self.assertIn("Prompt outputs failed validation", message)
        self.assertIn("UNETLoader", message)
        self.assertIn("flux3.safetensors", message)

    def test_runninghub_task_id_is_persisted_in_extra_info_only(self):
        task_id = uuid.uuid4().hex
        task = task_store.create_task(
            user=self._current_user(),
            task_type=task_store.TASK_TYPE_COMFYUI_WORKFLOW,
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
            comfyui.runninghub,
            "submit_workflow",
            AsyncMock(return_value="runninghub-123"),
        ):
            asyncio.run(
                comfyui._run_video_generation(
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
        self.assertEqual(persisted["status"], "submitted")
        self.assertEqual(persisted["extra_info"]["runninghub_task_id"], "runninghub-123")
        self.assertEqual(persisted["extra_info"]["provider_task_id"], "runninghub-123")
        columns = column_names("generation_tasks")
        raw_json = task_extra_info_json(task_id)
        self.assertNotIn("runninghub_task_id", columns)
        self.assertEqual(json.loads(raw_json)["runninghub_task_id"], "runninghub-123")


class SelfhostWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temp_dir.name) / "output"
        self.output_root.mkdir()
        settings_store.init_db()
        ensure_test_user("user-a", username="user_a", display_name="User A")
        self.workflow_file = Path(self.temp_dir.name) / "workflow.json"
        self.workflow_file.write_text(
            json.dumps({
                "18:17": {"inputs": {"value": "old"}},
                "18:5": {"inputs": {"text": "old negative"}},
                "18:16": {"inputs": {"switch": False}},
                "18:11": {"inputs": {"sampling_mode.seed": 7}},
                "18:24": {"inputs": {"switch": True}},
                "19": {"inputs": {"megapixels": 1.0, "aspect_ratio": "1:1 (Square)", "multiple": 16}},
            }),
            encoding="utf-8",
        )
        self.calls: list[tuple] = []

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def _task(self) -> dict:
        task = task_store.create_task(
            user={"id": "user-a", "username": "user_a", "display_name": "User A"},
            task_type=task_store.TASK_TYPE_COMFYUI_WORKFLOW,
            generation_type="image",
            requested_count=1,
            output_root=self.output_root,
            extra_info={"source": "selfhost", "workflow_key": "text-to-image"},
        )
        task_store.update_task(task["id"], status="running", started=True)
        return task_store.get_task(task["id"])

    def _client(self, routes: dict):
        calls = self.calls

        class FakeClient:
            def __init__(self, *args, **kwargs):
                del args, kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json=None):
                calls.append(("POST", url, json))
                return routes[("POST", url)]()

            async def get(self, url, params=None):
                calls.append(("GET", url, params))
                return routes[("GET", url.split("?")[0])]()

        return FakeClient

    async def _run(self, task, *, cancel_event=None):
        with patch.object(comfyui, "get_comfyui_config", return_value={"url": "http://comfy.test"}), patch(
            "app.api.comfyui.asyncio.sleep",
            new=AsyncMock(),
        ):
            await comfyui._run_selfhost_workflow(
                task_id=task["id"],
                workflow_file=self.workflow_file,
                scalar_inputs={"prompt": "a cat", "resolution": "720p", "aspect_ratio": "9:16"},
                file_inputs={},
                task_dir=Path(task["storage_path"]),
                cancel_event=cancel_event,
            )

    async def test_selfhost_stores_prompt_id_and_image_artifact(self):
        task = self._task()
        prompt_id = "11111111-1111-1111-1111-111111111111"

        def prompt_response():
            return httpx.Response(200, json={"prompt_id": prompt_id, "node_errors": {}})

        def history_response():
            return httpx.Response(200, json={
                prompt_id: {
                    "status": {"completed": True},
                    "outputs": {"9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}},
                }
            })

        def view_response():
            return httpx.Response(200, content=b"png")

        routes = {
            ("POST", "http://comfy.test/prompt"): prompt_response,
            ("GET", f"http://comfy.test/history/{prompt_id}"): history_response,
            ("GET", "http://comfy.test/view"): view_response,
        }
        with patch("app.api.comfyui.httpx.AsyncClient", self._client(routes)):
            await self._run(task)

        posted = self.calls[0][2]["prompt"]
        self.assertEqual(posted["18:17"]["inputs"]["value"], "a cat")
        self.assertEqual(posted["18:5"]["inputs"]["text"], "old negative")
        self.assertEqual(posted["19"]["inputs"]["megapixels"], 1280 * 720 / (1024 * 1024))
        self.assertEqual(posted["19"]["inputs"]["aspect_ratio"], "9:16 (Portrait Widescreen)")
        self.assertIs(posted["18:16"]["inputs"]["switch"], False)
        self.assertEqual(posted["18:11"]["inputs"]["sampling_mode.seed"], 7)
        self.assertIs(posted["18:24"]["inputs"]["switch"], True)
        saved = task_store.get_task(task["id"])
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["extra_info"]["comfyui_prompt_id"], prompt_id)
        self.assertEqual(saved["artifacts"][0]["kind"], "image")
        self.assertEqual((Path(task["storage_path"]) / "out.png").read_bytes(), b"png")

    async def test_selfhost_cancel_before_prompt_does_not_submit(self):
        task = self._task()
        cancel_event = asyncio.Event()
        cancel_event.set()
        with patch("app.api.comfyui.httpx.AsyncClient", self._client({})):
            await self._run(task, cancel_event=cancel_event)

        self.assertEqual(self.calls, [])
        self.assertEqual(task_store.get_task(task["id"])["status"], "cancelled")

    async def test_selfhost_cancel_after_prompt_calls_job_cancel(self):
        task = self._task()
        prompt_id = "22222222-2222-2222-2222-222222222222"
        cancel_event = asyncio.Event()

        def prompt_response():
            cancel_event.set()
            return httpx.Response(200, json={"prompt_id": prompt_id, "node_errors": {}})

        def cancel_response():
            return httpx.Response(200, json={"cancelled": True})

        def history_response():
            return httpx.Response(200, json={})

        routes = {
            ("POST", "http://comfy.test/prompt"): prompt_response,
            ("POST", f"http://comfy.test/api/jobs/{prompt_id}/cancel"): cancel_response,
            ("GET", f"http://comfy.test/history/{prompt_id}"): history_response,
        }
        with patch("app.api.comfyui.httpx.AsyncClient", self._client(routes)):
            await self._run(task, cancel_event=cancel_event)

        self.assertIn(("POST", f"http://comfy.test/api/jobs/{prompt_id}/cancel", None), self.calls)
        saved = task_store.get_task(task["id"])
        self.assertEqual(saved["status"], "cancelled")
        self.assertEqual(saved["artifacts"], [])

    async def test_selfhost_cancel_falls_back_when_job_route_is_missing(self):
        task = self._task()
        prompt_id = "33333333-3333-3333-3333-333333333333"
        cancel_event = asyncio.Event()

        def prompt_response():
            cancel_event.set()
            return httpx.Response(200, json={"prompt_id": prompt_id, "node_errors": {}})

        routes = {
            ("POST", "http://comfy.test/prompt"): prompt_response,
            ("POST", f"http://comfy.test/api/jobs/{prompt_id}/cancel"): lambda: httpx.Response(404),
            ("POST", "http://comfy.test/interrupt"): lambda: httpx.Response(200),
            ("POST", "http://comfy.test/queue"): lambda: httpx.Response(200),
            ("GET", f"http://comfy.test/history/{prompt_id}"): lambda: httpx.Response(200, json={}),
        }
        with patch("app.api.comfyui.httpx.AsyncClient", self._client(routes)):
            await self._run(task, cancel_event=cancel_event)

        self.assertIn(("POST", "http://comfy.test/interrupt", {"prompt_id": prompt_id}), self.calls)
        self.assertIn(("POST", "http://comfy.test/queue", {"delete": [prompt_id]}), self.calls)
        self.assertEqual(task_store.get_task(task["id"])["status"], "cancelled")

    async def test_selfhost_cancel_keeps_completed_history(self):
        task = self._task()
        prompt_id = "44444444-4444-4444-4444-444444444444"
        cancel_event = asyncio.Event()

        def prompt_response():
            cancel_event.set()
            return httpx.Response(200, json={"prompt_id": prompt_id, "node_errors": {}})

        def history_response():
            return httpx.Response(200, json={
                prompt_id: {
                    "status": {"completed": True},
                    "outputs": {"9": {"images": [{"filename": "done.png", "subfolder": "", "type": "output"}]}},
                }
            })

        routes = {
            ("POST", "http://comfy.test/prompt"): prompt_response,
            ("POST", f"http://comfy.test/api/jobs/{prompt_id}/cancel"): lambda: httpx.Response(200, json={"cancelled": False}),
            ("GET", f"http://comfy.test/history/{prompt_id}"): history_response,
            ("GET", "http://comfy.test/view"): lambda: httpx.Response(200, content=b"img"),
        }
        with patch("app.api.comfyui.httpx.AsyncClient", self._client(routes)):
            await self._run(task, cancel_event=cancel_event)

        saved = task_store.get_task(task["id"])
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["artifacts"][0]["kind"], "image")

    def test_task_payload_lists_image_urls_and_leaves_video_empty(self):
        task = task_store.create_task(
            user={"id": "user-a", "username": "user_a", "display_name": "User A"},
            task_type=task_store.TASK_TYPE_COMFYUI_WORKFLOW,
            generation_type="image",
            requested_count=1,
            output_root=self.output_root,
            extra_info={"source": "selfhost"},
        )
        image = Path(task["storage_path"]) / "out.png"
        image.write_bytes(b"png")
        task_store.add_artifact(task["id"], path=image, kind="image", status="completed")
        payload = comfyui._task_payload(task_store.get_task(task["id"]))
        self.assertEqual(payload["video_url"], None)
        self.assertEqual(len(payload["image_urls"]), 1)
        self.assertIn("/preview", payload["image_urls"][0])


if __name__ == "__main__":
    unittest.main()
