from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api import common
from app.api.auth import require_current_user
from app.core import uploads
from app.core.config import app_config, resolve_output_dir
from app.services import poster_video, task_store

router = APIRouter(dependencies=[Depends(require_current_user)])

MAX_BATCH_SIZE = 50
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MEDIA_TYPES = {"video", "image"}

_tasks: dict[str, dict] = {}


def _task_payload(record: dict, cached: dict | None = None) -> dict:
    items = list(cached.get("items", [])) if cached else []
    if not items:
        items = [
            {
                "id": artifact["id"],
                "filename": artifact.get("name") or artifact["id"],
                "status": artifact.get("status", "pending"),
                "message": "处理完成" if artifact.get("status") == "completed" else "处理失败",
                "video_url": common.artifact_url(record["id"], artifact["id"])
                if artifact.get("kind") == "video" and artifact.get("status") == "completed"
                else None,
                "image_url": common.artifact_url(record["id"], artifact["id"])
                if artifact.get("kind") == "image" and artifact.get("status") == "completed"
                else None,
                "asset_url": common.artifact_url(record["id"], artifact["id"])
                if artifact.get("kind") in {"image", "video"} and artifact.get("status") == "completed"
                else None,
                "error": artifact.get("error"),
            }
            for artifact in record.get("artifacts", [])
            if artifact.get("kind") != "archive"
        ]
    archive = next(
        (artifact for artifact in record.get("artifacts", []) if artifact.get("kind") == "archive"),
        None,
    )
    return {
        "user_id": record["user_id"],
        "media_type": record["generation_type"],
        "status": record["status"],
        "progress": record["progress"],
        "message": record["message"],
        "items": items,
        "zip_url": common.artifact_url(record["id"], archive["id"], "download") if archive else None,
        "error": record.get("error"),
    }


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

    allowed_extensions = VIDEO_EXTENSIONS if media_type == "video" else IMAGE_EXTENSIONS
    default_suffix = ".mp4" if media_type == "video" else ".jpg"
    allowed_mime_types = uploads.VIDEO_MIME_TYPES if media_type == "video" else uploads.IMAGE_MIME_TYPES
    max_size = uploads.MAX_VIDEO_FILE_SIZE if media_type == "video" else uploads.MAX_IMAGE_FILE_SIZE
    for asset in assets:
        uploads.validate_upload(
            asset,
            allowed_extensions=allowed_extensions,
            allowed_mime_types=allowed_mime_types,
            max_size=max_size,
            default_suffix=default_suffix,
            label=media_type,
        )

    task_id = uuid.uuid4().hex
    task_record = task_store.create_task(
        user=user,
        task_type=task_store.TASK_TYPE_POSTER,
        generation_type=media_type,
        requested_count=len(assets),
        task_id=task_id,
        output_root=resolve_output_dir(app_config),
        message="批量任务已创建，等待开始处理...",
        extra_info={"media_type": media_type},
    )
    task_dir = Path(task_record["storage_path"])
    input_dir = task_dir / "input"
    output_dir = task_dir / "output"
    try:
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        saved_files: list[dict] = []
        output_suffix = ".mp4" if media_type == "video" else ".jpg"
        output_label = "poster" if media_type == "video" else "poster_image"

        for index, asset in enumerate(assets, start=1):
            suffix = Path(asset.filename or "").suffix.lower() or default_suffix
            file_id = uuid.uuid4().hex
            safe_name = common.safe_filename(asset.filename or f"{media_type}_{index}{suffix}", f"{media_type}_{index}{suffix}")
            input_path = input_dir / f"{file_id}{suffix}"
            await uploads.save_upload(
                asset,
                input_path,
                allowed_extensions=allowed_extensions,
                allowed_mime_types=allowed_mime_types,
                max_size=max_size,
                default_suffix=default_suffix,
                label=media_type,
            )

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
        poster_video.create_overlay(parsed_template, overlay_path)
    except poster_video.PosterVideoError as exc:
        task_store.update_task(
            task_id,
            status="failed",
            progress=0,
            message="创建大字报任务失败",
            error=str(exc),
            success_count=0,
            failed_count=len(assets),
            finished=True,
        )
        for saved_file in locals().get("saved_files", []):
            Path(saved_file["input_path"]).unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException as exc:
        task_store.update_task(
            task_id,
            status="failed",
            progress=0,
            message="保存大字报任务素材失败",
            error=str(exc.detail),
            success_count=0,
            failed_count=len(assets),
            finished=True,
        )
        for saved_file in locals().get("saved_files", []):
            Path(saved_file["input_path"]).unlink(missing_ok=True)
        raise
    except Exception as exc:
        task_store.update_task(
            task_id,
            status="failed",
            progress=0,
            message="保存大字报任务素材失败",
            error=str(exc),
            success_count=0,
            failed_count=len(assets),
            finished=True,
        )
        for saved_file in locals().get("saved_files", []):
            Path(saved_file["input_path"]).unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="保存任务素材失败") from exc

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
    try:
        record = task_store.get_task(task_id, user["id"])
    except task_store.TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    return _task_payload(record, _tasks.get(task_id))


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
        task_store.update_task(
            task_id,
            status="running",
            progress=1,
            message=f"开始处理 {total} 个{label}...",
            started=True,
        )

        for index, item in enumerate(files, start=1):
            set_item(item["id"], status="running", message=f"正在生成大字报{label}...")
            task.update(
                status="running",
                progress=max(1, round((index - 1) / total * 92)),
                message=f"正在处理第 {index}/{total} 个{label}：{item['filename']}",
            )
            task_store.update_task(
                task_id,
                status="running",
                progress=task["progress"],
                message=task["message"],
            )

            try:
                processor = poster_video.process_video if media_type == "video" else poster_video.process_image
                await asyncio.to_thread(
                    processor,
                    item["input_path"],
                    overlay_path,
                    item["output_path"],
                )
                public_url = common.artifact_url(task_id, item["id"])
                set_item(
                    item["id"],
                    status="completed",
                    message="处理完成",
                    video_url=public_url if media_type == "video" else None,
                    image_url=public_url if media_type == "image" else None,
                    asset_url=public_url,
                    error=None,
                )
                task_store.add_artifact(
                    task_id,
                    artifact_id=item["id"],
                    path=item["output_path"],
                    name=item["output_path"].name,
                    kind=media_type,
                    mime_type="video/mp4" if media_type == "video" else "image/jpeg",
                    is_primary=completed == 0,
                )
                completed += 1
            except Exception as exc:
                set_item(item["id"], status="failed", message="处理失败", error=str(exc))
                failed += 1
                task_store.add_artifact(
                    task_id,
                    artifact_id=item["id"],
                    path=item["output_path"],
                    name=item["output_path"].name,
                    kind=media_type,
                    mime_type="video/mp4" if media_type == "video" else "image/jpeg",
                    status="failed",
                )

        zip_name = "poster_videos.zip" if media_type == "video" else "poster_images.zip"
        zip_path = task_dir / zip_name
        if completed:
            await asyncio.to_thread(common.create_output_zip, zip_path, [item["output_path"] for item in files if item["output_path"].exists()])
            archive_id = f"{task_id}-archive"
            task["zip_url"] = common.artifact_url(task_id, archive_id, "download")
            task_store.add_artifact(
                task_id,
                artifact_id=archive_id,
                path=zip_path,
                name=zip_name,
                kind="archive",
                mime_type="application/zip",
                is_primary=True,
            )

        final_status = "completed" if failed == 0 else ("failed" if completed == 0 else "partial_failed")
        final_message = f"批量处理完成：成功 {completed} 个，失败 {failed} 个。"
        task.update(status=final_status, progress=100, message=final_message)
        if failed and not completed:
            task["error"] = final_message
        task_store.update_task(
            task_id,
            status=final_status,
            progress=100,
            message=final_message,
            error=final_message if failed and not completed else None,
            success_count=completed,
            failed_count=failed,
            finished=True,
        )
    except Exception as exc:
        task.update(status="failed", progress=0, message=f"批量处理失败：{exc}", error=str(exc))
        task_store.update_task(
            task_id,
            status="failed",
            progress=0,
            message=f"批量处理失败：{exc}",
            error=str(exc),
            success_count=completed,
            failed_count=max(failed, total - completed),
            finished=True,
        )
