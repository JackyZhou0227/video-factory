from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import template_production as template_api
from app.api.auth import require_current_user


class TemplateProductionApiTests(unittest.TestCase):
    def setUp(self):
        template_api._tasks.clear()
        self.user_id = "user-a"

        def current_user():
            return {"id": self.user_id, "username": self.user_id, "display_name": self.user_id}

        app = FastAPI()
        app.include_router(template_api.router, prefix="/api")
        app.dependency_overrides[require_current_user] = current_user
        self.client = TestClient(app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.client.close()
        self.temp_dir.cleanup()
        template_api._tasks.clear()

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

    def test_task_rejects_duplicate_subtitle_replacement_sources(self):
        manifest = [
            {"requirement_id": "doctor-scene", "file_index": 0, "media_type": "video", "name": "doctor.mp4"},
            {"requirement_id": "clinic-scene", "file_index": 1, "media_type": "video", "name": "clinic.mp4"},
        ]
        replacements = [
            {"source": "医生", "replacement": "yi生"},
            {"source": "医生", "replacement": "医师"},
        ]
        with patch.object(template_api.template_production, "require_ffmpeg"):
            response = self.client.post(
                "/api/template-production/tasks",
                data={
                    "template_id": "zhongyi-xunfang",
                    "scripts": json.dumps(["这是一条足够长的模板量产接口测试文案。"], ensure_ascii=False),
                    "generate_count": "1",
                    "video_config": json.dumps({"ratio": "9:16"}),
                    "subtitle_replacements": json.dumps(replacements, ensure_ascii=False),
                    "material_manifest": json.dumps(manifest, ensure_ascii=False),
                },
                files=[
                    ("materials", ("doctor.mp4", b"video-one", "video/mp4")),
                    ("materials", ("clinic.mp4", b"video-two", "video/mp4")),
                ],
            )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("重复添加", response.json()["detail"])

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


if __name__ == "__main__":
    unittest.main()
