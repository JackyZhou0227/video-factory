from __future__ import annotations

import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import digital_human, tts_studio
from app.api.auth import require_current_user
from app.db.models import VoiceProfile
from app.services.tts import EDGE_TTS_MODEL
from app.services import poster_video, settings_store, task_store
from tests.pg_test_utils import ensure_test_user


class TTSStudioSpeedTests(unittest.TestCase):
    def test_variant_reuses_tempo_builder_and_preserves_original(self):
        ffmpeg = poster_video.ffmpeg_executable()
        if ffmpeg is None:
            self.skipTest("FFmpeg is not installed")
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "preview_original.wav"
            subprocess.run(
                [ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.2", str(original)],
                check=True, capture_output=True,
            )
            original_bytes = original.read_bytes()
            with patch.object(
                poster_video, "build_atempo_filter", wraps=poster_video.build_atempo_filter
            ) as tempo:
                adjusted = tts_studio._create_speech_rate_variant(original, 1.2)
            self.assertEqual(original.read_bytes(), original_bytes)
            self.assertEqual(adjusted.name, "preview_1_2x.wav")
            self.assertAlmostEqual(poster_video.probe_audio_duration(adjusted), 1.0, delta=0.1)
            tempo.assert_called_once_with(1.2)

    def test_tts_keeps_existing_rate_limits(self):
        for rate in (0.9, 1.51, 3, float("nan"), float("inf")):
            with self.subTest(rate=rate), self.assertRaises(HTTPException) as error:
                tts_studio._normalize_speech_rate(rate)
            self.assertEqual(error.exception.status_code, 422)


class TTSStudioApiTests(unittest.TestCase):
    def setUp(self):
        self.user_id = "user-a"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temp_dir.name) / "output"
        self.output_root.mkdir()
        settings_store.init_db()
        ensure_test_user(self.user_id, username="user_a", display_name=self.user_id)
        ensure_test_user("user-b", username="user_b", display_name="user-b")
        self.voice_output_patch = patch.object(
            tts_studio.voice_profiles,
            "_output_root",
            return_value=self.output_root,
            create=True,
        )
        self.voice_output_patch.start()

        app = FastAPI()
        app.include_router(tts_studio.router, prefix="/api")
        app.dependency_overrides[require_current_user] = self._current_user
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.voice_output_patch.stop()
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
        self.assertRegex(payload["audio_url"], r"^/api/tasks/[0-9a-f]+/artifacts/[0-9a-f]+/preview$")
        task = task_store.get_task(payload["task_id"], self.user_id)
        self.assertEqual(task["task_type"], task_store.TASK_TYPE_VOICE)
        self.assertTrue((self.output_root / "tasks").joinpath(task["created_at"][0:4], task["created_at"][5:7], task["created_at"][8:10], task_store.TASK_TYPE_VOICE, payload["task_id"], "preview_original.mp3").is_file())
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
                "validation": "static",
                "checks": {"configuration": "passed", "network": "skipped"},
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

    def test_speech_rate_variant_updates_the_original_task(self):
        edge_voice = {
            "id": "zh-CN-XiaoxiaoNeural",
            "name": "晓晓",
            "gender": "female",
            "description": "温暖自然",
        }

        async def write_audio(_model_name, _request, output_path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"original audio")

        with patch.object(tts_studio, "resolve_output_dir", return_value=self.output_root), patch.object(
            tts_studio.tts_service,
            "list_voices",
            return_value=[edge_voice],
        ), patch.object(tts_studio.tts_service, "synthesize", AsyncMock(side_effect=write_audio)):
            generated = self.client.post(
                "/api/tts-studio/edge-tts/preview",
                data={"text": "original", "voice_id": edge_voice["id"]},
            ).json()

        task_id = generated["task_id"]
        artifact_id = generated["artifact_id"]
        task = task_store.get_task(task_id, self.user_id)
        adjusted_path = Path(task["storage_path"]) / "preview_1_2x.mp3"
        adjusted_path.write_bytes(b"adjusted audio")
        with patch.object(tts_studio, "resolve_output_dir", return_value=self.output_root), patch.object(
            tts_studio,
            "_create_speech_rate_variant",
            return_value=adjusted_path,
        ), patch.object(task_store, "_output_root", return_value=self.output_root.resolve()):
            response = self.client.post(
                "/api/tts-studio/preview/speech-rate",
                data={"task_id": task_id, "artifact_id": artifact_id, "speech_rate": "1.2"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        persisted = task_store.get_task(task_id, self.user_id)
        self.assertEqual(persisted["success_count"], 1)
        self.assertEqual(persisted["failed_count"], 0)
        self.assertEqual(len(persisted["artifacts"]), 2)
        self.assertFalse(persisted["artifacts"][1]["counts_toward_result"])


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

    def test_voice_profile_crud_is_private_and_stores_transcript_in_database(self):
        reference_audio = b"reference audio"
        response = self.client.post(
            "/api/tts-studio/voice-profiles",
            data={
                "name": "Personal voice",
                "language": "English",
                "ref_text": "Original reference text",
            },
            files={"ref_audio": ("reference.wav", reference_audio, "audio/wav")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        profile = response.json()
        self.assertNotIn("user_id", profile)
        self.assertNotIn("relative_path", profile)
        self.assertRegex(profile["audio_filename"], r"^reference-[0-9a-f]+\.wav$")

        with settings_store._orm_session() as session:
            stored = session.scalar(select(VoiceProfile).where(VoiceProfile.id == profile["id"]))
            self.assertEqual(stored.user_id, "user-a")
            self.assertEqual(stored.name, "Personal voice")
            self.assertEqual(stored.ref_text, "Original reference text")
            stored_path = self.output_root / stored.relative_path
        self.assertEqual(stored_path.read_bytes(), reference_audio)
        self.assertRegex(stored_path.name, r"^reference-[0-9a-f]+\.wav$")
        self.assertEqual([item.name for item in stored_path.parent.iterdir()], [stored_path.name])

        response = self.client.get("/api/tts-studio/voice-profiles")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["id"] for item in response.json()], [profile["id"]])

        self.user_id = "user-b"
        response = self.client.get("/api/tts-studio/voice-profiles")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])
        self.assertEqual(
            self.client.get(f"/api/tts-studio/voice-profiles/{profile['id']}/audio").status_code,
            404,
        )
        self.assertEqual(
            self.client.put(
                f"/api/tts-studio/voice-profiles/{profile['id']}",
                data={"name": "Stolen", "language": "Chinese", "ref_text": "No"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(f"/api/tts-studio/voice-profiles/{profile['id']}").status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                "/api/tts-studio/voice-clone/preview",
                data={"text": "No access", "voice_profile_id": profile["id"]},
            ).status_code,
            404,
        )

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

    def test_personal_profile_is_available_for_clone_from_database(self):
        created = self.client.post(
            "/api/tts-studio/voice-profiles",
            data={"name": "My voice", "language": "Chinese", "ref_text": "Database reference text"},
            files={"ref_audio": ("reference.mp3", b"database reference", "audio/mpeg")},
        )
        self.assertEqual(created.status_code, 200, created.text)
        profile = created.json()

        async def write_audio(model_name, request, output_path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"generated")
            return SimpleNamespace(output_path=output_path, duration=0, model_name=model_name, voice_id=None, timings=())

        with patch.object(tts_studio, "resolve_output_dir", return_value=self.output_root), patch.object(
            tts_studio.tts_service, "synthesize", new=AsyncMock(side_effect=write_audio)
        ) as synthesize:
            response = self.client.post(
                "/api/tts-studio/voice-clone/preview",
                data={"text": "Use my voice", "voice_profile_id": profile["id"], "language": "Chinese"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        request = synthesize.await_args.args[1]
        self.assertEqual(request.reference_audio.read_bytes(), b"database reference")
        self.assertEqual(request.reference_text, "Database reference text")

    def test_replacing_profile_audio_removes_old_revision_and_rolls_back_failed_database_update(self):
        created = self.client.post(
            "/api/tts-studio/voice-profiles",
            data={"name": "Voice", "language": "Chinese", "ref_text": "First text"},
            files={"ref_audio": ("reference.wav", b"first audio", "audio/wav")},
        ).json()
        with settings_store._orm_session() as session:
            profile = session.get(VoiceProfile, created["id"])
            first_path = self.output_root / profile.relative_path

        response = self.client.put(
            f"/api/tts-studio/voice-profiles/{created['id']}",
            data={"name": "Updated", "language": "English", "ref_text": "Second text"},
            files={"ref_audio": ("reference.mp3", b"second audio", "audio/mpeg")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        with settings_store._orm_session() as session:
            profile = session.get(VoiceProfile, created["id"])
            second_path = self.output_root / profile.relative_path
            self.assertEqual(profile.ref_text, "Second text")
        self.assertFalse(first_path.exists())
        self.assertEqual(second_path.read_bytes(), b"second audio")

        real_orm_session = tts_studio.voice_profiles._orm_session
        session_calls = 0

        def fail_second_session():
            nonlocal session_calls
            session_calls += 1
            if session_calls == 2:
                raise RuntimeError("database unavailable")
            return real_orm_session()

        with patch.object(
            tts_studio.voice_profiles,
            "_orm_session",
            side_effect=fail_second_session,
        ), self.assertRaisesRegex(RuntimeError, "database unavailable"):
            self.client.put(
                f"/api/tts-studio/voice-profiles/{created['id']}",
                data={"name": "Broken", "language": "Chinese", "ref_text": "Broken text"},
                files={"ref_audio": ("reference.flac", b"third audio", "audio/flac")},
            )

        with settings_store._orm_session() as session:
            profile = session.get(VoiceProfile, created["id"])
            self.assertEqual(profile.name, "Updated")
            self.assertEqual(profile.ref_text, "Second text")
        self.assertEqual(second_path.read_bytes(), b"second audio")
        self.assertEqual([item.name for item in second_path.parent.iterdir()], [second_path.name])

    def test_missing_profile_audio_returns_404_for_preview_and_clone(self):
        created = self.client.post(
            "/api/tts-studio/voice-profiles",
            data={"name": "Voice", "language": "Chinese", "ref_text": "Reference"},
            files={"ref_audio": ("reference.wav", b"audio", "audio/wav")},
        ).json()
        with settings_store._orm_session() as session:
            profile = session.get(VoiceProfile, created["id"])
            (self.output_root / profile.relative_path).unlink()

        self.assertEqual(self.client.get(created["audio_url"]).status_code, 404)
        response = self.client.post(
            "/api/tts-studio/voice-clone/preview",
            data={"text": "Generate", "voice_profile_id": created["id"]},
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_voice_profile_limit_rejects_twenty_first_without_leaving_a_file(self):
        now = settings_store._now_iso()
        with settings_store._orm_session() as session:
            session.add_all(
                VoiceProfile(
                    id=f"voice-{index}",
                    user_id=self.user_id,
                    name=f"Voice {index}",
                    language="Chinese",
                    ref_text="Reference",
                    relative_path=f"voice_profiles/{self.user_id}/voice-{index}/reference-{index}.wav",
                    file_size=1,
                    created_at=now,
                    updated_at=now,
                )
                for index in range(20)
            )

        response = self.client.post(
            "/api/tts-studio/voice-profiles",
            data={"name": "Overflow", "language": "Chinese", "ref_text": "Reference"},
            files={"ref_audio": ("reference.wav", b"audio", "audio/wav")},
        )

        self.assertEqual(response.status_code, 422, response.text)
        voice_root = self.output_root / "voice_profiles" / self.user_id
        self.assertFalse(any(path.is_file() for path in voice_root.rglob("*")))

    def test_concurrent_creates_at_nineteen_allow_exactly_one_profile(self):
        now = settings_store._now_iso()
        with settings_store._orm_session() as session:
            session.add_all(
                VoiceProfile(
                    id=f"voice-{index}",
                    user_id=self.user_id,
                    name=f"Voice {index}",
                    language="Chinese",
                    ref_text="Reference",
                    relative_path=f"voice_profiles/{self.user_id}/voice-{index}/reference-{index}.wav",
                    file_size=1,
                    created_at=now,
                    updated_at=now,
                )
                for index in range(19)
            )

        def create(index: int) -> int:
            with TestClient(self.client.app) as client:
                response = client.post(
                    "/api/tts-studio/voice-profiles",
                    data={"name": f"Concurrent {index}", "language": "Chinese", "ref_text": "Reference"},
                    files={"ref_audio": (f"reference-{index}.wav", b"audio", "audio/wav")},
                )
                return response.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = sorted(executor.map(create, (1, 2)))

        self.assertEqual(statuses, [200, 422])
        with settings_store._orm_session() as session:
            count = len(session.scalars(select(VoiceProfile).where(VoiceProfile.user_id == self.user_id)).all())
        self.assertEqual(count, 20)


if __name__ == "__main__":
    unittest.main()
