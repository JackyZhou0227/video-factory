from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api import common
from app.api.auth import require_current_user
from app.core import uploads
from app.core.config import app_config, resolve_output_dir
from app.schemas.template_definition import (
    MAX_TOTAL_MATERIAL_COUNT,
    TemplateDefinition,
    TemplateRuntimeValidationError,
    validate_material_manifest,
)
from app.services import settings_store, task_store, template_production, template_registry
from app.services.llm import LLMConfig, LLMMessage, LLMServiceError, llm_service
from app.services.tts import EDGE_TTS_MODEL, TTSRequest, tts_service

router = APIRouter(prefix="/template-production", tags=["template-production"])

MAX_GENERATE_COUNT = 50
MAX_MATERIAL_COUNT = MAX_TOTAL_MATERIAL_COUNT
MAX_SUBTITLE_REPLACEMENTS = 30
MAX_SUBTITLE_TERM_LENGTH = 80
TEMPLATE_TTS_VOICE_ID = "zh-CN-YunjianNeural"
TEMPLATE_TTS_SPEED = 1.0
TEMPLATE_TTS_VOLUME = 100
VIDEO_EXTENSIONS = template_production.VIDEO_EXTENSIONS
IMAGE_EXTENSIONS = template_production.IMAGE_EXTENSIONS
BGM_EXTENSIONS = {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"}
MAX_BGM_FILE_SIZE = 20 * 1024 * 1024
MAX_TEMPLATE_FILE_SIZE = uploads.MAX_JSON_FILE_SIZE
PIPELINE_CAPABILITIES = {
    "generic_concat_v1": {},
    "zhongyi_visit_v1": {},
}

_tasks: dict[str, dict[str, Any]] = {}


class ScriptGenerateRequest(BaseModel):
    template_id: str
    variables: dict[str, str]
    count: int | None = Field(default=None, ge=1, le=10)
    material_context: dict[str, int] = Field(default_factory=dict)


class ScriptRewriteRequest(BaseModel):
    template_id: str
    variables: dict[str, str]
    original_script: str = Field(..., min_length=10, max_length=5000)
    material_context: dict[str, int] = Field(default_factory=dict)


class SubtitleReplacementRequest(BaseModel):
    source: str
    replacement: str


# ============================================================================
# Helper Functions - Templates
# ============================================================================

def _runtime_capabilities(template: TemplateDefinition) -> dict[str, Any]:
    pipeline = PIPELINE_CAPABILITIES[template.production.pipeline_id]
    return {
        **pipeline,
        "subtitle_replacements": True,
        "script_rewrite": template.script_generation.rewrite_prompt_template is not None,
    }


def _template_payload(template: TemplateDefinition, *, is_builtin: bool) -> dict[str, Any]:
    return {
        **template.model_dump(mode="json", exclude_none=True),
        "is_builtin": is_builtin,
        "runtime_capabilities": _runtime_capabilities(template),
    }


def _get_template(user_id: str, template_id: str, *, not_found_status: int = 422) -> TemplateDefinition:
    try:
        return template_registry.get_template(user_id, template_id)
    except template_registry.TemplateNotFoundError as exc:
        raise HTTPException(status_code=not_found_status, detail=str(exc)) from None
    except template_registry.TemplateRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ============================================================================
# Routes - Templates CRUD
# ============================================================================

@router.get("/templates")
def list_templates(user: dict = Depends(require_current_user)):
    try:
        entries = template_registry.template_registry.list_entries(user["id"])
    except template_registry.TemplateRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "templates": [
            _template_payload(entry.definition, is_builtin=entry.is_builtin)
            for entry in entries
        ]
    }


@router.get("/templates/{template_id}")
def get_template(template_id: str, user: dict = Depends(require_current_user)):
    try:
        entry = template_registry.template_registry.get_entry(user["id"], template_id)
    except template_registry.TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except template_registry.TemplateRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"template": _template_payload(entry.definition, is_builtin=entry.is_builtin)}


@router.post("/templates/import", status_code=201)
async def import_template(file: UploadFile = File(...), user: dict = Depends(require_current_user)):
    import tempfile

    with tempfile.TemporaryDirectory(prefix="video-factory-template-") as temp_dir:
        temp_path = Path(temp_dir) / "template.json"
        await uploads.save_upload(
            file,
            temp_path,
            allowed_extensions={".json"},
            allowed_mime_types=uploads.JSON_MIME_TYPES,
            max_size=min(template_registry.MAX_TEMPLATE_JSON_BYTES, MAX_TEMPLATE_FILE_SIZE),
            default_suffix=".json",
            label="模板 JSON",
        )
        payload = temp_path.read_bytes()
    try:
        definition = template_registry.import_template_json(user["id"], payload)
    except template_registry.TemplateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except template_registry.TemplateImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except template_registry.TemplateRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"template": _template_payload(definition, is_builtin=False)}


@router.get("/templates/{template_id}/export")
def export_template(template_id: str, user: dict = Depends(require_current_user)):
    try:
        content = template_registry.export_registered_template_json(user["id"], template_id)
    except template_registry.TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except template_registry.TemplateRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(
        content=f"{content}\n",
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{template_id}.json"'},
    )


# ============================================================================
# Routes - Subtitle Replacements CRUD
# ============================================================================

@router.get("/subtitle-replacements")
def list_subtitle_replacements(user: dict = Depends(require_current_user)):
    """List the shared subtitle replacement rules available to every user."""
    return {"replacements": settings_store.list_subtitle_replacements()}


@router.post("/subtitle-replacements", status_code=201)
def create_subtitle_replacement(
    payload: SubtitleReplacementRequest,
    user: dict = Depends(require_current_user),
):
    try:
        replacement = settings_store.create_subtitle_replacement(
            source=payload.source,
            replacement=payload.replacement,
        )
    except settings_store.SubtitleReplacementConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"replacement": replacement}


@router.put("/subtitle-replacements/{replacement_id}")
def update_subtitle_replacement(
    replacement_id: int,
    payload: SubtitleReplacementRequest,
    user: dict = Depends(require_current_user),
):
    try:
        replacement = settings_store.update_subtitle_replacement(
            replacement_id,
            source=payload.source,
            replacement=payload.replacement,
        )
    except settings_store.SubtitleReplacementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except settings_store.SubtitleReplacementConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"replacement": replacement}


@router.delete("/subtitle-replacements/{replacement_id}", status_code=204)
def delete_subtitle_replacement(
    replacement_id: int,
    user: dict = Depends(require_current_user),
):
    try:
        settings_store.delete_subtitle_replacement(replacement_id)
    except settings_store.SubtitleReplacementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return Response(status_code=204)


# ============================================================================
# Helper Functions - BGM
# ============================================================================

def _bgm_track_payload(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": track["id"],
        "name": track["name"],
        "duration": track["duration"],
        "file_size": track["file_size"],
        "preview_url": f"/api/template-production/bgm/{track['id']}/audio",
        "created_at": track["created_at"],
    }


# ============================================================================
# Routes - BGM CRUD
# ============================================================================

@router.get("/bgm")
def list_bgm_tracks(user: dict = Depends(require_current_user)):
    tracks = settings_store.list_bgm_tracks(user["id"])
    return {"bgm_tracks": [_bgm_track_payload(track) for track in tracks]}


@router.get("/bgm/{bgm_id}/audio")
def get_bgm_audio(bgm_id: str, user: dict = Depends(require_current_user)):
    try:
        track = settings_store.get_bgm_track(user["id"], bgm_id)
    except settings_store.BgmTrackNotFoundError:
        raise HTTPException(status_code=404, detail="背景音乐不存在") from None
    output_root = resolve_output_dir(app_config).resolve()
    file_path = (output_root / track["relative_path"]).resolve()
    try:
        file_path.relative_to(output_root / "bgm" / user["id"])
    except ValueError:
        raise HTTPException(status_code=404, detail="背景音乐不存在") from None
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="背景音乐文件不存在")
    return FileResponse(file_path, media_type="audio/mpeg", content_disposition_type="inline")


@router.post("/bgm", status_code=201)
async def upload_bgm_track(
    file: UploadFile = File(...),
    user: dict = Depends(require_current_user),
):
    suffix = uploads.validate_upload(
        file,
        allowed_extensions=BGM_EXTENSIONS,
        allowed_mime_types=uploads.AUDIO_MIME_TYPES,
        max_size=MAX_BGM_FILE_SIZE,
        default_suffix=".mp3",
        label="背景音乐",
    )

    bgm_id = uuid.uuid4().hex
    output_root = resolve_output_dir(app_config)
    bgm_dir = output_root / "bgm" / user["id"]
    bgm_dir.mkdir(parents=True, exist_ok=True)
    file_path = bgm_dir / f"{bgm_id}{suffix}"
    try:
        file_size = await uploads.save_upload(
            file,
            file_path,
            allowed_extensions=BGM_EXTENSIONS,
            allowed_mime_types=uploads.AUDIO_MIME_TYPES,
            max_size=MAX_BGM_FILE_SIZE,
            default_suffix=".mp3",
            label="背景音乐",
        )
        duration = await asyncio.to_thread(template_production.probe_duration, file_path)
    except template_production.TemplateProductionError:
        duration = 0.0
    except HTTPException:
        file_path.unlink(missing_ok=True)
        raise
    except Exception:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="保存背景音乐失败") from None

    relative_path = f"bgm/{user['id']}/{bgm_id}{suffix}"
    safe_name = common.safe_filename(file.filename or f"bgm{suffix}", f"bgm{suffix}")
    try:
        track = settings_store.create_bgm_track(
            user_id=user["id"],
            bgm_id=bgm_id,
            name=safe_name,
            relative_path=relative_path,
            duration=duration,
            file_size=file_size,
        )
    except ValueError as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception:
        file_path.unlink(missing_ok=True)
        raise
    return {"bgm_track": _bgm_track_payload(track)}


@router.delete("/bgm/{bgm_id}", status_code=204)
def delete_bgm_track(
    bgm_id: str,
    user: dict = Depends(require_current_user),
):
    try:
        track = settings_store.get_bgm_track(user["id"], bgm_id)
    except settings_store.BgmTrackNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    output_root = resolve_output_dir(app_config).resolve()
    file_path = (output_root / track["relative_path"]).resolve()
    try:
        file_path.relative_to(output_root / "bgm" / user["id"])
    except ValueError:
        raise HTTPException(status_code=404, detail="背景音乐不存在") from None
    file_path.unlink(missing_ok=True)

    try:
        settings_store.delete_bgm_track(user["id"], bgm_id)
    except settings_store.BgmTrackNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return Response(status_code=204)


# ============================================================================
# Helper Functions - Tasks
# ============================================================================

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
    items = [
        {
            "id": artifact["id"],
            "index": index,
            "script": "",
            "status": artifact.get("status", "pending"),
            "message": "生成完成" if artifact.get("status") == "completed" else "生成失败",
            "video_url": common.artifact_url(record["id"], artifact["id"])
            if artifact.get("kind") == "video" and artifact.get("status") == "completed"
            else None,
            "error": artifact.get("error"),
        }
        for index, artifact in enumerate(
            (item for item in record.get("artifacts", []) if item.get("kind") == "video"),
            start=1,
        )
    ]
    archive = next(
        (artifact for artifact in record.get("artifacts", []) if artifact.get("kind") == "archive"),
        None,
    )
    return {
        "user_id": record["user_id"],
        "template_id": extra.get("template_id"),
        "template_version": extra.get("template_version"),
        "pipeline_id": extra.get("pipeline_id"),
        "bgm_name": extra.get("bgm_name"),
        "status": record["status"],
        "progress": record["progress"],
        "message": record["message"],
        "items": items,
        "zip_url": common.artifact_url(record["id"], archive["id"], "download") if archive else None,
        "error": record.get("error"),
    }


def _parse_subtitle_replacements(value: str) -> list[dict[str, str]]:
    parsed = common.parse_json_field(value or "[]", "subtitle_replacements", list)
    if len(parsed) > MAX_SUBTITLE_REPLACEMENTS:
        raise HTTPException(status_code=422, detail=f"字幕替换规则最多添加 {MAX_SUBTITLE_REPLACEMENTS} 条")

    replacements: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail=f"第 {index} 条字幕替换规则格式不正确")
        source = str(item.get("source") or "").strip()
        replacement = str(item.get("replacement") or "").strip()
        if not source or not replacement:
            raise HTTPException(status_code=422, detail=f"第 {index} 条字幕替换规则需要填写原词和替换词")
        if "\n" in source or "\r" in source or "\n" in replacement or "\r" in replacement:
            raise HTTPException(status_code=422, detail=f"第 {index} 条字幕替换规则不能包含换行")
        if len(source) > MAX_SUBTITLE_TERM_LENGTH or len(replacement) > MAX_SUBTITLE_TERM_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"第 {index} 条字幕替换规则的词语长度不能超过 {MAX_SUBTITLE_TERM_LENGTH} 个字符",
            )
        if source == replacement:
            raise HTTPException(status_code=422, detail=f"第 {index} 条字幕替换规则的原词和替换词不能相同")
        if source in seen_sources:
            raise HTTPException(status_code=422, detail=f"字幕原词“{source}”重复添加")
        seen_sources.add(source)
        replacements.append({"source": source, "replacement": replacement})
    return replacements


def _validate_material_manifest(
    template: TemplateDefinition,
    manifest: list[dict],
    file_count: int,
) -> list[dict[str, Any]]:
    try:
        parsed = validate_material_manifest(template, manifest, file_count)
    except TemplateRuntimeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return [item.model_dump(mode="json", exclude_none=True) for item in parsed]


# ============================================================================
# Routes - Script Generation & Rewrite
# ============================================================================

@router.post("/scripts/generate")
async def generate_scripts(payload: ScriptGenerateRequest, user: dict = Depends(require_current_user)):
    template = _get_template(user["id"], payload.template_id)
    count = payload.count or template.script_generation.default_candidate_count
    try:
        prompt = template_production.build_script_prompt(
            template,
            payload.variables,
            count,
            payload.material_context,
        )
    except template_production.TemplateProductionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    stored = settings_store.get_llm_settings(user["id"])
    config = LLMConfig(**stored)
    messages = [
        LLMMessage(role="system", content=template.script_generation.system_prompt),
        LLMMessage(role="user", content=prompt),
    ]
    try:
        content = await llm_service.generate(
            config,
            messages,
            temperature=template.script_generation.temperature,
            max_tokens=template.script_generation.max_tokens,
        )
    except LLMServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    scripts = template_production.parse_generated_scripts(content, count)
    if not scripts:
        raise HTTPException(status_code=502, detail="LLM 没有返回可用文案，请重试或手工添加")
    return {"scripts": scripts}


@router.post("/scripts/rewrite")
async def rewrite_script(payload: ScriptRewriteRequest, user: dict = Depends(require_current_user)):
    template = _get_template(user["id"], payload.template_id)
    try:
        rewrite_prompt = template_production.build_rewrite_prompt(
            template,
            payload.variables,
            payload.original_script,
            payload.material_context,
        )
    except template_production.TemplateProductionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    config = LLMConfig(**settings_store.get_llm_settings(user["id"]))
    try:
        content = await llm_service.generate(
            config,
            [
                LLMMessage(role="system", content=template.script_generation.system_prompt),
                LLMMessage(role="user", content=rewrite_prompt),
            ],
            temperature=template.script_generation.temperature,
            max_tokens=template.script_generation.max_tokens,
        )
    except LLMServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    scripts = template_production.parse_generated_scripts(content, 1)
    if not scripts:
        raise HTTPException(status_code=502, detail="LLM 没有返回可用文案，请重试")
    return {"script": scripts[0]}


# ============================================================================
# Routes - Task Creation & Execution
# ============================================================================

@router.post("/tasks")
async def create_task(
    template_id: str = Form(...),
    scripts: str = Form(...),
    generate_count: int = Form(...),
    video_config: str = Form(...),
    subtitle_replacements: str = Form("[]"),
    material_manifest: str = Form(...),
    materials: list[UploadFile] = File(...),
    bgm_id: str = Form(""),
    user: dict = Depends(require_current_user),
):
    try:
        template = _get_template(user["id"], template_id)
        template_id = template.id
        template_production.require_ffmpeg()
    except template_production.TemplateProductionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    maximum_batch_size = min(MAX_GENERATE_COUNT, template.production.max_batch_size)
    if generate_count < 1 or generate_count > maximum_batch_size:
        raise HTTPException(status_code=422, detail=f"generate_count 必须在 1-{maximum_batch_size} 之间")
    if not materials or len(materials) > MAX_MATERIAL_COUNT:
        raise HTTPException(status_code=422, detail=f"素材数量必须在 1-{MAX_MATERIAL_COUNT} 之间")

    script_values = [str(item).strip() for item in common.parse_json_field(scripts, "scripts", list) if str(item).strip()]
    if not script_values or len(script_values) > MAX_GENERATE_COUNT:
        raise HTTPException(status_code=422, detail="文案数量必须在 1-50 之间")
    video = common.parse_json_field(video_config, "video_config", dict)
    subtitle_style_value = video.get("subtitle_style")
    if subtitle_style_value is not None and not isinstance(subtitle_style_value, dict):
        raise HTTPException(status_code=422, detail="subtitle_style 格式不正确")
    subtitle_style = template_production.normalize_subtitle_style(subtitle_style_value)
    # The form field remains accepted for older clients, but production always
    # uses the shared database rules captured when this task is created.
    stored_replacements = settings_store.list_subtitle_replacements()
    parsed_replacements = [
        {"source": item["source"], "replacement": item["replacement"]}
        for item in stored_replacements
    ]
    manifest = common.parse_json_field(material_manifest, "material_manifest", list)
    manifest = _validate_material_manifest(template, manifest, len(materials))
    manifest_by_index = {int(item["file_index"]): item for item in manifest}
    for index, upload in enumerate(materials):
        item = manifest_by_index[index]
        media_type = item["media_type"]
        allowed = IMAGE_EXTENSIONS if media_type == "image" else VIDEO_EXTENSIONS
        allowed_mime_types = uploads.IMAGE_MIME_TYPES if media_type == "image" else uploads.VIDEO_MIME_TYPES
        max_size = uploads.MAX_IMAGE_FILE_SIZE if media_type == "image" else uploads.MAX_VIDEO_FILE_SIZE
        suffix = uploads.validate_upload(
            upload,
            allowed_extensions=allowed,
            allowed_mime_types=allowed_mime_types,
            max_size=max_size,
            filename=upload.filename or item.get("name"),
            label=media_type,
        )

    # Template production is intentionally portrait-only. Accepting the legacy
    # video_config.ratio field keeps older clients compatible without allowing
    # it to alter the rendered output.
    ratio = template_production.DEFAULT_VIDEO_RATIO

    bgm_path: Path | None = None
    bgm_name: str | None = None
    if bgm_id:
        try:
            bgm_track = settings_store.get_bgm_track(user["id"], bgm_id)
        except settings_store.BgmTrackNotFoundError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        bgm_path = resolve_output_dir(app_config) / bgm_track["relative_path"]
        if not bgm_path.exists():
            raise HTTPException(status_code=422, detail="背景音乐文件不存在，请重新上传")
        bgm_name = bgm_track["name"]

    task_id = uuid.uuid4().hex
    task_record = task_store.create_task(
        user=user,
        task_type=task_store.TASK_TYPE_TEMPLATE,
        generation_type="video",
        requested_count=generate_count,
        task_id=task_id,
        output_root=resolve_output_dir(app_config),
        message="任务已创建，等待处理",
        extra_info={
            "template_id": template_id,
            "template_version": template.template_version,
            "pipeline_id": template.production.pipeline_id,
            "bgm_name": bgm_name,
        },
    )
    task_dir = Path(task_record["storage_path"])
    input_dir = task_dir / "input"
    output_dir = task_dir / "output"
    temp_dir = task_dir / "temp"
    saved_materials: list[dict[str, Any]] = []
    try:
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        for index, upload in enumerate(materials):
            item = manifest_by_index[index]
            media_type = item["media_type"]
            allowed = IMAGE_EXTENSIONS if media_type == "image" else VIDEO_EXTENSIONS
            allowed_mime_types = uploads.IMAGE_MIME_TYPES if media_type == "image" else uploads.VIDEO_MIME_TYPES
            max_size = uploads.MAX_IMAGE_FILE_SIZE if media_type == "image" else uploads.MAX_VIDEO_FILE_SIZE
            suffix = uploads.validate_upload(
                upload,
                allowed_extensions=allowed,
                allowed_mime_types=allowed_mime_types,
                max_size=max_size,
                filename=upload.filename or item.get("name"),
                label=media_type,
            )
            material_id = uuid.uuid4().hex
            safe_name = common.safe_filename(upload.filename or f"material_{index}{suffix}", f"material_{index}{suffix}")
            input_path = input_dir / f"{material_id}{suffix}"
            await uploads.save_upload(
                upload,
                input_path,
                allowed_extensions=allowed,
                allowed_mime_types=allowed_mime_types,
                max_size=max_size,
                filename=upload.filename or item.get("name"),
                label=media_type,
            )
            saved_materials.append(
                {
                    "id": material_id,
                    "name": safe_name,
                    "media_type": media_type,
                    "requirement_id": item["requirement_id"],
                    "input_path": input_path,
                }
            )
    except HTTPException as exc:
        task_store.update_task(
            task_id,
            status="failed",
            progress=0,
            message="保存模板量产素材失败",
            error=str(exc.detail),
            success_count=0,
            failed_count=generate_count,
            finished=True,
        )
        for item in saved_materials:
            Path(item["input_path"]).unlink(missing_ok=True)
        raise
    except Exception as exc:
        task_store.update_task(
            task_id,
            status="failed",
            progress=0,
            message="保存模板量产素材失败",
            error=str(exc),
            success_count=0,
            failed_count=generate_count,
            finished=True,
        )
        for item in saved_materials:
            Path(item["input_path"]).unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="保存模板素材失败") from exc

    task_items = [
        {
            "id": uuid.uuid4().hex,
            "index": index + 1,
            "script": script_values[index % len(script_values)],
            "status": "pending",
            "message": "等待生成",
            "video_url": None,
            "error": None,
        }
        for index in range(generate_count)
    ]
    _tasks[task_id] = {
        "user_id": user["id"],
        "template_id": template_id,
        "template_version": template.template_version,
        "pipeline_id": template.production.pipeline_id,
        "_template_snapshot": template.model_dump(mode="json", exclude_none=True),
        "_subtitle_replacements": parsed_replacements,
        "_subtitle_style": subtitle_style,
        "_bgm_path": bgm_path,
        "bgm_name": bgm_name,
        "status": "pending",
        "progress": 0,
        "message": "任务已创建，等待处理",
        "items": task_items,
        "zip_url": None,
        "error": None,
    }
    asyncio.create_task(
        _run_task(
            task_id=task_id,
            task_dir=task_dir,
            output_dir=output_dir,
            temp_dir=temp_dir,
            materials=saved_materials,
            ratio=ratio,
            subtitle_replacements=parsed_replacements,
            subtitle_style=subtitle_style,
            bgm_path=bgm_path,
        )
    )
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


# ============================================================================
# Task Execution - Background Runner
# ============================================================================

async def _run_task(
    *,
    task_id: str,
    task_dir: Path,
    output_dir: Path,
    temp_dir: Path,
    materials: list[dict[str, Any]],
    ratio: str,
    subtitle_replacements: list[dict[str, str]],
    subtitle_style: dict[str, Any] | None = None,
    bgm_path: Path | None = None,
) -> None:
    task = _tasks[task_id]
    completed_outputs: list[Path] = []
    failed = 0
    try:
        pipeline_id = task.get("pipeline_id")
        if pipeline_id is None:
            pipeline_id = (
                "zhongyi_visit_v1"
                if task["template_id"] == template_production.ZHONGYI_TEMPLATE_ID
                else "generic_concat_v1"
            )
        is_zhongyi = pipeline_id == "zhongyi_visit_v1"
        prepared_segments: list[Path] = []
        if is_zhongyi:
            task.update(status="running", progress=10, message="素材已就绪，正在生成视频")
        else:
            task.update(status="running", progress=1, message="正在标准化素材")
            for index, material in enumerate(materials, start=1):
                segment_path = temp_dir / f"segment_{index:02d}.mp4"
                await asyncio.to_thread(
                    template_production.prepare_material_segment,
                    material["input_path"],
                    segment_path,
                    media_type=material["media_type"],
                    ratio=ratio,
                )
                prepared_segments.append(segment_path)
                task.update(
                    progress=max(2, round(index / len(materials) * 10)),
                    message=f"正在处理素材 {index}/{len(materials)}",
                )
        common.persist_task_update(
            task_id,
            status="running",
            progress=task["progress"],
            message=task["message"],
            started=True,
        )

        total = len(task["items"])
        for index, item in enumerate(task["items"], start=1):
            item.update(status="running", message="正在生成配音")
            task.update(
                progress=10 + round((index - 1) / total * 85),
                message=f"正在生成第 {index}/{total} 条视频",
            )
            common.persist_task_update(
                task_id,
                status="running",
                progress=task["progress"],
                message=task["message"],
            )
            audio_path = temp_dir / f"audio_{index:03d}.mp3"
            output_path = output_dir / f"template_video_{index:03d}.mp4"
            try:
                tts_text = template_production.script_text_for_tts(item["script"]) if is_zhongyi else item["script"]
                tts_result = await tts_service.synthesize(
                    EDGE_TTS_MODEL,
                    _template_tts_request(tts_text),
                    audio_path,
                )
                audio_duration = tts_result.duration or await asyncio.to_thread(template_production.probe_duration, audio_path)
                item["message"] = "正在合成视频"
                if is_zhongyi:
                    await asyncio.to_thread(
                        template_production.compose_zhongyi_video,
                        materials,
                        audio_path,
                        output_path,
                        script=item["script"],
                        work_dir=temp_dir / f"video_{index:03d}",
                        seed=f"{task_id}:{index}",
                        ratio=ratio,
                        audio_duration=audio_duration,
                        timings=tts_result.timings,
                        subtitle_replacements=subtitle_replacements,
                        subtitle_style=subtitle_style,
                        bgm_path=bgm_path,
                    )
                else:
                    await asyncio.to_thread(
                        template_production.compose_video,
                        prepared_segments,
                        audio_path,
                        output_path,
                        seed=f"{task_id}:{index}",
                        audio_duration=audio_duration,
                        script=item["script"],
                        work_dir=temp_dir / f"video_{index:03d}",
                        ratio=ratio,
                        timings=tts_result.timings,
                        subtitle_replacements=subtitle_replacements,
                        subtitle_style=subtitle_style,
                        bgm_path=bgm_path,
                    )
                completed_outputs.append(output_path)
                item.update(
                    status="completed",
                    message="生成完成",
                    video_url=_artifact_url(task_id, item["id"]),
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
            finally:
                audio_path.unlink(missing_ok=True)

        if completed_outputs:
            zip_path = task_dir / "template_videos.zip"
            await asyncio.to_thread(common.create_output_zip, zip_path, completed_outputs)
            archive_id = f"{task_id}-archive"
            task["zip_url"] = _artifact_url(task_id, archive_id, "download")
            common.persist_artifact(
                task_id,
                artifact_id=archive_id,
                path=zip_path,
                name=zip_path.name,
                kind="archive",
                mime_type="application/zip",
                is_primary=True,
            )

        completed = len(completed_outputs)
        status = "failed" if completed == 0 else ("partial_failed" if failed else "completed")
        message = f"批量生成完成：成功 {completed} 条，失败 {failed} 条"
        task.update(status=status, progress=100, message=message, error=message if completed == 0 else None)
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
        task.update(status="failed", progress=0, message="模板量产任务失败", error=str(exc))
        common.persist_task_update(
            task_id,
            status="failed",
            progress=0,
            message="模板量产任务失败",
            error=str(exc),
            success_count=len(completed_outputs),
            failed_count=max(failed, len(task.get("items", [])) - len(completed_outputs)),
            finished=True,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _template_tts_request(text: str) -> TTSRequest:
    return TTSRequest(
        text=text,
        voice_id=TEMPLATE_TTS_VOICE_ID,
        speed=TEMPLATE_TTS_SPEED,
        volume=TEMPLATE_TTS_VOLUME,
    )
