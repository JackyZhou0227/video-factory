from __future__ import annotations

import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.services import smart_editing, template_production


class SmartEditingTests(unittest.TestCase):
    def test_normalize_keywords_preserves_order_and_allows_duplicates(self):
        self.assertEqual(
            smart_editing.normalize_keywords([" 医院 ", "医生", "医院", "问诊"]),
            ["医院", "医生", "医院", "问诊"],
        )

        for values in (["医院", ""],):
            with self.subTest(values=values), self.assertRaises(smart_editing.SmartEditingError):
                smart_editing.normalize_keywords(values)

        with self.assertRaises(smart_editing.SmartEditingError):
            smart_editing.normalize_keywords("医院,医生")

    def test_parse_keyword_response_preserves_duplicates_and_code_fences(self):
        content = "```json\n[\"诊所\", \"医生\", \"医生\"]\n```"
        self.assertEqual(
            smart_editing.parse_keyword_response(content),
            ["诊所", "医生", "医生"],
        )

    def test_normalize_keywords_rejects_non_chinese_terms(self):
        with self.assertRaisesRegex(smart_editing.SmartEditingError, "必须使用中文"):
            smart_editing.normalize_keywords(["clinic"])

    def test_timeline_is_round_robin_deterministic_and_uses_pacing_range(self):
        materials = [
            {"input_path": Path("hospital-a.jpg"), "media_type": "image", "keyword_index": 0},
            {"input_path": Path("hospital-b.jpg"), "media_type": "image", "keyword_index": 0},
            {"input_path": Path("doctor.mp4"), "media_type": "video", "keyword_index": 1},
            {"input_path": Path("consultation.png"), "media_type": "image", "keyword_index": 2},
        ]

        with patch.object(template_production, "probe_duration", return_value=30.0):
            first = smart_editing.build_timeline(
                materials,
                3,
                24.0,
                seed="task-a:1",
                pacing="standard",
            )
            second = smart_editing.build_timeline(
                materials,
                3,
                24.0,
                seed="task-a:1",
                pacing="standard",
            )

        self.assertEqual(first, second)
        self.assertGreaterEqual(sum(item.duration for item in first), 24.1)
        self.assertTrue(all(2.5 <= item.duration <= 4.0 for item in first))
        self.assertEqual(
            [item.keyword_index for item in first],
            [index % 3 for index in range(len(first))],
        )
        group_zero_paths = [item.source_path for item in first if item.keyword_index == 0]
        self.assertTrue(
            all(current != previous for previous, current in zip(group_zero_paths, group_zero_paths[1:]))
        )

    def test_timeline_rejects_empty_groups_and_missing_paths(self):
        with self.assertRaisesRegex(smart_editing.SmartEditingError, "第 2 个关键词"):
            smart_editing.build_timeline(
                [{"input_path": Path("hospital.jpg"), "media_type": "image", "keyword_index": 0}],
                2,
                5.0,
                seed="missing-group",
            )

        with self.assertRaisesRegex(smart_editing.SmartEditingError, "素材路径不能为空"):
            smart_editing.build_timeline(
                [{"input_path": "", "media_type": "image", "keyword_index": 0}],
                1,
                5.0,
                seed="missing-path",
            )

    def test_video_start_position_is_seeded_and_short_video_can_start_at_zero(self):
        material = [{"input_path": Path("doctor.mp4"), "media_type": "video", "keyword_index": 0}]

        with patch.object(template_production, "probe_duration", return_value=30.0):
            long_video = smart_editing.build_timeline(
                material,
                1,
                4.0,
                seed="long-video",
                pacing="fast",
            )
        self.assertTrue(all(item.start_time > 0 for item in long_video))
        self.assertTrue(all(item.start_time < 30.0 - item.duration for item in long_video))

        with patch.object(template_production, "probe_duration", return_value=1.0):
            short_video = smart_editing.build_timeline(
                material,
                1,
                4.0,
                seed="short-video",
                pacing="fast",
            )
        self.assertTrue(all(item.start_time == 0 for item in short_video))

    def test_compose_prepares_cover_segments_with_image_motion_and_reuses_shared_muxer(self):
        materials = [
            {"input_path": Path("hospital.jpg"), "media_type": "image", "keyword_index": 0},
            {"input_path": Path("doctor.mp4"), "media_type": "video", "keyword_index": 1},
        ]
        timeline = [
            smart_editing.TimelineSegment(Path("hospital.jpg"), "image", 0, 2.0, 0.0),
            smart_editing.TimelineSegment(Path("doctor.mp4"), "video", 1, 3.0, 4.5),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "output.mp4"
            with patch.object(template_production, "require_ffmpeg"), patch.object(
                smart_editing,
                "build_timeline",
                return_value=timeline,
            ), patch.object(template_production, "prepare_material_segment") as prepare, patch.object(
                template_production,
                "compose_prepared_video",
                return_value=output_path,
            ) as compose:
                result = smart_editing.compose_video(
                    materials,
                    2,
                    root / "audio.mp3",
                    output_path,
                    script="这是一条用于测试智能剪辑共享合成逻辑的文案。",
                    work_dir=root / "work",
                    seed="task:1",
                    audio_duration=5.0,
                    subtitle_replacements=[{"source": "医生", "replacement": "yi生"}],
                    bgm_path=root / "bgm.mp3",
                )

        self.assertEqual(result, output_path)
        self.assertEqual(prepare.call_count, 2)
        self.assertTrue(prepare.call_args_list[0].kwargs["image_motion"])
        self.assertFalse(prepare.call_args_list[1].kwargs["image_motion"])
        self.assertEqual(prepare.call_args_list[0].kwargs["fill_mode"], "cover")
        self.assertEqual(prepare.call_args_list[1].kwargs["start_time"], 4.5)
        self.assertFalse(compose.call_args.kwargs["subtitle_style"]["notice_enabled"])
        self.assertEqual(
            compose.call_args.kwargs["subtitle_replacements"],
            [{"source": "医生", "replacement": "yi生"}],
        )
        self.assertEqual(compose.call_args.kwargs["bgm_path"], root / "bgm.mp3")

    def test_image_motion_filter_is_applied_to_ffmpeg_command(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            template_production,
            "require_ffmpeg",
        ), patch.object(template_production, "_run") as run:
            template_production.prepare_material_segment(
                Path(temp_dir) / "image.jpg",
                Path(temp_dir) / "segment.mp4",
                media_type="image",
                ratio="9:16",
                segment_duration=2.0,
                target_size=(180, 320),
                fill_mode="cover",
                image_motion=True,
            )

        command = run.call_args.args[0]
        video_filter = command[command.index("-vf") + 1]
        self.assertIn("zoompan", video_filter)
        self.assertIn("crop=180:320", video_filter)
        self.assertIn("format=yuv420p", video_filter)

    def test_ffmpeg_composition_handles_image_motion_short_video_loop_and_audio_trim(self):
        ffmpeg = template_production.ffmpeg_executable()
        if ffmpeg is None:
            self.skipTest("FFmpeg is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "hospital.png"
            video_path = root / "doctor.mp4"
            audio_path = root / "audio.wav"
            output_path = root / "smart-output.mp4"
            Image.new("RGB", (80, 80), "#d97757").save(image_path)
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=160x90:rate=30",
                    "-t",
                    "0.7",
                    "-pix_fmt",
                    "yuv420p",
                    str(video_path),
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=3.2",
                    str(audio_path),
                ],
                check=True,
                capture_output=True,
            )

            with patch.object(template_production, "ratio_size", return_value=(180, 320)):
                smart_editing.compose_video(
                    [
                        {"input_path": image_path, "media_type": "image", "keyword_index": 0},
                        {"input_path": video_path, "media_type": "video", "keyword_index": 1},
                    ],
                    2,
                    audio_path,
                    output_path,
                    script="这是一条用于验证智能剪辑实际合成效果的测试文案。",
                    work_dir=root / "work",
                    seed="ffmpeg-smart-editing",
                    pacing="fast",
                    audio_duration=3.2,
                )

            self.assertTrue(output_path.is_file())
            self.assertGreater(output_path.stat().st_size, 1000)
            self.assertAlmostEqual(template_production.probe_duration(output_path), 3.2, delta=0.15)


if __name__ == "__main__":
    unittest.main()
