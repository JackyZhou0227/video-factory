from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.schemas.template_definition import TemplateDefinition
from app.services import template_production


def _generic_template(response_format: str = "plain_scripts_v1") -> TemplateDefinition:
    return TemplateDefinition.model_validate({
        "schema_version": 1,
        "template_version": 1,
        "id": "generic-test-template",
        "name": "通用测试模板",
        "description": "用于服务层单元测试。",
        "content_fields": [
            {
                "key": "tone",
                "label": "表达风格",
                "input_type": "select",
                "required": True,
                "default": "calm",
                "options": [
                    {"value": "calm", "label": "克制"},
                    {"value": "warm", "label": "温暖"},
                ],
            },
            {
                "key": "subject",
                "label": "介绍对象",
                "required": True,
                "min_length": 2,
                "max_length": 100,
            },
        ],
        "material_requirements": [
            {
                "key": "main-image",
                "label": "主体图片",
                "description": "用于视频主体画面的图片。",
                "media_type": "image",
                "min_count": 1,
                "max_count": 2,
            }
        ],
        "script_generation": {
            "system_prompt": "你是短视频文案编导。",
            "prompt_template": "生成 {{candidate_count}} 条文案。\n{{content_context}}\n{{material_context}}\n{{response_contract}}",
            "rewrite_prompt_template": "重写 {{original_script}}\n{{content_context}}\n{{response_contract}}",
            "response_format": response_format,
            "default_candidate_count": 3,
            "temperature": 0.75,
            "max_tokens": 2400,
        },
        "production": {
            "pipeline_id": "generic_concat_v1",
            "default_ratio": "9:16",
            "default_batch_size": 5,
            "max_batch_size": 50,
        },
    })


class TemplateProductionTests(unittest.TestCase):
    def test_prompt_and_script_parser(self):
        prompt = template_production.build_script_prompt(
            _generic_template(),
            {"subject": "王医生"},
            3,
        )
        self.assertIn("生成 3 条文案", prompt)
        self.assertIn("介绍对象：王医生", prompt)
        scripts = template_production.parse_generated_scripts(json.dumps(["这是第一条足够长的测试文案。", "这是第二条足够长的测试文案。"], ensure_ascii=False))
        self.assertEqual(len(scripts), 2)

    def test_segmented_prompt_and_structured_script_parsing(self):
        template = _generic_template(response_format="segmented_scripts_v1")
        prompt = template_production.build_script_prompt(
            template,
            {"subject": "王医生"},
            1,
            {"main-image": 2},
        )
        self.assertIn("介绍对象：王医生", prompt)
        self.assertIn("主体图片：2 个", prompt)
        self.assertIn("文案风格", prompt)

        sentences = ["这条口播内容真实自然且完整" for _ in range(16)]
        content = json.dumps({"scripts": [{"style": "口播", "sentences": sentences}]}, ensure_ascii=False)
        scripts = template_production.parse_generated_scripts(content)
        self.assertEqual(len(template_production.split_script_sentences(scripts[0])), 16)

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
            ass_path = template_production.write_subtitle_ass(
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

    def test_generic_subtitles_apply_replacements_with_shared_safety_notice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ass_path = template_production.write_subtitle_ass(
                "医生介绍\n医生问诊",
                4.0,
                Path(temp_dir) / "subtitles.ass",
                target_size=(1080, 1920),
                subtitle_replacements=[{"source": "医生", "replacement": "yi生"}],
            )

            content = ass_path.read_text(encoding="utf-8-sig")
            self.assertIn("yi生介绍", content)
            self.assertIn("yi生问诊", content)
            self.assertIn("Style: Notice,", content)
            notice = template_production.DEFAULT_SUBTITLE_STYLE["notice_text"]
            self.assertIn(notice.replace("\n", "\\N"), content)

    def test_shared_safety_notice_uses_lower_top_margin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ass_path = template_production.write_subtitle_ass(
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

    def test_default_subtitle_style_keeps_current_ass_visual_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ass_path = template_production.write_subtitle_ass(
                "测试文案",
                3.0,
                Path(temp_dir) / "subtitles.ass",
                target_size=(1080, 1920),
            )

            styles = {
                line.split(",", 2)[0].removeprefix("Style: "): line.split(",")
                for line in ass_path.read_text(encoding="utf-8-sig").splitlines()
                if line.startswith("Style: ")
            }
            self.assertEqual(styles["Subtitle"][1:], [
                "Microsoft YaHei", "65", "&H001FD2FF", "&H001FD2FF", "&H00000000", "&H70000000",
                "-1", "0", "0", "0", "100", "100", "0", "0", "1", "5", "1", "2", "70", "70", "250", "1",
            ])
            self.assertEqual(styles["Notice"][1:], [
                "Microsoft YaHei", "33", "&H00FFFFFF", "&H00FFFFFF", "&H50000000", "&H50000000",
                "0", "0", "0", "0", "100", "100", "0", "0", "1", "1", "1", "8", "50", "50", "106", "1",
            ])

    def test_default_subtitle_style_keeps_legacy_scaling_for_other_output_ratios(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for height in (1080, 1440):
                ass_path = template_production.write_subtitle_ass(
                    "测试文案",
                    3.0,
                    Path(temp_dir) / f"subtitles-{height}.ass",
                    target_size=(1080, height),
                )
                styles = {
                    line.split(",", 2)[0].removeprefix("Style: "): line.split(",")
                    for line in ass_path.read_text(encoding="utf-8-sig").splitlines()
                    if line.startswith("Style: ")
                }

                self.assertEqual(styles["Subtitle"][2], str(max(34, round(height * 0.034))))
                self.assertEqual(styles["Subtitle"][16], str(max(3, round(height * 0.0026))))
                self.assertEqual(styles["Subtitle"][21], str(max(80, round(height * 0.13))))
                self.assertEqual(styles["Notice"][2], str(max(22, round(height * 0.017))))
                self.assertEqual(styles["Notice"][16], "1")
                self.assertEqual(styles["Notice"][21], str(max(34, round(height * 0.055))))

    def test_normalize_subtitle_style_rejects_non_boolean_notice_and_non_finite_numbers(self):
        style = template_production.normalize_subtitle_style(
            {"font_size": float("inf"), "notice_enabled": "false"}
        )

        self.assertEqual(style["font_size"], template_production.DEFAULT_SUBTITLE_STYLE["font_size"])
        self.assertTrue(style["notice_enabled"])
        self.assertFalse(template_production.normalize_subtitle_style({"notice_enabled": False})["notice_enabled"])

    def test_custom_subtitle_style_updates_ass_and_can_hide_notice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ass_path = template_production.write_subtitle_ass(
                "测试文案",
                3.0,
                Path(temp_dir) / "subtitles.ass",
                target_size=(1080, 1920),
                subtitle_style={
                    "font_family": "SimHei",
                    "font_size": 72,
                    "color": "#123456",
                    "outline_color": "#FEDCBA",
                    "outline_width": 3,
                    "bottom_margin": 190,
                    "alignment": "left",
                    "notice_enabled": False,
                },
            )

            content = ass_path.read_text(encoding="utf-8-sig")
            self.assertIn("Style: Subtitle,SimHei,72,&H00563412,&H00563412,&H00BADCFE,&H70000000,", content)
            self.assertIn("1,3,1,1,70,70,190,1", content)
            self.assertNotIn("Style: Notice,", content)
            self.assertNotIn(",Notice,,", content)

    def test_custom_notice_content_and_style_are_rendered(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ass_path = template_production.write_subtitle_ass(
                "测试文案",
                3.0,
                Path(temp_dir) / "subtitles.ass",
                target_size=(1080, 1920),
                subtitle_style={
                    "notice_text": "请谨遵医嘱\n内容仅作参考",
                    "notice_font_size": 42,
                    "notice_color": "#112233",
                    "notice_outline_color": "#445566",
                    "notice_outline_width": 2,
                    "notice_top_margin": 70,
                },
            )

            content = ass_path.read_text(encoding="utf-8-sig")
            self.assertIn("Style: Notice,Microsoft YaHei,42,&H00332211,&H00332211,&H50665544,&H50000000,", content)
            self.assertIn("1,2,1,8,50,50,70,1", content)
            self.assertIn("请谨遵医嘱\\N内容仅作参考", content)

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
                script="医生介绍",
                work_dir=root / "generic-work",
                subtitle_replacements=[{"source": "医生", "replacement": "yi生"}],
            )
            self.assertTrue(output_path.exists())
            self.assertGreater(output_path.stat().st_size, 1000)
            self.assertGreater(template_production.probe_duration(output_path), 1.8)
            self.assertFalse((root / "generic-work" / "subtitles.ass").exists())

            subtitle_frame = root / "subtitle-frame.png"
            subprocess.run(
                [ffmpeg, "-y", "-ss", "1", "-i", str(output_path), "-frames:v", "1", str(subtitle_frame)],
                check=True,
                capture_output=True,
            )
            frame = Image.open(subtitle_frame).convert("RGB")
            yellow_pixels = sum(1 for red, green, blue in frame.getdata() if red > 175 and green > 130 and blue < 120)
            self.assertGreater(yellow_pixels, 20)


if __name__ == "__main__":
    unittest.main()
