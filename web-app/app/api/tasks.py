from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.auth import require_current_user
from app.services import task_store

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(require_current_user)])
try:
    DISPLAY_TIMEZONE = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    DISPLAY_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")


def _date_boundary(value: Optional[date], *, end: bool = False) -> Optional[str]:
    if value is None:
        return None
    boundary = time.max if end else time.min
    local_datetime = datetime.combine(value, boundary, tzinfo=DISPLAY_TIMEZONE)
    return local_datetime.astimezone(timezone.utc).isoformat()


def _artifact_urls(task_id: str, artifact: dict) -> dict:
    artifact_id = artifact["id"]
    return {
        **artifact,
        "preview_url": f"/api/tasks/{task_id}/artifacts/{artifact_id}/preview",
        "download_url": f"/api/tasks/{task_id}/artifacts/{artifact_id}/download",
    }


def task_payload(task: dict) -> dict:
    payload = task_store.public_task(task)
    payload["artifacts"] = [_artifact_urls(task["id"], item) for item in payload["artifacts"]]
    download_artifact = task_store.select_task_download(task)
    payload["download_url"] = f"/api/tasks/{task['id']}/download" if download_artifact else None
    return payload


def _owned_task(task_id: str, user_id: str) -> dict:
    try:
        return task_store.get_task(task_id, user_id)
    except task_store.TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found") from None


@router.get("")
def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    task_type: Optional[str] = Query(None),
    generation_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    created_from: Optional[date] = Query(None),
    created_to: Optional[date] = Query(None),
    user: dict = Depends(require_current_user),
):
    try:
        tasks, total = task_store.list_tasks(
            user["id"],
            page=page,
            page_size=page_size,
            task_type=task_type,
            generation_type=generation_type,
            status=status,
            created_from=_date_boundary(created_from),
            created_to=_date_boundary(created_to, end=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {
        "items": [task_payload(task) for task in tasks],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/{task_id}")
def get_task(task_id: str, user: dict = Depends(require_current_user)):
    return task_payload(_owned_task(task_id, user["id"]))


def _artifact_response(task: dict, artifact_id: str, *, download: bool) -> FileResponse:
    try:
        artifact, path = task_store.resolve_artifact_path(task, artifact_id)
    except task_store.ArtifactNotFoundError:
        raise HTTPException(status_code=404, detail="Artifact not found") from None
    return FileResponse(
        path,
        media_type=artifact.get("mime_type") or "application/octet-stream",
        filename=artifact.get("name") or path.name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/{task_id}/artifacts/{artifact_id}/preview")
def preview_artifact(task_id: str, artifact_id: str, user: dict = Depends(require_current_user)):
    return _artifact_response(_owned_task(task_id, user["id"]), artifact_id, download=False)


@router.get("/{task_id}/artifacts/{artifact_id}/download")
def download_artifact(task_id: str, artifact_id: str, user: dict = Depends(require_current_user)):
    return _artifact_response(_owned_task(task_id, user["id"]), artifact_id, download=True)


@router.get("/{task_id}/download")
def download_task(task_id: str, user: dict = Depends(require_current_user)):
    task = _owned_task(task_id, user["id"])
    artifact = task_store.select_task_download(task)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Task has no downloadable artifact")
    return _artifact_response(task, artifact["id"], download=True)
