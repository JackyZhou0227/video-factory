from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import digital_human, tts_studio
from app.api.auth import require_current_user
from app.services.tts import EDGE_TTS_MODEL


class TTSStudioApiTests(unittest.TestCase):
    def setUp(self):
        self.user_id = "user-a"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temp_dir.name) / "output"
        self.output_root.mkdir()
        self.voice_root_patch = patch.object(
            tts_studio.voice_profiles,
            "_root",
            return_value=Path(self.temp_dir.name),
        )
        self.voice_root_patch.start()

        app = FastAPI()
        app.include_router(tts_studio.router, prefix="/api")
        app.dependency_overrides[require_current_user] = self._current_user
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.voice_root_patch.stop()
        self.temp_dir.cleanup()

    def _current_user(self):
        return {"id": self.user_id, "username": self.user_id, "display_name": self.user_id}

    def test_edge_tts_lists_voices_and_generates_original_speed_mp3(self):
        edge_voice = {
            "id": "zh-CN-XiaoxiaoNeural",
            "name": "晓晓",
            "gender": "female",
            "description": "温暖自然",
        }

        async def write_audio(model_name, request, output_path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"edge audio")
            return SimpleNamespace(
                output_path=output_path,
                duration=1.0,
                model_name=model_name,
                voice_id=request.voice_id,
                timings=(),
            )

        synthesize = AsyncMock(side_effect=write_audio)
        with patch.object(tts_studio, "resolve_output_dir", return_value=self.output_root), patch.object(
            tts_studio.tts_service,
            "list_voices",
            return_value=[edge_voice],
        ), patch.object(tts_studio.tts_service, "synthesize", synthesize):
            voices_response = self.client.get("/api/tts-studio/edge-tts/voices")
            response = self.client.post(
                "/api/tts-studio/edge-tts/preview",
                data={
                    "text": "Edge TTS preview.",
                    "voice_id": edge_voice["id"],
                    "speech_rate": "1.4",
                },
            )

        self.assertEqual(voices_response.status_code, 200, voices_response.text)
        self.assertEqual(voices_response.json(), [edge_voice])
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertRegex(
            payload["audio_url"],
            rf"^/output/tts-studio/{re.escape(self.user_id)}/[0-9a-f]+/preview_original[.]mp3$",
        )
        self.assertEqual(payload["original_audio_url"], payload["audio_url"])
        self.assertIsNone(payload["adjusted_audio_url"])
        self.assertEqual(payload["tts_mode"], "edge-tts")

        call = synthesize.await_args
        model_name = call.kwargs["model_name"] if "model_name" in call.kwargs else call.args[0]
        request = call.kwargs["request"] if "request" in call.kwargs else call.args[1]
        output_path = call.kwargs["output_path"] if "output_path" in call.kwargs else call.args[2]
        self.assertEqual(model_name, EDGE_TTS_MODEL)
        self.assertEqual(request.voice_id, edge_voice["id"])
        self.assertEqual(request.speed, 1.0)
        self.assertEqual(output_path.suffix, ".mp3")

    def test_provider_status_endpoint_returns_tts_availability(self):
        provider_statuses = [
            {
                "id": "edge_tts",
                "model_name": "Edge-TTS",
                "display_name": "预设音色",
                "runtime": "cloud",
                "enabled": True,
                "available": True,
                "status": "available",
                "reason": None,
                "validation": "deferred_network",
                "checks": {"configuration": "passed", "network": "deferred"},
            }
        ]
        with patch.object(tts_studio.tts_service, "provider_statuses", return_value=provider_statuses) as statuses:
            response = self.client.get("/api/tts-studio/providers")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), provider_statuses)
        statuses.assert_called_once_with()

    def test_speech_rate_variant_keeps_original_audio_and_returns_separate_adjusted_audio(self):
        original_path = self.output_root / "tts-studio" / self.user_id / "preview" / "preview_original.wav"
        original_path.parent.mkdir(parents=True, exist_ok=True)
        original_path.write_bytes(b"original audio")
        adjusted_path = original_path.with_name("preview_1_2x.wav")

        with patch.object(tts_studio, "resolve_output_dir", return_value=self.output_root), patch.object(
            tts_studio, "_create_speech_rate_variant", return_value=adjusted_path
        ):
            response = self.client.post(
                "/api/tts-studio/preview/speech-rate",
                data={
                    "audio_url": "/output/tts-studio/user-a/preview/preview_original.wav",
                    "speech_rate": "1.2",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["original_audio_url"], "/output/tts-studio/user-a/preview/preview_original.wav")
        self.assertEqual(payload["adjusted_audio_url"], "/output/tts-studio/user-a/preview/preview_1_2x.wav")
        self.assertNotEqual(payload["original_audio_url"], payload["adjusted_audio_url"])
        self.assertTrue(original_path.is_file())

    def test_speech_rate_rejects_slowdown_below_normal_speed(self):
        original_path = self.output_root / "tts-studio" / self.user_id / "preview" / "preview_original.wav"
        original_path.parent.mkdir(parents=True, exist_ok=True)
        original_path.write_bytes(b"original audio")

        with patch.object(tts_studio, "resolve_output_dir", return_value=self.output_root):
            response = self.client.post(
                "/api/tts-studio/preview/speech-rate",
                data={
                    "audio_url": "/output/tts-studio/user-a/preview/preview_original.wav",
                    "speech_rate": "0.9",
                },
            )

        self.assertEqual(response.status_code, 422, response.text)

    def test_speech_rate_rejects_digital_human_and_foreign_user_audio_paths(self):
        digital_human_path = self.output_root / "tts" / "legacy-preview" / "preview_original.wav"
        other_user_path = self.output_root / "tts-studio" / "user-b" / "foreign-preview" / "preview_original.wav"
        for audio_path in (digital_human_path, other_user_path):
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            audio_path.write_bytes(b"audio")

        with patch.object(tts_studio, "resolve_output_dir", return_value=self.output_root):
            for audio_path in (digital_human_path, other_user_path):
                audio_url = f"/output/{audio_path.relative_to(self.output_root).as_posix()}"
                response = self.client.post(
                    "/api/tts-studio/preview/speech-rate",
                    data={"audio_url": audio_url, "speech_rate": "1.2"},
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_tts_studio_routes_do_not_replace_digital_human_video_generation(self):
        app = FastAPI()
        app.include_router(digital_human.router, prefix="/api")
        app.include_router(tts_studio.router, prefix="/api")
        app.dependency_overrides[require_current_user] = self._current_user

        route_methods = app.openapi()["paths"]
        self.assertIn("/api/tts-studio/providers", route_methods)
        self.assertIn("/api/tts-studio/edge-tts/voices", route_methods)
        self.assertIn("/api/tts-studio/edge-tts/preview", route_methods)
        self.assertIn("post", route_methods["/api/tts-studio/edge-tts/preview"])
        self.assertIn("/api/generate-video", route_methods)
        self.assertIn("post", route_methods["/api/generate-video"])
        self.assertNotIn("/api/tts-studio/generate-video", route_methods)
        for legacy_path in (
            "/api/tts/languages",
            "/api/tts/preview/speech-rate",
            "/api/tts/voice-clone/preview",
            "/api/voice-profiles",
            "/api/voice-profiles/{voice_profile_id}/audio",
        ):
            self.assertNotIn(legacy_path, route_methods)

        with TestClient(app) as client:
            response = client.post("/api/generate-video")
        self.assertEqual(response.status_code, 422, response.text)

    def test_voice_profile_crud_uses_the_shared_voice_profile_library(self):
        reference_audio = b"reference audio"
        response = self.client.post(
            "/api/tts-studio/voice-profiles",
            data={
                "name": "Shared voice",
                "language": "English",
                "ref_text": "Original reference text",
            },
            files={"ref_audio": ("reference.wav", reference_audio, "audio/wav")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        profile = response.json()

        index_path = Path(self.temp_dir.name) / "data" / "voice_profiles" / "index.json"
        self.assertTrue(index_path.is_file())
        self.assertFalse((Path(self.temp_dir.name) / "data" / "tts_studio_voice_profiles").exists())
        stored_profiles = json.loads(index_path.read_text(encoding="utf-8"))["voices"]
        self.assertEqual([item["id"] for item in stored_profiles], [profile["id"]])
        self.assertEqual(stored_profiles[0]["name"], "Shared voice")
        self.assertEqual(stored_profiles[0]["ref_text"], "Original reference text")

        response = self.client.get("/api/tts-studio/voice-profiles")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["id"] for item in response.json()], [profile["id"]])

        self.user_id = "user-b"
        response = self.client.get("/api/tts-studio/voice-profiles")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["id"] for item in response.json()], [profile["id"]])

        self.user_id = "user-a"
        response = self.client.get(f"/api/tts-studio/voice-profiles/{profile['id']}/audio")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, reference_audio)

        response = self.client.put(
            f"/api/tts-studio/voice-profiles/{profile['id']}",
            data={
                "name": "Updated voice",
                "language": "Chinese",
                "ref_text": "Updated reference text",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "Updated voice")
        self.assertEqual(response.json()["ref_text"], "Updated reference text")

        response = self.client.delete(f"/api/tts-studio/voice-profiles/{profile['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"deleted": True})
        response = self.client.get("/api/tts-studio/voice-profiles")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    def test_existing_profile_is_available_for_clone_without_migration(self):
        voice_id = "be551487b21e49be8cc13da0c5a97694"
        voice_dir = Path(self.temp_dir.name) / "data" / "voice_profiles" / voice_id
        voice_dir.mkdir(parents=True)
        reference_path = voice_dir / "reference.mp3"
        reference_path.write_bytes(b"legacy reference")
        index_path = Path(self.temp_dir.name) / "data" / "voice_profiles" / "index.json"
        index_path.write_text(
            json.dumps(
                {
                    "voices": [
                        {
                            "id": voice_id,
                            "name": "Legacy voice",
                            "language": "Chinese",
                            "ref_text": "Legacy reference text",
                            "audio_filename": reference_path.name,
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        response = self.client.get("/api/tts-studio/voice-profiles")
        self.assertEqual(response.status_code, 200, response.text)
        profile = response.json()[0]
        self.assertEqual(profile["id"], voice_id)
        self.assertEqual(profile["audio_url"], f"/api/tts-studio/voice-profiles/{voice_id}/audio")
        self.assertEqual(self.client.get(profile["audio_url"]).content, b"legacy reference")

        async def write_audio(model_name, request, output_path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"generated")
            return SimpleNamespace(output_path=output_path, duration=0, model_name=model_name, voice_id=None, timings=())

        with patch.object(tts_studio, "resolve_output_dir", return_value=self.output_root), patch.object(
            tts_studio.tts_service, "synthesize", new=AsyncMock(side_effect=write_audio)
        ) as synthesize:
            response = self.client.post(
                "/api/tts-studio/voice-clone/preview",
                data={"text": "Use the shared voice", "voice_profile_id": voice_id, "language": "Chinese"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        request = synthesize.await_args.args[1]
        self.assertEqual(request.reference_audio, reference_path)
        self.assertEqual(request.reference_text, "Legacy reference text")


if __name__ == "__main__":
    unittest.main()
