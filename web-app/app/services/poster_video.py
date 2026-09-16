from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920

COMMON_FONT_FILES = [
    ("Microsoft YaHei", "msyh.ttc"),
    ("Microsoft YaHei Bold", "msyhbd.ttc"),
    ("SimHei", "simhei.ttf"),
    ("SimSun", "simsun.ttc"),
    ("DengXian", "Deng.ttf"),
    ("DengXian Bold", "Dengb.ttf"),
    ("KaiTi", "simkai.ttf"),
    ("FangSong", "simfang.ttf"),
]

FONT_EXTENSIONS = {".ttf", ".ttc", ".otf"}


class PosterVideoError(RuntimeError):
    pass


def ffmpeg_executable() -> str | None:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def require_ffmpeg() -> None:
    if ffmpeg_executable() is None:
        raise PosterVideoError("缺少 FFmpeg，请安装系统 FFmpeg 或 imageio-ffmpeg 依赖")


def discover_fonts() -> list[dict[str, str]]:
    seen: set[str] = set()
    fonts: list[dict[str, str]] = []
    font_dir = Path("C:/Windows/Fonts")

    def add_font(label: str, path: Path) -> None:
        resolved = str(path.resolve())
        if resolved in seen or not path.exists():
            return
        seen.add(resolved)
        fonts.append({"label": label, "path": resolved})

    for label, filename in COMMON_FONT_FILES:
        add_font(label, font_dir / filename)

    if font_dir.exists():
        for path in sorted(font_dir.iterdir(), key=lambda item: item.name.lower()):
            if path.suffix.lower() in FONT_EXTENSIONS:
                add_font(path.stem, path)

    return fonts


def _font_path_from_template(font_path: str | None) -> str:
    fonts = discover_fonts()
    allowed_paths = {font["path"] for font in fonts}
    if font_path and str(Path(font_path).resolve()) in allowed_paths:
        return str(Path(font_path).resolve())
    if fonts:
        return fonts[0]["path"]
    raise PosterVideoError("No usable font found. Please install a Chinese TrueType/OpenType font.")


def _parse_color(value: str | None, default: str, opacity: float | None = None) -> tuple[int, int, int, int]:
    raw = (value or default).strip()
    try:
        rgba = ImageColor.getcolor(raw, "RGBA")
    except ValueError:
        rgba = ImageColor.getcolor(default, "RGBA")
    if opacity is None:
        return rgba
    alpha = max(0, min(255, round(255 * max(0.0, min(1.0, opacity)))))
    return rgba[:3] + (alpha,)


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _as_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    if not text.strip():
        return []

    lines: list[str] = []
    for paragraph in text.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue

        current = ""
        for char in paragraph:
            candidate = f"{current}{char}"
            bbox = draw.textbbox((0, 0), candidate, font=font, stroke_width=0)
            if bbox[2] - bbox[0] <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = char
        if current:
            lines.append(current)

    return lines


def _draw_text_block(draw: ImageDraw.ImageDraw, block: dict[str, Any]) -> None:
    text = str(block.get("text") or "").strip()
    if not text:
        return

    x = round(_as_float(block.get("x"), 10, 0, 100) / 100 * TARGET_WIDTH)
    y = round(_as_float(block.get("y"), 10, 0, 100) / 100 * TARGET_HEIGHT)
    width = round(_as_float(block.get("width"), 80, 5, 100) / 100 * TARGET_WIDTH)
    font_size = _as_int(block.get("fontSize"), 64, 18, 180)
    padding_x = _as_int(block.get("paddingX"), 28, 0, 120)
    padding_y = _as_int(block.get("paddingY"), 18, 0, 120)
    radius = _as_int(block.get("radius"), 10, 0, 80)
    stroke_width = _as_int(block.get("strokeWidth"), 0, 0, 16)
    line_height = _as_float(block.get("lineHeight"), 1.18, 0.9, 2.0)
    align = str(block.get("align") or "center").lower()
    if align not in {"left", "center", "right"}:
        align = "center"

    font_path = _font_path_from_template(block.get("fontPath"))
    font = ImageFont.truetype(font_path, font_size)
    max_text_width = max(1, width - padding_x * 2)
    lines = _wrap_text(draw, text, font, max_text_width)
    if not lines:
        return

    line_gap = round(font_size * max(0, line_height - 1))
    metrics = [draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width) for line in lines]
    line_heights = [max(1, bbox[3] - bbox[1]) for bbox in metrics]
    text_height = sum(line_heights) + line_gap * max(0, len(lines) - 1)
    box_height = text_height + padding_y * 2

    bg_opacity = _as_float(block.get("backgroundOpacity"), 1.0, 0, 1)
    bg_color = _parse_color(block.get("backgroundColor"), "#ffffff", bg_opacity)
    if bg_color[3] > 0:
        draw.rounded_rectangle([x, y, x + width, y + box_height], radius=radius, fill=bg_color)

    color = _parse_color(block.get("color"), "#111111")
    stroke_color = _parse_color(block.get("strokeColor"), "#000000")
    cursor_y = y + padding_y
    for index, line in enumerate(lines):
        bbox = metrics[index]
        line_width = bbox[2] - bbox[0]
        if align == "left":
            text_x = x + padding_x
        elif align == "right":
            text_x = x + width - padding_x - line_width
        else:
            text_x = x + (width - line_width) / 2
        draw.text(
            (text_x, cursor_y - bbox[1]),
            line,
            font=font,
            fill=color,
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
        )
        cursor_y += line_heights[index] + line_gap


def parse_template(template_json: str) -> dict[str, Any]:
    try:
        template = json.loads(template_json)
    except json.JSONDecodeError as exc:
        raise PosterVideoError("template must be valid JSON") from exc
    if not isinstance(template, dict):
        raise PosterVideoError("template must be a JSON object")
    blocks = template.get("blocks")
    if not isinstance(blocks, list):
        raise PosterVideoError("template.blocks must be a list")
    return {"blocks": [block for block in blocks if isinstance(block, dict)]}


def create_overlay(template: dict[str, Any], output_path: Path) -> None:
    overlay = Image.new("RGBA", (TARGET_WIDTH, TARGET_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for block in template.get("blocks", []):
        _draw_text_block(draw, block)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(output_path)


def _fit_image_layers(image: Image.Image) -> Image.Image:
    source = ImageOps.exif_transpose(image).convert("RGB")
    background = ImageOps.fit(source, (TARGET_WIDTH, TARGET_HEIGHT), method=Image.Resampling.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(radius=24))

    foreground = source.copy()
    foreground.thumbnail((TARGET_WIDTH, TARGET_HEIGHT), Image.Resampling.LANCZOS)
    x = (TARGET_WIDTH - foreground.width) // 2
    y = (TARGET_HEIGHT - foreground.height) // 2
    background.paste(foreground, (x, y))
    return background


def process_image(input_path: Path, overlay_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(input_path) as source:
            canvas = _fit_image_layers(source)
        with Image.open(overlay_path) as overlay:
            canvas = canvas.convert("RGBA")
            canvas.alpha_composite(overlay.convert("RGBA"))
        canvas.convert("RGB").save(output_path, format="JPEG", quality=92, optimize=True)
    except Exception as exc:
        raise PosterVideoError(f"image processing failed: {exc}") from exc


def _run_ffmpeg(command: list[str]) -> subprocess.CompletedProcess[str]:
    resolved = list(command)
    if resolved and resolved[0] == "ffmpeg":
        executable = ffmpeg_executable()
        if executable is None:
            raise PosterVideoError("缺少 FFmpeg，请安装系统 FFmpeg 或 imageio-ffmpeg 依赖")
        resolved[0] = executable
    return subprocess.run(resolved, check=True, capture_output=True, text=True)


def _positive_duration(value: Any, label: str) -> float:
    try:
        duration = float(value)
    except (TypeError, ValueError, OverflowError):
        raise PosterVideoError(f"{label}时长无效") from None
    if not math.isfinite(duration) or duration <= 0:
        raise PosterVideoError(f"{label}时长必须是有效正数")
    return duration


def calculate_timing(
    source_type: str,
    *,
    video_duration: float | None = None,
    narration_duration: float | None = None,
    bgm_duration: float | None = None,
) -> dict[str, Any]:
    if source_type not in {"image", "video"}:
        raise PosterVideoError("素材类型必须是图片或视频")
    if narration_duration is not None:
        narration_duration = _positive_duration(narration_duration, "口播")
    if bgm_duration is not None:
        bgm_duration = _positive_duration(bgm_duration, "BGM")
    if source_type == "image":
        target = narration_duration if narration_duration is not None else bgm_duration
        if target is None:
            raise PosterVideoError("图片转视频必须提供口播音频或背景音乐")
    else:
        video_duration = _positive_duration(video_duration, "视频")
        target = min(video_duration, narration_duration) if narration_duration is not None else video_duration
    return {
        "source_type": source_type,
        "target_duration": target,
        "video_speed": video_duration / target if source_type == "video" else 1.0,
        "narration_speed": narration_duration / target if narration_duration is not None else 1.0,
    }


def build_atempo_filter(rate: float) -> str:
    speed = _positive_duration(rate, "变速倍率")
    if speed < 1:
        raise PosterVideoError("只支持大于或等于 1 的加速倍率")
    filters = []
    # Small atempo stages avoid sample skipping at high speech speed.
    while speed > 2:
        filters.append("atempo=2")
        speed /= 2
    filters.append(f"atempo={speed:.12g}")
    return ",".join(filters)


def _compose_command(
    input_path: Path,
    overlay_path: Path,
    output_path: Path,
    *,
    timing: dict[str, Any],
    has_original_audio: bool,
    narration_path: Path | None,
    bgm_path: Path | None,
    original_audio_offset: float = 0.0,
) -> list[str]:
    duration = f"{timing['target_duration']:.6f}"
    command = ["ffmpeg", "-y"]
    filters: list[str] = []
    audio_inputs: list[tuple[int, float, float]] = []
    if timing["source_type"] == "image":
        command.extend(["-loop", "1", "-framerate", "30", "-i", str(input_path)])
        filters.append("[0:v:0]setsar=1,format=yuv420p[outv]")
        next_index = 1
    else:
        command.extend(["-i", str(input_path), "-i", str(overlay_path)])
        filters.extend([
            f"[0:V:0]setpts=(PTS-STARTPTS)/{timing['video_speed']:.12g},fps=30,split=2[bgsrc][fgsrc]",
            f"[bgsrc]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},gblur=sigma=24[bg]",
            f"[fgsrc]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"format=rgba,pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black@0[fg]",
            "[bg][fg]overlay=0:0[base]",
            "[base][1:v:0]overlay=0:0:format=auto,setsar=1[outv]",
        ])
        next_index = 2
        if has_original_audio:
            audio_inputs.append((0, timing["video_speed"], 1.0))
    if narration_path is not None:
        command.extend(["-i", str(narration_path)])
        audio_inputs.append((next_index, timing["narration_speed"], 1.0))
        next_index += 1
    if bgm_path is not None:
        command.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
        audio_inputs.append((next_index, 1.0, 0.6))

    for index, (input_index, speed, weight) in enumerate(audio_inputs):
        alignment = ""
        if input_index == 0 and timing["source_type"] == "video":
            offset = original_audio_offset / speed
            if offset > 0:
                # adelay can emit leading silence before an input PTS is available.
                alignment = f"adelay={round(offset * 48000)}S:all=1,asetpts=N/SR/TB,"
            elif offset < 0:
                alignment = f"atrim=start={-offset:.12g},asetpts=PTS-STARTPTS,"
        filters.append(
            f"[{input_index}:a:0]asetpts=PTS-STARTPTS,{build_atempo_filter(speed)},"
            f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"{alignment}volume={weight},apad,atrim=duration={duration}[audio{index}]"
        )
    if audio_inputs:
        labels = "".join(f"[audio{index}]" for index in range(len(audio_inputs)))
        filters.append(
            f"{labels}amix=inputs={len(audio_inputs)}:duration=longest:"
            "dropout_transition=0:normalize=0[outa]"
        )
    command.extend(["-filter_complex", ";".join(filters), "-map", "[outv]"])
    if audio_inputs:
        command.extend(["-map", "[outa]", "-c:a", "aac", "-b:a", "192k"])
    else:
        command.append("-an")
    command.extend([
        "-t", duration, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_path),
    ])
    return command


def process_video(
    input_path: Path,
    overlay_path: Path,
    output_path: Path,
    *,
    source_type: str = "video",
    narration_path: Path | None = None,
    bgm_path: Path | None = None,
    mute_original_audio: bool = True,
    narration_duration: float | None = None,
    bgm_duration: float | None = None,
) -> dict[str, Any]:
    require_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        video_info = probe_media(input_path) if source_type == "video" else {}
        if source_type == "video" and not video_info["has_video"]:
            raise PosterVideoError(f"素材没有视频轨道：{input_path.name}")
        if narration_path is not None and narration_duration is None:
            narration_duration = probe_audio_duration(narration_path)
        if bgm_path is not None and bgm_duration is None:
            bgm_duration = probe_audio_duration(bgm_path)
        timing = calculate_timing(
            source_type,
            video_duration=video_info.get("video_duration"),
            narration_duration=narration_duration if narration_path is not None else None,
            bgm_duration=bgm_duration if bgm_path is not None else None,
        )
        with tempfile.TemporaryDirectory(prefix="poster-", dir=output_path.parent) as temp:
            render_input = input_path
            if source_type == "image":
                render_input = Path(temp) / "frame.jpg"
                process_image(input_path, overlay_path, render_input)
            _run_ffmpeg(_compose_command(
                render_input, overlay_path, output_path,
                timing=timing,
                has_original_audio=bool(video_info.get("has_audio") and not mute_original_audio),
                narration_path=narration_path,
                bgm_path=bgm_path,
                original_audio_offset=(
                    video_info.get("audio_start_time", 0) - video_info.get("video_start_time", 0)
                ),
            ))
        return timing
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        if isinstance(exc, PosterVideoError):
            raise
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or "").strip() or (exc.stdout or "").strip() or "FFmpeg 执行失败"
        else:
            detail = str(exc)
        raise PosterVideoError(textwrap.shorten(detail, width=900, placeholder="...")) from exc


def _decode_stream_timing(path: Path, selector: str, kind: str) -> dict[str, float]:
    executable = ffmpeg_executable()
    if executable is None:
        raise PosterVideoError("缺少 FFmpeg，请安装系统 FFmpeg 或 imageio-ffmpeg 依赖")
    command = [
        executable, "-hide_banner", "-nostdin", "-nostats", "-i", str(path),
        "-map", selector,
    ]
    if kind == "video":
        command.extend(["-vf", "showinfo=checksum=0", "-fps_mode", "passthrough"])
    else:
        command.extend(["-af", "ashowinfo"])
    command.extend(["-progress", "pipe:1", "-f", "null", "-"])
    container_start = 0.0
    first_pts = None
    end_pts = None
    try:
        # Stream diagnostics instead of retaining a line for every decoded frame.
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace",
        ) as process:
            for line in process.stdout:
                start = re.search(r"^\s*Duration:.*,\s*start:\s*([-\d.]+)", line)
                if start:
                    container_start = float(start[1])
                if first_pts is None and "showinfo" in line:
                    pts = re.search(r"\bpts_time:([-\d.e+]+)", line)
                    if pts:
                        first_pts = float(pts[1])
                progress = re.fullmatch(r"out_time_us=(-?\d+)\s*", line)
                if progress:
                    end_pts = int(progress[1]) / 1_000_000
            returncode = process.wait()
    except OSError as exc:
        raise PosterVideoError(f"无法读取媒体时长：{path.name}") from exc
    if returncode or first_pts is None or end_pts is None:
        raise PosterVideoError(f"无法读取媒体时长：{path.name}")
    return {
        "start_time": container_start + first_pts,
        "duration": _positive_duration(end_pts - first_pts, "媒体"),
    }


def _probe_streams(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        command = [
            ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
        ]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            return json.loads(result.stdout or "{}")
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            raise PosterVideoError(f"无法读取媒体信息：{path.name}") from exc

    executable = ffmpeg_executable()
    if executable is None:
        raise PosterVideoError("缺少 FFmpeg，请安装系统 FFmpeg 或 imageio-ffmpeg 依赖")
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise PosterVideoError(f"媒体命令不可用：{executable}") from exc
    stderr = result.stderr or ""
    streams = []
    # The bundled FFmpeg may have no ffprobe. Decode each primary stream to a
    # null sink so a longer audio track cannot incorrectly set video duration.
    for kind, selector in (("video", "V"), ("audio", "a")):
        line = next(
            (line for line in stderr.splitlines()
             if re.search(rf"Stream #.*: {kind.title()}:", line) and "(attached pic)" not in line),
            None,
        )
        if line is None:
            continue
        stream: dict[str, Any] = {
            "codec_type": kind,
            **_decode_stream_timing(path, f"0:{selector}:0", kind),
        }
        resolution = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
        if kind == "video" and resolution:
            stream.update(width=int(resolution[1]), height=int(resolution[2]))
        streams.append(stream)
    return {"streams": streams}


def _stream_duration(
    path: Path, stream: dict[str, Any], container: dict[str, Any], label: str,
) -> float:
    duration = stream.get("duration")
    if duration is not None and duration != "N/A":
        return _positive_duration(duration, label)
    tagged = (stream.get("tags") or {}).get("DURATION")
    if tagged is not None and tagged != "N/A":
        match = re.fullmatch(r"(\d+):(\d+):(\d+(?:\.\d+)?)", str(tagged))
        if not match:
            raise PosterVideoError(f"{label}时长无效")
        _positive_duration(int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3]), label)
    if container.get("duration") is not None and container["duration"] != "N/A":
        _positive_duration(container["duration"], label)
    # Tags can be end timestamps, and container duration can belong to another track.
    selector = f"0:{stream['index']}"
    stream.update(_decode_stream_timing(path, selector, stream["codec_type"]))
    return stream["duration"]


def probe_media(path: Path) -> dict[str, Any]:
    raw = _probe_streams(path)
    streams = raw.get("streams") or []
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"
         and not (stream.get("disposition") or {}).get("attached_pic")),
        None,
    )
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    container = raw.get("format") or {}
    if video is None and audio is None:
        raise PosterVideoError(f"文件没有可用的音视频轨道：{path.name}")
    video_duration = _stream_duration(path, video, container, "视频") if video is not None else None
    audio_duration = _stream_duration(path, audio, container, "音频") if audio is not None else None
    info = {
        "has_video": video is not None,
        "has_audio": audio is not None,
        "video_duration": video_duration,
        "audio_duration": audio_duration,
    }
    for kind, stream in (("video", video), ("audio", audio)):
        value = stream.get("start_time") if stream is not None else None
        try:
            start = 0.0 if value is None or value == "N/A" else float(value)
        except (TypeError, ValueError, OverflowError):
            raise PosterVideoError(f"媒体起始时间无效：{path.name}") from None
        if not math.isfinite(start):
            raise PosterVideoError(f"媒体起始时间无效：{path.name}")
        info[f"{kind}_start_time"] = start
    return info


def probe_audio_duration(path: Path) -> float:
    info = probe_media(path)
    if not info["has_audio"]:
        raise PosterVideoError(f"文件没有音频轨道：{path.name}")
    return info["audio_duration"]


def probe_video(path: Path) -> dict[str, Any]:
    raw = _probe_streams(path)
    return {
        "streams": [
            stream for stream in raw.get("streams", []) if stream.get("codec_type") == "video"
            and not (stream.get("disposition") or {}).get("attached_pic")
        ]
    }
