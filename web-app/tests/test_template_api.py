from __future__ import annotations

import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import template_production as template_api
from app.api.auth import require_current_user
from app.services import settings_store, task_store
from app.services.template_registry import TemplateRegistry
from tests.pg_test_utils import ensure_test_user


class TemplateProductionApiTests(unittest.TestCase):
    def setUp(self):
        template_api._tasks.clear()
        self.user_id = "user-a"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temp_dir.name)
        self.registry = TemplateRegistry(storage_root=self.output_root / "templates")
        self.registry_patch = patch.object(
            template_api.template_registry,
            "template_registry",
            self.registry,
        )
        self.registry_patch.start()
        settings_store.init_db()
        self._ensure_test_user("user-a")
        self._ensure_test_user("user-b")

        def current_user():
            return {"id": self.user_id, "username": self.user_id, "display_name": self.user_id}

        app = FastAPI()
        app.include_router(template_api.router, prefix="/api")
        app.dependency_overrides[require_current_user] = current_user
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.registry_patch.stop()
        self.temp_dir.cleanup()
        template_api._tasks.clear()

    def _ensure_test_user(self, user_id: str) -> None:
        ensure_test_user(user_id, username=user_id, display_name=user_id)

    def importable_template(self, template_id: str = "user-doctor-intro") -> dict:
        value = json.loads(self.registry.export_template_json("user-a", "doctor-intro"))
        value.update(id=template_id, name="我的医生介绍", template_version=2)
        value["production"].update(default_batch_size=2, max_batch_size=2)
        return value

    def test_template_list_export_import_conflict_and_user_isolation(self):
        response = self.client.get("/api/template-production/templates")
        self.assertEqual(response.status_code, 200, response.text)
        templates = response.json()["templates"]
        self.assertEqual([item["id"] for item in templates[:2]], ["zhongyi-xunfang", "doctor-intro"])
        self.assertTrue(all(item["is_builtin"] for item in templates[:2]))
        self.assertTrue(
            all(item["runtime_capabilities"]["subtitle_replacements"] for item in templates)
        )

        response = self.client.get("/api/template-production/templates/zhongyi-xunfang/export")
        self.assertEqual(response.status_code, 200, response.text)
        exported = response.json()
        self.assertEqual(exported["id"], "zhongyi-xunfang")
        self.assertNotIn("runtime_capabilities", exported)
        self.assertIn("attachment", response.headers["content-disposition"])

        payload = json.dumps(self.importable_template(), ensure_ascii=False).encode("utf-8")
        response = self.client.post(
            "/api/template-production/templates/import",
            files={"file": ("template.json", payload, "application/json")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["template"]["id"], "user-doctor-intro")
        self.assertFalse(response.json()["template"]["is_builtin"])

        response = self.client.post(
            "/api/template-production/templates/import",
            files={"file": ("template.json", payload, "application/json")},
        )
        self.assertEqual(response.status_code, 409, response.text)

        self.user_id = "user-b"
        response = self.client.get("/api/template-production/templates/user-doctor-intro")
        self.assertEqual(response.status_code, 404, response.text)

    def test_import_rejects_unknown_pipeline_and_oversized_json(self):
        value = self.importable_template("unknown-pipeline-template")
        value["production"]["pipeline_id"] = "unregistered_v1"
        response = self.client.post(
            "/api/template-production/templates/import",
            files={"file": ("template.json", json.dumps(value).encode(), "application/json")},
        )
        self.assertEqual(response.status_code, 422, response.text)

        response = self.client.post(
            "/api/template-production/templates/import",
            files={"file": ("template.json", b" " * (128 * 1024 + 1), "application/json")},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_subtitle_replacement_crud_is_global_across_users(self):
        response = self.client.post(
            "/api/template-production/subtitle-replacements",
            json={"source": "医生", "replacement": "yi生"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        rule = response.json()["replacement"]

        response = self.client.post(
            "/api/template-production/subtitle-replacements",
            json={"source": "医生", "replacement": "医师"},
        )
        self.assertEqual(response.status_code, 409, response.text)

        self.user_id = "user-b"
        response = self.client.get("/api/template-production/subtitle-replacements")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["replacements"], [rule])

        response = self.client.put(
            f"/api/template-production/subtitle-replacements/{rule['id']}",
            json={"source": "名医", "replacement": "ming yi"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["replacement"]["source"], "名医")

        response = self.client.put(
            "/api/template-production/subtitle-replacements/999",
            json={"source": "missing", "replacement": "rule"},
        )
        self.assertEqual(response.status_code, 404, response.text)
        response = self.client.post(
            "/api/template-production/subtitle-replacements",
            json={"source": "same", "replacement": "same"},
        )
        self.assertEqual(response.status_code, 422, response.text)

        response = self.client.delete(f"/api/template-production/subtitle-replacements/{rule['id']}")
        self.assertEqual(response.status_code, 204, response.text)
        response = self.client.get("/api/template-production/subtitle-replacements")
        self.assertEqual(response.json()["replacements"], [])

    def test_imported_template_drives_task_pipeline_limits_and_snapshot(self):
        payload = json.dumps(self.importable_template(), ensure_ascii=False).encode("utf-8")
        response = self.client.post(
            "/api/template-production/templates/import",
            files={"file": ("template.json", payload, "application/json")},
        )
        self.assertEqual(response.status_code, 201, response.text)

        manifest = [
            {"requirement_id": "doctor-image", "file_index": 0, "media_type": "image", "name": "doctor.png"},
            {"requirement_id": "hospital-scene", "file_index": 1, "media_type": "video", "name": "hospital.mp4"},
        ]
        global_replacement = settings_store.create_subtitle_replacement(source="医生", replacement="yi生")
        run_task = AsyncMock(return_value=None)
        with patch.object(template_api, "resolve_output_dir", return_value=self.output_root), patch.object(
            template_api.template_production, "require_ffmpeg"
        ), patch.object(template_api, "_run_task", run_task):
            response = self.client.post(
                "/api/template-production/tasks",
                data={
                    "template_id": "user-doctor-intro",
                    "scripts": json.dumps(["这是一条足够长的用户模板测试文案。"], ensure_ascii=False),
                    "generate_count": "2",
                    "video_config": json.dumps({"ratio": "9:16"}),
                    "subtitle_replacements": json.dumps(
                        [{"source": "client-only", "replacement": "ignored"}],
                        ensure_ascii=False,
                    ),
                    "material_manifest": json.dumps(manifest),
                },
                files=[
                    ("materials", ("doctor.png", b"image", "image/png")),
                    ("materials", ("hospital.mp4", b"video", "video/mp4")),
                ],
            )
        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]
        stored = template_api._tasks[task_id]
        self.assertEqual(stored["pipeline_id"], "generic_concat_v1")
        self.assertEqual(stored["template_version"], 2)
        self.assertEqual(stored["_template_snapshot"]["id"], "user-doctor-intro")
        self.assertEqual(
            run_task.call_args.kwargs["subtitle_replacements"],
            [{"source": global_replacement["source"], "replacement": global_replacement["replacement"]}],
        )
        self.assertEqual(stored["_subtitle_replacements"], run_task.call_args.kwargs["subtitle_replacements"])

        response = self.client.get(f"/api/template-production/tasks/{task_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("_template_snapshot", response.json())

        with patch.object(template_api.template_production, "require_ffmpeg"):
            response = self.client.post(
                "/api/template-production/tasks",
                data={
                    "template_id": "user-doctor-intro",
                    "scripts": json.dumps(["这是一条足够长的用户模板测试文案。"], ensure_ascii=False),
                    "generate_count": "3",
                    "video_config": json.dumps({"ratio": "9:16"}),
                    "material_manifest": json.dumps(manifest),
                },
                files=[
                    ("materials", ("doctor.png", b"image", "image/png")),
                    ("materials", ("hospital.mp4", b"video", "video/mp4")),
                ],
            )
        self.assertEqual(response.status_code, 422, response.text)

    def test_script_generation(self):
        llm_result = json.dumps(
            ["这是第一条用于接口测试的医生介绍口播文案。", "这是第二条用于接口测试的医生介绍口播文案。"],
            ensure_ascii=False,
        )
        with patch.object(template_api.settings_store, "get_llm_settings", return_value={
            "base_url": "https://llm.example/v1",
            "api_key": "",
            "model": "test-model",
        }), patch.object(template_api.llm_service, "generate", AsyncMock(return_value=llm_result)):
            response = self.client.post(
                "/api/template-production/scripts/generate",
                json={
                    "template_id": "doctor-intro",
                    "variables": {
                        "doctor-name": "张医生",
                        "hospital": "示例医院",
                        "department": "心内科",
                        "specialty": "慢性病管理",
                    },
                    "count": 2,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["scripts"]), 2)

    def test_task_creation_polling_and_user_isolation(self):
        manifest = [
            {"requirement_id": "doctor-scene", "file_index": 0, "media_type": "video", "name": "doctor.mp4"},
            {"requirement_id": "clinic-scene", "file_index": 1, "media_type": "video", "name": "clinic.mp4"},
        ]
        files = [
            ("materials", ("doctor.mp4", b"video-one", "video/mp4")),
            ("materials", ("clinic.mp4", b"video-two", "video/mp4")),
        ]
        settings_store.create_subtitle_replacement(source="医生", replacement="yi生")
        run_task = AsyncMock(return_value=None)
        with patch.object(template_api, "resolve_output_dir", return_value=self.output_root), patch.object(
            template_api.template_production, "require_ffmpeg"
        ), patch.object(template_api, "_run_task", run_task):
            response = self.client.post(
                "/api/template-production/tasks",
                data={
                    "template_id": "zhongyi-xunfang",
                    "scripts": json.dumps(["这是一条足够长的模板量产接口测试文案。"], ensure_ascii=False),
                    "generate_count": "2",
                    "video_config": json.dumps({"ratio": "9:16"}),
                    "subtitle_replacements": json.dumps(
                        [{"source": "医生", "replacement": "yi生"}],
                        ensure_ascii=False,
                    ),
                    "material_manifest": json.dumps(manifest, ensure_ascii=False),
                },
                files=files,
            )

        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]
        persisted_task = task_store.get_task(task_id, "user-a")
        self.assertEqual(persisted_task["task_type"], task_store.TASK_TYPE_TEMPLATE)
        self.assertEqual(persisted_task["generation_type"], "video")
        self.assertEqual(persisted_task["requested_count"], 2)
        self.assertEqual(persisted_task["extra_info"]["pipeline_id"], "zhongyi_visit_v1")
        response = self.client.get(f"/api/template-production/tasks/{task_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 2)
        self.assertEqual(
            {item["script"] for item in response.json()["items"]},
            {"这是一条足够长的模板量产接口测试文案。"},
        )
        self.assertEqual(
            run_task.call_args.kwargs["subtitle_replacements"],
            [{"source": "医生", "replacement": "yi生"}],
        )

        self.user_id = "user-b"
        response = self.client.get(f"/api/template-production/tasks/{task_id}")
        self.assertEqual(response.status_code, 404)

    def test_task_uses_global_subtitle_replacements_instead_of_form_values(self):
        manifest = [
            {"requirement_id": "doctor-scene", "file_index": 0, "media_type": "video", "name": "doctor.mp4"},
            {"requirement_id": "clinic-scene", "file_index": 1, "media_type": "video", "name": "clinic.mp4"},
        ]
        settings_store.create_subtitle_replacement(source="医生", replacement="yi生")
        run_task = AsyncMock(return_value=None)
        with patch.object(template_api, "resolve_output_dir", return_value=self.output_root), patch.object(
            template_api.template_production, "require_ffmpeg"
        ), patch.object(template_api, "_run_task", run_task):
            response = self.client.post(
                "/api/template-production/tasks",
                data={
                    "template_id": "zhongyi-xunfang",
                    "scripts": json.dumps(["这是一条足够长的模板量产接口测试文案。"], ensure_ascii=False),
                    "generate_count": "1",
                    "video_config": json.dumps({"ratio": "9:16"}),
                    "subtitle_replacements": json.dumps(
                        [
                            {"source": "client", "replacement": "one"},
                            {"source": "client", "replacement": "two"},
                        ],
                        ensure_ascii=False,
                    ),
                    "material_manifest": json.dumps(manifest, ensure_ascii=False),
                },
                files=[
                    ("materials", ("doctor.mp4", b"video-one", "video/mp4")),
                    ("materials", ("clinic.mp4", b"video-two", "video/mp4")),
                ],
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            run_task.call_args.kwargs["subtitle_replacements"],
            [{"source": "医生", "replacement": "yi生"}],
        )

    def test_task_captures_and_passes_subtitle_style(self):
        manifest = [
            {"requirement_id": "doctor-scene", "file_index": 0, "media_type": "video", "name": "doctor.mp4"},
            {"requirement_id": "clinic-scene", "file_index": 1, "media_type": "video", "name": "clinic.mp4"},
        ]
        requested_style = {
            "font_family": "SimHei",
            "font_size": 72,
            "color": "#123456",
            "outline_width": 3,
            "alignment": "left",
            "notice_enabled": False,
        }
        run_task = AsyncMock(return_value=None)
        with patch.object(template_api, "resolve_output_dir", return_value=self.output_root), patch.object(
            template_api.template_production, "require_ffmpeg"
        ), patch.object(template_api, "_run_task", run_task):
            response = self.client.post(
                "/api/template-production/tasks",
                data={
                    "template_id": "zhongyi-xunfang",
                    "scripts": json.dumps(["这是一条用于验证字幕样式配置传递的模板量产测试文案。"], ensure_ascii=False),
                    "generate_count": "1",
                    "video_config": json.dumps({"ratio": "16:9", "subtitle_style": requested_style}),
                    "material_manifest": json.dumps(manifest, ensure_ascii=False),
                },
                files=[
                    ("materials", ("doctor.mp4", b"video-one", "video/mp4")),
                    ("materials", ("clinic.mp4", b"video-two", "video/mp4")),
                ],
            )

        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]
        expected_style = template_api.template_production.normalize_subtitle_style(requested_style)
        self.assertEqual(template_api._tasks[task_id]["_subtitle_style"], expected_style)
        self.assertEqual(run_task.call_args.kwargs["subtitle_style"], expected_style)
        self.assertEqual(
            run_task.call_args.kwargs["ratio"],
            template_api.template_production.DEFAULT_VIDEO_RATIO,
        )

    def test_task_rejects_non_object_subtitle_style(self):
        manifest = [
            {"requirement_id": "doctor-scene", "file_index": 0, "media_type": "video", "name": "doctor.mp4"},
            {"requirement_id": "clinic-scene", "file_index": 1, "media_type": "video", "name": "clinic.mp4"},
        ]
        with patch.object(template_api.template_production, "require_ffmpeg"):
            response = self.client.post(
                "/api/template-production/tasks",
                data={
                    "template_id": "zhongyi-xunfang",
                    "scripts": json.dumps(["这是一条用于验证字幕样式参数校验的模板量产测试文案。"], ensure_ascii=False),
                    "generate_count": "1",
                    "video_config": json.dumps({"ratio": "9:16", "subtitle_style": "invalid"}),
                    "material_manifest": json.dumps(manifest, ensure_ascii=False),
                },
                files=[
                    ("materials", ("doctor.mp4", b"video-one", "video/mp4")),
                    ("materials", ("clinic.mp4", b"video-two", "video/mp4")),
                ],
            )

        self.assertEqual(response.status_code, 422, response.text)

    def test_run_task_keeps_tts_text_original_and_passes_subtitle_replacements(self):
        task_id = "subtitle-replacement-task"
        task_dir = self.output_root / task_id
        output_dir = task_dir / "output"
        temp_dir = task_dir / "temp"
        output_dir.mkdir(parents=True)
        temp_dir.mkdir(parents=True)
        original_script = "医生介绍医生"
        replacements = [{"source": "医生", "replacement": "yi生"}]
        template_api._tasks[task_id] = {
            "template_id": template_api.template_production.ZHONGYI_TEMPLATE_ID,
            "status": "pending",
            "progress": 0,
            "message": "等待生成",
            "items": [
                {
                    "id": "item-1",
                    "index": 1,
                    "script": original_script,
                    "status": "pending",
                    "message": "等待生成",
                    "video_url": None,
                    "error": None,
                }
            ],
            "zip_url": None,
            "error": None,
        }

        synthesize = AsyncMock(return_value=SimpleNamespace(duration=1.0, timings=()))

        def compose_video(_materials, _audio_path, output_path, **_kwargs):
            output_path.write_bytes(b"video")

        with patch.object(template_api.tts_service, "synthesize", synthesize), patch.object(
            template_api.template_production,
            "compose_zhongyi_video",
            side_effect=compose_video,
        ) as compose, patch.object(template_api, "_public_output_url", return_value="/output/test"):
            asyncio.run(
                template_api._run_task(
                    task_id=task_id,
                    task_dir=task_dir,
                    output_dir=output_dir,
                    temp_dir=temp_dir,
                    materials=[],
                    ratio="9:16",
                    subtitle_replacements=replacements,
                )
            )

        tts_request = synthesize.await_args.args[1]
        self.assertEqual(tts_request.text, template_api.template_production.script_text_for_tts(original_script))
        self.assertIn("医生", tts_request.text)
        self.assertNotIn("yi生", tts_request.text)
        self.assertEqual(compose.call_args.kwargs["script"], original_script)
        self.assertEqual(compose.call_args.kwargs["subtitle_replacements"], replacements)
        self.assertIsNone(compose.call_args.kwargs["subtitle_style"])

    def test_template_tts_request_uses_fixed_yunjian_voice(self):
        request = template_api._template_tts_request("固定配音测试")

        self.assertEqual(request.voice_id, "zh-CN-YunjianNeural")
        self.assertEqual(request.speed, 1.0)
        self.assertEqual(request.volume, 100)

    def test_zhongyi_script_generation_returns_candidates_without_validating_them(self):
        candidate_result = json.dumps(
            {"scripts": [{"style": "寻访过程", "sentences": ["这是一条可以解析但结构偏短的候选文案"]}]},
            ensure_ascii=False,
        )
        generate = AsyncMock(return_value=candidate_result)
        with patch.object(
            template_api.settings_store,
            "get_llm_settings",
            return_value={"base_url": "https://llm.example/v1", "api_key": "", "model": "test-model"},
        ), patch.object(template_api.llm_service, "generate", generate):
            response = self.client.post(
                "/api/template-production/scripts/generate",
                json={
                    "template_id": "zhongyi-xunfang",
                    "variables": {
                        "address": "湖北阳新老街",
                        "name": "马医生",
                        "specialty": "痛风调理",
                        "feature": "三代中医世家",
                    },
                    "count": 1,
                    "material_context": {"doctor-scene": 2, "clinic-scene": 1},
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(generate.await_count, 1)
        self.assertEqual(len(response.json()["scripts"]), 1)
        self.assertNotIn("warnings", response.json())

    def test_zhongyi_task_rejects_material_groups_outside_original_template(self):
        manifest = [
            {"requirement_id": "presenter-scene", "file_index": 0, "media_type": "video", "name": "presenter.mp4"},
        ]
        with patch.object(template_api.template_production, "require_ffmpeg"):
            response = self.client.post(
                "/api/template-production/tasks",
                data={
                    "template_id": "zhongyi-xunfang",
                    "scripts": json.dumps(["这是一条足够长的模板量产接口测试文案。"], ensure_ascii=False),
                    "generate_count": "1",
                    "video_config": json.dumps({"ratio": "9:16"}),
                    "material_manifest": json.dumps(manifest),
                },
                files=[("materials", ("presenter.mp4", b"video", "video/mp4"))],
            )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("presenter-scene", response.json()["detail"])

    def test_single_candidate_rewrite_only_returns_one_script(self):
        rewritten_sentences = ["重新创作后的候选文案内容真实自然" for _ in range(15)]
        rewritten_result = json.dumps(
            {"scripts": [{"style": "寻访过程", "sentences": rewritten_sentences}]},
            ensure_ascii=False,
        )
        generate = AsyncMock(return_value=rewritten_result)
        with patch.object(
            template_api.settings_store,
            "get_llm_settings",
            return_value={"base_url": "https://llm.example/v1", "api_key": "", "model": "test-model"},
        ), patch.object(template_api.llm_service, "generate", generate):
            response = self.client.post(
                "/api/template-production/scripts/rewrite",
                json={
                    "template_id": "zhongyi-xunfang",
                    "variables": {
                        "address": "湖北阳新老街",
                        "name": "马医生",
                        "specialty": "痛风调理",
                        "feature": "三代中医世家",
                    },
                    "original_script": "这是需要单独重写的当前候选文案，内容需要换一个表达角度。",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["script"])
        self.assertEqual(generate.await_count, 1)
        messages = generate.await_args.args[1]
        self.assertIn("当前候选", messages[1].content)

    def test_bgm_upload_list_delete_and_user_isolation(self):
        with patch.object(template_api, "resolve_output_dir", return_value=self.output_root), \
             patch.object(template_api.template_production, "probe_duration", return_value=12.5):
            response = self.client.post(
                "/api/template-production/bgm",
                files={"file": ("my-song.mp3", b"audio-bytes", "audio/mpeg")},
            )
        self.assertEqual(response.status_code, 201, response.text)
        track = response.json()["bgm_track"]
        self.assertEqual(track["name"], "my-song.mp3")
        self.assertEqual(track["duration"], 12.5)
        self.assertEqual(track["file_size"], len(b"audio-bytes"))
        self.assertRegex(track["preview_url"], rf"^/api/template-production/bgm/{re.escape(track['id'])}/audio$")
        track_id = track["id"]

        stored_track = settings_store.get_bgm_track("user-a", track_id)
        persisted = self.output_root / stored_track["relative_path"]
        self.assertTrue(persisted.exists())

        response = self.client.get("/api/template-production/bgm")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["bgm_tracks"]), 1)
        self.assertEqual(response.json()["bgm_tracks"][0]["id"], track_id)

        self.user_id = "user-b"
        response = self.client.get("/api/template-production/bgm")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["bgm_tracks"], [])

        response = self.client.delete(f"/api/template-production/bgm/{track_id}")
        self.assertEqual(response.status_code, 404, response.text)

        self.user_id = "user-a"
        with patch.object(template_api, "resolve_output_dir", return_value=self.output_root):
            response = self.client.delete(f"/api/template-production/bgm/{track_id}")
        self.assertEqual(response.status_code, 204, response.text)
        self.assertFalse(persisted.exists())

        response = self.client.get("/api/template-production/bgm")
        self.assertEqual(response.json()["bgm_tracks"], [])

    def test_bgm_upload_rejects_unsupported_extension(self):
        response = self.client.post(
            "/api/template-production/bgm",
            files={"file": ("song.txt", b"text", "text/plain")},
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("格式", response.json()["detail"])

    def test_bgm_upload_rejects_oversized_file(self):
        with patch.object(template_api, "MAX_BGM_FILE_SIZE", 10):
            response = self.client.post(
                "/api/template-production/bgm",
                files={"file": ("big.mp3", b"x" * 11, "audio/mpeg")},
            )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("不能超过", response.json()["detail"])

    def test_bgm_upload_cleans_up_file_when_db_limit_reached(self):
        with patch.object(template_api, "resolve_output_dir", return_value=self.output_root), \
             patch.object(template_api.template_production, "probe_duration", return_value=1.0):
            for i in range(settings_store.MAX_BGM_TRACKS_PER_USER):
                resp = self.client.post(
                    "/api/template-production/bgm",
                    files={"file": (f"song-{i}.mp3", b"audio", "audio/mpeg")},
                )
                self.assertEqual(resp.status_code, 201, resp.text)

        overflow_dir = self.output_root / "bgm" / self.user_id
        before_count = len(list(overflow_dir.glob("*.mp3")))
        self.assertEqual(before_count, settings_store.MAX_BGM_TRACKS_PER_USER)

        with patch.object(template_api, "resolve_output_dir", return_value=self.output_root), \
             patch.object(template_api.template_production, "probe_duration", return_value=1.0):
            response = self.client.post(
                "/api/template-production/bgm",
                files={"file": ("overflow.mp3", b"audio", "audio/mpeg")},
            )
        self.assertEqual(response.status_code, 422, response.text)
        after_count = len(list(overflow_dir.glob("*.mp3")))
        self.assertEqual(after_count, before_count)

    def test_task_creation_with_bgm_stores_and_passes_bgm_path(self):
        with patch.object(template_api, "resolve_output_dir", return_value=self.output_root), \
             patch.object(template_api.template_production, "probe_duration", return_value=10.0):
            response = self.client.post(
                "/api/template-production/bgm",
                files={"file": ("bgm.mp3", b"audio", "audio/mpeg")},
            )
        self.assertEqual(response.status_code, 201, response.text)
        bgm_id = response.json()["bgm_track"]["id"]
        expected_bgm_path = self.output_root / f"bgm/{self.user_id}/{bgm_id}.mp3"

        manifest = [
            {"requirement_id": "doctor-scene", "file_index": 0, "media_type": "video", "name": "doctor.mp4"},
            {"requirement_id": "clinic-scene", "file_index": 1, "media_type": "video", "name": "clinic.mp4"},
        ]
        run_task = AsyncMock(return_value=None)
        with patch.object(template_api, "resolve_output_dir", return_value=self.output_root), \
             patch.object(template_api.template_production, "require_ffmpeg"), \
             patch.object(template_api, "_run_task", run_task):
            response = self.client.post(
                "/api/template-production/tasks",
                data={
                    "template_id": "zhongyi-xunfang",
                    "scripts": json.dumps(["这是一条足够长的模板量产BGM测试文案。"], ensure_ascii=False),
                    "generate_count": "1",
                    "video_config": json.dumps({"ratio": "9:16"}),
                    "material_manifest": json.dumps(manifest),
                    "bgm_id": bgm_id,
                },
                files=[
                    ("materials", ("doctor.mp4", b"video-one", "video/mp4")),
                    ("materials", ("clinic.mp4", b"video-two", "video/mp4")),
                ],
            )
        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]
        self.assertEqual(template_api._tasks[task_id]["_bgm_path"], expected_bgm_path)
        self.assertEqual(template_api._tasks[task_id]["bgm_name"], "bgm.mp3")
        self.assertEqual(run_task.call_args.kwargs["bgm_path"], expected_bgm_path)

    def test_task_creation_rejects_unknown_bgm_id(self):
        manifest = [
            {"requirement_id": "doctor-scene", "file_index": 0, "media_type": "video", "name": "doctor.mp4"},
            {"requirement_id": "clinic-scene", "file_index": 1, "media_type": "video", "name": "clinic.mp4"},
        ]
        with patch.object(template_api, "resolve_output_dir", return_value=self.output_root), \
             patch.object(template_api.template_production, "require_ffmpeg"):
            response = self.client.post(
                "/api/template-production/tasks",
                data={
                    "template_id": "zhongyi-xunfang",
                    "scripts": json.dumps(["这是一条足够长的模板量产BGM测试文案。"], ensure_ascii=False),
                    "generate_count": "1",
                    "video_config": json.dumps({"ratio": "9:16"}),
                    "material_manifest": json.dumps(manifest),
                    "bgm_id": "nonexistent-bgm-id",
                },
                files=[
                    ("materials", ("doctor.mp4", b"video-one", "video/mp4")),
                    ("materials", ("clinic.mp4", b"video-two", "video/mp4")),
                ],
            )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("背景音乐", response.json()["detail"])

    def test_task_creation_rejects_bgm_with_missing_file(self):
        settings_store.create_bgm_track(
            user_id=self.user_id,
            bgm_id="orphan-bgm",
            name="orphan.mp3",
            relative_path=f"bgm/{self.user_id}/orphan.mp3",
            duration=5.0,
            file_size=100,
        )

        manifest = [
            {"requirement_id": "doctor-scene", "file_index": 0, "media_type": "video", "name": "doctor.mp4"},
            {"requirement_id": "clinic-scene", "file_index": 1, "media_type": "video", "name": "clinic.mp4"},
        ]
        with patch.object(template_api, "resolve_output_dir", return_value=self.output_root), \
             patch.object(template_api.template_production, "require_ffmpeg"):
            response = self.client.post(
                "/api/template-production/tasks",
                data={
                    "template_id": "zhongyi-xunfang",
                    "scripts": json.dumps(["这是一条足够长的模板量产BGM测试文案。"], ensure_ascii=False),
                    "generate_count": "1",
                    "video_config": json.dumps({"ratio": "9:16"}),
                    "material_manifest": json.dumps(manifest),
                    "bgm_id": "orphan-bgm",
                },
                files=[
                    ("materials", ("doctor.mp4", b"video-one", "video/mp4")),
                    ("materials", ("clinic.mp4", b"video-two", "video/mp4")),
                ],
            )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("不存在", response.json()["detail"])

    def test_run_task_passes_bgm_path_to_compose(self):
        task_id = "bgm-compose-task"
        task_dir = self.output_root / task_id
        output_dir = task_dir / "output"
        temp_dir = task_dir / "temp"
        output_dir.mkdir(parents=True)
        temp_dir.mkdir(parents=True)
        bgm_path = self.output_root / "test_bgm.mp3"
        bgm_path.write_bytes(b"bgm-audio")

        template_api._tasks[task_id] = {
            "template_id": "doctor-intro",
            "status": "pending",
            "progress": 0,
            "message": "等待生成",
            "items": [
                {
                    "id": "item-1",
                    "index": 1,
                    "script": "这是一条用于测试BGM合成的视频文案。",
                    "status": "pending",
                    "message": "等待生成",
                    "video_url": None,
                    "error": None,
                }
            ],
            "zip_url": None,
            "error": None,
        }

        synthesize = AsyncMock(return_value=SimpleNamespace(duration=1.0, timings=()))

        def compose_video(_segments, _audio_path, output_path, **_kwargs):
            output_path.write_bytes(b"video")

        with patch.object(template_api.tts_service, "synthesize", synthesize), \
             patch.object(template_api.template_production, "compose_video", side_effect=compose_video) as compose, \
             patch.object(template_api.template_production, "prepare_material_segment"), \
             patch.object(template_api, "_public_output_url", return_value="/output/test"):
            asyncio.run(
                template_api._run_task(
                    task_id=task_id,
                    task_dir=task_dir,
                    output_dir=output_dir,
                    temp_dir=temp_dir,
                    materials=[],
                    ratio="9:16",
                    subtitle_replacements=[],
                    bgm_path=bgm_path,
                )
            )

        self.assertEqual(compose.call_args.kwargs["bgm_path"], bgm_path)

    def test_run_task_without_bgm_passes_none_to_compose(self):
        task_id = "no-bgm-compose-task"
        task_dir = self.output_root / task_id
        output_dir = task_dir / "output"
        temp_dir = task_dir / "temp"
        output_dir.mkdir(parents=True)
        temp_dir.mkdir(parents=True)

        template_api._tasks[task_id] = {
            "template_id": "doctor-intro",
            "status": "pending",
            "progress": 0,
            "message": "等待生成",
            "items": [
                {
                    "id": "item-1",
                    "index": 1,
                    "script": "这是一条用于测试无BGM合成的视频文案。",
                    "status": "pending",
                    "message": "等待生成",
                    "video_url": None,
                    "error": None,
                }
            ],
            "zip_url": None,
            "error": None,
        }

        synthesize = AsyncMock(return_value=SimpleNamespace(duration=1.0, timings=()))

        def compose_video(_segments, _audio_path, output_path, **_kwargs):
            output_path.write_bytes(b"video")

        with patch.object(template_api.tts_service, "synthesize", synthesize), \
             patch.object(template_api.template_production, "compose_video", side_effect=compose_video) as compose, \
             patch.object(template_api.template_production, "prepare_material_segment"), \
             patch.object(template_api, "_public_output_url", return_value="/output/test"):
            asyncio.run(
                template_api._run_task(
                    task_id=task_id,
                    task_dir=task_dir,
                    output_dir=output_dir,
                    temp_dir=temp_dir,
                    materials=[],
                    ratio="9:16",
                    subtitle_replacements=[],
                    bgm_path=None,
                )
            )

        self.assertIsNone(compose.call_args.kwargs["bgm_path"])


if __name__ == "__main__":
    unittest.main()
