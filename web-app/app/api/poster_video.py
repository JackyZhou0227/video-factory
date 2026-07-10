from __future__ import annotations

import asyncio
import re
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.auth import require_current_user
from app.core.config import app_config, resolve_output_dir
from app.services import poster_video

router = APIRouter(dependencies=[Depends(require_current_user)])

MAX_BATCH_SIZE = 50
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MEDIA_TYPES = {"video", "image"}

_tasks: dict[str, dict] = {}


def _public_output_url(path: Path) -> str:
    output_root = resolve_output_dir(app_config).resolve()
    relative_path = path.resolve().relative_to(output_root).as_posix()
    return f"/output/{relative_path}"


def _safe_filename(filename: str, fallback: str) -> str:
    raw = Path(filename or fallback).name
    safe = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", raw, flags=re.UNICODE).strip("._")
    return safe or fallback


def _new_task(user_id: str, task_dir: Path, files: list[dict], media_type: str) -> dict:
    return {
        "user_id": user_id,
        "media_type": media_type,
        "status": "pending",
        "progress": 0,
        "message": "批量任务已创建，等待开始处理...",
        "items": [
            {
                "id": item["id"],
                "filename": item["filename"],
                "status": "pending",
                "message": "等待处理",
                "video_url": None,
                "image_url": None,
                "asset_url": None,
                "error": None,
            }
            for item in files
        ],
        "zip_url": None,
        "output_dir": str(task_dir),
        "error": None,
    }


@router.get("/poster-videos/fonts")
def get_poster_video_fonts():
    return poster_video.discover_fonts()


@router.post("/poster-videos/generate")
async def generate_poster_videos(
    user: dict = Depends(require_current_user),
    template: str = Form(...),
    media_type: str = Form("video"),
    assets: list[UploadFile] = File(...),
):
    media_type = media_type.strip().lower()
    if media_type not in MEDIA_TYPES:
        raise HTTPException(status_code=422, detail="media_type must be 'video' or 'image'")
    if not assets:
        raise HTTPException(status_code=422, detail=f"Please upload at least one {media_type}")
    if len(assets) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=422, detail=f"Batch size cannot exceed {MAX_BATCH_SIZE} files")

    try:
        parsed_template = poster_video.parse_template(template)
        if media_type == "video":
            poster_video.require_ffmpeg()
    except poster_video.PosterVideoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    output_root = resolve_output_dir(app_config)
    task_id = uuid.uuid4().hex
    task_dir = output_root / "poster_video" / task_id
    input_dir = task_dir / "input"
    output_dir = task_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_files: list[dict] = []
    allowed_extensions = VIDEO_EXTENSIONS if media_type == "video" else IMAGE_EXTENSIONS
    default_suffix = ".mp4" if media_type == "video" else ".jpg"
    output_suffix = ".mp4" if media_type == "video" else ".jpg"
    output_label = "poster" if media_type == "video" else "poster_image"

    for index, asset in enumerate(assets, start=1):
        suffix = Path(asset.filename or "").suffix.lower() or default_suffix
        if suffix not in allowed_extensions:
            raise HTTPException(status_code=422, detail=f"Unsupported {media_type} format: {asset.filename}")

        file_id = uuid.uuid4().hex
        safe_name = _safe_filename(asset.filename or f"{media_type}_{index}{suffix}", f"{media_type}_{index}{suffix}")
        input_path = input_dir / f"{file_id}{suffix}"
        input_path.write_bytes(await asset.read())

        output_name = f"{Path(safe_name).stem}_{file_id[:8]}_{output_label}{output_suffix}"
        output_path = output_dir / output_name
        saved_files.append(
            {
                "id": file_id,
                "filename": safe_name,
                "input_path": input_path,
                "output_path": output_path,
            }
        )

    overlay_path = task_dir / "overlay.png"
    try:
        poster_video.create_overlay(parsed_template, overlay_path)
    except poster_video.PosterVideoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _tasks[task_id] = _new_task(user_id=user["id"], task_dir=task_dir, files=saved_files, media_type=media_type)
    asyncio.create_task(
        _run_batch(
            task_id=task_id,
            files=saved_files,
            overlay_path=overlay_path,
            task_dir=task_dir,
            media_type=media_type,
        )
    )
    return {"task_id": task_id}


@router.get("/poster-videos/task/{task_id}")
def get_poster_video_task(task_id: str, user: dict = Depends(require_current_user)):
    task = _tasks.get(task_id)
    if task is None or task.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def _run_batch(task_id: str, files: list[dict], overlay_path: Path, task_dir: Path, media_type: str) -> None:
    task = _tasks[task_id]
    total = len(files)
    completed = 0
    failed = 0

    def set_item(file_id: str, **updates):
        for item in task["items"]:
            if item["id"] == file_id:
                item.update(updates)
                return

    try:
        label = "视频" if media_type == "video" else "图片"
        task.update(status="running", progress=1, message=f"开始处理 {total} 个{label}...")

        for index, item in enumerate(files, start=1):
            set_item(item["id"], status="running", message=f"正在生成大字报{label}...")
            task.update(
                status="running",
                progress=max(1, round((index - 1) / total * 92)),
                message=f"正在处理第 {index}/{total} 个{label}：{item['filename']}",
            )

            try:
                processor = poster_video.process_video if media_type == "video" else poster_video.process_image
                await asyncio.to_thread(
                    processor,
                    item["input_path"],
                    overlay_path,
                    item["output_path"],
                )
                public_url = _public_output_url(item["output_path"])
                set_item(
                    item["id"],
                    status="completed",
                    message="处理完成",
                    video_url=public_url if media_type == "video" else None,
                    image_url=public_url if media_type == "image" else None,
                    asset_url=public_url,
                    error=None,
                )
                completed += 1
            except Exception as exc:
                set_item(item["id"], status="failed", message="处理失败", error=str(exc))
                failed += 1

        zip_name = "poster_videos.zip" if media_type == "video" else "poster_images.zip"
        zip_path = task_dir / zip_name
        if completed:
            await asyncio.to_thread(_create_zip, zip_path, [item["output_path"] for item in files if item["output_path"].exists()])
            task["zip_url"] = _public_output_url(zip_path)

        final_status = "completed" if failed == 0 else ("failed" if completed == 0 else "completed")
        final_message = f"批量处理完成：成功 {completed} 个，失败 {failed} 个。"
        task.update(status=final_status, progress=100, message=final_message)
        if failed and not completed:
            task["error"] = final_message
    except Exception as exc:
        task.update(status="failed", progress=0, message=f"批量处理失败：{exc}", error=str(exc))


def _create_zip(zip_path: Path, files: list[Path]) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
