#!/usr/bin/env python3
"""Render a lightweight, local preview for a validated template definition.

This helper intentionally previews the generic media flow only. It does not
call the Video Factory backend, an LLM, TTS provider, or any remote service.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
RATIO_SIZES = {
    "9:16": (540, 960),
    "16:9": (960, 540),
    "1:1": (720, 720),
    "3:4": (600, 800),
}


class PreviewError(RuntimeError):
    pass


def load_validator():
    import importlib.util

    path = SCRIPT_DIR / "validate_template.py"
    spec = importlib.util.spec_from_file_location("template_preview_validator", path)
    if spec is None or spec.loader is None:
        raise PreviewError("无法加载模板校验器")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PreviewError(f"无法读取 JSON 文件：{path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PreviewError(f"JSON 语法错误（第 {exc.lineno} 行，第 {exc.colno} 列）：{exc.msg}") from exc


def executable(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise PreviewError(f"找不到 {name}，请先安装 FFmpeg 并确保它在 PATH 中")
    return path


def run(command: list[str]) -> None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PreviewError(f"无法启动 FFmpeg：{exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[-1] if detail else "未知 FFmpeg 错误"
        raise PreviewError(f"FFmpeg 合成失败：{message}")


def media_files(root: Path) -> list[Path]:
    if not root.exists():
        raise PreviewError(f"素材目录不存在：{root}")
    if not root.is_dir():
        raise PreviewError(f"素材路径不是目录：{root}")
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS
    )


def group_materials(template: dict[str, Any], root: Path | None) -> dict[str, list[Path]]:
    requirements = template.get("material_requirements") or []
    groups = {str(item["key"]): [] for item in requirements}
    if root is None:
        return groups

    files = media_files(root)
    unused = list(files)
    for requirement in requirements:
        key = str(requirement["key"])
        media_type = requirement["media_type"]
        allowed = SUPPORTED_IMAGE_EXTENSIONS if media_type == "image" else SUPPORTED_VIDEO_EXTENSIONS
        named = [path for path in files if path.stem.lower().startswith(key.lower()) and path.suffix.lower() in allowed]
        if named:
            groups[key] = named[: requirement["max_count"]]
            unused = [path for path in unused if path not in groups[key]]

    for requirement in requirements:
        key = str(requirement["key"])
        if groups[key]:
            continue
        media_type = requirement["media_type"]
        allowed = SUPPORTED_IMAGE_EXTENSIONS if media_type == "image" else SUPPORTED_VIDEO_EXTENSIONS
        matching = [path for path in unused if path.suffix.lower() in allowed]
        groups[key] = matching[: requirement["max_count"]]
        unused = [path for path in unused if path not in groups[key]]
    return groups


def ratio_size(template: dict[str, Any]) -> tuple[int, int]:
    ratio = str((template.get("production") or {}).get("default_ratio") or "9:16")
    try:
        return RATIO_SIZES[ratio]
    except KeyError as exc:
        raise PreviewError(f"不支持的预览画幅：{ratio}") from exc


def make_clip(
    ffmpeg: str,
    source: Path | None,
    output: Path,
    *,
    size: tuple[int, int],
    duration: float,
    label: str,
    media_type: str,
) -> None:
    width, height = size
    if source is None:
        color = "#334155" if media_type == "video" else "#64748b"
        input_args = ["-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}:d={duration:.2f}:r=25"]
    elif media_type == "image":
        input_args = ["-loop", "1", "-t", f"{duration:.2f}", "-i", str(source)]
    else:
        input_args = ["-t", f"{duration:.2f}", "-i", str(source)]

    # Keep the preview renderer dependency-light: actual media is preserved,
    # while every clip is normalized to the selected canvas and frame rate.
    command = [ffmpeg, "-y", *input_args]
    command.extend([
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p",
        "-r", "25",
        "-an",
        "-t", f"{duration:.2f}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        str(output),
    ])
    run(command)


def concat_clips(ffmpeg: str, clips: list[Path], output: Path, *, duration: float) -> None:
    concat_file = output.with_suffix(".concat.txt")
    concat_file.write_text(
        "\n".join(f"file '{path.resolve().as_posix().replace("'", "'\\''")}'" for path in clips) + "\n",
        encoding="utf-8",
    )
    try:
        run([
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t", f"{duration:.2f}", "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(output),
        ])
    finally:
        concat_file.unlink(missing_ok=True)


def render(template: dict[str, Any], materials_root: Path | None, output: Path, ffmpeg: str) -> None:
    requirements = template.get("material_requirements") or []
    if not requirements:
        raise PreviewError("模板没有素材槽，无法生成预览")
    groups = group_materials(template, materials_root)
    size = ratio_size(template)
    clip_duration = 3.0
    clips: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="video-factory-preview-") as temp_dir:
        temp_root = Path(temp_dir)
        for index, requirement in enumerate(requirements, start=1):
            key = str(requirement["key"])
            selected = groups[key][0] if groups[key] else None
            clip_path = temp_root / f"clip_{index:02d}.mp4"
            make_clip(
                ffmpeg,
                selected,
                clip_path,
                size=size,
                duration=clip_duration,
                label=key,
                media_type=str(requirement["media_type"]),
            )
            clips.append(clip_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        concat_clips(ffmpeg, clips, output, duration=clip_duration * len(clips))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="为 Video Factory 模板生成本地预览视频")
    parser.add_argument("template", type=Path, help="已通过格式校验的模板 JSON")
    parser.add_argument("--materials", type=Path, help="用户素材目录；文件名以素材槽 key 开头时优先归入对应槽位")
    parser.add_argument("--content", type=Path, help="示例内容 JSON（当前仅用于保留工作流接口，不会发送到远程服务）")
    parser.add_argument("--output", type=Path, required=True, help="输出 MP4 路径")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg 可执行文件路径，默认从 PATH 查找")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        template = read_json(args.template)
        validator = load_validator()
        errors = validator.TemplateValidator().validate(template)
        if errors:
            raise PreviewError("模板未通过格式校验，请先运行 validate_template.py")
        if args.content is not None:
            content = read_json(args.content)
            if not isinstance(content, dict):
                raise PreviewError("--content 必须是 JSON 对象")
        ffmpeg = executable(args.ffmpeg) if args.ffmpeg == "ffmpeg" else args.ffmpeg
        if not Path(ffmpeg).exists() and args.ffmpeg != "ffmpeg":
            raise PreviewError(f"找不到 FFmpeg：{args.ffmpeg}")
        render(template, args.materials, args.output, ffmpeg)
    except PreviewError as exc:
        print(f"预览生成失败：{exc}", file=sys.stderr)
        return 1
    print(f"预览生成完成：{args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
