from __future__ import annotations

import json
import mimetypes
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session as OrmSession

from app.core.config import app_config, resolve_output_dir
from app.db.models import GenerationTask, User
from app.services import settings_store

TASK_TYPE_DIGITAL_HUMAN = "digital_human"
TASK_TYPE_VOICE = "voice_generation"
TASK_TYPE_TEMPLATE = "template_production"
TASK_TYPE_POSTER = "poster_video"
TASK_TYPE_SMART_EDITING = "smart_editing"

TASK_TYPES = {
    TASK_TYPE_DIGITAL_HUMAN,
    TASK_TYPE_VOICE,
    TASK_TYPE_TEMPLATE,
    TASK_TYPE_POSTER,
    TASK_TYPE_SMART_EDITING,
}
GENERATION_TYPES = {"voice", "image", "video"}
TASK_STATUSES = {
    "pending",
    "running",
    "submitted",
    "completed",
    "partial_failed",
    "failed",
    "cancelled",
}
TERMINAL_STATUSES = {"submitted", "completed", "partial_failed", "failed", "cancelled"}
ARTIFACT_STATUSES = {"pending", "running", "completed", "failed", "missing"}
FORBIDDEN_EXTRA_KEYS = {
    "api_key",
    "auth_token",
    "authorization",
    "client_secret",
    "credential",
    "credentials",
    "password",
    "private_key",
    "secret",
    "token",
    "access_token",
    "refresh_token",
}
FORBIDDEN_EXTRA_KEY_SUFFIXES = {
    "apikey",
    "password",
    "privatekey",
    "secret",
    "token",
}
PUBLIC_ARTIFACT_KEYS = {
    "id",
    "name",
    "kind",
    "mime_type",
    "status",
    "size",
    "created_at",
    "is_primary",
    "counts_toward_result",
    "error",
}
TASK_COLUMNS = (
    "id, user_id, creator_username, creator_display_name, task_type, generation_type, "
    "requested_count, success_count, failed_count, status, progress, message, error, "
    "storage_path, extra_info_json, artifacts_json, created_at, started_at, finished_at, updated_at"
)


class TaskNotFoundError(LookupError):
    pass


class ArtifactNotFoundError(LookupError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _json_loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _normalize_timestamp(value: str) -> str:
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError("timestamp must be an ISO-8601 datetime") from None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


def _validate_task_id(value: str) -> str:
    task_id = str(value or "").strip()
    try:
        uuid.UUID(task_id)
    except (AttributeError, TypeError, ValueError):
        raise ValueError("task_id must be a UUID") from None
    return task_id


def _is_forbidden_extra_key(key: Any) -> bool:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key).strip())
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    collapsed = normalized.replace("_", "")
    forbidden = {item.replace("_", "") for item in FORBIDDEN_EXTRA_KEYS}
    return collapsed in forbidden or any(
        collapsed.endswith(suffix) for suffix in FORBIDDEN_EXTRA_KEY_SUFFIXES
    )


def _normalize_extra_info(value: Optional[dict[str, Any]]) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("extra_info must be a JSON object")

    def validate(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if _is_forbidden_extra_key(key):
                    raise ValueError(f"Sensitive field is not allowed in extra_info: {key}")
                validate(nested)
        elif isinstance(item, list):
            for nested in item:
                validate(nested)

    validate(value)
    try:
        return json.loads(_json_dumps(value))
    except (TypeError, ValueError):
        raise ValueError("extra_info must contain JSON-serializable values") from None


def _safe_public_extra_info(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe_public_extra_info(nested)
            for key, nested in value.items()
            if not _is_forbidden_extra_key(key)
        }
    if isinstance(value, list):
        return [_safe_public_extra_info(item) for item in value]
    return value


def _validate_task_values(task_type: str, generation_type: str, status: str) -> None:
    if task_type not in TASK_TYPES:
        raise ValueError(f"Unsupported task type: {task_type}")
    if generation_type not in GENERATION_TYPES:
        raise ValueError(f"Unsupported generation type: {generation_type}")
    if status not in TASK_STATUSES:
        raise ValueError(f"Unsupported task status: {status}")


def _output_root(output_root: Optional[Path] = None) -> Path:
    return Path(output_root or resolve_output_dir(app_config)).resolve()


def task_directory(
    task_type: str,
    task_id: str,
    *,
    created_at: Optional[str] = None,
    output_root: Optional[Path] = None,
) -> Path:
    if task_type not in TASK_TYPES:
        raise ValueError(f"Unsupported task type: {task_type}")
    task_id = _validate_task_id(task_id)
    utc_timestamp = datetime.fromisoformat(_normalize_timestamp(created_at or _now_iso()))
    root = _output_root(output_root)
    path = (
        root
        / "tasks"
        / utc_timestamp.strftime("%Y")
        / utc_timestamp.strftime("%m")
        / utc_timestamp.strftime("%d")
        / task_type
        / task_id
    ).resolve()
    path.relative_to(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _row_to_record(row: dict[str, Any] | GenerationTask) -> dict[str, Any]:
    if isinstance(row, dict):
        record = dict(row)
    else:
        record = {
            column: getattr(row, column)
            for column in TASK_COLUMNS.split(", ")
        }
    record["extra_info"] = _json_loads(record.pop("extra_info_json", "{}"), {})
    record["artifacts"] = _json_loads(record.pop("artifacts_json", "[]"), [])
    return record


def _ensure_db() -> None:
    settings_store.init_db()


def _orm_session() -> OrmSession:
    return settings_store._orm_session()


def _task_owner_snapshot(session: OrmSession, user: dict[str, Any]) -> tuple[str, str]:
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        raise ValueError("user id is required")
    owner = session.scalar(select(User).where(User.id == user_id))
    if owner is None:
        raise ValueError("task owner does not exist")
    username = str(owner.username or user_id)
    return username, str(owner.display_name or username)


def _artifact_counts(artifacts: Iterable[dict[str, Any]]) -> tuple[int, int]:
    success = 0
    failed = 0
    for artifact in artifacts:
        if artifact.get("kind") == "archive" or artifact.get("counts_toward_result") is False:
            continue
        status = artifact.get("status")
        if status == "completed":
            success += 1
        elif status in {"failed", "missing"}:
            failed += 1
    return success, failed


def _normalize_artifacts(
    artifacts: Iterable[dict[str, Any]],
    *,
    storage_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for artifact in artifacts:
        item = dict(artifact)
        item.setdefault("id", uuid.uuid4().hex)
        item.setdefault("name", item["id"])
        item.setdefault("kind", "file")
        item.setdefault(
            "mime_type",
            mimetypes.guess_type(str(item["name"]))[0] or "application/octet-stream",
        )
        item.setdefault("status", "pending")
        item.setdefault("created_at", _now_iso())
        item.setdefault("is_primary", False)
        if item["status"] not in ARTIFACT_STATUSES:
            raise ValueError(f"Unsupported artifact status: {item['status']}")
        if "path" in item:
            item["path"] = str(Path(item["path"]).resolve())
            path = Path(item["path"])
            if storage_path is not None:
                try:
                    path.relative_to(Path(storage_path).resolve())
                except ValueError:
                    raise ValueError("artifact path must be inside task directory") from None
            item["size"] = int(item.get("size") or (path.stat().st_size if path.is_file() else 0))
        normalized.append(item)
    return normalized


def create_task(
    *,
    user: dict[str, Any],
    task_type: str,
    generation_type: str,
    requested_count: int,
    task_id: Optional[str] = None,
    created_at: Optional[str] = None,
    output_root: Optional[Path] = None,
    storage_path: Optional[Path] = None,
    extra_info: Optional[dict[str, Any]] = None,
    artifacts: Optional[list[dict[str, Any]]] = None,
    status: str = "pending",
    message: str = "任务已创建",
) -> dict[str, Any]:
    if not isinstance(requested_count, int) or requested_count < 1:
        raise ValueError("requested_count must be at least 1")
    _validate_task_values(task_type, generation_type, status)
    task_id = _validate_task_id(task_id or uuid.uuid4().hex)
    created_at = _normalize_timestamp(created_at or _now_iso())
    normalized_extra_info = _normalize_extra_info(extra_info)
    _ensure_db()
    with _orm_session() as session:
        username, display_name = _task_owner_snapshot(session, user)

    storage_path = storage_path or task_directory(
        task_type,
        task_id,
        created_at=created_at,
        output_root=output_root,
    )
    storage_path = Path(storage_path).resolve()
    try:
        storage_path.relative_to(_output_root(output_root))
    except ValueError:
        raise ValueError("storage_path must be inside output directory") from None
    storage_path.mkdir(parents=True, exist_ok=True)
    now = _now_iso()
    initial_artifacts = _normalize_artifacts(artifacts or [], storage_path=storage_path)
    success_count, failed_count = _artifact_counts(initial_artifacts)
    with _orm_session() as session:
        task = GenerationTask(
            id=task_id,
            user_id=str(user["id"]),
            creator_username=username,
            creator_display_name=display_name,
            task_type=task_type,
            generation_type=generation_type,
            requested_count=requested_count,
            success_count=success_count,
            failed_count=failed_count,
            status=status,
            progress=0,
            message=message,
            error=None,
            storage_path=str(storage_path),
            extra_info_json=_json_dumps(normalized_extra_info),
            artifacts_json=_json_dumps(initial_artifacts),
            created_at=created_at,
            started_at=None,
            finished_at=now if status in TERMINAL_STATUSES else None,
            updated_at=now,
        )
        session.add(task)
        session.flush()
    return _row_to_record(task)


def _fetch_row(session: OrmSession, task_id: str, user_id: Optional[str] = None) -> GenerationTask | None:
    query = select(GenerationTask).where(GenerationTask.id == task_id)
    if user_id is not None:
        query = query.where(GenerationTask.user_id == user_id)
    return session.scalar(query)


def get_task(task_id: str, user_id: Optional[str] = None) -> dict[str, Any]:
    _ensure_db()
    with _orm_session() as session:
        task = _fetch_row(session, task_id, user_id)
    if task is None:
        raise TaskNotFoundError("Task not found")
    return _row_to_record(task)


def update_task(
    task_id: str,
    *,
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    message: Optional[str] = None,
    error: Optional[str] = None,
    extra_info: Optional[dict[str, Any]] = None,
    artifacts: Optional[Iterable[dict[str, Any]]] = None,
    success_count: Optional[int] = None,
    failed_count: Optional[int] = None,
    started: bool = False,
    finished: Optional[bool] = None,
) -> dict[str, Any]:
    if status is not None and status not in TASK_STATUSES:
        raise ValueError(f"Unsupported task status: {status}")
    if progress is not None and not 0 <= int(progress) <= 100:
        raise ValueError("progress must be between 0 and 100")
    normalized_extra_info = _normalize_extra_info(extra_info) if extra_info is not None else None
    normalized_artifacts = None
    if artifacts is not None:
        task = get_task(task_id, user_id)
        normalized_artifacts = _normalize_artifacts(
            artifacts,
            storage_path=Path(task["storage_path"]),
        )
    if normalized_artifacts is not None:
        calculated_success, calculated_failed = _artifact_counts(normalized_artifacts)
        if success_count is None:
            success_count = calculated_success
        if failed_count is None:
            failed_count = calculated_failed
    if success_count is not None and int(success_count) < 0:
        raise ValueError("success_count must be non-negative")
    if failed_count is not None and int(failed_count) < 0:
        raise ValueError("failed_count must be non-negative")

    _ensure_db()
    now = _now_iso()
    with _orm_session() as session:
        task = _fetch_row(session, task_id, user_id)
        if task is None:
            raise TaskNotFoundError("Task not found")
        if status is not None:
            task.status = status
        if progress is not None:
            task.progress = int(progress)
        if message is not None:
            task.message = str(message)
        if error is not None:
            task.error = str(error)
        if normalized_extra_info is not None:
            task.extra_info_json = _json_dumps(normalized_extra_info)
        if normalized_artifacts is not None:
            task.artifacts_json = _json_dumps(normalized_artifacts)
        if success_count is not None:
            task.success_count = int(success_count)
        if failed_count is not None:
            task.failed_count = int(failed_count)
        if (started or status == "running") and task.started_at is None:
            task.started_at = now
        is_finished = finished if finished is not None else status in TERMINAL_STATUSES
        if is_finished and task.finished_at is None:
            task.finished_at = now
        task.updated_at = now
        session.flush()
    return _row_to_record(task)


def add_artifact(
    task_id: str,
    *,
    path: Path,
    name: Optional[str] = None,
    kind: str = "file",
    mime_type: Optional[str] = None,
    status: str = "completed",
    is_primary: bool = False,
    counts_toward_result: bool = True,
    user_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
) -> dict[str, Any]:
    path = Path(path).resolve()
    task = get_task(task_id, user_id)
    try:
        path.relative_to(Path(task["storage_path"]).resolve())
    except ValueError:
        raise ValueError("artifact path must be inside task directory") from None
    artifact = {
        "id": artifact_id or uuid.uuid4().hex,
        "name": name or path.name,
        "kind": kind,
        "mime_type": mime_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream",
        "path": str(path),
        "status": status,
        "size": path.stat().st_size if path.is_file() else 0,
        "created_at": _now_iso(),
        "is_primary": bool(is_primary),
        "counts_toward_result": bool(counts_toward_result),
    }
    artifacts = list(task["artifacts"])
    artifacts.append(artifact)
    return update_task(task_id, user_id=user_id, artifacts=artifacts)


def update_artifact(
    task_id: str,
    artifact_id: str,
    *,
    user_id: Optional[str] = None,
    **updates: Any,
) -> dict[str, Any]:
    task = get_task(task_id, user_id)
    artifacts = list(task["artifacts"])
    for artifact in artifacts:
        if artifact.get("id") == artifact_id:
            artifact.update(updates)
            return update_task(task_id, user_id=user_id, artifacts=artifacts)
    raise ArtifactNotFoundError("Artifact not found")


def _public_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in artifact.items() if key in PUBLIC_ARTIFACT_KEYS}
    path = Path(str(artifact.get("path") or ""))
    if artifact.get("status") == "completed" and not path.is_file():
        public["status"] = "missing"
    return public


def public_task(task: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in task.items() if key != "storage_path"}
    public["extra_info"] = _safe_public_extra_info(task.get("extra_info") or {})
    public["artifacts"] = [_public_artifact(item) for item in task.get("artifacts", [])]
    return public


def list_tasks(
    user_id: str,
    *,
    page: int = 1,
    page_size: int = 20,
    task_type: Optional[str] = None,
    generation_type: Optional[str] = None,
    status: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
) -> tuple[list[dict[str, Any]], int]:
    if page < 1 or page_size < 1 or page_size > 100:
        raise ValueError("Invalid pagination")
    if task_type is not None and task_type not in TASK_TYPES:
        raise ValueError("Unsupported task type")
    if generation_type is not None and generation_type not in GENERATION_TYPES:
        raise ValueError("Unsupported generation type")
    if status is not None and status not in TASK_STATUSES:
        raise ValueError("Unsupported task status")
    _ensure_db()
    filters = [GenerationTask.user_id == user_id]
    for column, value in (
        (GenerationTask.task_type, task_type),
        (GenerationTask.generation_type, generation_type),
        (GenerationTask.status, status),
    ):
        if value is not None:
            filters.append(column == value)
    if created_from is not None:
        filters.append(GenerationTask.created_at >= created_from)
    if created_to is not None:
        filters.append(GenerationTask.created_at <= created_to)
    offset = (page - 1) * page_size
    with _orm_session() as session:
        total = session.scalar(
            select(func.count()).select_from(GenerationTask).where(*filters)
        ) or 0
        tasks = session.scalars(
            select(GenerationTask)
            .where(*filters)
            .order_by(GenerationTask.created_at.desc())
            .limit(page_size)
            .offset(offset)
        ).all()
    return [_row_to_record(task) for task in tasks], int(total)


def resolve_artifact_path(task: dict[str, Any], artifact_id: str) -> tuple[dict[str, Any], Path]:
    storage_path = Path(str(task.get("storage_path") or "")).resolve()
    output_root = _output_root()
    try:
        storage_path.relative_to(output_root)
    except ValueError:
        raise ArtifactNotFoundError("Artifact is outside output directory") from None
    for artifact in task.get("artifacts", []):
        if artifact.get("id") != artifact_id:
            continue
        candidate = Path(str(artifact.get("path") or "")).resolve()
        try:
            candidate.relative_to(storage_path)
        except ValueError:
            raise ArtifactNotFoundError("Artifact is outside task directory") from None
        if not candidate.is_file():
            raise ArtifactNotFoundError("Artifact file not found")
        return artifact, candidate
    raise ArtifactNotFoundError("Artifact not found")


def resolve_output_file_for_user(relative_path: str, user_id: str) -> Path:
    """Resolve a legacy output URL only when it belongs to the authenticated user."""
    normalized = str(relative_path or "").replace("\\", "/").lstrip("/")
    output_root = _output_root()
    candidate = (output_root / normalized).resolve()
    try:
        canonical_relative = candidate.relative_to(output_root)
    except ValueError:
        raise ArtifactNotFoundError("Output file is outside output directory") from None
    if not candidate.is_file():
        raise ArtifactNotFoundError("Output file not found")

    parts = canonical_relative.parts
    if len(parts) >= 2 and parts[0] in {"tts-studio", "bgm"}:
        if parts[1] == user_id:
            return candidate
        raise ArtifactNotFoundError("Output file not found")
    if parts and parts[0] == "tasks":
        _ensure_db()
        with _orm_session() as session:
            storage_paths = session.scalars(
                select(GenerationTask.storage_path).where(GenerationTask.user_id == user_id)
            ).all()
        for storage_path in storage_paths:
            try:
                candidate.relative_to(Path(storage_path).resolve())
                return candidate
            except ValueError:
                continue
    raise ArtifactNotFoundError("Output file not found")


def select_task_download(task: dict[str, Any]) -> dict[str, Any] | None:
    artifacts = task.get("artifacts", [])
    archives = [
        item
        for item in artifacts
        if item.get("kind") == "archive" and item.get("status") == "completed"
    ]
    result_artifacts = [
        item
        for item in artifacts
        if item.get("kind") != "archive"
        and item.get("counts_toward_result") is not False
        and item.get("status") == "completed"
    ]
    candidates = [*archives, *(result_artifacts if len(result_artifacts) == 1 else [])]
    for artifact in candidates:
        try:
            resolved, _ = resolve_artifact_path(task, str(artifact.get("id") or ""))
        except ArtifactNotFoundError:
            continue
        return resolved
    return None


def mark_incomplete_tasks_failed() -> None:
    _ensure_db()
    now = _now_iso()
    with _orm_session() as session:
        session.execute(
            update(GenerationTask)
            .where(GenerationTask.status.in_(("pending", "running")))
            .values(
                status="failed",
                error=func.coalesce(GenerationTask.error, "后端重启时任务未完成"),
                message="后端重启时任务未完成",
                failed_count=case(
                    (
                        GenerationTask.failed_count
                        >= GenerationTask.requested_count - GenerationTask.success_count,
                        GenerationTask.failed_count,
                    ),
                    else_=GenerationTask.requested_count - GenerationTask.success_count,
                ),
                finished_at=func.coalesce(GenerationTask.finished_at, now),
                updated_at=now,
            )
        )
