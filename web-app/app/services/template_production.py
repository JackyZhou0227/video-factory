from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

TEMPLATE_IDS = {"zhongyi-xunfang", "doctor-intro"}
VIDEO_RATIOS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "3:4": (1080, 1440),
}


class TemplateProductionError(RuntimeError):
    pass


def require_template(template_id: str) -> str:
    normalized = str(template_id or "").strip()
    if normalized not in TEMPLATE_IDS:
        raise TemplateProductionError(f"不支持的模板：{normalized or '空'}")
    return normalized


def _required_value(variables: dict[str, str], key: str, label: str) -> str:
    value = str(variables.get(key) or "").strip()
    if not value:
        raise TemplateProductionError(f"请填写{label}")
    return value


def build_script_prompt(template_id: str, variables: dict[str, str], count: int = 3) -> str:
    template_id = require_template(template_id)
    count = max(1, min(10, int(count)))

    if template_id == "zhongyi-xunfang":
        address = _required_value(variables, "address", "医生地址")
        name = _required_value(variables, "name", "医生称呼")
        specialty = _required_value(variables, "specialty", "医生专长")
        feature = str(variables.get("feature") or "").strip() or "未特别说明"
        subject = f"地址：{address}\n称呼：{name}\n专长：{specialty}\n特点：{feature}"
        direction = "突出医生的特色、专业能力和真实寻访感"
    else:
        doctor_name = _required_value(variables, "doctor-name", "医生姓名")
        hospital = _required_value(variables, "hospital", "所在医院")
        department = _required_value(variables, "department", "科室")
        specialty = _required_value(variables, "specialty", "专业特长")
        subject = f"姓名：{doctor_name}\n医院：{hospital}\n科室：{department}\n专业特长：{specialty}"
        direction = "突出医生的专业能力、医院背景和可信赖感"

    return (
        "你是一位专业的中文短视频口播文案撰写专家。\n\n"
        f"【人物信息】\n{subject}\n\n"
        f"【任务】\n生成 {count} 条彼此明显不同的短视频口播文案。\n"
        "每条控制在 50-100 个汉字，语言自然、适合直接配音，不要标题、编号或解释。\n"
        f"{direction}，避免医疗效果承诺和夸张用语。\n\n"
        "【输出格式】\n只输出 JSON 字符串数组，例如：[\"第一条文案\", \"第二条文案\"]"
    )


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
        value = str(item or "").strip()
        if len(value) < 10 or value in seen:
            continue
        seen.add(value)
        scripts.append(value)
        if len(scripts) >= max(1, limit):
            break
    return scripts


def require_ffmpeg() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise TemplateProductionError(f"缺少媒体命令：{', '.join(missing)}")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or "FFmpeg 执行失败"
        raise TemplateProductionError(textwrap.shorten(detail, width=900, placeholder="...")) from exc


def probe_duration(path: Path) -> float:
    result = _run(
        [
            "ffprobe",
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
    if duration <= 0:
        raise TemplateProductionError(f"媒体时长无效：{path.name}")
    return duration


def ratio_size(ratio: str) -> tuple[int, int]:
    try:
        return VIDEO_RATIOS[ratio]
    except KeyError as exc:
        raise TemplateProductionError(f"不支持的画面比例：{ratio}") from exc


def _fit_filter(width: int, height: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,fps=30,format=yuv420p"
    )


def prepare_material_segment(
    source_path: Path,
    output_path: Path,
    *,
    media_type: str,
    ratio: str,
    segment_duration: float = 4.0,
    target_size: tuple[int, int] | None = None,
) -> Path:
    require_ffmpeg()
    width, height = target_size or ratio_size(ratio)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = max(1.0, min(10.0, float(segment_duration)))

    command = ["ffmpeg", "-y"]
    if media_type == "image":
        command.extend(["-loop", "1", "-t", f"{duration:.3f}", "-i", str(source_path)])
    elif media_type == "video":
        command.extend(["-stream_loop", "-1", "-t", f"{duration:.3f}", "-i", str(source_path)])
    else:
        raise TemplateProductionError(f"不支持的素材类型：{media_type}")

    command.extend(
        [
            "-an",
            "-vf",
            _fit_filter(width, height),
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
) -> Path:
    require_ffmpeg()
    duration = audio_duration or probe_duration(audio_path)
    sequence = build_material_sequence(segments, duration, seed=seed, segment_duration=segment_duration)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_path = output_path.with_suffix(".concat.txt")
    concat_path.write_text("\n".join(_concat_line(path) for path in sequence), encoding="utf-8")
    try:
        _run(
            [
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
                "-t",
                f"{duration:.3f}",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
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
    finally:
        concat_path.unlink(missing_ok=True)
    return output_path
