from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.services import template_production


class TemplateProductionTests(unittest.TestCase):
    def test_prompt_and_script_parser(self):
        prompt = template_production.build_script_prompt(
            "zhongyi-xunfang",
            {"address": "武汉", "name": "李医生", "specialty": "中医内科", "feature": "三代从医"},
            3,
        )
        self.assertIn("生成 3 条", prompt)
        self.assertIn("李医生", prompt)
        scripts = template_production.parse_generated_scripts(json.dumps(["这是第一条足够长的测试文案。", "这是第二条足够长的测试文案。"], ensure_ascii=False))
        self.assertEqual(len(scripts), 2)

    def test_zhongyi_prompt_and_structured_script_parsing(self):
        prompt = template_production.build_script_prompt(
            "zhongyi-xunfang",
            {"address": "湖北阳新老街", "name": "马医生", "specialty": "痛风调理", "feature": ""},
            3,
            {"doctor-scene": 2, "clinic-scene": 1},
        )
        self.assertIn("医生专长：痛风调理", prompt)
        self.assertIn("医生特点：未提供", prompt)
        self.assertIn("中医师问诊画面：2 个", prompt)
        self.assertIn("诊所环境画面：1 个", prompt)
        self.assertNotIn("寻访人出镜", prompt)
        self.assertNotIn("患者或候诊", prompt)
        self.assertIn("不得编造中医世家", prompt)
        self.assertIn("150-180 个汉字", prompt)
        self.assertIn("14-18 个短句", prompt)

        sentences = ["中医寻访问诊画面真实" for _ in range(16)]
        content = json.dumps({"scripts": [{"style": "寻访过程", "sentences": sentences}]}, ensure_ascii=False)
        scripts = template_production.parse_generated_scripts(content)
        self.assertEqual(len(template_production.split_script_sentences(scripts[0])), 16)

    def test_zhongyi_timeline_uses_two_material_groups_and_matches_duration(self):
        materials = [
            {"input_path": Path("doctor-a.mp4"), "media_type": "video", "requirement_id": "doctor-scene"},
            {"input_path": Path("doctor-b.mp4"), "media_type": "video", "requirement_id": "doctor-scene"},
            {"input_path": Path("clinic.mp4"), "media_type": "video", "requirement_id": "clinic-scene"},
        ]
        with patch.object(template_production, "probe_duration", return_value=30.0):
            first = template_production.build_zhongyi_timeline(materials, 40.0, seed="task-1")
            second = template_production.build_zhongyi_timeline(materials, 40.0, seed="task-1")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 7)
        self.assertEqual(first[1].requirement_id, "clinic-scene")
        self.assertEqual(first[2].requirement_id, "doctor-scene")
        self.assertEqual(
            {item.requirement_id for item in first},
            {"doctor-scene", "clinic-scene"},
        )
        visible_duration = sum(item.duration for item in first) - 6 * template_production.ZHONGYI_TRANSITION_DURATION
        self.assertAlmostEqual(visible_duration, 40.0, places=5)

    def test_subtitle_fallback_covers_full_audio(self):
        cues = template_production.build_subtitle_cues("第一句\n这是稍长一些的第二句\n最后一句", 9.0)
        self.assertEqual(cues[0][0], 0)
        self.assertEqual(cues[-1][1], 9.0)
        self.assertTrue(all(start < end for start, end, _ in cues))

    def test_subtitle_replacements_are_literal_longest_first_and_non_cascading(self):
        replacements = [
            {"source": "医生", "replacement": "yi生"},
            {"source": "医生介绍", "replacement": "专家介绍"},
            {"source": "生", "replacement": "sheng"},
        ]

        result = template_production.apply_subtitle_replacements("医生介绍医生生", replacements)

        self.assertEqual(result, "专家介绍yi生sheng")

    def test_subtitle_replacements_apply_after_cue_timing_is_built(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ass_path = template_production.write_zhongyi_ass(
                "医生介绍\n医生问诊",
                4.0,
                Path(temp_dir) / "subtitles.ass",
                target_size=(1080, 1920),
                subtitle_replacements=[{"source": "医生", "replacement": "yi生"}],
            )

            content = ass_path.read_text(encoding="utf-8-sig")
            self.assertIn("yi生介绍", content)
            self.assertIn("yi生问诊", content)
            self.assertNotIn(",,医生", content)

    def test_zhongyi_safety_notice_uses_lower_top_margin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ass_path = template_production.write_zhongyi_ass(
                "测试文案",
                3.0,
                Path(temp_dir) / "subtitles.ass",
                target_size=(1080, 1920),
            )

            notice_style = next(
                line for line in ass_path.read_text(encoding="utf-8-sig").splitlines() if line.startswith("Style: Notice,")
            )
            style_fields = notice_style.split(",")
            self.assertEqual(style_fields[2], str(max(22, round(1920 * 0.017))))
            self.assertEqual(style_fields[-2], str(max(34, round(1920 * 0.055))))

    def test_material_sequence_is_deterministic_and_fills_duration(self):
        segments = [Path("a.mp4"), Path("b.mp4"), Path("c.mp4")]
        first = template_production.build_material_sequence(segments, 13, seed="task-1")
        second = template_production.build_material_sequence(segments, 13, seed="task-1")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        self.assertNotEqual(first[0], first[1])

    def test_ffmpeg_image_video_and_audio_composition(self):
        ffmpeg = template_production.ffmpeg_executable()
        if ffmpeg is None:
            self.skipTest("FFmpeg is not installed")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "image.png"
            Image.new("RGB", (64, 64), "#d97757").save(image_path)
            source_video = root / "source.mp4"
            audio_path = root / "audio.wav"
            subprocess.run(
                [ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=30", "-t", "1", "-pix_fmt", "yuv420p", str(source_video)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2.2", str(audio_path)],
                check=True,
                capture_output=True,
            )

            image_segment = template_production.prepare_material_segment(
                image_path,
                root / "image-segment.mp4",
                media_type="image",
                ratio="9:16",
                segment_duration=1,
                target_size=(180, 320),
            )
            video_segment = template_production.prepare_material_segment(
                source_video,
                root / "video-segment.mp4",
                media_type="video",
                ratio="9:16",
                segment_duration=1,
                target_size=(180, 320),
            )
            output_path = template_production.compose_video(
                [image_segment, video_segment],
                audio_path,
                root / "output.mp4",
                seed="integration",
                segment_duration=1,
            )
            self.assertTrue(output_path.exists())
            self.assertGreater(output_path.stat().st_size, 1000)
            self.assertGreater(template_production.probe_duration(output_path), 1.8)

            zhongyi_output = root / "zhongyi-output.mp4"
            materials = [
                {"input_path": source_video, "media_type": "video", "requirement_id": "doctor-scene"},
                {"input_path": source_video, "media_type": "video", "requirement_id": "clinic-scene"},
            ]
            with patch.object(template_production, "ratio_size", return_value=(180, 320)):
                template_production.compose_zhongyi_video(
                    materials,
                    audio_path,
                    zhongyi_output,
                    script="走在湖北阳新的老街上\n我终于找到了马医生\n这里保留着真实的问诊日常",
                    work_dir=root / "zhongyi-work",
                    seed="zhongyi-integration",
                    audio_duration=2.2,
                )
            self.assertTrue(zhongyi_output.exists())
            self.assertAlmostEqual(template_production.probe_duration(zhongyi_output), 2.2, delta=0.15)

            subtitle_frame = root / "subtitle-frame.png"
            subprocess.run(
                [ffmpeg, "-y", "-ss", "1", "-i", str(zhongyi_output), "-frames:v", "1", str(subtitle_frame)],
                check=True,
                capture_output=True,
            )
            frame = Image.open(subtitle_frame).convert("RGB")
            yellow_pixels = sum(1 for red, green, blue in frame.getdata() if red > 175 and green > 130 and blue < 120)
            self.assertGreater(yellow_pixels, 20)


if __name__ == "__main__":
    unittest.main()
