from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api import common
from app.api.auth import require_current_user
from app.core import uploads
from app.core.config import app_config, resolve_output_dir
from app.services import poster_video, settings_store, task_store
from app.services.task_runtime import run_blocking

router = APIRouter(dependencies=[Depends(require_current_user)])

MAX_BATCH_SIZE = 50
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"}
MEDIA_TYPES = {"video", "image"}

_tasks: dict[str, dict] = {}


def _task_payload(record: dict, cached: dict | None = None) -> dict:
    extra = record.get("extra_info") or {}
    items = list(cached.get("items", [])) if cached else []
    if not items:
        items = list(extra.get("items", []))
    if not items:
        items = [
            {
                "id": artifact["id"],
                "filename": artifact.get("name") or artifact["id"],
                "source_type": artifact.get("kind"),
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
        "bgm_name": extra.get("bgm_name"),
        "narration_name": extra.get("narration_name"),
        "narration_duration": extra.get("narration_duration"),
        "bgm_duration": extra.get("bgm_duration"),
        "mute_original_audio": extra.get("mute_original_audio", True),
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
                "source_type": item.get("source_type", media_type),
                "target_duration": None,
                "video_speed": None,
                "narration_speed": None,
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


def _persist_items(task_id: str, task: dict, **updates) -> None:
    extra = task_store.get_task(task_id).get("extra_info") or {}
    extra.update(updates.pop("extra_info", {}))
    task_store.update_task(task_id, extra_info={**extra, "items": task["items"]}, **updates)


def _upload_options(source_type: str) -> dict:
    if source_type == "image":
        extensions, mime_types, max_size, suffix = (
            IMAGE_EXTENSIONS, uploads.IMAGE_MIME_TYPES, uploads.MAX_IMAGE_FILE_SIZE, ".jpg",
        )
    elif source_type == "video":
        extensions, mime_types, max_size, suffix = (
            VIDEO_EXTENSIONS, uploads.VIDEO_MIME_TYPES, uploads.MAX_VIDEO_FILE_SIZE, ".mp4",
        )
    else:
        extensions, mime_types, max_size, suffix = (
            AUDIO_EXTENSIONS, uploads.AUDIO_MIME_TYPES, uploads.MAX_AUDIO_FILE_SIZE, None,
        )
    return {
        "allowed_extensions": extensions,
        "allowed_mime_types": mime_types,
        "max_size": max_size,
        "default_suffix": suffix,
        "label": source_type,
    }


def _source_type_for_upload(asset: UploadFile, output_mode: str) -> str:
    suffix = Path(asset.filename or "").suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    declared_mime = (asset.content_type or "").split(";", 1)[0].strip().lower()
    if declared_mime.startswith("image/"):
        return "image"
    if declared_mime.startswith("video/"):
        return "video"
    return output_mode


def _resolve_bgm(user_id: str, bgm_id: str, output_root: Path) -> tuple[Path | None, str | None]:
    if not bgm_id:
        return None, None
    try:
        track = settings_store.get_bgm_track(user_id, bgm_id)
    except settings_store.BgmTrackNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    bgm_root = (output_root / "bgm" / user_id).resolve()
    bgm_path = (output_root / track["relative_path"]).resolve()
    if not bgm_path.is_relative_to(bgm_root) or not bgm_path.is_file():
        raise HTTPException(status_code=422, detail="BGM file not found")
    return bgm_path, track["name"]


@router.get("/poster-videos/fonts")
def get_poster_video_fonts():
    return poster_video.discover_fonts()


@router.post("/poster-videos/generate")
async def generate_poster_videos(
    user: dict = Depends(require_current_user),
    template: str = Form(...),
    media_type: str = Form("video"),
    assets: list[UploadFile] = File(...),
    narration_audio: UploadFile | None = File(None),
    bgm_id: str = Form(""),
    mute_original_audio: bool = Form(True),
):
    media_type = media_type.strip().lower()
    if media_type not in MEDIA_TYPES:
        raise HTTPException(status_code=422, detail="media_type must be 'video' or 'image'")
    if not assets:
        raise HTTPException(status_code=422, detail=f"Please upload at least one {media_type}")
    if len(assets) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=422, detail=f"Batch size cannot exceed {MAX_BATCH_SIZE} files")
    bgm_id = bgm_id.strip()
    if media_type == "image" and (narration_audio is not None or bgm_id):
        raise HTTPException(status_code=422, detail="Image output does not accept narration_audio or BGM")

    try:
        parsed_template = poster_video.parse_template(template)
        if media_type == "video":
            poster_video.require_ffmpeg()
    except poster_video.PosterVideoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    source_types = []
    for asset in assets:
        source_type = _source_type_for_upload(asset, media_type)
        if media_type == "image" and source_type != "image":
            raise HTTPException(status_code=422, detail="Image output only accepts image sources")
        uploads.validate_upload(asset, **_upload_options(source_type))
        source_types.append(source_type)
    if media_type == "video" and "image" in source_types and narration_audio is None and not bgm_id:
        raise HTTPException(status_code=422, detail="Video output containing images requires narration_audio or BGM")
    if narration_audio is not None:
        uploads.validate_upload(narration_audio, **_upload_options("audio"))
    output_root = resolve_output_dir(app_config).resolve()
    bgm_source, bgm_name = _resolve_bgm(user["id"], bgm_id, output_root)

    task_id = uuid.uuid4().hex
    task_record = common.create_task(
        user=user,
        task_type=task_store.TASK_TYPE_POSTER,
        generation_type=media_type,
        requested_count=len(assets),
        task_id=task_id,
        output_root=output_root,
        message="批量任务已创建，等待开始处理...",
        extra_info={
            "media_type": media_type,
            "bgm_id": bgm_id or None,
            "bgm_name": bgm_name,
            "narration_name": common.safe_filename(narration_audio.filename, "narration")
            if narration_audio is not None else None,
            "mute_original_audio": mute_original_audio,
            "narration_duration": None,
            "bgm_duration": None,
        },
    )
    task_dir = Path(task_record["storage_path"])
    input_dir = task_dir / "input"
    output_dir = task_dir / "output"
    overlay_path = task_dir / "overlay.png"
    saved_files: list[dict] = []
    output_suffix = ".mp4" if media_type == "video" else ".jpg"
    output_label = "poster" if media_type == "video" else "poster_image"
    for index, (asset, source_type) in enumerate(zip(assets, source_types), start=1):
        suffix = Path(asset.filename or "").suffix.lower() or _upload_options(source_type)["default_suffix"]
        file_id = uuid.uuid4().hex
        safe_name = common.safe_filename(asset.filename, f"{source_type}_{index}{suffix}")
        saved_files.append({
            "id": file_id,
            "filename": safe_name,
            "source_type": source_type,
            "input_path": input_dir / f"{file_id}{suffix}",
            "output_path": output_dir / f"{Path(safe_name).stem}_{file_id[:8]}_{output_label}{output_suffix}",
        })
    task = _new_task(user_id=user["id"], task_dir=task_dir, files=saved_files, media_type=media_type)
    narration_path = None
    bgm_path = None
    narration_duration = None
    bgm_duration = None
    try:
        _persist_items(task_id, task)
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        for asset, item in zip(assets, saved_files):
            await uploads.save_upload(
                asset, item["input_path"], **_upload_options(item["source_type"]),
            )
        if narration_audio is not None:
            narration_path = input_dir / f"narration{Path(narration_audio.filename).suffix.lower()}"
            await uploads.save_upload(narration_audio, narration_path, **_upload_options("audio"))
        if bgm_source is not None:
            bgm_path = input_dir / f"bgm_snapshot{bgm_source.suffix.lower()}"
            await run_blocking("media", shutil.copy2, bgm_source, bgm_path)
        if narration_path is not None:
            narration_duration = await run_blocking("media", poster_video.probe_audio_duration, narration_path)
        if bgm_path is not None:
            bgm_duration = await run_blocking("media", poster_video.probe_audio_duration, bgm_path)
        _persist_items(
            task_id, task,
            extra_info={"narration_duration": narration_duration, "bgm_duration": bgm_duration},
        )
        poster_video.create_overlay(parsed_template, overlay_path)
        _tasks[task_id] = task
        common.schedule_task(task_id, lambda: _run_batch(
            task_id=task_id,
            files=saved_files,
            overlay_path=overlay_path,
            task_dir=task_dir,
            media_type=media_type,
            narration_path=narration_path,
            bgm_path=bgm_path,
            mute_original_audio=mute_original_audio,
            narration_duration=narration_duration,
            bgm_duration=bgm_duration,
        ))
    except Exception as exc:
        error = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
        for item in task["items"]:
            item.update(status="failed", message="处理失败", error=error)
        task.update(status="failed", error=error)
        _persist_items(
            task_id, task,
            status="failed",
            progress=0,
            message="创建大字报任务失败",
            error=error,
            success_count=0,
            failed_count=len(assets),
            finished=True,
        )
        for snapshot in input_dir.glob("*"):
            snapshot.unlink(missing_ok=True)
        overlay_path.unlink(missing_ok=True)
        _tasks.pop(task_id, None)
        if isinstance(exc, HTTPException):
            raise
        if isinstance(exc, poster_video.PosterVideoError):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail="保存任务素材失败") from exc
    return {"task_id": task_id}


@router.get("/poster-videos/task/{task_id}")
def get_poster_video_task(task_id: str, user: dict = Depends(require_current_user)):
    try:
        record = task_store.get_task(task_id, user["id"])
    except task_store.TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    return _task_payload(record, _tasks.get(task_id))


async def _run_batch(
    task_id: str,
    files: list[dict],
    overlay_path: Path,
    task_dir: Path,
    media_type: str,
    *,
    narration_path: Path | None = None,
    bgm_path: Path | None = None,
    mute_original_audio: bool = True,
    narration_duration: float | None = None,
    bgm_duration: float | None = None,
) -> None:
    task = _tasks[task_id]
    total = len(files)
    completed = 0
    failed = 0
    completed_outputs: list[Path] = []

    def set_item(file_id: str, **updates):
        for item in task["items"]:
            if item["id"] == file_id:
                item.update(updates)
                return

    try:
        label = "视频" if media_type == "video" else "图片"
        task.update(status="running", progress=1, message=f"开始处理 {total} 个{label}...")
        _persist_items(
            task_id, task,
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
            _persist_items(
                task_id, task,
                status="running",
                progress=task["progress"],
                message=task["message"],
            )

            try:
                processor = poster_video.process_video if media_type == "video" else poster_video.process_image
                options = {
                    "source_type": item.get("source_type", "video"),
                    "narration_path": narration_path,
                    "bgm_path": bgm_path,
                    "mute_original_audio": mute_original_audio,
                    "narration_duration": narration_duration,
                    "bgm_duration": bgm_duration,
                } if media_type == "video" else {}
                metadata = await run_blocking("media",
                    processor,
                    item["input_path"],
                    overlay_path,
                    item["output_path"],
                    **options,
                )
                if media_type == "video" and metadata:
                    set_item(item["id"], **metadata)
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
                completed_outputs.append(item["output_path"])
            except Exception as exc:
                item["output_path"].unlink(missing_ok=True)
                set_item(
                    item["id"], status="failed", message="处理失败", error=str(exc),
                    video_url=None, image_url=None, asset_url=None,
                )
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
            _persist_items(
                task_id, task,
                success_count=completed,
                failed_count=failed,
            )

        zip_name = "poster_videos.zip" if media_type == "video" else "poster_images.zip"
        zip_path = task_dir / zip_name
        if completed:
            await run_blocking("media", common.create_output_zip, zip_path, completed_outputs)
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
                counts_toward_result=False,
            )

        final_status = "completed" if failed == 0 else ("failed" if completed == 0 else "partial_failed")
        final_message = f"批量处理完成：成功 {completed} 个，失败 {failed} 个。"
        task.update(status=final_status, progress=100, message=final_message)
        if failed and not completed:
            task["error"] = final_message
        _persist_items(
            task_id, task,
            status=final_status,
            progress=100,
            message=final_message,
            error=final_message if failed and not completed else None,
            success_count=completed,
            failed_count=failed,
            finished=True,
        )
    except Exception as exc:
        for item in task["items"]:
            if item["status"] not in {"completed", "failed"}:
                item.update(status="failed", message="处理失败", error=str(exc))
        task.update(status="failed", progress=0, message=f"批量处理失败：{exc}", error=str(exc))
        _persist_items(
            task_id, task,
            status="failed",
            progress=0,
            message=f"批量处理失败：{exc}",
            error=str(exc),
            success_count=completed,
            failed_count=max(failed, total - completed),
            finished=True,
        )
