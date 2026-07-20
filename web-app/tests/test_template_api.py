from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
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

    def test_voices_and_script_generation(self):
        response = self.client.get("/api/template-production/tts/voices")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model_name"], "Edge-TTS")

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
        with patch.object(template_api, "resolve_output_dir", return_value=self.output_root), patch.object(
            template_api, "_run_task", AsyncMock(return_value=None)
        ):
            response = self.client.post(
                "/api/template-production/tasks",
                data={
                    "template_id": "zhongyi-xunfang",
                    "scripts": json.dumps(["这是一条足够长的模板量产接口测试文案。"], ensure_ascii=False),
                    "generate_count": "2",
                    "tts_config": json.dumps({"voice_id": "zh-CN-XiaoxiaoNeural", "speed": 1, "volume": 80}),
                    "video_config": json.dumps({"ratio": "9:16"}),
                    "material_manifest": json.dumps(manifest, ensure_ascii=False),
                },
                files=files,
            )

        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]
        response = self.client.get(f"/api/template-production/tasks/{task_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 2)

        self.user_id = "user-b"
        response = self.client.get(f"/api/template-production/tasks/{task_id}")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
