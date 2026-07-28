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

from app.services.tts import TTSTiming

TEMPLATE_IDS = {"zhongyi-xunfang", "doctor-intro"}
ZHONGYI_TEMPLATE_ID = "zhongyi-xunfang"
ZHONGYI_MIN_CHARS = 150
ZHONGYI_MAX_CHARS = 180
ZHONGYI_MIN_SENTENCES = 14
ZHONGYI_MAX_SENTENCES = 18
VIDEO_RATIOS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "3:4": (1080, 1440),
}
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
ZHONGYI_SAFETY_NOTICE = "人文记录 无不良引导\\N如有不适 请线上就医"


class TemplateProductionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TimelineSegment:
    source_path: Path
    media_type: str
    requirement_id: str
    duration: float
    start_time: float


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


def build_script_prompt(
    template_id: str,
    variables: dict[str, str],
    count: int = 3,
    material_context: dict[str, int] | None = None,
) -> str:
    template_id = require_template(template_id)
    count = max(1, min(10, int(count)))

    if template_id == ZHONGYI_TEMPLATE_ID:
        address = _required_value(variables, "address", "医生地址")
        name = _required_value(variables, "name", "医生称呼")
        specialty = _required_value(variables, "specialty", "医生专长")
        feature = str(variables.get("feature") or "").strip()
        material_names = {
            "doctor-scene": "中医师问诊画面",
            "clinic-scene": "诊所环境画面",
        }
        available_materials = [
            f"- {material_names[key]}：{max(0, int(value))} 个"
            for key, value in (material_context or {}).items()
            if key in material_names and int(value) > 0
        ]
        material_summary = "\n".join(available_materials) or "- 尚未提供素材数量，仅按人物信息创作文案"
        feature_value = feature or "未提供"
        return f"""你是一名大健康领域的人文纪实短视频编导。
请根据用户提供的信息，生成 {count} 条“中医寻访”口播文案。

【用户提供的信息】
- 医生地址：{address}
- 医生称呼：{name}
- 医生专长：{specialty}
- 医生特点：{feature_value}

【可用画面】
{material_summary}

【创作要求】
1. 使用第一人称寻访视角，语气真实、克制、有温度，不使用广告腔。
2. 每条文案包含 {ZHONGYI_MIN_CHARS}-{ZHONGYI_MAX_CHARS} 个汉字，拆分为 {ZHONGYI_MIN_SENTENCES}-{ZHONGYI_MAX_SENTENCES} 个短句。
3. 每个短句适合单独显示为一行短视频字幕，不要在句子中换行。
4. 开头两句从医生地址切入，并自然表达“找到这位医生”。
5. 中段依次描述现场印象、医生专长、相关健康困扰和问诊状态。
6. 结尾落到医生的职业态度、人物特点或给人的信任感。
7. 各条文案分别侧重寻访过程、问诊观察和人物特点；不足三条时按此前顺序选择，超过三条时继续变换切入角度。
8. 地址、称呼、专长和特点必须与输入一致，不得擅自增加具体事实。
9. 如果医生特点为“未提供”，不得编造中医世家、祖传、几代行医、秘方、古法、患者慕名而来或远道而来等信息。
10. 不虚构医院、科室、从医年限、患者数量、真实病例或素材中无法确认的事件。
11. 不承诺医疗效果，不使用“治愈”“根治”“包好”“保证有效”等表达。
12. 不添加关注、私信、咨询、购买或其他引流内容。
13. 只输出合法 JSON，不使用 Markdown 代码块或额外解释。

【输出格式】
{{
  "scripts": [
    {{"style": "寻访过程", "sentences": ["第一句", "第二句"]}},
    {{"style": "问诊观察", "sentences": ["第一句", "第二句"]}},
    {{"style": "人物特点", "sentences": ["第一句", "第二句"]}}
  ]
}}"""

    doctor_name = _required_value(variables, "doctor-name", "医生姓名")
    hospital = _required_value(variables, "hospital", "所在医院")
    department = _required_value(variables, "department", "科室")
    specialty = _required_value(variables, "specialty", "专业特长")
    subject = f"姓名：{doctor_name}\n医院：{hospital}\n科室：{department}\n专业特长：{specialty}"
    return (
        "你是一位专业的中文短视频口播文案撰写专家。\n\n"
        f"【人物信息】\n{subject}\n\n"
        f"【任务】\n生成 {count} 条彼此明显不同的短视频口播文案。\n"
        "每条控制在 50-100 个汉字，语言自然、适合直接配音，不要标题、编号或解释。\n"
        "突出医生的专业能力、医院背景和可信赖感，避免医疗效果承诺和夸张用语。\n\n"
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


def _fit_filter(width: int, height: int, *, fill_mode: str = "contain") -> str:
    if fill_mode == "cover":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps=30,format=yuv420p"
        )
    if fill_mode != "contain":
        raise TemplateProductionError(f"不支持的画面填充方式：{fill_mode}")
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30,format=yuv420p"
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

    command.extend(
        [
            "-an",
            "-vf",
            _fit_filter(width, height, fill_mode=fill_mode),
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


def write_zhongyi_ass(
    script: str,
    duration: float,
    output_path: Path,
    *,
    target_size: tuple[int, int],
    timings: tuple[TTSTiming, ...] | list[TTSTiming] = (),
) -> Path:
    width, height = target_size
    subtitle_size = max(34, round(height * 0.034))
    notice_size = max(22, round(height * 0.017))
    outline = max(3, round(height * 0.0026))
    bottom_margin = max(80, round(height * 0.13))
    top_margin = max(34, round(height * 0.035))
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
        f"Style: Subtitle,Microsoft YaHei,{subtitle_size},&H001FD2FF,&H001FD2FF,&H00000000,&H70000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline},1,2,70,70,{bottom_margin},1",
        f"Style: Notice,Microsoft YaHei,{notice_size},&H00FFFFFF,&H00FFFFFF,&H50000000,&H50000000,"
        f"0,0,0,0,100,100,0,0,1,1,1,8,50,50,{top_margin},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{_ass_time(0)},{_ass_time(duration)},Notice,,0,0,0,,{ZHONGYI_SAFETY_NOTICE}",
    ]
    lines.extend(
        f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},Subtitle,,0,0,0,,{_ass_text(text)}"
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

    ass_path = write_zhongyi_ass(
        script,
        duration,
        work_dir / "subtitles.ass",
        target_size=target_size,
        timings=timings,
    )
    command = ["ffmpeg", "-y"]
    for segment_path in prepared:
        command.extend(["-i", str(segment_path)])
    command.extend(["-i", str(audio_path)])

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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            f"{len(prepared)}:a:0",
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
