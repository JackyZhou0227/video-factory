from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import smart_editing as smart_api
from app.api import tasks as tasks_api
from app.api.auth import require_current_user
from app.services import settings_store, task_store


class SmartEditingApiTests(unittest.TestCase):
    def setUp(self):
        smart_api._tasks.clear()
        self.user_id = "user-a"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temp_dir.name)
        self.original_db_path = settings_store._db_path
        settings_store._db_path = lambda: self.output_root / "settings.db"
        settings_store.init_db()
        self._ensure_test_user("user-a")
        self._ensure_test_user("user-b")

        def current_user():
            return {
                "id": self.user_id,
                "username": self.user_id,
                "display_name": self.user_id,
            }

        app = FastAPI()
        app.include_router(smart_api.router, prefix="/api")
        app.include_router(tasks_api.router, prefix="/api")
        app.dependency_overrides[require_current_user] = current_user
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        settings_store._db_path = self.original_db_path
        self.temp_dir.cleanup()
        smart_api._tasks.clear()

    def _ensure_test_user(self, user_id: str) -> None:
        now = settings_store._now_iso()
        with settings_store._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (id, username, display_name, is_default, created_at, updated_at)
                VALUES (?, ?, ?, 0, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (user_id, user_id, user_id, now, now),
            )

    def _create_bgm_track(
        self,
        *,
        user_id: str = "user-a",
        bgm_id: str = "smart-bgm",
        create_file: bool = True,
    ) -> Path:
        relative_path = f"bgm/{user_id}/{bgm_id}.mp3"
        file_path = self.output_root / relative_path
        if create_file:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"bgm-audio")
        settings_store.create_bgm_track(
            user_id=user_id,
            bgm_id=bgm_id,
            name=f"{bgm_id}.mp3",
            relative_path=relative_path,
            duration=12.0,
            file_size=9,
        )
        return file_path

    def _post_task(
        self,
        *,
        keywords: list[str] | None = None,
        manifest: list[dict] | None = None,
        files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
        generate_count: int = 3,
        pacing: str = "standard",
        bgm_id: str = "",
    ):
        keyword_values = keywords or ["医院", "医生"]
        file_values = files or [
            ("materials", ("hospital.jpg", b"image-data", "image/jpeg")),
            ("materials", ("doctor.mp4", b"video-data", "video/mp4")),
        ]
        manifest_values = manifest or [
            {"keyword_index": 0, "file_index": 0, "media_type": "image", "name": "hospital.jpg"},
            {"keyword_index": 1, "file_index": 1, "media_type": "video", "name": "doctor.mp4"},
        ]
        data = {
            "script": "这是一条用于验证智能剪辑任务创建流程的完整测试文案。",
            "keywords": json.dumps(keyword_values, ensure_ascii=False),
            "pacing": pacing,
            "generate_count": str(generate_count),
            "material_manifest": json.dumps(manifest_values, ensure_ascii=False),
        }
        if bgm_id:
            data["bgm_id"] = bgm_id
        return self.client.post(
            "/api/smart-editing/tasks",
            data=data,
            files=file_values,
        )

    def test_task_creation_saves_mixed_materials_snapshot_and_task_center_record(self):
        settings_store.create_subtitle_replacement(source="医生", replacement="yi生")
        run_task = AsyncMock(return_value=None)
        with patch.object(smart_api, "resolve_output_dir", return_value=self.output_root), patch.object(
            smart_api.template_production,
            "require_ffmpeg",
        ), patch.object(smart_api, "_run_task", run_task):
            response = self._post_task()

        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]
        stored = task_store.get_task(task_id, self.user_id)
        self.assertEqual(stored["task_type"], task_store.TASK_TYPE_SMART_EDITING)
        self.assertEqual(stored["requested_count"], 3)
        self.assertEqual(stored["extra_info"]["keywords"], ["医院", "医生"])
        self.assertEqual(stored["extra_info"]["pacing"], "standard")
        self.assertIsNone(stored["extra_info"]["bgm_name"])
        self.assertEqual(
            stored["extra_info"]["subtitle_replacements_snapshot"],
            [{"source": "医生", "replacement": "yi生"}],
        )
        self.assertEqual(
            [item["material_count"] for item in stored["extra_info"]["material_groups"]],
            [1, 1],
        )

        run_kwargs = run_task.call_args.kwargs
        self.assertIsNone(run_kwargs["bgm_path"])
        self.assertIsNone(smart_api._tasks[task_id]["_bgm_path"])
        self.assertEqual([item["media_type"] for item in run_kwargs["materials"]], ["image", "video"])
        self.assertEqual([item["keyword_index"] for item in run_kwargs["materials"]], [0, 1])
        for material in run_kwargs["materials"]:
            self.assertTrue(material["input_path"].is_file())
            material["input_path"].resolve().relative_to(Path(stored["storage_path"]).resolve())

        settings_store.update_subtitle_replacement(1, source="医生", replacement="专家")
        self.assertEqual(
            run_kwargs["subtitle_replacements"],
            [{"source": "医生", "replacement": "yi生"}],
        )

        detail = self.client.get(f"/api/smart-editing/tasks/{task_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["keywords"], ["医院", "医生"])

        task_center = self.client.get("/api/tasks", params={"task_type": "smart_editing"})
        self.assertEqual(task_center.status_code, 200, task_center.text)
        self.assertEqual(task_center.json()["total"], 1)
        self.assertEqual(task_center.json()["items"][0]["task_type"], "smart_editing")

    def test_task_creation_with_bgm_uses_task_snapshot(self):
        source_bgm_path = self._create_bgm_track()
        run_task = AsyncMock(return_value=None)
        with patch.object(smart_api, "resolve_output_dir", return_value=self.output_root), patch.object(
            smart_api.template_production,
            "require_ffmpeg",
        ), patch.object(smart_api, "_run_task", run_task):
            response = self._post_task(bgm_id="smart-bgm")

        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]
        stored = task_store.get_task(task_id, self.user_id)
        snapshot_path = run_task.call_args.kwargs["bgm_path"]
        self.assertEqual(stored["extra_info"]["bgm_name"], "smart-bgm.mp3")
        self.assertEqual(smart_api._tasks[task_id]["bgm_name"], "smart-bgm.mp3")
        self.assertEqual(smart_api._tasks[task_id]["_bgm_path"], snapshot_path)
        self.assertNotEqual(snapshot_path, source_bgm_path)
        snapshot_path.resolve().relative_to((Path(stored["storage_path"]) / "input").resolve())
        self.assertEqual(snapshot_path.read_bytes(), b"bgm-audio")

        source_bgm_path.unlink()
        self.assertTrue(snapshot_path.is_file())
        detail = self.client.get(f"/api/smart-editing/tasks/{task_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["bgm_name"], "smart-bgm.mp3")

    def test_task_creation_rejects_unknown_foreign_and_missing_bgm(self):
        self._create_bgm_track(user_id="user-b", bgm_id="foreign-bgm")
        self._create_bgm_track(bgm_id="missing-bgm", create_file=False)
        with patch.object(smart_api, "resolve_output_dir", return_value=self.output_root), patch.object(
            smart_api.template_production,
            "require_ffmpeg",
        ):
            unknown = self._post_task(bgm_id="unknown-bgm")
            foreign = self._post_task(bgm_id="foreign-bgm")
            missing = self._post_task(bgm_id="missing-bgm")

        self.assertEqual(unknown.status_code, 422, unknown.text)
        self.assertIn("背景音乐", unknown.json()["detail"])
        self.assertEqual(foreign.status_code, 422, foreign.text)
        self.assertIn("背景音乐", foreign.json()["detail"])
        self.assertEqual(missing.status_code, 422, missing.text)
        self.assertIn("文件不存在", missing.json()["detail"])

    def test_task_creation_rejects_duplicate_keywords_empty_groups_and_illegal_files(self):
        with patch.object(smart_api.template_production, "require_ffmpeg"):
            duplicate = self._post_task(keywords=["医院", " 医院 "])
            empty_group = self._post_task(
                manifest=[
                    {"keyword_index": 0, "file_index": 0, "media_type": "image", "name": "hospital.jpg"},
                ],
                files=[("materials", ("hospital.jpg", b"image-data", "image/jpeg"))],
            )
            illegal = self._post_task(
                keywords=["医院"],
                manifest=[
                    {"keyword_index": 0, "file_index": 0, "media_type": "image", "name": "hospital.txt"},
                ],
                files=[("materials", ("hospital.txt", b"not-image", "text/plain"))],
            )
            bad_pacing = self._post_task(pacing="turbo")
            too_many_outputs = self._post_task(generate_count=11)

        self.assertEqual(duplicate.status_code, 422, duplicate.text)
        self.assertIn("重复", duplicate.json()["detail"])
        self.assertEqual(empty_group.status_code, 422, empty_group.text)
        self.assertIn("第 2 个关键词", empty_group.json()["detail"])
        self.assertEqual(illegal.status_code, 422, illegal.text)
        self.assertIn("不支持", illegal.json()["detail"])
        self.assertEqual(bad_pacing.status_code, 422, bad_pacing.text)
        self.assertEqual(too_many_outputs.status_code, 422, too_many_outputs.text)

    def test_task_creation_rejects_more_than_twenty_materials(self):
        files = [
            ("materials", (f"image-{index}.jpg", b"image", "image/jpeg"))
            for index in range(21)
        ]
        manifest = [
            {
                "keyword_index": 0,
                "file_index": index,
                "media_type": "image",
                "name": f"image-{index}.jpg",
            }
            for index in range(21)
        ]
        with patch.object(smart_api.template_production, "require_ffmpeg"):
            response = self._post_task(keywords=["医院"], manifest=manifest, files=files)

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("素材数量", response.json()["detail"])

    def test_run_task_calls_tts_once_reuses_audio_and_keeps_partial_results(self):
        task_id = uuid.uuid4().hex
        record = task_store.create_task(
            user={"id": self.user_id, "username": self.user_id, "display_name": self.user_id},
            task_type=task_store.TASK_TYPE_SMART_EDITING,
            generation_type="video",
            requested_count=3,
            task_id=task_id,
            output_root=self.output_root,
            extra_info={"script": "原始医生文案", "keywords": ["医院", "医生"]},
        )
        task_dir = Path(record["storage_path"])
        output_dir = task_dir / "output"
        temp_dir = task_dir / "temp"
        output_dir.mkdir(parents=True)
        temp_dir.mkdir(parents=True)
        bgm_path = task_dir / "bgm.mp3"
        bgm_path.write_bytes(b"bgm")
        item_ids = [uuid.uuid4().hex for _ in range(3)]
        smart_api._tasks[task_id] = {
            "user_id": self.user_id,
            "script": "原始医生文案",
            "keywords": ["医院", "医生"],
            "pacing": "fast",
            "generate_count": 3,
            "status": "pending",
            "progress": 0,
            "message": "等待生成",
            "items": [
                {
                    "id": item_id,
                    "index": index,
                    "status": "pending",
                    "message": "等待生成",
                    "video_url": None,
                    "download_url": None,
                    "error": None,
                }
                for index, item_id in enumerate(item_ids, start=1)
            ],
            "zip_url": None,
            "error": None,
        }
        audio_paths: list[Path] = []

        async def synthesize(_model_name, _request, output_path):
            output_path.write_bytes(b"audio")
            return SimpleNamespace(duration=6.0, timings=())

        def compose(_materials, _keyword_count, audio_path, output_path, **_kwargs):
            audio_paths.append(audio_path)
            if output_path.name.endswith("002.mp4"):
                raise RuntimeError("second version failed")
            output_path.write_bytes(b"video")
            return output_path

        replacements = [{"source": "医生", "replacement": "yi生"}]
        synthesize_mock = AsyncMock(side_effect=synthesize)
        with patch.object(smart_api.tts_service, "synthesize", synthesize_mock), patch.object(
            smart_api.smart_editing,
            "compose_video",
            side_effect=compose,
        ) as compose_mock:
            asyncio.run(
                smart_api._run_task(
                    task_id=task_id,
                    task_dir=task_dir,
                    output_dir=output_dir,
                    temp_dir=temp_dir,
                    script="原始医生文案",
                    keywords=["医院", "医生"],
                    pacing="fast",
                    materials=[
                        {"input_path": Path("hospital.jpg"), "media_type": "image", "keyword_index": 0},
                        {"input_path": Path("doctor.mp4"), "media_type": "video", "keyword_index": 1},
                    ],
                    subtitle_replacements=replacements,
                    bgm_path=bgm_path,
                )
            )

        self.assertEqual(synthesize_mock.await_count, 1)
        self.assertEqual(compose_mock.call_count, 3)
        self.assertEqual(len(set(audio_paths)), 1)
        request = synthesize_mock.await_args.args[1]
        self.assertEqual(request.text, "原始医生文案")
        self.assertEqual(request.voice_id, smart_api.SMART_EDITING_TTS_VOICE_ID)
        self.assertTrue(all(call.kwargs["script"] == "原始医生文案" for call in compose_mock.call_args_list))
        self.assertTrue(
            all(call.kwargs["subtitle_replacements"] == replacements for call in compose_mock.call_args_list)
        )
        self.assertTrue(all(call.kwargs["bgm_path"] == bgm_path for call in compose_mock.call_args_list))
        self.assertEqual(
            [call.kwargs["seed"] for call in compose_mock.call_args_list],
            [f"{task_id}:1", f"{task_id}:2", f"{task_id}:3"],
        )

        stored = task_store.get_task(task_id, self.user_id)
        self.assertEqual(stored["status"], "partial_failed")
        self.assertEqual(stored["success_count"], 2)
        self.assertEqual(stored["failed_count"], 1)
        self.assertTrue((task_dir / "smart_edit_videos.zip").is_file())
        self.assertEqual(smart_api._tasks[task_id]["status"], "partial_failed")
        self.assertEqual(
            [item["status"] for item in smart_api._tasks[task_id]["items"]],
            ["completed", "failed", "completed"],
        )


if __name__ == "__main__":
    unittest.main()
