from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

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

    def test_material_sequence_is_deterministic_and_fills_duration(self):
        segments = [Path("a.mp4"), Path("b.mp4"), Path("c.mp4")]
        first = template_production.build_material_sequence(segments, 13, seed="task-1")
        second = template_production.build_material_sequence(segments, 13, seed="task-1")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        self.assertNotEqual(first[0], first[1])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is not installed")
    def test_ffmpeg_image_video_and_audio_composition(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "image.png"
            Image.new("RGB", (64, 64), "#d97757").save(image_path)
            source_video = root / "source.mp4"
            audio_path = root / "audio.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=30", "-t", "1", "-pix_fmt", "yuv420p", str(source_video)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2.2", str(audio_path)],
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


if __name__ == "__main__":
    unittest.main()
