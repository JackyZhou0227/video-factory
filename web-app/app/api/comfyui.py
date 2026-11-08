from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api import common
from app.api.auth import require_current_user
from app.core.config import ROOT, app_config
from app.core import uploads
from app.services import runninghub, settings_store, task_store
from app.services import workflow_catalog
from app.services.llm import LLMConfig, LLMServiceError, llm_service

router = APIRouter(dependencies=[Depends(require_current_user)])

RUNNINGHUB_TASKS_URL = "https://www.runninghub.cn/bill-task"
RUNNINGHUB_WORKS_URL = "https://www.runninghub.cn/user-center"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"}

# In-memory task store: task_id -> task state dict
_tasks: dict[str, dict] = {}


class RunningHubSettingsUpdate(BaseModel):
    api_key: Optional[str] = Field(default=None)
    concurrent_limit: Optional[int] = Field(default=None, ge=1, le=10)
    instance_type: Optional[str] = Field(default=None)


class LLMSettingsUpdate(BaseModel):
    base_url: Optional[str] = Field(default=None, max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=1000)
    model: Optional[str] = Field(default=None, max_length=200)
    clear_api_key: bool = False


class LLMSettingsTest(BaseModel):
    base_url: Optional[str] = Field(default=None, max_length=500)
    api_key: Optional[str] = Field(default=None, max_length=1000)
    model: Optional[str] = Field(default=None, max_length=200)


def _get_config():
    return app_config


def _output_root(cfg: dict) -> Path:
    output_root = Path(cfg["server"]["output_dir"])
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root


def _task_payload(task: dict) -> dict:
    extra = task.get("extra_info") or {}
    video_artifact = next(
        (
            artifact
            for artifact in task.get("artifacts", [])
            if artifact.get("kind") == "video" and artifact.get("status") == "completed"
        ),
        None,
    )
    video_url = common.artifact_url(task["id"], video_artifact["id"]) if video_artifact else None
    return {
        "user_id": task["user_id"],
        "status": task["status"],
        "progress": task["progress"],
        "message": task["message"],
        "video_url": video_url,
        "provider_task_id": extra.get("provider_task_id") or extra.get("runninghub_task_id"),
        "provider_task_url": extra.get("provider_task_url") or extra.get("runninghub_task_url", RUNNINGHUB_TASKS_URL),
        "provider_dashboard_url": extra.get("provider_dashboard_url") or extra.get("runninghub_works_url", RUNNINGHUB_WORKS_URL),
        "runninghub_task_id": extra.get("runninghub_task_id") or extra.get("provider_task_id"),
        "runninghub_task_url": extra.get("runninghub_task_url") or extra.get("provider_task_url", RUNNINGHUB_TASKS_URL),
        "runninghub_works_url": extra.get("runninghub_works_url") or extra.get("provider_dashboard_url", RUNNINGHUB_WORKS_URL),
        "error": task.get("error"),
    }


def _resolve_runninghub_inputs(
    user_id: str,
    api_key: Optional[str],
    instance_type: Optional[str],
    workflow_id: Optional[str] = None,
) -> tuple[str, str, Optional[str]]:
    stored = settings_store.get_runninghub_settings(user_id)

    resolved_api_key = (api_key or stored["api_key"]).strip()
    resolved_workflow_id = workflow_id or settings_store.FIXED_DIGITAL_HUMAN_WORKFLOW_ID
    resolved_instance_type = instance_type
    if isinstance(resolved_instance_type, str):
        resolved_instance_type = resolved_instance_type.strip() or None
    if resolved_instance_type is None:
        resolved_instance_type = stored["instance_type"] or None

    if not resolved_api_key:
        raise HTTPException(status_code=422, detail="请先在设置页配置 RunningHub API Key")

    return resolved_api_key, resolved_workflow_id, resolved_instance_type


def _workflow_form_values(workflow: dict, form) -> dict:
    declarations = {field["key"]: field for field in workflow["inputs"]}
    unknown = set(form.keys()) - declarations.keys()
    if unknown:
        raise HTTPException(status_code=422, detail=f"未知工作流参数：{', '.join(sorted(unknown))}")

    values = {}
    for key in declarations:
        items = form.getlist(key)
        if len(items) > 1:
            raise HTTPException(status_code=422, detail=f"{key}只能提供一个值")
        if items:
            values[key] = items[0]
    return values


def _validate_workflow_inputs(workflow: dict, values: dict) -> tuple[dict, dict]:
    file_fields = {
        field["key"]: field
        for field in workflow["inputs"]
        if field["type"] in {"image", "audio"}
    }
    scalar_values = {key: value for key, value in values.items() if key not in file_fields}
    scalar_values = workflow_catalog.validate_scalar_inputs(workflow, scalar_values)
    files = {}
    for key, field in file_fields.items():
        upload = values.get(key)
        if upload is None:
            if field.get("required"):
                raise HTTPException(status_code=422, detail=f"请上传{field['label']}")
            continue
        if not isinstance(upload, StarletteUploadFile):
            raise HTTPException(status_code=422, detail=f"{field['label']}必须是文件")
        is_image = field["type"] == "image"
        allowed_mime_types = uploads.IMAGE_MIME_TYPES if is_image else uploads.AUDIO_MIME_TYPES
        max_size = uploads.MAX_IMAGE_FILE_SIZE if is_image else uploads.MAX_AUDIO_FILE_SIZE
        files[key] = {
            "upload": upload,
            "suffix": uploads.validate_upload(
                upload,
                allowed_extensions=field["extensions"],
                allowed_mime_types=allowed_mime_types,
                max_size=max_size,
                label=field["label"],
            ),
            "field": field,
            "max_size": max_size,
            "allowed_mime_types": allowed_mime_types,
        }
    return scalar_values, files


async def _create_workflow_task(
    *,
    user: dict,
    workflow: dict,
    values: dict,
    api_key: Optional[str] = None,
    instance_type: Optional[str] = None,
    output_root: Optional[Path] = None,
) -> dict:
    if workflow["provider"] != "runninghub":
        raise HTTPException(status_code=422, detail="暂不支持此工作流服务来源")

    scalar_values, files = _validate_workflow_inputs(workflow, values)
    resolved_api_key, resolved_workflow_id, resolved_instance_type = _resolve_runninghub_inputs(
        user_id=user["id"],
        api_key=api_key,
        instance_type=instance_type,
        workflow_id=workflow["workflow_id"],
    )
    cfg = _get_config()
    output_root = output_root or _output_root(cfg)
    task_id = uuid.uuid4().hex
    task_record = common.create_task(
        user=user,
        task_type=task_store.TASK_TYPE_COMFYUI_WORKFLOW,
        generation_type="video",
        requested_count=1,
        task_id=task_id,
        output_root=output_root,
        extra_info={
            "provider": workflow["provider"],
            "workflow_key": workflow["key"],
        },
        message="任务已创建，等待提交 ComfyUI 工作流...",
    )
    task_dir = Path(task_record["storage_path"])
    provider_inputs = {
        field["runninghub_parameter"]: value
        for field in workflow["inputs"]
        if field["type"] in {"text", "number", "select"} and (value := scalar_values.get(field["key"])) is not None
    }
    saved_paths: list[Path] = []
    try:
        for key, item in files.items():
            file_path = task_dir / f"input_{key}{item['suffix']}"
            await uploads.save_upload(
                item["upload"],
                file_path,
                allowed_extensions=item["field"]["extensions"],
                allowed_mime_types=item["allowed_mime_types"],
                max_size=item["max_size"],
                label=item["field"]["label"],
            )
            saved_paths.append(file_path)
            provider_inputs[item["field"]["runninghub_parameter"]] = str(file_path)
    except HTTPException as exc:
        task_store.update_task(
            task_id,
            status="failed",
            progress=0,
            message="保存工作流输入素材失败",
            error=str(exc.detail),
            success_count=0,
            failed_count=1,
            finished=True,
        )
        for path in saved_paths:
            path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        task_store.update_task(
            task_id,
            status="failed",
            progress=0,
            message="保存工作流输入素材失败",
            error=str(exc),
            success_count=0,
            failed_count=1,
            finished=True,
        )
        for path in saved_paths:
            path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="保存工作流输入素材失败") from exc

    _tasks[task_id] = {
        "user_id": user["id"],
        "status": "pending",
        "progress": 0,
        "message": "任务已创建，等待提交 ComfyUI 工作流...",
        "video_url": None,
        "provider_task_id": None,
        "provider_task_url": RUNNINGHUB_TASKS_URL,
        "provider_dashboard_url": RUNNINGHUB_WORKS_URL,
        "error": None,
    }
    common.schedule_task(
        task_id,
        lambda: _run_workflow_generation(
            task_id=task_id,
            workflow={**workflow, "workflow_id": resolved_workflow_id},
            inputs=provider_inputs,
            api_key=resolved_api_key,
            instance_type=resolved_instance_type,
        ),
    )
    return {"task_id": task_id}


@router.get("/workflows")
def list_workflows(user: dict = Depends(require_current_user)):
    del user
    return workflow_catalog.list_public_workflows()


@router.post("/workflows/{workflow_key}/generate")
async def generate_workflow(
    workflow_key: str,
    request: Request,
    user: dict = Depends(require_current_user),
):
    workflow = workflow_catalog.get_workflow(workflow_key)
    form = await request.form()
    values = _workflow_form_values(workflow, form)
    return await _create_workflow_task(user=user, workflow=workflow, values=values)


@router.get("/settings")
def get_settings(user: dict = Depends(require_current_user)):
    return {
        "runninghub": settings_store.public_runninghub_settings(user=user, user_id=user["id"]),
        "llm": settings_store.public_llm_settings(user_id=user["id"]),
    }


@router.put("/settings/runninghub")
def update_runninghub_settings(payload: RunningHubSettingsUpdate, user: dict = Depends(require_current_user)):
    updated = settings_store.update_runninghub_settings(
        user_id=user["id"],
        api_key=payload.api_key,
        concurrent_limit=payload.concurrent_limit,
        instance_type=payload.instance_type,
    )
    return settings_store.public_runninghub_settings(updated, user=user, user_id=user["id"])


@router.put("/settings/llm")
def update_llm_settings(payload: LLMSettingsUpdate, user: dict = Depends(require_current_user)):
    updated = settings_store.update_llm_settings(
        user_id=user["id"],
        base_url=payload.base_url,
        api_key=payload.api_key,
        model=payload.model,
        clear_api_key=payload.clear_api_key,
    )
    return settings_store.public_llm_settings(updated, user_id=user["id"])


@router.post("/settings/llm/test")
async def test_llm_settings(payload: LLMSettingsTest, user: dict = Depends(require_current_user)):
    stored = settings_store.get_llm_settings(user["id"])
    config = LLMConfig(
        base_url=stored["base_url"] if payload.base_url is None else payload.base_url.strip(),
        api_key=stored["api_key"] if payload.api_key is None else payload.api_key.strip(),
        model=stored["model"] if payload.model is None else payload.model.strip(),
    )
    try:
        response = await llm_service.test_connection(config)
    except LLMServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"ok": True, "response": response[:100]}


@router.post("/generate-video")
async def generate_video(
    user: dict = Depends(require_current_user),
    image: UploadFile = File(...),
    audio: UploadFile = File(...),
    runninghub_api_key: Optional[str] = Form(None),
    runninghub_instance_type: Optional[str] = Form(None),
    runninghub_concurrent_limit: int = Form(1),
):
    """Compatibility endpoint for the original digital-human input fields."""
    if runninghub_concurrent_limit < 1 or runninghub_concurrent_limit > 10:
        raise HTTPException(status_code=422, detail="runninghub_concurrent_limit must be between 1 and 10")

    workflow = workflow_catalog.get_workflow("digital-human-lipsync")
    cfg = _get_config()
    runninghub_api_key, runninghub_workflow_id, runninghub_instance_type = _resolve_runninghub_inputs(
        user_id=user["id"],
        api_key=runninghub_api_key,
        instance_type=runninghub_instance_type,
        workflow_id=workflow["workflow_id"],
    )
    output_root = _output_root(cfg)
    image_suffix = uploads.validate_upload(
        image,
        allowed_extensions=IMAGE_EXTENSIONS,
        allowed_mime_types=uploads.IMAGE_MIME_TYPES,
        max_size=uploads.MAX_IMAGE_FILE_SIZE,
        default_suffix=".jpg",
        label="图片",
    )
    audio_suffix = uploads.validate_upload(
        audio,
        allowed_extensions=AUDIO_EXTENSIONS,
        allowed_mime_types=uploads.AUDIO_MIME_TYPES,
        max_size=uploads.MAX_AUDIO_FILE_SIZE,
        default_suffix=".wav",
        label="音频",
    )

    task_id = uuid.uuid4().hex
    task_record = common.create_task(
        user=user,
        task_type=task_store.TASK_TYPE_COMFYUI_WORKFLOW,
        generation_type="video",
        requested_count=1,
        task_id=task_id,
        output_root=output_root,
        extra_info={
            "provider": workflow["provider"],
            "workflow_key": workflow["key"],
        },
        message="任务已创建，等待提交 RunningHub...",
    )
    task_dir = Path(task_record["storage_path"])

    image_path = task_dir / f"character{image_suffix}"
    audio_path = task_dir / f"input_audio{audio_suffix}"
    try:
        await uploads.save_upload(
            image,
            image_path,
            allowed_extensions=IMAGE_EXTENSIONS,
            allowed_mime_types=uploads.IMAGE_MIME_TYPES,
            max_size=uploads.MAX_IMAGE_FILE_SIZE,
            default_suffix=".jpg",
            label="图片",
        )
        await uploads.save_upload(
            audio,
            audio_path,
            allowed_extensions=AUDIO_EXTENSIONS,
            allowed_mime_types=uploads.AUDIO_MIME_TYPES,
            max_size=uploads.MAX_AUDIO_FILE_SIZE,
            default_suffix=".wav",
            label="音频",
        )
    except HTTPException as exc:
        task_store.update_task(
            task_id,
            status="failed",
            progress=0,
            message="保存数字人输入素材失败",
            error=str(exc.detail),
            success_count=0,
            failed_count=1,
            finished=True,
        )
        image_path.unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        task_store.update_task(
            task_id,
            status="failed",
            progress=0,
            message="保存数字人输入素材失败",
            error=str(exc),
            success_count=0,
            failed_count=1,
            finished=True,
        )
        image_path.unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="保存输入素材失败") from exc

    _tasks[task_id] = {
        "user_id": user["id"],
        "status": "pending",
        "progress": 0,
        "message": "任务已创建，等待提交 RunningHub...",
        "video_url": None,
        "runninghub_task_id": None,
        "runninghub_task_url": RUNNINGHUB_TASKS_URL,
        "runninghub_works_url": RUNNINGHUB_WORKS_URL,
        "error": None,
    }

    common.schedule_task(task_id, lambda: _run_video_generation(
            task_id=task_id,
            task_dir=task_dir,
            image_path=image_path,
            audio_path=audio_path,
            api_key=runninghub_api_key,
            workflow_id=runninghub_workflow_id,
            instance_type=runninghub_instance_type,
        ))

    return {"task_id": task_id}


@router.get("/task/{task_id}")
def get_task(task_id: str, user: dict = Depends(require_current_user)):
    try:
        return _task_payload(task_store.get_task(task_id, user["id"]))
    except task_store.TaskNotFoundError:
        task = _tasks.get(task_id)
        if task is None or task.get("user_id") != user["id"]:
            raise HTTPException(status_code=404, detail="Task not found") from None
        return task


async def _run_video_generation(
    task_id: str,
    task_dir: Path,
    image_path: Path,
    audio_path: Path,
    api_key: str,
    workflow_id: str,
    instance_type: Optional[str],
):
    await _run_workflow_generation(
        task_id=task_id,
        workflow={
            "key": "digital-human-lipsync",
            "provider": "runninghub",
            "workflow_id": workflow_id,
        },
        inputs={
            "videoimage": str(image_path),
            "audio": str(audio_path),
        },
        api_key=api_key,
        instance_type=instance_type,
    )


async def _run_workflow_generation(
    task_id: str,
    workflow: dict,
    inputs: dict,
    api_key: str,
    instance_type: Optional[str],
):
    def _update(status: str, progress: int, message: str):
        cached_task = _tasks.get(task_id)
        if cached_task is not None:
            cached_task.update(status=status, progress=progress, message=message)
        task_store.update_task(
            task_id,
            status=status,
            progress=progress,
            message=message,
            started=status == "running",
        )

    try:
        _update("running", 55, "正在提交 ComfyUI 工作流...")
        provider_task_id = await runninghub.submit_workflow(
            workflow_id=workflow["workflow_id"],
            parameters=inputs,
            api_key=api_key,
            instance_type=instance_type,
        )
        record = task_store.get_task(task_id)
        extra_info = dict(record.get("extra_info") or {})
        extra_info.update(
            {
                "provider": workflow["provider"],
                "workflow_key": workflow["key"],
                "workflow_id": workflow["workflow_id"],
                "provider_task_id": str(provider_task_id),
                "provider_task_url": RUNNINGHUB_TASKS_URL,
                "provider_dashboard_url": RUNNINGHUB_WORKS_URL,
                "provider_instance_type": instance_type,
                "runninghub_task_id": str(provider_task_id),
                "runninghub_workflow_id": workflow["workflow_id"],
                "runninghub_instance_type": instance_type,
                "runninghub_task_url": RUNNINGHUB_TASKS_URL,
                "runninghub_works_url": RUNNINGHUB_WORKS_URL,
            }
        )
        task_store.update_task(
            task_id,
            status="submitted",
            progress=100,
            message="工作流任务已提交成功，请到 RunningHub 查看进度和作品。",
            extra_info=extra_info,
            success_count=1,
            failed_count=0,
            finished=True,
        )
        cached_task = _tasks.get(task_id)
        if cached_task is not None:
            cached_task.update(
                status="submitted",
                progress=100,
                message="工作流任务已提交成功，请到 RunningHub 查看进度和作品。",
                provider_task_id=provider_task_id,
                provider_task_url=RUNNINGHUB_TASKS_URL,
                provider_dashboard_url=RUNNINGHUB_WORKS_URL,
                runninghub_task_id=provider_task_id,
                runninghub_task_url=RUNNINGHUB_TASKS_URL,
                runninghub_works_url=RUNNINGHUB_WORKS_URL,
            )
    except Exception as exc:
        try:
            task_store.update_task(
                task_id,
                status="failed",
                progress=0,
                message=f"生成失败：{exc}",
                error=str(exc),
                failed_count=1,
                finished=True,
            )
        except task_store.TaskNotFoundError:
            pass
        cached_task = _tasks.get(task_id)
        if cached_task is not None:
            cached_task.update(
                status="failed",
                progress=0,
                message=f"生成失败：{exc}",
                error=str(exc),
            )
