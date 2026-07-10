from __future__ import annotations

import json
import shutil
import subprocess
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


def require_ffmpeg() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise PosterVideoError(f"Missing required command: {', '.join(missing)}")


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
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _compose_command(input_path: Path, overlay_path: Path, output_path: Path, audio_codec: str) -> list[str]:
    filter_complex = (
        f"[0:v]split=2[bgsrc][fgsrc];"
        f"[bgsrc]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},gblur=sigma=24[bg];"
        f"[fgsrc]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black@0[fg];"
        f"[bg][fg]overlay=0:0[base];"
        f"[base][1:v]overlay=0:0:format=auto[outv]"
    )
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-i",
        str(overlay_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-shortest",
    ]
    if audio_codec == "copy":
        command.extend(["-c:a", "copy"])
    else:
        command.extend(["-c:a", "aac", "-b:a", "192k"])
    command.extend(["-movflags", "+faststart", str(output_path)])
    return command


def process_video(input_path: Path, overlay_path: Path, output_path: Path) -> None:
    require_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        _run_ffmpeg(_compose_command(input_path, overlay_path, output_path, "copy"))
    except subprocess.CalledProcessError:
        if output_path.exists():
            output_path.unlink()
        try:
            _run_ffmpeg(_compose_command(input_path, overlay_path, output_path, "aac"))
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or "ffmpeg failed"
            raise PosterVideoError(textwrap.shorten(detail, width=900, placeholder="...")) from exc


def probe_video(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = _run_ffmpeg(command)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or "ffprobe failed"
        raise PosterVideoError(detail) from exc
    return json.loads(result.stdout or "{}")
