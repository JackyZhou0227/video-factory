from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api import common
from app.api.auth import require_current_user
from app.core import uploads
from app.core.config import app_config, resolve_output_dir
from app.services import settings_store, smart_editing, task_store, template_production
from app.services.task_runtime import run_blocking
from app.services.tts import EDGE_TTS_MODEL, TTSRequest, tts_service

router = APIRouter(prefix="/smart-editing", tags=["smart-editing"])

MIN_SCRIPT_LENGTH = 10
MAX_SCRIPT_LENGTH = 5000
MAX_GENERATE_COUNT = 10
MAX_MATERIAL_FILE_SIZE = uploads.MAX_VIDEO_FILE_SIZE
SMART_EDITING_TTS_VOICE_ID = "zh-CN-YunjianNeural"
SMART_EDITING_TTS_SPEED = 1.0
SMART_EDITING_TTS_VOLUME = 100

_tasks: dict[str, dict[str, Any]] = {}


def _task_payload(record: dict[str, Any], cached: dict[str, Any] | None = None) -> dict[str, Any]:
    if cached is not None:
        payload = {key: value for key, value in cached.items() if not key.startswith("_")}
        payload.update(
            status=record["status"],
            progress=record["progress"],
            message=record["message"],
            error=record.get("error"),
        )
        return payload

    extra = record.get("extra_info") or {}
    video_artifacts = [
        artifact for artifact in record.get("artifacts", []) if artifact.get("kind") == "video"
    ]
    artifacts_by_index = {
        index: artifact for index, artifact in enumerate(video_artifacts, start=1)
    }
    expected_count = int(record.get("requested_count") or 0)
    items = [
        _persisted_item_payload(record["id"], index, artifacts_by_index.get(index))
        for index in range(1, max(expected_count, len(video_artifacts)) + 1)
    ]
    archive = next(
        (artifact for artifact in record.get("artifacts", []) if artifact.get("kind") == "archive"),
        None,
    )
    return {
        "user_id": record["user_id"],
        "script": extra.get("script", ""),
        "keywords": extra.get("keywords", []),
        "pacing": extra.get("pacing", "standard"),
        "bgm_name": extra.get("bgm_name"),
        "generate_count": record["requested_count"],
        "status": record["status"],
        "progress": record["progress"],
        "message": record["message"],
        "items": items,
        "zip_url": common.artifact_url(record["id"], archive["id"], "download") if archive else None,
        "error": record.get("error"),
    }


def _persisted_item_payload(
    task_id: str,
    index: int,
    artifact: dict[str, Any] | None,
) -> dict[str, Any]:
    if artifact is None:
        return {
            "id": f"{task_id}-item-{index}",
            "index": index,
            "status": "failed",
            "message": "任务未完成",
            "video_url": None,
            "download_url": None,
            "error": "该版本在后端重启前未完成",
        }
    status = artifact.get("status", "pending")
    completed = status == "completed"
    return {
        "id": artifact["id"],
        "index": index,
        "status": status,
        "message": "生成完成" if completed else "生成失败",
        "video_url": common.artifact_url(task_id, artifact["id"]) if completed else None,
        "download_url": common.artifact_url(task_id, artifact["id"], "download") if completed else None,
        "error": artifact.get("error"),
    }


def _normalize_manifest(
    manifest: list[dict[str, Any]],
    *,
    file_count: int,
    keyword_count: int,
) -> list[dict[str, Any]]:
    if len(manifest) != file_count:
        raise HTTPException(status_code=422, detail="material_manifest 与上传文件数量不一致")

    normalized: list[dict[str, Any]] = []
    seen_file_indexes: set[int] = set()
    counts = [0] * keyword_count
    for position, item in enumerate(manifest, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail=f"第 {position} 条素材清单格式不正确")
        file_index = item.get("file_index")
        keyword_index = item.get("keyword_index")
        if isinstance(file_index, bool) or not isinstance(file_index, int):
            raise HTTPException(status_code=422, detail=f"第 {position} 条素材缺少有效 file_index")
        if isinstance(keyword_index, bool) or not isinstance(keyword_index, int):
            raise HTTPException(status_code=422, detail=f"第 {position} 条素材缺少有效 keyword_index")
        if not 0 <= file_index < file_count or file_index in seen_file_indexes:
            raise HTTPException(status_code=422, detail="material_manifest 的 file_index 必须唯一且连续")
        if not 0 <= keyword_index < keyword_count:
            raise HTTPException(status_code=422, detail="素材关键词序号超出范围")

        media_type = str(item.get("media_type") or "").strip().lower()
        if media_type not in {"image", "video"}:
            raise HTTPException(status_code=422, detail="素材类型必须是 image 或 video")
        name = str(item.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail=f"第 {position} 条素材缺少文件名")

        seen_file_indexes.add(file_index)
        counts[keyword_index] += 1
        normalized.append(
            {
                "file_index": file_index,
                "keyword_index": keyword_index,
                "media_type": media_type,
                "name": name,
            }
        )

    if seen_file_indexes != set(range(file_count)):
        raise HTTPException(status_code=422, detail="material_manifest 的 file_index 必须覆盖全部文件")
    empty_groups = [index + 1 for index, count in enumerate(counts) if count == 0]
    if empty_groups:
        labels = "、".join(str(index) for index in empty_groups)
        raise HTTPException(status_code=422, detail=f"第 {labels} 个关键词没有上传素材")
    return sorted(normalized, key=lambda item: item["file_index"])


def _validate_uploads(upload_items: list[UploadFile], manifest: list[dict[str, Any]]) -> None:
    manifest_by_index = {item["file_index"]: item for item in manifest}
    for index, upload in enumerate(upload_items):
        item = manifest_by_index[index]
        allowed = (
            template_production.IMAGE_EXTENSIONS
            if item["media_type"] == "image"
            else template_production.VIDEO_EXTENSIONS
        )
        allowed_mime_types = uploads.IMAGE_MIME_TYPES if item["media_type"] == "image" else uploads.VIDEO_MIME_TYPES
        max_size = uploads.MAX_IMAGE_FILE_SIZE if item["media_type"] == "image" else uploads.MAX_VIDEO_FILE_SIZE
        uploads.validate_upload(
            upload,
            allowed_extensions=allowed,
            allowed_mime_types=allowed_mime_types,
            max_size=max_size,
            filename=upload.filename or item["name"],
            label=item["media_type"],
        )


def _task_child_dir(task_dir: Path, name: str) -> Path:
    root = task_dir.resolve()
    child = (root / name).resolve()
    try:
        child.relative_to(root)
    except ValueError:
        raise RuntimeError("任务目录越界") from None
    child.mkdir(parents=True, exist_ok=True)
    return child


def _resolve_bgm_track(
    user_id: str,
    bgm_id: str,
    output_root: Path,
) -> tuple[Path | None, str | None]:
    normalized_id = str(bgm_id or "").strip()
    if not normalized_id:
        return None, None
    try:
        track = settings_store.get_bgm_track(user_id, normalized_id)
    except settings_store.BgmTrackNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    bgm_root = (output_root / "bgm" / user_id).resolve()
    bgm_path = (output_root / track["relative_path"]).resolve()
    try:
        bgm_path.relative_to(bgm_root)
    except ValueError:
        raise HTTPException(status_code=422, detail="背景音乐不存在") from None
    if not bgm_path.is_file():
        raise HTTPException(status_code=422, detail="背景音乐文件不存在，请重新上传")
    return bgm_path, track["name"]


async def _save_upload(
    upload: UploadFile,
    destination: Path,
    *,
    media_type: str,
    filename: str | None = None,
) -> int:
    allowed = template_production.IMAGE_EXTENSIONS if media_type == "image" else template_production.VIDEO_EXTENSIONS
    allowed_mime_types = uploads.IMAGE_MIME_TYPES if media_type == "image" else uploads.VIDEO_MIME_TYPES
    max_size = uploads.MAX_IMAGE_FILE_SIZE if media_type == "image" else uploads.MAX_VIDEO_FILE_SIZE
    return await uploads.save_upload(
        upload,
        destination,
        allowed_extensions=allowed,
        allowed_mime_types=allowed_mime_types,
        max_size=max_size,
        filename=filename,
        label=media_type,
    )


@router.post("/tasks")
async def create_task(
    script: str = Form(...),
    keywords: str = Form(...),
    pacing: str = Form("standard"),
    generate_count: int = Form(5),
    material_manifest: str = Form(...),
    materials: list[UploadFile] = File(...),
    bgm_id: str = Form(""),
    user: dict = Depends(require_current_user),
):
    clean_script = str(script or "").strip()
    if not MIN_SCRIPT_LENGTH <= len(clean_script) <= MAX_SCRIPT_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"script 长度必须在 {MIN_SCRIPT_LENGTH}-{MAX_SCRIPT_LENGTH} 个字符之间",
        )
    if not 1 <= generate_count <= MAX_GENERATE_COUNT:
        raise HTTPException(
            status_code=422,
            detail=f"generate_count 必须在 1-{MAX_GENERATE_COUNT} 之间",
        )
    if not materials or len(materials) > smart_editing.MAX_MATERIALS:
        raise HTTPException(
            status_code=422,
            detail=f"素材数量必须在 1-{smart_editing.MAX_MATERIALS} 之间",
        )

    try:
        normalized_keywords = smart_editing.normalize_keywords(
            common.parse_json_field(keywords, "keywords", list)
        )
        smart_editing.pacing_range(pacing)
        template_production.require_ffmpeg()
    except smart_editing.SmartEditingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except template_production.TemplateProductionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    manifest = _normalize_manifest(
        common.parse_json_field(material_manifest, "material_manifest", list),
        file_count=len(materials),
        keyword_count=len(normalized_keywords),
    )
    _validate_uploads(materials, manifest)
    replacements_snapshot = [
        {"source": item["source"], "replacement": item["replacement"]}
        for item in settings_store.list_subtitle_replacements(user["id"])
    ]
    material_groups = [
        {
            "keyword_index": index,
            "keyword": keyword,
            "material_count": sum(1 for item in manifest if item["keyword_index"] == index),
            "media_types": sorted(
                {item["media_type"] for item in manifest if item["keyword_index"] == index}
            ),
        }
        for index, keyword in enumerate(normalized_keywords)
    ]
    output_root = resolve_output_dir(app_config).resolve()
    bgm_source_path, bgm_name = _resolve_bgm_track(user["id"], bgm_id, output_root)

    task_id = uuid.uuid4().hex
    task_record = common.create_task(
        user=user,
        task_type=task_store.TASK_TYPE_SMART_EDITING,
        generation_type="video",
        requested_count=generate_count,
        task_id=task_id,
        output_root=output_root,
        message="任务已创建，等待处理",
        extra_info={
            "script": clean_script,
            "keywords": normalized_keywords,
            "pacing": pacing,
            "generate_count": generate_count,
            "bgm_name": bgm_name,
            "subtitle_replacements_snapshot": replacements_snapshot,
            "material_groups": material_groups,
        },
    )
    task_dir = Path(task_record["storage_path"])
    input_dir = _task_child_dir(task_dir, "input")
    output_dir = _task_child_dir(task_dir, "output")
    temp_dir = _task_child_dir(task_dir, "temp")
    manifest_by_index = {item["file_index"]: item for item in manifest}
    saved_materials: list[dict[str, Any]] = []
    bgm_path: Path | None = None
    try:
        if bgm_source_path is not None:
            bgm_path = (input_dir / f"bgm_snapshot{bgm_source_path.suffix.lower()}").resolve()
            bgm_path.relative_to(input_dir.resolve())
            shutil.copy2(bgm_source_path, bgm_path)
        for index, upload in enumerate(materials):
            item = manifest_by_index[index]
            suffix = Path(upload.filename or item["name"]).suffix.lower()
            material_id = uuid.uuid4().hex
            input_path = (input_dir / f"{material_id}{suffix}").resolve()
            input_path.relative_to(input_dir.resolve())
            await _save_upload(
                upload,
                input_path,
                media_type=item["media_type"],
                filename=upload.filename or item["name"],
            )
            saved_materials.append(
                {
                    "id": material_id,
                    "name": common.safe_filename(
                        upload.filename or item["name"],
                        f"material_{index}{suffix}",
                    ),
                    "media_type": item["media_type"],
                    "keyword_index": item["keyword_index"],
                    "file_index": index,
                    "input_path": input_path,
                }
            )
    except Exception as exc:
        common.persist_task_update(
            task_id,
            status="failed",
            progress=0,
            message="保存智能剪辑素材失败",
            error=str(exc),
            success_count=0,
            failed_count=generate_count,
            finished=True,
        )
        for item in saved_materials:
            Path(item["input_path"]).unlink(missing_ok=True)
        if bgm_path is not None:
            bgm_path.unlink(missing_ok=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=422, detail=str(exc) or "保存智能剪辑素材失败") from exc

    task_items = [
        {
            "id": uuid.uuid4().hex,
            "index": index + 1,
            "status": "pending",
            "message": "等待生成",
            "video_url": None,
            "download_url": None,
            "error": None,
        }
        for index in range(generate_count)
    ]
    _tasks[task_id] = {
        "user_id": user["id"],
        "script": clean_script,
        "keywords": normalized_keywords,
        "pacing": pacing,
        "_bgm_path": bgm_path,
        "bgm_name": bgm_name,
        "generate_count": generate_count,
        "status": "pending",
        "progress": 0,
        "message": "任务已创建，等待处理",
        "items": task_items,
        "zip_url": None,
        "error": None,
    }
    common.schedule_task(task_id, lambda: _run_task(
            task_id=task_id,
            task_dir=task_dir,
            output_dir=output_dir,
            temp_dir=temp_dir,
            script=clean_script,
            keywords=normalized_keywords,
            pacing=pacing,
            materials=saved_materials,
            subtitle_replacements=replacements_snapshot,
            bgm_path=bgm_path,
        ))
    return {"task_id": task_id}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, user: dict = Depends(require_current_user)):
    try:
        record = task_store.get_task(task_id, user["id"])
    except task_store.TaskNotFoundError:
        task = _tasks.get(task_id)
        if task is None or task.get("user_id") != user["id"]:
            raise HTTPException(status_code=404, detail="Task not found") from None
        return {key: value for key, value in task.items() if not key.startswith("_")}
    return _task_payload(record, _tasks.get(task_id))


async def _run_task(
    *,
    task_id: str,
    task_dir: Path,
    output_dir: Path,
    temp_dir: Path,
    script: str,
    keywords: list[str],
    pacing: str,
    materials: list[dict[str, Any]],
    subtitle_replacements: list[dict[str, str]],
    bgm_path: Path | None = None,
) -> None:
    task = _tasks[task_id]
    completed_outputs: list[Path] = []
    failed = 0
    audio_path = temp_dir / "narration.mp3"
    try:
        task.update(status="running", progress=5, message="正在生成配音")
        common.persist_task_update(
            task_id,
            status="running",
            progress=5,
            message="正在生成配音",
            started=True,
        )
        tts_result = await tts_service.synthesize(
            EDGE_TTS_MODEL,
            _smart_editing_tts_request(script),
            audio_path,
        )
        audio_duration = tts_result.duration or await run_blocking("media",
            template_production.probe_duration,
            audio_path,
        )

        total = len(task["items"])
        for index, item in enumerate(task["items"], start=1):
            item.update(status="running", message="正在合成视频")
            progress = 15 + round((index - 1) / total * 80)
            task.update(progress=progress, message=f"正在生成第 {index}/{total} 条视频")
            common.persist_task_update(
                task_id,
                status="running",
                progress=progress,
                message=task["message"],
            )
            output_path = output_dir / f"smart_edit_video_{index:03d}.mp4"
            try:
                await run_blocking("media",
                    smart_editing.compose_video,
                    materials,
                    len(keywords),
                    audio_path,
                    output_path,
                    script=script,
                    work_dir=temp_dir / f"video_{index:03d}",
                    seed=f"{task_id}:{index}",
                    pacing=pacing,
                    audio_duration=audio_duration,
                    timings=tts_result.timings,
                    subtitle_replacements=subtitle_replacements,
                    subtitle_style=smart_editing.DEFAULT_SUBTITLE_STYLE,
                    bgm_path=bgm_path,
                )
                completed_outputs.append(output_path)
                item.update(
                    status="completed",
                    message="生成完成",
                    video_url=common.artifact_url(task_id, item["id"]),
                    download_url=common.artifact_url(task_id, item["id"], "download"),
                    error=None,
                )
                common.persist_artifact(
                    task_id,
                    artifact_id=item["id"],
                    path=output_path,
                    name=output_path.name,
                    kind="video",
                    mime_type="video/mp4",
                    is_primary=len(completed_outputs) == 1,
                )
            except Exception as exc:
                failed += 1
                item.update(status="failed", message="生成失败", error=str(exc))
                common.persist_artifact(
                    task_id,
                    artifact_id=item["id"],
                    path=output_path,
                    name=output_path.name,
                    kind="video",
                    mime_type="video/mp4",
                    status="failed",
                )

        if completed_outputs:
            zip_path = task_dir / "smart_edit_videos.zip"
            await run_blocking("media", common.create_output_zip, zip_path, completed_outputs)
            archive_id = f"{task_id}-archive"
            task["zip_url"] = common.artifact_url(task_id, archive_id, "download")
            common.persist_artifact(
                task_id,
                artifact_id=archive_id,
                path=zip_path,
                name=zip_path.name,
                kind="archive",
                mime_type="application/zip",
                is_primary=True,
                counts_toward_result=False,
            )

        completed = len(completed_outputs)
        status = "failed" if completed == 0 else ("partial_failed" if failed else "completed")
        message = f"智能剪辑完成：成功 {completed} 条，失败 {failed} 条"
        task.update(
            status=status,
            progress=100,
            message=message,
            error=message if completed == 0 else None,
        )
        common.persist_task_update(
            task_id,
            status=status,
            progress=100,
            message=message,
            error=message if completed == 0 else None,
            success_count=completed,
            failed_count=failed,
            finished=True,
        )
    except Exception as exc:
        for item in task.get("items", []):
            if item.get("status") not in {"completed", "failed"}:
                item.update(status="failed", message="生成失败", error=str(exc))
        failed_count = max(failed, len(task.get("items", [])) - len(completed_outputs))
        task.update(status="failed", progress=0, message="智能剪辑任务失败", error=str(exc))
        common.persist_task_update(
            task_id,
            status="failed",
            progress=0,
            message="智能剪辑任务失败",
            error=str(exc),
            success_count=len(completed_outputs),
            failed_count=failed_count,
            finished=True,
        )
    finally:
        audio_path.unlink(missing_ok=True)
        shutil.rmtree(temp_dir, ignore_errors=True)


def _smart_editing_tts_request(text: str) -> TTSRequest:
    return TTSRequest(
        text=text,
        voice_id=SMART_EDITING_TTS_VOICE_ID,
        speed=SMART_EDITING_TTS_SPEED,
        volume=SMART_EDITING_TTS_VOLUME,
    )
