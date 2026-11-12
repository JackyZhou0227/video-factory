from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api import common
from app.api.auth import require_current_user
from app.core.config import ROOT, app_config, get_comfyui_config
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


def _workflow_form_values(workflow: dict, form, exclude_keys: set = None) -> dict:
    """Extract workflow parameter values from form data.

    Args:
        workflow: Workflow definition
        form: Form data (StarletteFormData)
        exclude_keys: Keys to ignore (e.g. routing params like 'source')
    """
    exclude_keys = exclude_keys or set()
    declarations = {field["key"]: field for field in workflow["inputs"]}
    unknown = set(form.keys()) - declarations.keys() - exclude_keys
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
    source_config: dict,
    api_key: Optional[str] = None,
    instance_type: Optional[str] = None,
    output_root: Optional[Path] = None,
) -> dict:
    """
    Create and execute a workflow task

    Args:
        user: Current user
        workflow: Workflow definition from catalog
        values: Form values (scalar + files)
        source_config: Source-specific config (from get_workflow_source_config)
        api_key: Optional RunningHub API key override
        instance_type: Optional RunningHub instance type override
        output_root: Optional output directory override
    """
    # Only RunningHub is supported for now
    if "workflow_id" not in source_config:
        raise HTTPException(status_code=422, detail="暂不支持此工作流服务来源")

    scalar_values, files = _validate_workflow_inputs(workflow, values)
    resolved_api_key, resolved_workflow_id, resolved_instance_type = _resolve_runninghub_inputs(
        user_id=user["id"],
        api_key=api_key,
        instance_type=instance_type,
        workflow_id=source_config["workflow_id"],
    )
    cfg = _get_config()
    output_root = output_root or _output_root(cfg)
    task_id = uuid.uuid4().hex
    task_record = common.create_task(
        user=user,
        task_type=task_store.TASK_TYPE_COMFYUI_WORKFLOW,
        generation_type=workflow.get("generation_type", "video"),
        requested_count=1,
        task_id=task_id,
        output_root=output_root,
        extra_info={
            "source": "runninghub",
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


async def _create_selfhost_task(
    *,
    user: dict,
    workflow: dict,
    values: dict,
    source_config: dict,
    output_root: Optional[Path] = None,
) -> dict:
    """
    Create and execute a self-hosted ComfyUI workflow task

    Args:
        user: Current user
        workflow: Workflow definition from catalog
        values: Form values (scalar + files)
        source_config: Source-specific config (contains workflow_path)
        output_root: Optional output directory override
    """
    # Validate workflow_path exists
    if "workflow_path" not in source_config:
        raise HTTPException(status_code=422, detail="工作流文件未配置")

    workflow_file_path = ROOT / source_config["workflow_path"]
    if not workflow_file_path.exists():
        raise HTTPException(status_code=500, detail=f"工作流文件不存在: {workflow_file_path}")

    # Validate and save inputs
    scalar_values, files = _validate_workflow_inputs(workflow, values)

    cfg = _get_config()
    output_root = output_root or _output_root(cfg)
    task_id = uuid.uuid4().hex

    # Create task record
    task_record = common.create_task(
        user=user,
        task_type=task_store.TASK_TYPE_COMFYUI_WORKFLOW,
        generation_type=workflow.get("generation_type", "video"),
        requested_count=1,
        task_id=task_id,
        output_root=output_root,
        extra_info={
            "source": "selfhost",
            "workflow_key": workflow["key"],
            "workflow_file": str(workflow_file_path),
        },
        message="任务已创建，准备提交到本地 ComfyUI...",
    )

    task_dir = Path(task_record["storage_path"])

    # Save uploaded files
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
    except HTTPException as exc:
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

    # Update in-memory task state
    _tasks[task_id] = {
        "user_id": user["id"],
        "status": "pending",
        "progress": 0,
        "message": "任务已创建，等待提交本地 ComfyUI...",
        "video_url": None,
        "provider_task_id": None,
        "provider_task_url": None,
        "provider_dashboard_url": None,
        "error": None,
    }

    # Schedule async execution
    common.schedule_task(
        task_id,
        lambda: _run_selfhost_workflow(
            task_id=task_id,
            workflow_file=workflow_file_path,
            scalar_inputs=scalar_values,
            file_inputs={key: saved_paths[i] for i, key in enumerate(files.keys())},
            task_dir=task_dir,
        ),
    )

    return {"task_id": task_id}


def _comfyui_error_message(response: httpx.Response) -> str:
    """Turn ComfyUI's /prompt response into one readable line (e.g. missing models)."""
    try:
        payload = response.json()
    except ValueError:
        return f"ComfyUI 返回 {response.status_code}：{response.text[:300]}"

    parts: list[str] = []
    error = payload.get("error")
    if isinstance(error, dict) and error.get("message"):
        parts.append(str(error["message"]))
    elif isinstance(error, str) and error:
        parts.append(error)

    for node_id, node_error in (payload.get("node_errors") or {}).items():
        class_type = node_error.get("class_type", node_id)
        for item in node_error.get("errors") or []:
            details = item.get("details") or item.get("message") or ""
            parts.append(f"{class_type}: {details}".strip())

    if not parts:
        return f"ComfyUI 返回 {response.status_code}"
    return "ComfyUI 拒绝了工作流：" + "；".join(parts)


def _execution_error_message(status_info: dict) -> str:
    """Pull the exception message out of a history entry's execution_error event."""
    for event in status_info.get("messages") or []:
        if isinstance(event, list) and len(event) == 2 and event[0] == "execution_error":
            data = event[1] or {}
            node = data.get("node_type") or data.get("node_id") or "节点"
            message = data.get("exception_message") or "执行失败"
            return f"ComfyUI 执行出错（{node}）：{str(message).strip()}"
    return "ComfyUI 执行出错"


async def _run_selfhost_workflow(
    *,
    task_id: str,
    workflow_file: Path,
    scalar_inputs: dict,
    file_inputs: dict[str, Path],
    task_dir: Path,
):
    """
    Execute workflow on self-hosted ComfyUI

    Args:
        task_id: Task ID
        workflow_file: Path to workflow JSON file
        scalar_inputs: Scalar input values (text, number, select)
        file_inputs: File input paths {key: saved_path}
        task_dir: Task output directory
    """
    comfyui_url = get_comfyui_config()["url"].rstrip("/")

    try:
        # Load workflow template
        with open(workflow_file, "r", encoding="utf-8") as f:
            workflow_json = json.load(f)

        # Get workflow definition from task record
        task_record = task_store.get_task(task_id)
        workflow_key = task_record.get("extra_info", {}).get("workflow_key")
        if not workflow_key:
            raise Exception("任务缺少 workflow_key")

        workflow_def = workflow_catalog.get_workflow(workflow_key)

        # Modify workflow nodes directly (Pixelle-Video style)
        for field in workflow_def["inputs"]:
            if field["type"] in {"text", "textarea", "number", "select"}:
                key = field["key"]
                value = scalar_inputs.get(key)
                if value is not None:
                    node_id = field.get("selfhost_node_id")
                    input_key = field.get("selfhost_input_key")
                    if node_id and input_key:
                        if node_id in workflow_json:
                            workflow_json[node_id]["inputs"][input_key] = value

        # TODO: Handle file inputs (may need custom node support)

        # Update task status
        task_store.update_task(
            task_id,
            status="running",
            progress=10,
            message="正在提交工作流到 ComfyUI...",
        )

        # Submit to ComfyUI
        client_id = uuid.uuid4().hex
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{comfyui_url}/prompt",
                json={"prompt": workflow_json, "client_id": client_id},
            )
        # ComfyUI 缺模型/缺节点时仍返回 200，只在 node_errors 里报错
        if response.status_code != 200 or response.json().get("node_errors"):
            raise Exception(_comfyui_error_message(response))
        prompt_id = response.json()["prompt_id"]

        task_store.update_task(
            task_id,
            status="running",
            progress=30,
            message=f"工作流已提交，等待执行... (ID: {prompt_id[:8]})",
        )

        # Poll for completion
        max_attempts = 120  # 2 minutes
        for attempt in range(max_attempts):
            await asyncio.sleep(1)

            async with httpx.AsyncClient(timeout=10.0) as client:
                hist_response = await client.get(f"{comfyui_url}/history/{prompt_id}")
                hist_response.raise_for_status()
                history = hist_response.json()

            if prompt_id in history:
                job = history[prompt_id]
                status_info = job.get("status", {})

                if status_info.get("completed"):
                    # Success - download outputs
                    outputs = job.get("outputs", {})
                    downloaded_files = []

                    for node_id, node_outputs in outputs.items():
                        if "images" in node_outputs:
                            for img in node_outputs["images"]:
                                filename = img["filename"]
                                subfolder = img.get("subfolder", "")
                                file_type = img.get("type", "output")

                                # Download from ComfyUI
                                async with httpx.AsyncClient(timeout=30.0) as client:
                                    img_response = await client.get(
                                        f"{comfyui_url}/view",
                                        params={"filename": filename, "subfolder": subfolder, "type": file_type},
                                    )
                                    img_response.raise_for_status()

                                    output_path = task_dir / filename
                                    output_path.write_bytes(img_response.content)
                                    downloaded_files.append(output_path)

                    if not downloaded_files:
                        raise Exception("工作流执行成功，但未生成任何输出文件")

                    # Register artifacts
                    for path in downloaded_files:
                        task_store.add_artifact(
                            task_id,
                            path=path,
                            kind="image",
                            status="completed",
                            is_primary=(path == downloaded_files[0]),
                        )

                    task_store.update_task(
                        task_id,
                        status="completed",
                        progress=100,
                        message=f"完成！生成了 {len(downloaded_files)} 个文件",
                        success_count=len(downloaded_files),
                        finished=True,
                    )
                    return

                elif status_info.get("status_str") == "error":
                    raise Exception(_execution_error_message(status_info))

            # Update progress
            progress = min(30 + (attempt * 60 // max_attempts), 90)
            task_store.update_task(
                task_id,
                progress=progress,
                message=f"执行中... ({attempt}/{max_attempts})",
            )

        # Timeout
        raise Exception(f"执行超时 ({max_attempts}秒)")

    except Exception as exc:
        task_store.update_task(
            task_id,
            status="failed",
            progress=0,
            message="执行失败",
            error=str(exc),
            failed_count=1,
            finished=True,
        )
        raise


@router.get("/workflows")
def list_workflows(user: dict = Depends(require_current_user)):
    del user
    return workflow_catalog.list_public_workflows()


@router.post("/workflows/{workflow_key}/generate")
async def generate_workflow(
    workflow_key: str,
    source: str = Form(...),
    request: Request = None,
    user: dict = Depends(require_current_user),
):
    """
    Generate a workflow task

    Args:
        workflow_key: Workflow identifier
        source: Execution environment - "runninghub" or "selfhost"
        request: FastAPI request (for form data)
        user: Current user
    """
    # Validate source
    if source not in {"runninghub", "selfhost"}:
        raise HTTPException(
            status_code=422, detail="source 必须是 runninghub 或 selfhost"
        )

    # Get workflow and verify it supports the source
    workflow = workflow_catalog.get_workflow(workflow_key)
    source_config = workflow_catalog.get_workflow_source_config(workflow_key, source)

    # Parse form values (exclude routing params)
    form = await request.form()
    values = _workflow_form_values(workflow, form, exclude_keys={"source"})

    # Route to appropriate executor
    if source == "runninghub":
        # Existing RunningHub logic
        return await _create_workflow_task(
            user=user, workflow=workflow, values=values, source_config=source_config
        )
    elif source == "selfhost":
        # Self-hosted ComfyUI execution
        return await _create_selfhost_task(
            user=user, workflow=workflow, values=values, source_config=source_config
        )
    else:
        # Should never reach here due to earlier validation
        raise HTTPException(status_code=500, detail="未知的执行环境")


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
    source_config = workflow_catalog.get_workflow_source_config("digital-human-lipsync", "runninghub")
    cfg = _get_config()
    runninghub_api_key, runninghub_workflow_id, runninghub_instance_type = _resolve_runninghub_inputs(
        user_id=user["id"],
        api_key=runninghub_api_key,
        instance_type=runninghub_instance_type,
        workflow_id=source_config["workflow_id"],
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
            "source": "runninghub",
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
                "source": "runninghub",
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
