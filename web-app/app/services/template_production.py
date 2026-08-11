from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.template_definition import (
    TemplateDefinition,
    TemplateRuntimeValidationError,
    render_script_prompt,
)
from app.services import template_registry
from app.services.tts import TTSTiming

ZHONGYI_TEMPLATE_ID = "zhongyi-xunfang"
DEFAULT_VIDEO_RATIO = "9:16"
VIDEO_RATIOS = {
    DEFAULT_VIDEO_RATIO: (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "3:4": (1080, 1440),
}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
ZHONGYI_SLOT_PLAN = (
    ("doctor-scene", 0.12, ("clinic-scene",)),
    ("clinic-scene", 0.13, ("doctor-scene",)),
    ("doctor-scene", 0.13, ("clinic-scene",)),
    ("clinic-scene", 0.12, ("doctor-scene",)),
    ("doctor-scene", 0.17, ("clinic-scene",)),
    ("clinic-scene", 0.15, ("doctor-scene",)),
    ("doctor-scene", 0.18, ("clinic-scene",)),
)
ZHONGYI_TRANSITION_DURATION = 0.3
TEMPLATE_SAFETY_NOTICE = "人文记录 无不良引导\\N如有不适 请线上就医"
BGM_VOLUME_WEIGHT = 0.6
DEFAULT_SUBTITLE_STYLE = {
    "font_family": "Microsoft YaHei",
    "font_size": 65,
    "color": "#FFD21F",
    "outline_color": "#000000",
    "outline_width": 5,
    "bottom_margin": 250,
    "alignment": "center",
    "notice_enabled": True,
    "notice_text": "人文记录 无不良引导\n如有不适 请线上就医",
    "notice_font_size": 33,
    "notice_color": "#FFFFFF",
    "notice_outline_color": "#000000",
    "notice_outline_width": 1,
    "notice_top_margin": 106,
}
SUBTITLE_FONT_FAMILIES = frozenset({"Microsoft YaHei", "SimHei", "SimSun", "KaiTi"})
SUBTITLE_ALIGNMENT_CODES = {"left": 1, "center": 2, "right": 3}

class TemplateProductionError(RuntimeError):
    pass


def normalize_subtitle_style(value: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize user-facing subtitle style values into ASS-safe settings."""

    raw = value if isinstance(value, dict) else {}

    def number(name: str, minimum: int, maximum: int) -> int:
        try:
            parsed = int(float(raw.get(name, DEFAULT_SUBTITLE_STYLE[name])))
        except (TypeError, ValueError, OverflowError):
            parsed = DEFAULT_SUBTITLE_STYLE[name]
        return max(minimum, min(maximum, parsed))

    def color(name: str) -> str:
        candidate = str(raw.get(name, DEFAULT_SUBTITLE_STYLE[name]) or "").strip()
        if re.fullmatch(r"#[0-9A-Fa-f]{6}", candidate):
            return candidate.upper()
        return DEFAULT_SUBTITLE_STYLE[name]

    family = str(raw.get("font_family", DEFAULT_SUBTITLE_STYLE["font_family"]) or "").strip()
    alignment = str(raw.get("alignment", DEFAULT_SUBTITLE_STYLE["alignment"]) or "").strip().lower()
    notice_text = str(raw.get("notice_text", DEFAULT_SUBTITLE_STYLE["notice_text"]) or "").strip()
    notice_text = notice_text.replace("\r\n", "\n").replace("\r", "\n")

    notice_enabled = raw.get("notice_enabled", DEFAULT_SUBTITLE_STYLE["notice_enabled"])

    return {
        "font_family": family if family in SUBTITLE_FONT_FAMILIES else DEFAULT_SUBTITLE_STYLE["font_family"],
        "font_size": number("font_size", 36, 108),
        "color": color("color"),
        "outline_color": color("outline_color"),
        "outline_width": number("outline_width", 0, 12),
        "bottom_margin": number("bottom_margin", 80, 480),
        "alignment": alignment if alignment in SUBTITLE_ALIGNMENT_CODES else DEFAULT_SUBTITLE_STYLE["alignment"],
        "notice_enabled": notice_enabled if isinstance(notice_enabled, bool) else DEFAULT_SUBTITLE_STYLE["notice_enabled"],
        "notice_text": notice_text[:120],
        "notice_font_size": number("notice_font_size", 18, 58),
        "notice_color": color("notice_color"),
        "notice_outline_color": color("notice_outline_color"),
        "notice_outline_width": number("notice_outline_width", 0, 6),
        "notice_top_margin": number("notice_top_margin", 30, 260),
    }


def _ass_color(value: str, alpha: str = "00") -> str:
    normalized = str(value or "#000000").lstrip("#")
    red, green, blue = normalized[0:2], normalized[2:4], normalized[4:6]
    return f"&H{alpha}{blue}{green}{red}"


def _scaled_subtitle_value(
    style: dict[str, Any],
    name: str,
    height: int,
    *,
    legacy_minimum: int,
    legacy_ratio: float,
) -> int:
    """Keep the existing rendered defaults exact at every output ratio."""

    if style[name] == DEFAULT_SUBTITLE_STYLE[name]:
        return max(legacy_minimum, round(height * legacy_ratio))
    return max(0, round(style[name] * height / 1920))


@dataclass(frozen=True)
class TimelineSegment:
    source_path: Path
    media_type: str
    requirement_id: str
    duration: float
    start_time: float


def require_template(template_id: str) -> str:
    return resolve_template_definition(template_id).id


def resolve_template_definition(template: str | TemplateDefinition) -> TemplateDefinition:
    if isinstance(template, TemplateDefinition):
        return template
    normalized = str(template or "").strip()
    try:
        # String-based calls are kept for built-in-template compatibility. User
        # templates are resolved by the API and passed here as definitions.
        entry = template_registry.template_registry.get_entry("__builtin__", normalized)
    except template_registry.TemplateRegistryError as exc:
        raise TemplateProductionError(f"不支持的模板：{normalized or '空'}") from exc
    if not entry.is_builtin:
        raise TemplateProductionError(f"不支持的模板：{normalized or '空'}")
    return entry.definition


def build_script_prompt(
    template: str | TemplateDefinition,
    variables: dict[str, str],
    count: int = 3,
    material_context: dict[str, int] | None = None,
) -> str:
    definition = resolve_template_definition(template)
    try:
        return render_script_prompt(
            definition,
            variables,
            candidate_count=max(1, min(10, int(count))),
            material_context=material_context,
        )
    except (TemplateRuntimeValidationError, TypeError, ValueError) as exc:
        raise TemplateProductionError(str(exc)) from exc


def build_rewrite_prompt(
    template: str | TemplateDefinition,
    variables: dict[str, str],
    original_script: str,
    material_context: dict[str, int] | None = None,
) -> str:
    definition = resolve_template_definition(template)
    try:
        return render_script_prompt(
            definition,
            variables,
            candidate_count=1,
            material_context=material_context,
            original_script=original_script,
        )
    except TemplateRuntimeValidationError as exc:
        raise TemplateProductionError(str(exc)) from exc


def parse_generated_scripts(content: str, limit: int = 10) -> list[str]:
    raw = str(content or "").strip()
    if not raw:
        return []

    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE).strip()
    candidates: list[Any] = []
    try:
        parsed = json.loads(fenced)
        if isinstance(parsed, list):
            candidates = parsed
        elif isinstance(parsed, dict):
            value = parsed.get("scripts") or parsed.get("items")
            if isinstance(value, list):
                candidates = value
    except json.JSONDecodeError:
        candidates = []

    if not candidates:
        candidates = [
            re.sub(r"^(?:文案\s*)?\d+\s*[：:、.)）-]\s*", "", line).strip(" \t\"'")
            for line in raw.splitlines()
        ]

    scripts: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if isinstance(item, dict):
            sentences = item.get("sentences")
            if isinstance(sentences, list):
                value = "\n".join(str(sentence or "").strip() for sentence in sentences if str(sentence or "").strip())
            else:
                value = str(item.get("script") or item.get("content") or "").strip()
        else:
            value = str(item or "").strip()
        if len(value) < 10 or value in seen:
            continue
        seen.add(value)
        scripts.append(value)
        if len(scripts) >= max(1, limit):
            break
    return scripts


def split_script_sentences(script: str) -> list[str]:
    text = str(script or "").strip()
    if not text:
        return []
    blocks = [part.strip() for part in re.split(r"\r?\n+", text) if part.strip()]
    sentences: list[str] = []
    for block in blocks:
        parts = [part.strip() for part in re.split(r"(?<=[。！？!?；;])\s*", block) if part.strip()]
        for part in parts:
            if len(part) > 20:
                comma_parts = [value.strip() for value in re.split(r"(?<=[，,])\s*", part) if value.strip()]
                sentences.extend(comma_parts)
            else:
                sentences.append(part)
    return sentences


def script_text_for_tts(script: str) -> str:
    sentences = split_script_sentences(script)
    normalized = []
    for sentence in sentences:
        value = sentence.strip()
        if value and value[-1] not in "，。！？!?；;":
            value += "。"
        normalized.append(value)
    return "".join(normalized)


def require_ffmpeg() -> None:
    if ffmpeg_executable() is None:
        raise TemplateProductionError("缺少 FFmpeg，请安装系统 FFmpeg 或 imageio-ffmpeg 依赖")


def ffmpeg_executable() -> str | None:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    resolved_command = list(command)
    if resolved_command and resolved_command[0] == "ffmpeg":
        executable = ffmpeg_executable()
        if executable is None:
            raise TemplateProductionError("缺少 FFmpeg，请安装系统 FFmpeg 或 imageio-ffmpeg 依赖")
        resolved_command[0] = executable
    try:
        return subprocess.run(resolved_command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise TemplateProductionError(f"媒体命令不可用：{resolved_command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or "FFmpeg 执行失败"
        raise TemplateProductionError(textwrap.shorten(detail, width=900, placeholder="...")) from exc


def probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        result = _run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ]
        )
        try:
            duration = float(result.stdout.strip())
        except ValueError as exc:
            raise TemplateProductionError(f"无法读取媒体时长：{path.name}") from exc
    else:
        executable = ffmpeg_executable()
        if executable is None:
            raise TemplateProductionError("缺少 FFmpeg，请安装系统 FFmpeg 或 imageio-ffmpeg 依赖")
        result = subprocess.run(
            [executable, "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        if not match:
            raise TemplateProductionError(f"无法读取媒体时长：{path.name}")
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if duration <= 0:
        raise TemplateProductionError(f"媒体时长无效：{path.name}")
    return duration


def ratio_size(ratio: str) -> tuple[int, int]:
    try:
        return VIDEO_RATIOS[ratio]
    except KeyError as exc:
        raise TemplateProductionError(f"不支持的画面比例：{ratio}") from exc


def _fit_geometry_filter(width: int, height: int, *, fill_mode: str = "contain") -> str:
    if fill_mode == "cover":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1"
        )
    if fill_mode != "contain":
        raise TemplateProductionError(f"不支持的画面填充方式：{fill_mode}")
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    )


def _fit_filter(width: int, height: int, *, fill_mode: str = "contain") -> str:
    return f"{_fit_geometry_filter(width, height, fill_mode=fill_mode)},fps=30,format=yuv420p"


def _image_motion_filter(width: int, height: int, *, fill_mode: str = "cover") -> str:
    return (
        f"{_fit_geometry_filter(width, height, fill_mode=fill_mode)},"
        f"zoompan=z='min(zoom+0.0008,1.08)':d=1:s={width}x{height}:fps=30,"
        "format=yuv420p"
    )


def prepare_material_segment(
    source_path: Path,
    output_path: Path,
    *,
    media_type: str,
    ratio: str,
    segment_duration: float = 4.0,
    target_size: tuple[int, int] | None = None,
    fill_mode: str = "contain",
    start_time: float = 0.0,
    image_motion: bool = False,
) -> Path:
    require_ffmpeg()
    width, height = target_size or ratio_size(ratio)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = max(1.0, float(segment_duration))

    command = ["ffmpeg", "-y"]
    if media_type == "image":
        command.extend(["-loop", "1", "-t", f"{duration:.3f}", "-i", str(source_path)])
    elif media_type == "video":
        command.extend(
            [
                "-stream_loop",
                "-1",
                "-ss",
                f"{max(0.0, float(start_time)):.3f}",
                "-t",
                f"{duration:.3f}",
                "-i",
                str(source_path),
            ]
        )
    else:
        raise TemplateProductionError(f"不支持的素材类型：{media_type}")

    video_filter = (
        _image_motion_filter(width, height, fill_mode=fill_mode)
        if media_type == "image" and image_motion
        else _fit_filter(width, height, fill_mode=fill_mode)
    )
    command.extend(
        [
            "-an",
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    _run(command)
    return output_path


def build_material_sequence(
    segments: list[Path],
    target_duration: float,
    *,
    seed: str,
    segment_duration: float = 4.0,
) -> list[Path]:
    if not segments:
        raise TemplateProductionError("没有可用于合成的素材")
    required = max(1, int(target_duration / segment_duration) + 1)
    rng = random.Random(seed)
    result: list[Path] = []
    previous: Path | None = None

    while len(result) < required:
        batch = list(segments)
        rng.shuffle(batch)
        if len(batch) > 1 and previous is not None and batch[0] == previous:
            batch[0], batch[1] = batch[1], batch[0]
        result.extend(batch)
        previous = result[-1]
    return result[:required]


def _concat_line(path: Path) -> str:
    escaped = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{escaped}'"


def compose_video(
    segments: list[Path],
    audio_path: Path,
    output_path: Path,
    *,
    seed: str,
    audio_duration: float | None = None,
    segment_duration: float = 4.0,
    script: str | None = None,
    work_dir: Path | None = None,
    ratio: str = "9:16",
    timings: tuple[TTSTiming, ...] | list[TTSTiming] = (),
    subtitle_replacements: tuple[dict[str, str], ...] | list[dict[str, str]] = (),
    subtitle_style: dict[str, Any] | None = None,
    bgm_path: Path | None = None,
) -> Path:
    require_ffmpeg()
    duration = audio_duration or probe_duration(audio_path)
    sequence = build_material_sequence(segments, duration, seed=seed, segment_duration=segment_duration)
    return compose_prepared_video(
        sequence,
        audio_path,
        output_path,
        audio_duration=duration,
        script=script,
        work_dir=work_dir,
        ratio=ratio,
        timings=timings,
        subtitle_replacements=subtitle_replacements,
        subtitle_style=subtitle_style,
        bgm_path=bgm_path,
    )


def compose_prepared_video(
    sequence: list[Path],
    audio_path: Path,
    output_path: Path,
    *,
    audio_duration: float | None = None,
    script: str | None = None,
    work_dir: Path | None = None,
    ratio: str = "9:16",
    timings: tuple[TTSTiming, ...] | list[TTSTiming] = (),
    subtitle_replacements: tuple[dict[str, str], ...] | list[dict[str, str]] = (),
    subtitle_style: dict[str, Any] | None = None,
    bgm_path: Path | None = None,
) -> Path:
    require_ffmpeg()
    if not sequence:
        raise TemplateProductionError("没有可用于合成的素材")
    duration = audio_duration or probe_duration(audio_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_path = output_path.with_suffix(".concat.txt")
    ass_path: Path | None = None
    if script and script.strip():
        subtitle_dir = work_dir or output_path.parent
        ass_path = write_subtitle_ass(
            script,
            duration,
            subtitle_dir / "subtitles.ass",
            target_size=ratio_size(ratio),
            timings=timings,
            subtitle_replacements=subtitle_replacements,
            subtitle_style=subtitle_style,
        )
    concat_path.write_text("\n".join(_concat_line(path) for path in sequence), encoding="utf-8")
    try:
        command = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-i",
            str(audio_path),
        ]
        has_bgm = bgm_path is not None
        if has_bgm:
            command.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
        command.extend(["-t", f"{duration:.3f}"])

        filter_parts: list[str] = []
        if has_bgm:
            filter_parts.append(
                f"[1:a][2:a]amix=inputs=2:duration=first:dropout_transition=0:"
                f"weights='1 {BGM_VOLUME_WEIGHT}':normalize=0[aout]"
            )
        if filter_parts:
            if ass_path is not None:
                filter_parts.append(f"[0:v]ass=filename='{_ffmpeg_filter_path(ass_path)}'[vout]")
            command.extend(["-filter_complex", ";".join(filter_parts)])
            command.extend(["-map", "[vout]" if ass_path is not None else "0:v:0"])
            command.extend(["-map", "[aout]"])
        else:
            command.extend(["-map", "0:v:0", "-map", "1:a:0"])
            if ass_path is not None:
                command.extend(["-vf", f"ass=filename='{_ffmpeg_filter_path(ass_path)}'"])
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        _run(command)
    finally:
        concat_path.unlink(missing_ok=True)
        if ass_path is not None:
            ass_path.unlink(missing_ok=True)
    return output_path


def build_zhongyi_timeline(
    materials: list[dict[str, Any]],
    target_duration: float,
    *,
    seed: str,
    transition_duration: float = ZHONGYI_TRANSITION_DURATION,
) -> list[TimelineSegment]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for material in materials:
        grouped.setdefault(str(material.get("requirement_id") or ""), []).append(material)

    rng = random.Random(seed)
    duration_cache: dict[Path, float] = {}
    previous_path: Path | None = None
    timeline: list[TimelineSegment] = []
    for index, (requirement_id, share, fallbacks) in enumerate(ZHONGYI_SLOT_PLAN):
        candidates = grouped.get(requirement_id) or []
        selected_requirement = requirement_id
        if not candidates:
            for fallback in fallbacks:
                if grouped.get(fallback):
                    candidates = grouped[fallback]
                    selected_requirement = fallback
                    break
        if not candidates:
            raise TemplateProductionError(f"中医寻访缺少可用于 {requirement_id} 槽位的素材")

        choices = list(candidates)
        rng.shuffle(choices)
        if len(choices) > 1 and Path(choices[0]["input_path"]) == previous_path:
            choices[0], choices[1] = choices[1], choices[0]
        selected = choices[0]
        source_path = Path(selected["input_path"])
        media_type = str(selected.get("media_type") or "video")
        raw_duration = max(1.0, target_duration * share + (transition_duration if index < len(ZHONGYI_SLOT_PLAN) - 1 else 0))
        source_duration = 0.0
        if media_type == "video":
            if source_path not in duration_cache:
                duration_cache[source_path] = probe_duration(source_path)
            source_duration = duration_cache[source_path]
        max_start = max(0.0, source_duration - raw_duration)
        start_time = rng.uniform(0, max_start) if max_start > 0.25 else 0.0
        timeline.append(
            TimelineSegment(
                source_path=source_path,
                media_type=media_type,
                requirement_id=selected_requirement,
                duration=raw_duration,
                start_time=start_time,
            )
        )
        previous_path = source_path
    return timeline


def _normalize_spoken_text(value: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(value or ""))


def build_subtitle_cues(
    script: str,
    duration: float,
    timings: tuple[TTSTiming, ...] | list[TTSTiming] = (),
) -> list[tuple[float, float, str]]:
    sentences = [re.sub(r"[，。！？!?；;]+$", "", value.strip()) for value in split_script_sentences(script)]
    sentences = [value for value in sentences if value]
    if not sentences:
        return []

    usable_timings = [timing for timing in timings if _normalize_spoken_text(timing.text)]
    if usable_timings:
        boundary_lengths = [len(_normalize_spoken_text(timing.text)) for timing in usable_timings]
        sentence_lengths = [max(1, len(_normalize_spoken_text(sentence))) for sentence in sentences]
        if sum(boundary_lengths) < sum(sentence_lengths) * 0.8:
            usable_timings = []

    if usable_timings:
        cues: list[tuple[float, float, str]] = []
        boundary_index = 0
        for sentence_index, (sentence, target_length) in enumerate(zip(sentences, sentence_lengths)):
            start = 0.0 if sentence_index == 0 else cues[-1][1]
            consumed = 0
            end = start
            while boundary_index < len(usable_timings) and consumed < target_length:
                consumed += boundary_lengths[boundary_index]
                end = usable_timings[boundary_index].end
                boundary_index += 1
            if sentence_index == len(sentences) - 1:
                end = duration
            cues.append((max(0.0, start), min(duration, max(start + 0.12, end)), sentence))
        return cues

    weights = [max(1, len(_normalize_spoken_text(sentence))) for sentence in sentences]
    total_weight = sum(weights)
    cursor = 0.0
    cues = []
    for index, (sentence, weight) in enumerate(zip(sentences, weights)):
        end = duration if index == len(sentences) - 1 else cursor + duration * weight / total_weight
        cues.append((cursor, max(cursor + 0.12, end), sentence))
        cursor = end
    return cues


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(float(seconds) * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def _ass_text(value: str) -> str:
    return str(value).replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def apply_subtitle_replacements(
    text: str,
    replacements: tuple[dict[str, str], ...] | list[dict[str, str]] = (),
) -> str:
    replacement_map = {
        str(item.get("source") or ""): str(item.get("replacement") or "")
        for item in replacements
        if str(item.get("source") or "")
    }
    if not replacement_map:
        return str(text or "")

    sources = sorted(replacement_map, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(source) for source in sources))
    return pattern.sub(lambda match: replacement_map[match.group(0)], str(text or ""))


def write_subtitle_ass(
    script: str,
    duration: float,
    output_path: Path,
    *,
    target_size: tuple[int, int],
    timings: tuple[TTSTiming, ...] | list[TTSTiming] = (),
    subtitle_replacements: tuple[dict[str, str], ...] | list[dict[str, str]] = (),
    subtitle_style: dict[str, Any] | None = None,
) -> Path:
    width, height = target_size
    style = normalize_subtitle_style(subtitle_style)
    subtitle_size = _scaled_subtitle_value(
        style, "font_size", height, legacy_minimum=34, legacy_ratio=0.034
    )
    outline = _scaled_subtitle_value(
        style, "outline_width", height, legacy_minimum=3, legacy_ratio=0.0026
    )
    bottom_margin = _scaled_subtitle_value(
        style, "bottom_margin", height, legacy_minimum=80, legacy_ratio=0.13
    )
    subtitle_alignment = SUBTITLE_ALIGNMENT_CODES[style["alignment"]]
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Subtitle,{style['font_family']},{subtitle_size},{_ass_color(style['color'])},"
        f"{_ass_color(style['color'])},{_ass_color(style['outline_color'])},&H70000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline},1,{subtitle_alignment},70,70,{bottom_margin},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if style["notice_enabled"] and style["notice_text"]:
        notice_size = _scaled_subtitle_value(
            style, "notice_font_size", height, legacy_minimum=22, legacy_ratio=0.017
        )
        notice_outline = (
            1
            if style["notice_outline_width"] == DEFAULT_SUBTITLE_STYLE["notice_outline_width"]
            else max(0, round(style["notice_outline_width"] * height / 1920))
        )
        top_margin = _scaled_subtitle_value(
            style, "notice_top_margin", height, legacy_minimum=34, legacy_ratio=0.055
        )
        lines.insert(
            -3,
            f"Style: Notice,{style['font_family']},{notice_size},{_ass_color(style['notice_color'])},"
            f"{_ass_color(style['notice_color'])},{_ass_color(style['notice_outline_color'], '50')},&H50000000,"
            f"0,0,0,0,100,100,0,0,1,{notice_outline},1,8,50,50,{top_margin},1",
        )
        lines.append(
            f"Dialogue: 0,{_ass_time(0)},{_ass_time(duration)},Notice,,0,0,0,,"
            f"{_ass_text(style['notice_text'])}"
        )
    lines.extend(
        f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},Subtitle,,0,0,0,,"
        f"{_ass_text(apply_subtitle_replacements(text, subtitle_replacements))}"
        for start, end, text in build_subtitle_cues(script, duration, timings)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8-sig")
    return output_path


def _ffmpeg_filter_path(path: Path) -> str:
    value = path.resolve().as_posix().replace("\\", "/")
    return value.replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")


def compose_zhongyi_video(
    materials: list[dict[str, Any]],
    audio_path: Path,
    output_path: Path,
    *,
    script: str,
    work_dir: Path,
    seed: str,
    ratio: str = "9:16",
    audio_duration: float | None = None,
    timings: tuple[TTSTiming, ...] | list[TTSTiming] = (),
    subtitle_replacements: tuple[dict[str, str], ...] | list[dict[str, str]] = (),
    subtitle_style: dict[str, Any] | None = None,
    bgm_path: Path | None = None,
) -> Path:
    require_ffmpeg()
    duration = audio_duration or probe_duration(audio_path)
    if duration <= 0:
        raise TemplateProductionError("配音时长无效")
    target_size = ratio_size(ratio)
    transition = min(ZHONGYI_TRANSITION_DURATION, max(0.12, duration / 100))
    timeline = build_zhongyi_timeline(materials, duration, seed=seed, transition_duration=transition)
    work_dir.mkdir(parents=True, exist_ok=True)

    prepared: list[Path] = []
    for index, segment in enumerate(timeline, start=1):
        segment_path = work_dir / f"slot_{index:02d}.mp4"
        prepare_material_segment(
            segment.source_path,
            segment_path,
            media_type=segment.media_type,
            ratio=ratio,
            segment_duration=segment.duration,
            target_size=target_size,
            fill_mode="cover",
            start_time=segment.start_time,
        )
        prepared.append(segment_path)

    ass_path = write_subtitle_ass(
        script,
        duration,
        work_dir / "subtitles.ass",
        target_size=target_size,
        timings=timings,
        subtitle_replacements=subtitle_replacements,
        subtitle_style=subtitle_style,
    )
    command = ["ffmpeg", "-y"]
    for segment_path in prepared:
        command.extend(["-i", str(segment_path)])
    command.extend(["-i", str(audio_path)])
    audio_input_index = len(prepared)
    has_bgm = bgm_path is not None
    if has_bgm:
        command.extend(["-stream_loop", "-1", "-i", str(bgm_path)])

    filters: list[str] = []
    cumulative = timeline[0].duration
    previous_label = "[0:v]"
    for index in range(1, len(timeline)):
        output_label = f"[xf{index}]"
        offset = max(0.0, cumulative - transition * index)
        filters.append(
            f"{previous_label}[{index}:v]xfade=transition=fade:duration={transition:.3f}:offset={offset:.3f}{output_label}"
        )
        previous_label = output_label
        cumulative += timeline[index].duration
    filters.append(f"{previous_label}ass=filename='{_ffmpeg_filter_path(ass_path)}'[vout]")
    if has_bgm:
        bgm_input_index = audio_input_index + 1
        filters.append(
            f"[{audio_input_index}:a][{bgm_input_index}:a]amix=inputs=2:duration=first:"
            f"dropout_transition=0:weights='1 {BGM_VOLUME_WEIGHT}':normalize=0[aout]"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if has_bgm:
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vout]",
                "-map",
                "[aout]",
            ]
        )
    else:
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vout]",
                "-map",
                f"{audio_input_index}:a:0",
            ]
        )
    command.extend(
        [
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    _run(command)
    return output_path
