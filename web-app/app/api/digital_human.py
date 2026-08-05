from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.auth import require_current_user
from app.core.config import ROOT, app_config
from app.services import runninghub, settings_store
from app.services.llm import LLMConfig, LLMServiceError, llm_service

router = APIRouter(dependencies=[Depends(require_current_user)])

RUNNINGHUB_TASKS_URL = "https://www.runninghub.cn/bill-task"
RUNNINGHUB_WORKS_URL = "https://www.runninghub.cn/user-center"

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


def _resolve_runninghub_inputs(
    user_id: str,
    api_key: Optional[str],
    instance_type: Optional[str],
) -> tuple[str, str, Optional[str]]:
    stored = settings_store.get_runninghub_settings(user_id)

    resolved_api_key = (api_key or stored["api_key"]).strip()
    resolved_workflow_id = settings_store.FIXED_DIGITAL_HUMAN_WORKFLOW_ID
    resolved_instance_type = instance_type
    if isinstance(resolved_instance_type, str):
        resolved_instance_type = resolved_instance_type.strip() or None
    if resolved_instance_type is None:
        resolved_instance_type = stored["instance_type"] or None

    if not resolved_api_key:
        raise HTTPException(status_code=422, detail="请先在设置页配置 RunningHub API Key")

    return resolved_api_key, resolved_workflow_id, resolved_instance_type


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
    """Create a RunningHub task from a character image and uploaded audio."""
    if runninghub_concurrent_limit < 1 or runninghub_concurrent_limit > 10:
        raise HTTPException(status_code=422, detail="runninghub_concurrent_limit must be between 1 and 10")

    cfg = _get_config()
    runninghub_api_key, runninghub_workflow_id, runninghub_instance_type = _resolve_runninghub_inputs(
        user_id=user["id"],
        api_key=runninghub_api_key,
        instance_type=runninghub_instance_type,
    )
    output_root = _output_root(cfg)

    task_id = uuid.uuid4().hex
    task_dir = output_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    image_path = task_dir / f"character{Path(image.filename).suffix or '.jpg'}"
    image_path.write_bytes(await image.read())
    audio_path = task_dir / f"input_audio{Path(audio.filename).suffix or '.wav'}"
    audio_path.write_bytes(await audio.read())

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

    asyncio.create_task(
        _run_video_generation(
            task_id=task_id,
            task_dir=task_dir,
            image_path=image_path,
            audio_path=audio_path,
            api_key=runninghub_api_key,
            workflow_id=runninghub_workflow_id,
            instance_type=runninghub_instance_type,
        )
    )

    return {"task_id": task_id}


@router.get("/task/{task_id}")
def get_task(task_id: str, user: dict = Depends(require_current_user)):
    task = _tasks.get(task_id)
    if task is None or task.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Task not found")
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
    def _update(status: str, progress: int, message: str):
        _tasks[task_id].update(status=status, progress=progress, message=message)

    try:
        _update("running", 55, "音频已确认，正在提交 RunningHub 数字人工作流...")
        runninghub_task_id = await runninghub.submit_digital_human(
            image_path=image_path,
            audio_path=audio_path,
            workflow_id=workflow_id,
            api_key=api_key,
            instance_type=instance_type,
        )
        _tasks[task_id].update(
            status="submitted",
            progress=100,
            message="RunningHub 任务已提交成功。生成通常需要较长时间，请到 RunningHub 查看进度和作品。",
            runninghub_task_id=runninghub_task_id,
            runninghub_task_url=RUNNINGHUB_TASKS_URL,
            runninghub_works_url=RUNNINGHUB_WORKS_URL,
        )
    except Exception as exc:
        _tasks[task_id].update(
            status="failed",
            progress=0,
            message=f"生成失败：{exc}",
            error=str(exc),
        )
