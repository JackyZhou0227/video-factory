from __future__ import annotations

import json
import math
import subprocess
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.services import poster_video


class PosterTimingTests(unittest.TestCase):
    def test_timing_rules(self):
        cases = [
            ("image", None, 15, 60, 15, 1, 1),
            ("image", None, None, 60, 60, 1, 1),
            ("video", 10, 15, 60, 10, 1, 1.5),
            ("video", 30, 15, 60, 15, 2, 1),
            ("video", 15, 15, None, 15, 1, 1),
            ("video", 15, None, 60, 15, 1, 1),
            ("video", 15, None, None, 15, 1, 1),
            ("video", 10, 90, None, 10, 1, 9),
        ]
        for source, video, narration, bgm, target, video_speed, narration_speed in cases:
            with self.subTest(source=source, video=video, narration=narration, bgm=bgm):
                result = poster_video.calculate_timing(
                    source, video_duration=video, narration_duration=narration, bgm_duration=bgm
                )
                self.assertEqual(result, {
                    "source_type": source,
                    "target_duration": target,
                    "video_speed": video_speed,
                    "narration_speed": narration_speed,
                })

    def test_image_requires_audio_and_durations_must_be_finite_and_positive(self):
        with self.assertRaises(poster_video.PosterVideoError):
            poster_video.calculate_timing("image")
        for value in (0, -1, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(poster_video.PosterVideoError):
                poster_video.calculate_timing("video", video_duration=value)
            with self.subTest(audio=value), self.assertRaises(poster_video.PosterVideoError):
                poster_video.calculate_timing("image", narration_duration=value, bgm_duration=60)

    def test_atempo_chain_preserves_large_and_precise_ratios(self):
        for rate in (1, 1.2, 1.56789, 2, 3, 9, 128):
            with self.subTest(rate=rate):
                parts = poster_video.build_atempo_filter(rate).split(",")
                factors = [float(part.removeprefix("atempo=")) for part in parts]
                self.assertTrue(all(1 <= value <= 2 for value in factors))
                self.assertAlmostEqual(math.prod(factors), rate, places=6)
        for rate in (0, 0.5, float("inf"), float("nan")):
            with self.subTest(rate=rate), self.assertRaises(poster_video.PosterVideoError):
                poster_video.build_atempo_filter(rate)

    def test_probe_uses_stream_duration_and_ignores_album_art(self):
        payload = {
            "format": {"duration": "60"},
            "streams": [
                {"codec_type": "video", "duration": "15", "width": 160, "height": 90},
                {"codec_type": "audio", "duration": "60"},
            ],
        }
        with patch.object(poster_video.shutil, "which", return_value="ffprobe"), patch.object(
            poster_video.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, json.dumps(payload), ""),
        ):
            info = poster_video.probe_media(Path("video.mp4"))
        self.assertEqual(info["video_duration"], 15)
        self.assertEqual(info["audio_duration"], 60)
        payload["streams"][0]["disposition"] = {"attached_pic": 1}
        with patch.object(poster_video.shutil, "which", return_value="ffprobe"), patch.object(
            poster_video.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, json.dumps(payload), ""),
        ):
            info = poster_video.probe_media(Path("audio.mp3"))
        self.assertFalse(info["has_video"])
        self.assertTrue(info["has_audio"])

    def test_probe_rejects_invalid_duration_and_audio_without_audio_stream(self):
        for payload in (
            {"streams": [{"codec_type": "audio", "duration": "NaN"}]},
            {"streams": [{"codec_type": "audio", "duration": "0"}]},
            {"streams": [{"codec_type": "video", "duration": "1"}]},
        ):
            with self.subTest(payload=payload), patch.object(
                poster_video.shutil, "which", return_value="ffprobe"
            ), patch.object(
                poster_video.subprocess, "run",
                return_value=subprocess.CompletedProcess([], 0, json.dumps(payload), ""),
            ), self.assertRaises(poster_video.PosterVideoError):
                poster_video.probe_audio_duration(Path("invalid.wav"))

    def test_probe_rejects_nonfinite_start_times(self):
        for kind in ("video", "audio"):
            for start in ("NaN", "inf", "-inf"):
                with self.subTest(kind=kind, start=start), patch.object(
                    poster_video, "_probe_streams",
                    return_value={"streams": [
                        {"codec_type": kind, "duration": "1.2", "start_time": start},
                    ]},
                ), self.assertRaises(poster_video.PosterVideoError):
                    poster_video.probe_media(Path("invalid-start.mp4"))

    def test_composition_selects_video_excluding_attached_pictures(self):
        command = poster_video._compose_command(
            Path("video.mp4"), Path("overlay.png"), Path("output.mp4"),
            timing=poster_video.calculate_timing("video", video_duration=1.2),
            has_original_audio=False, narration_path=None, bgm_path=None,
        )
        self.assertIn("[0:V:0]", command[command.index("-filter_complex") + 1])
        with patch.object(poster_video.shutil, "which", return_value=None), patch.object(
            poster_video, "ffmpeg_executable", return_value="ffmpeg",
        ), patch.object(
            poster_video.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 1, "", (
                "Stream #0:0: Video: png, rgba, 180x320 (attached pic)\n"
                "Stream #0:1: Video: h264, yuv420p, 160x90\n"
            )),
        ), patch.object(
            poster_video, "_decode_stream_timing",
            return_value={"duration": 1.2, "start_time": 0.0},
        ) as decode:
            self.assertAlmostEqual(poster_video.probe_media(Path("video.mp4"))["video_duration"], 1.2)
        self.assertEqual(decode.call_args.args[1], "0:V:0")


class PosterCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = poster_video.ffmpeg_executable()
        if not cls.ffmpeg:
            raise unittest.SkipTest("FFmpeg is not installed")
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.image = cls.root / "picture.png"
        cls.overlay = cls.root / "overlay.png"
        cls.video = cls.root / "video.mp4"
        cls.silent_video = cls.root / "silent.mp4"
        Image.new("RGB", (160, 90), "#335588").save(cls.image)
        Image.new("RGBA", (180, 320), (0, 0, 0, 0)).save(cls.overlay)
        for name, duration, frequency in (
            ("voice_short", 0.6, 440),
            ("voice_long", 3.6, 440),
            ("bgm_short", 0.3, 880),
            ("bgm_long", 2.4, 880),
        ):
            cls.run_ffmpeg([
                "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={duration}",
                str(cls.root / f"{name}.wav"),
            ])
        cls.run_ffmpeg([
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=1.2",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=0.3",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(cls.video),
        ])
        cls.run_ffmpeg(["-i", str(cls.video), "-an", "-c:v", "copy", str(cls.silent_video)])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def run_ffmpeg(cls, args):
        return subprocess.run(
            [cls.ffmpeg, "-y", "-hide_banner", *args], check=True, capture_output=True,
            timeout=30,
        )

    def compose(self, name, source=None, **options):
        output = self.root / f"{name}.mp4"
        with patch.object(poster_video, "TARGET_WIDTH", 180), patch.object(
            poster_video, "TARGET_HEIGHT", 320
        ):
            result = poster_video.process_video(
                source or self.video, self.overlay, output, **options
            )
        info = poster_video.probe_media(output)
        self.assertAlmostEqual(info["video_duration"], result["target_duration"], delta=0.15)
        self.assertGreater(output.stat().st_size, 1000)
        return output, result, info

    def test_image_uses_narration_before_bgm_and_bgm_only_duration(self):
        _, result, info = self.compose(
            "image_voice", self.image, source_type="image",
            narration_path=self.root / "voice_short.wav", bgm_path=self.root / "bgm_long.wav",
        )
        self.assertAlmostEqual(result["target_duration"], 0.6, places=2)
        self.assertTrue(info["has_audio"])
        _, result, _ = self.compose(
            "image_music", self.image, source_type="image", bgm_path=self.root / "bgm_long.wav",
        )
        self.assertAlmostEqual(result["target_duration"], 2.4, places=2)

    def test_long_narration_accelerates_above_two_times(self):
        _, result, info = self.compose(
            "long_voice", narration_path=self.root / "voice_long.wav",
        )
        self.assertAlmostEqual(result["narration_speed"], 3, places=2)
        self.assertAlmostEqual(info["audio_duration"], 1.2, delta=0.15)

    def test_short_narration_accelerates_video_and_original_audio(self):
        with patch.object(poster_video, "_run_ffmpeg", wraps=poster_video._run_ffmpeg) as run:
            _, result, info = self.compose(
                "short_voice", narration_path=self.root / "voice_short.wav", mute_original_audio=False,
            )
        self.assertAlmostEqual(result["video_speed"], 2, places=2)
        command = run.call_args.args[0]
        filters = command[command.index("-filter_complex") + 1]
        self.assertIn("atempo=2", filters)
        self.assertAlmostEqual(info["audio_duration"], 0.6, delta=0.15)

    def test_bgm_loops_and_does_not_change_video_duration(self):
        output, result, _ = self.compose(
            "looped_music", bgm_path=self.root / "bgm_short.wav",
        )
        self.assertAlmostEqual(result["target_duration"], 1.2, places=2)
        tail = self.run_ffmpeg([
            "-sseof", "-0.15", "-i", str(output), "-vn", "-ac", "1",
            "-f", "s16le", "-",
        ]).stdout
        self.assertGreater(len(tail), 100)
        samples = array("h")
        samples.frombytes(tail)
        self.assertGreater(max(abs(value) for value in samples), 400)

    def test_default_mutes_original_and_short_original_does_not_truncate_video(self):
        _, _, muted = self.compose("muted")
        self.assertFalse(muted["has_audio"])
        _, _, audible = self.compose("original", mute_original_audio=False)
        self.assertTrue(audible["has_audio"])
        self.assertAlmostEqual(audible["audio_duration"], 1.2, delta=0.15)
        _, _, silent = self.compose("no_audio", self.silent_video, mute_original_audio=False)
        self.assertFalse(silent["has_audio"])

    def test_probe_and_composition_without_ffprobe(self):
        original_which = poster_video.shutil.which
        with patch.object(
            poster_video.shutil, "which",
            side_effect=lambda name: None if name == "ffprobe" else original_which(name),
        ):
            info = poster_video.probe_media(self.video)
            self.assertTrue(info["has_audio"])
            self.assertAlmostEqual(info["video_duration"], 1.2, delta=0.15)
            self.compose("fallback_probe", narration_path=self.root / "voice_short.wav")

    def test_offset_mkv_uses_stream_span_instead_of_end_timestamp(self):
        source = self.root / "offset.mkv"
        self.run_ffmpeg([
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=1.2",
            "-vf", "setpts=PTS+2/TB", "-fps_mode", "passthrough",
            "-c:v", "libx264", str(source),
        ])
        info = poster_video.probe_media(source)
        self.assertAlmostEqual(info["video_duration"], 1.2, delta=0.02)
        _, timing, info = self.compose("offset_mkv_normal", source)
        self.assertAlmostEqual(timing["target_duration"], 1.2, delta=0.02)
        self.assertAlmostEqual(info["video_duration"], 1.2, delta=0.04)
        _, timing, info = self.compose(
            "offset_mkv_fast", source, narration_path=self.root / "voice_short.wav",
        )
        self.assertAlmostEqual(timing["video_speed"], 2, delta=0.02)
        self.assertAlmostEqual(info["video_duration"], 0.6, delta=0.04)

    def test_offset_mp4_without_ffprobe_uses_stream_span(self):
        source = self.root / "offset.mp4"
        self.run_ffmpeg([
            "-itsoffset", "2", "-f", "lavfi", "-i",
            "testsrc2=size=160x90:rate=30:duration=1.2",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=3.2",
            "-fps_mode", "passthrough", "-c:v", "libx264", "-c:a", "aac", str(source),
        ])
        original_which = poster_video.shutil.which
        with patch.object(
            poster_video.shutil, "which",
            side_effect=lambda name: None if name == "ffprobe" else original_which(name),
        ):
            info = poster_video.probe_media(source)
            self.assertAlmostEqual(info["video_duration"], 1.2, delta=0.02)
            _, timing, info = self.compose("offset_mp4_normal", source)
            self.assertAlmostEqual(timing["target_duration"], 1.2, delta=0.02)
            self.assertAlmostEqual(info["video_duration"], 1.2, delta=0.04)
            _, timing, info = self.compose(
                "offset_mp4_fast", source, narration_path=self.root / "voice_short.wav",
            )
            self.assertAlmostEqual(timing["video_speed"], 2, delta=0.02)
            self.assertAlmostEqual(info["video_duration"], 0.6, delta=0.04)

    def test_live_webm_without_duration_metadata_uses_decoded_span(self):
        source = self.root / "live.webm"
        self.run_ffmpeg([
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=1.2",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=2.4",
            "-c:v", "libvpx-vp9", "-c:a", "libopus", "-live", "1", str(source),
        ])
        original_which = poster_video.shutil.which
        for without_ffprobe in (False, True):
            with self.subTest(without_ffprobe=without_ffprobe), patch.object(
                poster_video.shutil, "which",
                side_effect=lambda name: (
                    None if without_ffprobe and name == "ffprobe" else original_which(name)
                ),
            ):
                info = poster_video.probe_media(source)
                self.assertAlmostEqual(info["video_duration"], 1.2, delta=0.02)
                self.assertAlmostEqual(info["audio_duration"], 2.4, delta=0.03)
                _, timing, info = self.compose(f"live_webm_{without_ffprobe}", source)
                self.assertAlmostEqual(timing["target_duration"], 1.2, delta=0.02)
                self.assertAlmostEqual(info["video_duration"], 1.2, delta=0.04)

    def test_invalid_duration_metadata_does_not_fall_back_to_valid_audio(self):
        for field, value in (
            ("duration", "NaN"), ("duration", "0"),
            ("tag", "NaN"), ("tag", "00:00:00.000000000"),
            ("container", "NaN"), ("container", "0"),
        ):
            stream = {"codec_type": "audio", "index": 0}
            container = {"duration": "0.6"}
            if field == "tag":
                stream["tags"] = {"DURATION": value}
            elif field == "container":
                container["duration"] = value
            else:
                stream["duration"] = value
            with self.subTest(field=field, value=value), patch.object(
                poster_video, "_probe_streams",
                return_value={"streams": [stream], "format": container},
            ), self.assertRaises(poster_video.PosterVideoError):
                poster_video.probe_audio_duration(self.root / "voice_short.wav")

    def test_delayed_original_audio_keeps_offset_scaled_by_video_speed(self):
        source = self.root / "delayed_original.mp4"
        self.run_ffmpeg([
            "-itsoffset", "2", "-f", "lavfi", "-i",
            "testsrc2=size=160x90:rate=30:duration=1.2",
            "-itsoffset", "2.6", "-f", "lavfi", "-i", "sine=frequency=220:duration=0.4",
            "-fps_mode", "passthrough", "-c:v", "libx264", "-c:a", "aac", str(source),
        ])
        narration = self.root / "silent_narration.wav"
        self.run_ffmpeg([
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.6", str(narration),
        ])
        original_which = poster_video.shutil.which
        for without_ffprobe in (False, True):
            for speed, target, onset, end in ((1, 1.2, 0.6, 1.0), (2, 0.6, 0.3, 0.5)):
                with self.subTest(without_ffprobe=without_ffprobe, speed=speed), patch.object(
                    poster_video.shutil, "which",
                    side_effect=lambda name: (
                        None if without_ffprobe and name == "ffprobe" else original_which(name)
                    ),
                ):
                    output, timing, info = self.compose(
                        f"delayed_original_{without_ffprobe}_{speed}", source,
                        mute_original_audio=False,
                        narration_path=narration if speed == 2 else None,
                    )
                    self.assertAlmostEqual(timing["video_speed"], speed, delta=0.02)
                    self.assertAlmostEqual(info["video_duration"], target, delta=0.04)
                    self.assertAlmostEqual(info["audio_duration"], target, delta=0.04)
                    samples = array("h")
                    samples.frombytes(self.run_ffmpeg([
                        "-i", str(output), "-vn", "-ac", "1", "-ar", "48000",
                        "-f", "s16le", "-",
                    ]).stdout)
                    audible = [index for index, value in enumerate(samples) if abs(value) > 300]
                    self.assertTrue(audible)
                    self.assertAlmostEqual(audible[0] / 48000, onset, delta=0.04)
                    self.assertAlmostEqual(audible[-1] / 48000, end, delta=0.05)

    def test_failure_removes_partial_output(self):
        output = self.root / "partial.mp4"

        def fail(command):
            output.write_bytes(b"partial")
            raise subprocess.CalledProcessError(1, command, stderr="encoder failed")

        with patch.object(poster_video, "_run_ffmpeg", side_effect=fail), self.assertRaises(
            poster_video.PosterVideoError
        ):
            poster_video.process_video(self.video, self.overlay, output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
