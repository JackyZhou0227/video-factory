"""Shared helper functions for API layer."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import HTTPException

from app.core.config import app_config, resolve_output_dir
from app.services import task_store
from app.services.task_runtime import TaskRuntimeCapacityError, get_task_runtime


def artifact_url(task_id: str, artifact_id: str, action: str = "preview") -> str:
    """Generate artifact URL for task center."""
    return f"/api/tasks/{task_id}/artifacts/{artifact_id}/{action}"


def public_output_url(path: Path) -> str:
    """Convert absolute output path to public URL path."""
    output_root = resolve_output_dir(app_config).resolve()
    relative = path.resolve().relative_to(output_root).as_posix()
    return f"/output/{relative}"


def persist_task_update(task_id: str, **updates: Any) -> None:
    """Update task metadata, ignoring TaskNotFoundError."""
    try:
        task_store.update_task(task_id, **updates)
    except task_store.TaskNotFoundError:
        pass


def persist_artifact(task_id: str, **artifact: Any) -> None:
    """Add artifact to task, ignoring TaskNotFoundError."""
    try:
        task_store.add_artifact(task_id, **artifact)
    except task_store.TaskNotFoundError:
        pass


def create_task(**kwargs: Any) -> dict[str, Any]:
    """Create a generation task, rejecting the request when quota is exceeded."""
    try:
        return task_store.create_task(**kwargs)
    except task_store.TaskQuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None


def schedule_task(task_id: str, runner: Callable[[], Awaitable[None]]) -> None:
    """Queue a persisted task in the application-owned execution runtime."""
    try:
        get_task_runtime().submit(task_id, runner)
    except TaskRuntimeCapacityError as exc:
        task_store.update_task(
            task_id,
            status="cancelled",
            message="任务队列已满，未开始执行",
            error=str(exc),
            finished=True,
        )
        raise HTTPException(status_code=429, detail=str(exc)) from None
    except RuntimeError:
        # Lightweight router tests intentionally do not mount the application lifespan.
        # Production always initializes the managed runtime before accepting requests.
        import asyncio

        asyncio.create_task(runner())


def safe_filename(filename: str, fallback: str) -> str:
    """Sanitize filename to remove unsafe characters."""
    value = Path(filename or fallback).name
    safe = re.sub(r"[^\w.\-一-鿿]+", "_", value, flags=re.UNICODE).strip("._")
    return safe or fallback


def parse_json_field(value: str, label: str, expected_type: type) -> Any:
    """Parse and validate JSON form field."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"{label} 必须是有效 JSON") from exc
    if not isinstance(parsed, expected_type):
        raise HTTPException(status_code=422, detail=f"{label} 格式不正确")
    return parsed


def create_output_zip(zip_path: Path, files: list[Path]) -> None:
    """Create ZIP archive from list of output files."""
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
