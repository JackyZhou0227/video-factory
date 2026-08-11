from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from app.services import template_production
from app.services.tts import TTSTiming


MAX_KEYWORDS = 20
MAX_MATERIALS = 20
VIDEO_DURATION_SAFETY_MARGIN = 0.1
PACING_RANGES: dict[str, tuple[float, float]] = {
    "fast": (1.5, 2.5),
    "standard": (2.5, 4.0),
    "slow": (4.0, 6.0),
}
DEFAULT_SUBTITLE_STYLE = template_production.normalize_subtitle_style(
    {
        **template_production.DEFAULT_SUBTITLE_STYLE,
        "notice_enabled": False,
        "notice_text": "",
    }
)


class SmartEditingError(RuntimeError):
    pass


@dataclass(frozen=True)
class TimelineSegment:
    source_path: Path
    media_type: str
    keyword_index: int
    duration: float
    start_time: float


def normalize_keywords(values: Sequence[object]) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise SmartEditingError("keywords 必须是字符串数组")
    if not 1 <= len(values) <= MAX_KEYWORDS:
        raise SmartEditingError(f"关键词数量必须在 1-{MAX_KEYWORDS} 之间")

    normalized: list[str] = []
    seen: set[str] = set()
    for index, raw_value in enumerate(values, start=1):
        if not isinstance(raw_value, str):
            raise SmartEditingError(f"第 {index} 个关键词必须是字符串")
        value = raw_value.strip()
        if not value:
            raise SmartEditingError(f"第 {index} 个关键词不能为空")
        if len(value) > 100:
            raise SmartEditingError(f"第 {index} 个关键词不能超过 100 个字符")
        key = unicodedata.normalize("NFKC", value).casefold()
        if key in seen:
            raise SmartEditingError(f"关键词“{value}”重复")
        seen.add(key)
        normalized.append(value)
    return normalized


def pacing_range(pacing: str) -> tuple[float, float]:
    try:
        return PACING_RANGES[pacing]
    except KeyError as exc:
        raise SmartEditingError(f"不支持的剪辑节奏：{pacing}") from exc


def _group_materials(
    materials: Sequence[dict[str, Any]],
    keyword_count: int,
) -> dict[int, list[dict[str, Any]]]:
    if not 1 <= keyword_count <= MAX_KEYWORDS:
        raise SmartEditingError(f"关键词数量必须在 1-{MAX_KEYWORDS} 之间")
    if not 1 <= len(materials) <= MAX_MATERIALS:
        raise SmartEditingError(f"素材数量必须在 1-{MAX_MATERIALS} 之间")

    grouped = {index: [] for index in range(keyword_count)}
    for material in materials:
        try:
            keyword_index = int(material["keyword_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SmartEditingError("素材缺少有效的关键词序号") from exc
        if keyword_index not in grouped:
            raise SmartEditingError("素材关键词序号超出范围")
        media_type = str(material.get("media_type") or "")
        if media_type not in {"image", "video"}:
            raise SmartEditingError("素材类型必须是 image 或 video")
        raw_input_path = material.get("input_path")
        if raw_input_path is None or not str(raw_input_path).strip():
            raise SmartEditingError("素材路径不能为空")
        input_path = Path(raw_input_path)
        grouped[keyword_index].append({**material, "input_path": input_path})

    empty_groups = [index + 1 for index, items in grouped.items() if not items]
    if empty_groups:
        labels = "、".join(str(index) for index in empty_groups)
        raise SmartEditingError(f"第 {labels} 个关键词没有可用素材")
    return grouped


def build_timeline(
    materials: Sequence[dict[str, Any]],
    keyword_count: int,
    target_duration: float,
    *,
    seed: str,
    pacing: str = "standard",
) -> list[TimelineSegment]:
    if target_duration <= 0:
        raise SmartEditingError("配音时长无效")

    grouped = _group_materials(materials, keyword_count)
    minimum_duration, maximum_duration = pacing_range(pacing)
    required_duration = float(target_duration) + VIDEO_DURATION_SAFETY_MARGIN
    rng = random.Random(seed)
    queues: dict[int, list[dict[str, Any]]] = {index: [] for index in grouped}
    previous_by_group: dict[int, Path | None] = {index: None for index in grouped}
    duration_cache: dict[Path, float] = {}

    def next_material(keyword_index: int) -> dict[str, Any]:
        queue = queues[keyword_index]
        if not queue:
            queue.extend(grouped[keyword_index])
            rng.shuffle(queue)
            previous_path = previous_by_group[keyword_index]
            if len(queue) > 1 and previous_path is not None and queue[0]["input_path"] == previous_path:
                replacement_index = next(
                    (
                        index
                        for index, item in enumerate(queue[1:], start=1)
                        if item["input_path"] != previous_path
                    ),
                    None,
                )
                if replacement_index is not None:
                    queue[0], queue[replacement_index] = queue[replacement_index], queue[0]
        selected = queue.pop(0)
        previous_by_group[keyword_index] = selected["input_path"]
        return selected

    timeline: list[TimelineSegment] = []
    accumulated = 0.0
    while accumulated < required_duration:
        for keyword_index in range(keyword_count):
            if accumulated >= required_duration:
                break
            material = next_material(keyword_index)
            segment_duration = rng.uniform(minimum_duration, maximum_duration)
            source_path = material["input_path"]
            start_time = 0.0
            if material["media_type"] == "video":
                if source_path not in duration_cache:
                    duration_cache[source_path] = template_production.probe_duration(source_path)
                max_start = max(0.0, duration_cache[source_path] - segment_duration)
                if max_start > 0.25:
                    start_time = rng.uniform(0.0, max_start)
            timeline.append(
                TimelineSegment(
                    source_path=source_path,
                    media_type=material["media_type"],
                    keyword_index=keyword_index,
                    duration=segment_duration,
                    start_time=start_time,
                )
            )
            accumulated += segment_duration
    return timeline


def compose_video(
    materials: Sequence[dict[str, Any]],
    keyword_count: int,
    audio_path: Path,
    output_path: Path,
    *,
    script: str,
    work_dir: Path,
    seed: str,
    pacing: str = "standard",
    audio_duration: float | None = None,
    timings: tuple[TTSTiming, ...] | list[TTSTiming] = (),
    subtitle_replacements: tuple[dict[str, str], ...] | list[dict[str, str]] = (),
    subtitle_style: dict[str, Any] | None = None,
    bgm_path: Path | None = None,
) -> Path:
    template_production.require_ffmpeg()
    duration = audio_duration or template_production.probe_duration(audio_path)
    timeline = build_timeline(
        materials,
        keyword_count,
        duration,
        seed=seed,
        pacing=pacing,
    )
    work_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[Path] = []
    for index, segment in enumerate(timeline, start=1):
        segment_path = work_dir / f"segment_{index:03d}.mp4"
        template_production.prepare_material_segment(
            segment.source_path,
            segment_path,
            media_type=segment.media_type,
            ratio=template_production.DEFAULT_VIDEO_RATIO,
            segment_duration=segment.duration,
            fill_mode="cover",
            start_time=segment.start_time,
            image_motion=segment.media_type == "image",
        )
        prepared.append(segment_path)

    return template_production.compose_prepared_video(
        prepared,
        audio_path,
        output_path,
        audio_duration=duration,
        script=script,
        work_dir=work_dir,
        ratio=template_production.DEFAULT_VIDEO_RATIO,
        timings=timings,
        subtitle_replacements=subtitle_replacements,
        subtitle_style=subtitle_style or DEFAULT_SUBTITLE_STYLE,
        bgm_path=bgm_path,
    )
