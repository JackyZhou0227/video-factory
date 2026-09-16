from __future__ import annotations

import asyncio
import io
import subprocess
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from starlette.datastructures import Headers
from PIL import Image

from app.api import poster_video as poster_api
from app.api import tasks as tasks_api
from app.api.auth import require_current_user
from app.services import settings_store, task_store
from tests.pg_test_utils import ensure_test_user


class PosterVideoApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output_root = self.root / "output"
        self.output_root.mkdir()
        settings_store.init_db()
        ensure_test_user("user-a", username="user_a", display_name="User A")
        poster_api._tasks.clear()

        app = FastAPI()
        app.include_router(poster_api.router, prefix="/api")
        app.include_router(tasks_api.router, prefix="/api")
        app.dependency_overrides[require_current_user] = lambda: {
            "id": "user-a",
            "username": "user_a",
            "display_name": "User A",
        }
        self.client = TestClient(app)
        self.app = app
        self.enterContext(patch.object(poster_api, "resolve_output_dir", return_value=self.output_root))
        self.enterContext(patch.object(task_store, "resolve_output_dir", return_value=self.output_root))
        self.enterContext(patch.object(poster_api.poster_video, "require_ffmpeg"))
        self.enterContext(patch.object(
            poster_api.poster_video,
            "create_overlay",
            side_effect=lambda _template, path: path.write_bytes(b"overlay"),
        ))
        self.schedule = self.enterContext(patch.object(poster_api.common, "schedule_task"))

    def tearDown(self):
        self.client.close()
        poster_api._tasks.clear()
        self.temp_dir.cleanup()

    def post_batch(self, assets=None, *, media_type="video", narration=None, **fields):
        files = [
            ("assets", asset)
            for asset in (assets if assets is not None else [("clip.mp4", b"clip", "video/mp4")])
        ]
        if narration is not None:
            files.append(("narration_audio", narration))
        return self.client.post(
            "/api/poster-videos/generate",
            data={"media_type": media_type, "template": '{"blocks": []}', **fields},
            files=files,
        )

    def create_bgm(self, *, user_id="user-a", bgm_id="music", relative_path=None, missing=False):
        ensure_test_user(user_id)
        relative_path = relative_path or f"bgm/{user_id}/{bgm_id}.mp3"
        path = self.output_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not missing:
            path.write_bytes(b"music")
        settings_store.create_bgm_track(
            user_id=user_id,
            bgm_id=bgm_id,
            name=f"{bgm_id}.mp3",
            relative_path=relative_path,
            duration=999.0,
            file_size=5,
        )
        return path

    def test_real_mixed_batch_upload_render_query_and_download(self):
        ffmpeg = poster_api.poster_video.ffmpeg_executable()
        if ffmpeg is None:
            self.skipTest("FFmpeg is not installed")
        image = self.root / "still.png"
        video = self.root / "clip.mp4"
        voice = self.root / "voice.wav"
        music = self.create_bgm(relative_path="bgm/user-a/music.wav")
        Image.new("RGB", (80, 60), "#335588").save(image)
        for arguments in (
            ["-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=1.2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
            ["-f", "lavfi", "-i", "sine=frequency=440:duration=0.6", str(voice)],
            ["-f", "lavfi", "-i", "sine=frequency=880:duration=0.2", str(music)],
        ):
            subprocess.run([ffmpeg, "-y", *arguments], check=True, capture_output=True)

        with patch.object(poster_api.poster_video, "TARGET_WIDTH", 180), patch.object(
            poster_api.poster_video, "TARGET_HEIGHT", 320
        ), patch.object(
            poster_api.poster_video, "create_overlay",
            side_effect=lambda _template, path: Image.new("RGBA", (180, 320)).save(path),
        ):
            response = self.post_batch(
                [
                    ("still.png", image.read_bytes(), "image/png"),
                    ("clip.mp4", video.read_bytes(), "video/mp4"),
                    ("broken.png", b"not an image", "image/png"),
                ],
                narration=("voice.wav", voice.read_bytes(), "audio/wav"),
                bgm_id="music",
            )
            self.assertEqual(response.status_code, 200, response.text)
            music.unlink()
            asyncio.run(self.schedule.call_args.args[1]())

        task_id = response.json()["task_id"]
        poster_api._tasks.clear()
        result = self.client.get(f"/api/poster-videos/task/{task_id}")
        self.assertEqual(result.status_code, 200, result.text)
        payload = result.json()
        self.assertEqual(payload["status"], "partial_failed")
        self.assertEqual([item["status"] for item in payload["items"]], ["completed", "completed", "failed"])
        self.assertTrue(payload["items"][2]["error"])
        self.assertEqual(payload["items"][1]["video_speed"], 2)
        for item in payload["items"][:2]:
            self.assertAlmostEqual(item["target_duration"], 0.6, delta=0.01)
            preview = self.client.get(item["asset_url"])
            self.assertEqual(preview.status_code, 200, preview.text[:100] if preview.status_code != 200 else "")
            self.assertEqual(preview.headers["content-type"], "video/mp4")
            self.assertGreater(len(preview.content), 1000)
        archive = self.client.get(payload["zip_url"])
        self.assertEqual(archive.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
            self.assertEqual(len(zipped.namelist()), 2)
            self.assertTrue(all(name.endswith(".mp4") and "broken" not in name for name in zipped.namelist()))

    def assert_failed_submission(self, response, create_task, *, status=422):
        self.assertEqual(response.status_code, status, response.text)
        record = task_store.get_task(create_task.call_args.kwargs["task_id"], "user-a")
        self.assertEqual(record["status"], "failed")
        self.assertTrue(record["error"])
        self.assertEqual(record["failed_count"], record["requested_count"])
        self.assertIsNotNone(record["finished_at"])
        self.assertEqual(list((Path(record["storage_path"]) / "input").glob("*")), [])
        self.schedule.assert_not_called()
        return record

    def test_video_accepts_mixed_assets_and_probes_narration_once_before_scheduling(self):
        with patch.object(poster_api.poster_video, "probe_audio_duration", return_value=7.5) as probe:
            response = self.post_batch(
                [("still.PNG", b"still", "image/png"), ("clip.mov", b"clip", "video/quicktime")],
                narration=("voice.mp3", b"voice", "audio/mpeg"),
            )
        self.assertEqual(response.status_code, 200, response.text)
        record = task_store.get_task(response.json()["task_id"], "user-a")
        self.assertEqual(record["generation_type"], "video")
        self.assertEqual(record["requested_count"], 2)
        self.assertEqual([item["source_type"] for item in record["extra_info"]["items"]], ["image", "video"])
        self.assertEqual(record["extra_info"]["narration_duration"], 7.5)
        probe.assert_called_once()
        self.assertEqual(probe.call_args.args[0].read_bytes(), b"voice")
        self.assertEqual(probe.call_args.args[0].parent, Path(record["storage_path"]) / "input")
        self.schedule.assert_called_once()
        with patch.object(poster_api, "_run_batch") as run_batch:
            asyncio.run(self.schedule.call_args.args[1]())
        self.assertEqual([item["source_type"] for item in run_batch.call_args.kwargs["files"]], ["image", "video"])
        self.assertEqual(run_batch.call_args.kwargs["narration_duration"], 7.5)
        self.assertEqual(run_batch.call_args.kwargs["narration_path"], probe.call_args.args[0])

    def test_any_image_in_video_submission_requires_shared_audio(self):
        for assets in (
            [("still.jpg", b"still", "image/jpeg")],
            [("clip.mp4", b"clip", "video/mp4"), ("still.jpg", b"still", "image/jpeg")],
        ):
            with self.subTest(assets=assets):
                response = self.post_batch(assets)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn("audio", response.json()["detail"].lower())
        self.schedule.assert_not_called()

    def test_video_only_needs_no_shared_audio_and_mute_defaults_true_or_accepts_false(self):
        for fields, expected in (({}, True), ({"mute_original_audio": "false"}, False)):
            with self.subTest(fields=fields):
                response = self.post_batch(**fields)
                self.assertEqual(response.status_code, 200, response.text)
                record = task_store.get_task(response.json()["task_id"], "user-a")
                self.assertEqual(record["extra_info"]["mute_original_audio"], expected)
                with patch.object(poster_api, "_run_batch") as run_batch:
                    asyncio.run(self.schedule.call_args.args[1]())
                self.assertIs(run_batch.call_args.kwargs["mute_original_audio"], expected)

    def test_image_output_rejects_audio_bgm_and_video_sources(self):
        for fields in (
            {"narration": ("voice.mp3", b"voice", "audio/mpeg")},
            {"bgm_id": "music"},
        ):
            with self.subTest(fields=fields):
                response = self.post_batch([("still.jpg", b"still", "image/jpeg")], media_type="image", **fields)
                self.assertEqual(response.status_code, 422, response.text)
        response = self.post_batch(media_type="image")
        self.assertEqual(response.status_code, 422, response.text)
        self.schedule.assert_not_called()

    def test_source_specific_extension_and_mime_validation(self):
        for asset in (
            ("still.jpg", b"still", "video/mp4"),
            ("clip.mp4", b"clip", "image/jpeg"),
            ("still.gif", b"still", "image/gif"),
            ("file.txt", b"data", "application/octet-stream"),
        ):
            with self.subTest(asset=asset):
                response = self.post_batch([asset], narration=("voice.mp3", b"voice", "audio/mpeg"))
                self.assertEqual(response.status_code, 422, response.text)
        self.schedule.assert_not_called()

    def test_extensionless_media_uses_declared_mime_to_classify_source(self):
        with patch.object(poster_api.poster_video, "probe_audio_duration", return_value=4.0):
            response = self.post_batch(
                [("still", b"still", "image/png")],
                narration=("voice.mp3", b"voice", "audio/mpeg"),
            )
        self.assertEqual(response.status_code, 200, response.text)
        record = task_store.get_task(response.json()["task_id"], "user-a")
        self.assertEqual(record["extra_info"]["items"][0]["source_type"], "image")

    def test_source_specific_sizes_allow_image_and_video_limits(self):
        with patch.object(poster_api.uploads, "MAX_IMAGE_FILE_SIZE", 4), patch.object(
            poster_api.uploads, "MAX_VIDEO_FILE_SIZE", 8
        ), patch.object(poster_api.poster_video, "probe_audio_duration", return_value=4.0):
            for asset, expected in (
                (("still.jpg", b"1234", "image/jpeg"), 200),
                (("still.jpg", b"12345", "image/jpeg"), 422),
                (("clip.mp4", b"12345678", "video/mp4"), 200),
                (("clip.mp4", b"123456789", "video/mp4"), 422),
            ):
                with self.subTest(asset=asset):
                    response = self.post_batch([asset], narration=("voice.mp3", b"voice", "audio/mpeg"))
                    self.assertEqual(response.status_code, expected, response.text)

    def test_batch_limit_accepts_fifty_and_rejects_fifty_one(self):
        for count, expected in ((50, 200), (51, 422)):
            with self.subTest(count=count):
                response = self.post_batch([("clip.mp4", b"clip", "video/mp4")] * count)
                self.assertEqual(response.status_code, expected, response.text)

    def test_narration_extensions_and_generic_mime_are_supported(self):
        with patch.object(poster_api.poster_video, "probe_audio_duration", return_value=4.0) as probe:
            for extension, mime in (
                ("mp3", "audio/mpeg"), ("wav", "audio/wav"), ("aac", "audio/aac"),
                ("m4a", "audio/mp4"), ("ogg", "audio/ogg"), ("flac", "application/octet-stream"),
            ):
                with self.subTest(extension=extension):
                    response = self.post_batch(narration=(f"voice.{extension}", b"voice", mime))
                    self.assertEqual(response.status_code, 200, response.text)
                    task_store.update_task(response.json()["task_id"], status="cancelled", finished=True)
            self.assertEqual(probe.call_count, 6)

    def test_narration_rejects_extension_mime_and_oversize(self):
        with patch.object(poster_api.uploads, "MAX_AUDIO_FILE_SIZE", 4):
            for narration in (
                ("voice.mp4", b"1234", "audio/mp4"),
                ("voice.mp3", b"1234", "video/mp4"),
                ("voice.mp3", b"12345", "audio/mpeg"),
            ):
                with self.subTest(narration=narration):
                    response = self.post_batch(narration=narration)
                    self.assertEqual(response.status_code, 422, response.text)
        self.schedule.assert_not_called()

    def test_invalid_narration_persists_failure_and_cleans_all_input_snapshots(self):
        self.create_bgm()
        with patch.object(poster_api.common, "create_task", wraps=poster_api.common.create_task) as create, patch.object(
            poster_api.poster_video, "probe_audio_duration",
            side_effect=poster_api.poster_video.PosterVideoError("not an audio stream"),
        ):
            response = self.post_batch(narration=("voice.mp3", b"invalid", "audio/mpeg"), bgm_id="music")
        self.assert_failed_submission(response, create)

    def test_bgm_rejects_unknown_foreign_missing_and_escaping_paths(self):
        self.create_bgm(user_id="user-b", bgm_id="foreign")
        self.create_bgm(bgm_id="missing", missing=True)
        self.create_bgm(bgm_id="escaping", relative_path="bgm/user-a/../../outside.mp3")
        self.create_bgm(bgm_id="cross-user", relative_path="bgm/user-b/shared.mp3")
        for bgm_id in ("unknown", "foreign", "missing", "escaping", "cross-user"):
            with self.subTest(bgm_id=bgm_id):
                response = self.post_batch(bgm_id=bgm_id)
                self.assertEqual(response.status_code, 422, response.text)
        self.schedule.assert_not_called()

    def test_bgm_snapshot_is_probed_before_scheduling_and_survives_library_deletion(self):
        source = self.create_bgm()
        with patch.object(poster_api.poster_video, "probe_audio_duration", return_value=12.0) as probe:
            response = self.post_batch([("still.jpg", b"still", "image/jpeg")], bgm_id=" music ")
        self.assertEqual(response.status_code, 200, response.text)
        record = task_store.get_task(response.json()["task_id"], "user-a")
        probe.assert_called_once()
        snapshot = probe.call_args.args[0]
        self.assertNotEqual(snapshot, source)
        self.assertEqual(snapshot.parent, Path(record["storage_path"]) / "input")
        self.assertEqual(snapshot.read_bytes(), b"music")
        self.assertEqual(record["extra_info"]["bgm_name"], "music.mp3")
        self.assertEqual(record["extra_info"]["bgm_duration"], 12.0)
        source.unlink()
        settings_store.delete_bgm_track("user-a", "music")
        with patch.object(poster_api, "_run_batch") as run_batch:
            asyncio.run(self.schedule.call_args.args[1]())
        self.assertEqual(run_batch.call_args.kwargs["bgm_path"], snapshot)
        self.assertEqual(run_batch.call_args.kwargs["bgm_duration"], 12.0)
        self.assertEqual(snapshot.read_bytes(), b"music")

    def test_shared_audio_durations_are_probed_once_and_forwarded_to_each_video(self):
        self.create_bgm()
        calls = []

        def process(_input_path, _overlay_path, output_path, **kwargs):
            calls.append(kwargs)
            output_path.write_bytes(b"video")
            return {
                "source_type": kwargs["source_type"],
                "target_duration": 8.0,
                "video_speed": 1.0,
                "narration_speed": 1.0,
            }

        with patch.object(
            poster_api.poster_video, "probe_audio_duration", side_effect=[8.0, 20.0],
        ) as probe, patch.object(poster_api.poster_video, "process_video", side_effect=process):
            response = self.post_batch(
                [("still.jpg", b"still", "image/jpeg"), ("clip.mp4", b"clip", "video/mp4")],
                narration=("voice.mp3", b"voice", "audio/mpeg"),
                bgm_id="music",
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(probe.call_count, 2)
            asyncio.run(self.schedule.call_args.args[1]())
            self.assertEqual(probe.call_count, 2)
        self.assertEqual([call["source_type"] for call in calls], ["image", "video"])
        for call in calls:
            self.assertEqual(call["narration_duration"], 8.0)
            self.assertEqual(call["bgm_duration"], 20.0)
            self.assertIs(call["mute_original_audio"], True)
            self.assertEqual(call["narration_path"].read_bytes(), b"voice")
            self.assertEqual(call["bgm_path"].read_bytes(), b"music")
        record = task_store.get_task(response.json()["task_id"], "user-a")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["extra_info"]["narration_duration"], 8.0)
        self.assertEqual(record["extra_info"]["bgm_duration"], 20.0)
        self.assertEqual(record["extra_info"]["bgm_name"], "music.mp3")

    def test_invalid_bgm_persists_failure_and_cleans_snapshots(self):
        source = self.create_bgm()
        with patch.object(poster_api.common, "create_task", wraps=poster_api.common.create_task) as create, patch.object(
            poster_api.poster_video, "probe_audio_duration",
            side_effect=poster_api.poster_video.PosterVideoError("invalid BGM"),
        ):
            response = self.post_batch(bgm_id="music")
        self.assert_failed_submission(response, create)
        self.assertTrue(source.exists())

    def test_overlay_failure_cleans_audio_and_asset_snapshots(self):
        self.create_bgm()
        with patch.object(poster_api.common, "create_task", wraps=poster_api.common.create_task) as create, patch.object(
            poster_api.poster_video, "probe_audio_duration", return_value=3.0,
        ), patch.object(
            poster_api.poster_video, "create_overlay",
            side_effect=poster_api.poster_video.PosterVideoError("overlay failed"),
        ):
            response = self.post_batch(narration=("voice.mp3", b"voice", "audio/mpeg"), bgm_id="music")
        self.assert_failed_submission(response, create)

    def test_bgm_copy_failure_cleans_partial_snapshot_and_uploaded_inputs(self):
        source = self.create_bgm()

        def fail_copy(_source, destination):
            destination.write_bytes(b"partial")
            raise OSError("copy failed")

        with patch.object(poster_api.common, "create_task", wraps=poster_api.common.create_task) as create, patch.object(
            poster_api.shutil, "copy2", side_effect=fail_copy,
        ):
            response = self.post_batch(narration=("voice.mp3", b"voice", "audio/mpeg"), bgm_id="music")
        record = self.assert_failed_submission(response, create, status=500)
        self.assertEqual(record["extra_info"]["items"][0]["error"], "copy failed")
        self.assertTrue(source.exists())

    def test_streamed_audio_limit_failure_cleans_already_saved_asset(self):
        asset = UploadFile(io.BytesIO(b"clip"), filename="clip.mp4")
        narration = UploadFile(io.BytesIO(b"12345"), filename="voice.mp3")
        with patch.object(poster_api.common, "create_task", wraps=poster_api.common.create_task) as create, patch.object(
            poster_api.uploads, "MAX_AUDIO_FILE_SIZE", 4,
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(poster_api.generate_poster_videos(
                    user={"id": "user-a"},
                    template='{"blocks": []}',
                    media_type="video",
                    assets=[asset],
                    narration_audio=narration,
                    bgm_id="",
                    mute_original_audio=True,
                ))
        self.assertEqual(raised.exception.status_code, 422)
        record = task_store.get_task(create.call_args.kwargs["task_id"], "user-a")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["extra_info"]["items"][0]["status"], "failed")
        self.assertEqual(list((Path(record["storage_path"]) / "input").glob("*")), [])
        self.schedule.assert_not_called()

    def test_declared_upload_sizes_enforce_twenty_fifty_and_five_hundred_mb_limits(self):
        for filename, mime, limit, is_audio in (
            ("still.jpg", "image/jpeg", 20 * 1024 * 1024, False),
            ("clip.mp4", "video/mp4", 500 * 1024 * 1024, False),
            ("voice.mp3", "audio/mpeg", 50 * 1024 * 1024, True),
        ):
            with self.subTest(filename=filename):
                oversized = UploadFile(
                    io.BytesIO(b"data"), filename=filename, size=limit + 1,
                    headers=Headers({"content-type": mime}),
                )
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(poster_api.generate_poster_videos(
                        user={"id": "user-a"},
                        template='{"blocks": []}',
                        media_type="video",
                        assets=[UploadFile(io.BytesIO(b"clip"), filename="clip.mp4")] if is_audio else [oversized],
                        narration_audio=oversized if is_audio else None,
                        bgm_id="",
                        mute_original_audio=True,
                    ))
                self.assertEqual(raised.exception.status_code, 422)
        self.schedule.assert_not_called()

    def test_scheduler_failure_cleans_snapshots_and_persists_failure(self):
        self.schedule.side_effect = HTTPException(status_code=429, detail="queue full")
        with patch.object(poster_api.common, "create_task", wraps=poster_api.common.create_task) as create:
            response = self.post_batch()
        self.assertEqual(response.status_code, 429, response.text)
        record = task_store.get_task(create.call_args.kwargs["task_id"], "user-a")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(list((Path(record["storage_path"]) / "input").glob("*")), [])

    def test_pending_items_restore_after_cache_clear_and_task_owner_is_enforced(self):
        response = self.post_batch()
        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]
        poster_api._tasks.clear()
        response = self.client.get(f"/api/poster-videos/task/{task_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertEqual(response.json()["items"][0]["source_type"], "video")
        self.assertEqual(response.json()["items"][0]["status"], "pending")
        self.app.dependency_overrides[require_current_user] = lambda: {"id": "user-b"}
        self.assertEqual(self.client.get(f"/api/poster-videos/task/{task_id}").status_code, 404)

    def test_generation_requires_authentication(self):
        self.app.dependency_overrides.clear()
        self.assertEqual(self.post_batch().status_code, 401)
        self.schedule.assert_not_called()

    def test_create_image_batch_records_requested_count_and_date_path(self):
        with patch.object(poster_api, "resolve_output_dir", return_value=self.output_root), patch.object(
            poster_api.poster_video,
            "create_overlay",
            side_effect=lambda _template, path: path.write_bytes(b"overlay"),
        ), patch.object(poster_api, "_run_batch"):
            response = self.client.post(
                "/api/poster-videos/generate",
                data={"media_type": "image", "template": '{"blocks": []}'},
                files=[
                    ("assets", ("first.jpg", b"first", "image/jpeg")),
                    ("assets", ("second.png", b"second", "image/png")),
                ],
            )
        self.assertEqual(response.status_code, 200, response.text)
        task = task_store.get_task(response.json()["task_id"], "user-a")
        self.assertEqual(task["task_type"], task_store.TASK_TYPE_POSTER)
        self.assertEqual(task["generation_type"], "image")
        self.assertEqual(task["requested_count"], 2)
        self.assertIn(str(Path("tasks") / task["created_at"][:4] / task["created_at"][5:7]), task["storage_path"])

    def run_batch_case(self, outcomes: list[bool], *, media_type="image", observe=False) -> dict:
        task_id = uuid.uuid4().hex
        record = task_store.create_task(
            user={"id": "user-a", "username": "user_a", "display_name": "User A"},
            task_type=task_store.TASK_TYPE_POSTER,
            generation_type=media_type,
            requested_count=len(outcomes),
            task_id=task_id,
            output_root=self.output_root,
            extra_info={"bgm_name": "music.mp3", "narration_duration": 8.0, "custom_metadata": "preserved"},
        )
        task_dir = Path(record["storage_path"])
        files = []
        for index in range(len(outcomes)):
            input_path = task_dir / f"input-{index}.jpg"
            input_path.write_bytes(b"input")
            files.append({
                "id": f"item-{index}",
                "filename": f"input-{index}.jpg",
                "input_path": input_path,
                "output_path": task_dir / f"output-{index}{'.mp4' if media_type == 'video' else '.jpg'}",
            })
        if media_type == "video":
            for index, item in enumerate(files):
                item["source_type"] = "image" if index == 0 else "video"
        poster_api._tasks[task_id] = poster_api._new_task("user-a", task_dir, files, media_type)

        outcome_iter = iter(outcomes)
        self.observed_items = []

        def process(_input_path, _overlay_path, output_path, **kwargs):
            if observe:
                stored = task_store.get_task(task_id, "user-a")
                self.observed_items.append(stored["extra_info"].get("items", []))
            output_path.write_bytes(b"partial")
            if not next(outcome_iter):
                raise RuntimeError("render failed")
            output_path.write_bytes(b"result")
            if media_type == "video":
                self.assertEqual(kwargs["narration_duration"], 8.0)
                self.assertEqual(kwargs["bgm_duration"], 20.0)
                self.assertIs(kwargs["mute_original_audio"], False)
                self.assertEqual(kwargs["narration_path"], task_dir / "voice.mp3")
                self.assertEqual(kwargs["bgm_path"], task_dir / "music.mp3")
                return {
                    "source_type": kwargs["source_type"],
                    "target_duration": 8.0,
                    "video_speed": 1.25,
                    "narration_speed": 1.0,
                }
            self.assertEqual(kwargs, {})

        overlay = task_dir / "overlay.png"
        overlay.write_bytes(b"overlay")
        processor = "process_video" if media_type == "video" else "process_image"
        kwargs = {}
        if media_type == "video":
            kwargs = {
                "narration_path": task_dir / "voice.mp3",
                "bgm_path": task_dir / "music.mp3",
                "mute_original_audio": False,
                "narration_duration": 8.0,
                "bgm_duration": 20.0,
            }
        with patch.object(poster_api.poster_video, processor, side_effect=process):
            asyncio.run(poster_api._run_batch(task_id, files, overlay, task_dir, media_type, **kwargs))
        return task_store.get_task(task_id, "user-a")

    def test_video_item_metadata_and_errors_persist_and_restore_after_cache_clear(self):
        record = self.run_batch_case([True, False, True], media_type="video", observe=True)
        self.assertEqual(record["status"], "partial_failed")
        self.assertEqual(record["extra_info"]["bgm_name"], "music.mp3")
        self.assertEqual(record["extra_info"]["narration_duration"], 8.0)
        self.assertEqual(record["extra_info"]["custom_metadata"], "preserved")
        items = record["extra_info"]["items"]
        self.assertEqual([item["status"] for item in items], ["completed", "failed", "completed"])
        self.assertEqual(items[0]["source_type"], "image")
        self.assertEqual(items[2]["source_type"], "video")
        self.assertEqual(items[0]["target_duration"], 8.0)
        self.assertEqual(items[2]["video_speed"], 1.25)
        self.assertEqual(items[0]["narration_speed"], 1.0)
        self.assertEqual(items[1]["error"], "render failed")
        self.assertIsNone(items[1]["asset_url"])
        self.assertEqual(
            [[item["status"] for item in snapshot] for snapshot in self.observed_items],
            [["running", "pending", "pending"], ["completed", "running", "pending"], ["completed", "failed", "running"]],
        )
        poster_api._tasks.clear()
        response = self.client.get(f"/api/poster-videos/task/{record['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"], items)

    def test_item_result_is_persisted_before_archive_creation(self):
        observed = []

        def create_zip(path, outputs):
            task_id = next(iter(poster_api._tasks))
            observed.append(task_store.get_task(task_id, "user-a")["extra_info"].get("items", []))
            with zipfile.ZipFile(path, "w") as archive:
                for output in outputs:
                    archive.write(output, output.name)

        with patch.object(poster_api.common, "create_output_zip", side_effect=create_zip):
            self.run_batch_case([True, False])
        self.assertEqual([item["status"] for item in observed[0]], ["completed", "failed"])

    def test_partial_outputs_are_removed_and_excluded_from_downloadable_zip(self):
        record = self.run_batch_case([True, False, True])
        task_dir = Path(record["storage_path"])
        self.assertFalse((task_dir / "output-1.jpg").exists())
        with zipfile.ZipFile(task_dir / "poster_images.zip") as archive:
            self.assertEqual(archive.namelist(), ["output-0.jpg", "output-2.jpg"])
        poster_api._tasks.clear()
        payload = self.client.get(f"/api/poster-videos/task/{record['id']}").json()
        self.assertEqual(self.client.get(payload["zip_url"]).status_code, 200)
        self.assertEqual(self.client.get(payload["items"][0]["image_url"]).content, b"result")
        self.app.dependency_overrides[require_current_user] = lambda: {"id": "user-b"}
        self.assertEqual(self.client.get(payload["zip_url"]).status_code, 404)

    def test_legacy_artifact_fallback_still_builds_image_urls(self):
        record = self.run_batch_case([True])
        task_store.update_task(record["id"], extra_info={})
        poster_api._tasks.clear()
        payload = self.client.get(f"/api/poster-videos/task/{record['id']}").json()
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(self.client.get(payload["items"][0]["image_url"]).content, b"result")

    def test_batch_statuses_cover_success_partial_and_failure(self):
        completed = self.run_batch_case([True, True])
        partial = self.run_batch_case([True, False])
        failed = self.run_batch_case([False, False])

        self.assertEqual((completed["status"], completed["success_count"], completed["failed_count"]), ("completed", 2, 0))
        self.assertEqual((partial["status"], partial["success_count"], partial["failed_count"]), ("partial_failed", 1, 1))
        self.assertEqual((failed["status"], failed["success_count"], failed["failed_count"]), ("failed", 0, 2))
        self.assertTrue(any(item["kind"] == "archive" for item in completed["artifacts"]))
        self.assertTrue(any(item["kind"] == "archive" for item in partial["artifacts"]))
        self.assertFalse(any(item["kind"] == "archive" for item in failed["artifacts"]))


if __name__ == "__main__":
    unittest.main()
