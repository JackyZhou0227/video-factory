from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError as SqlAlchemyIntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.core.config import app_config
from app.db.engine import require_postgresql_url
from app.db.models import BgmTrack, Setting, SubtitleReplacement, User
from app.db.session import get_session_factory, session_scope as orm_session_scope

DEFAULT_USER_ID = "local-default"
DEFAULT_USERNAME = "local"
DEFAULT_DISPLAY_NAME = "本机用户"
RUNNINGHUB_NAMESPACE = "runninghub"
LLM_NAMESPACE = "llm"
FIXED_DIGITAL_HUMAN_WORKFLOW_ID = "2003717471859294210"
DEFAULT_RUNNINGHUB_INSTANCE_TYPE = "plus"
USER_PUBLIC_COLUMNS = "id, username, display_name, role, is_default, created_at, updated_at"
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
MAX_SUBTITLE_REPLACEMENTS = 30
MAX_SUBTITLE_REPLACEMENT_LENGTH = 80
MAX_BGM_TRACKS_PER_USER = 20
BGM_TRACK_COLUMNS = "id, user_id, name, relative_path, duration, file_size, created_at, updated_at"

class SubtitleReplacementNotFoundError(LookupError):
    pass


class SubtitleReplacementConflictError(ValueError):
    pass


class BgmTrackNotFoundError(LookupError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _orm_database_url() -> str:
    return require_postgresql_url(app_config)


@contextmanager
def _orm_session() -> Iterator[OrmSession]:
    with orm_session_scope(get_session_factory(_orm_database_url())) as session:
        yield session


def _public_user_record(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_default": user.is_default,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }

def _subtitle_replacement_record(replacement: SubtitleReplacement) -> dict[str, Any]:
    return {
        "id": replacement.id,
        "source": replacement.source,
        "replacement": replacement.replacement,
        "created_at": replacement.created_at,
        "updated_at": replacement.updated_at,
    }


def _bgm_track_record(track: BgmTrack) -> dict[str, Any]:
    return {
        column: getattr(track, column)
        for column in BGM_TRACK_COLUMNS.split(", ")
    }


def _orm_upsert_setting(
    session: OrmSession,
    *,
    user_id: str,
    namespace: str,
    setting_name: str,
    value: Any,
    value_type: str = "string",
    is_secret: bool = False,
) -> None:
    setting = session.scalar(
        select(Setting).where(
            Setting.user_id == user_id,
            Setting.namespace == namespace,
            Setting.setting_name == setting_name,
        )
    )
    now = _now_iso()
    normalized_value = str(value or "")
    if setting is None:
        session.add(
            Setting(
                user_id=user_id,
                namespace=namespace,
                setting_name=setting_name,
                value=normalized_value,
                value_type=value_type,
                is_secret=1 if is_secret else 0,
                created_at=now,
                updated_at=now,
            )
        )
        return

    setting.value = normalized_value
    setting.value_type = value_type
    setting.is_secret = 1 if is_secret else 0
    setting.updated_at = now


def _normalize_concurrent_limit(value: Any) -> int:
    try:
        concurrent_limit = int(value or 1)
    except (TypeError, ValueError):
        concurrent_limit = 1
    return min(max(concurrent_limit, 1), 10)


def _normalize_runninghub_settings(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    source = settings or {}
    raw_instance_type = source.get("instance_type")
    return {
        "api_key": str(source.get("api_key") or "").strip(),
        "workflow_id": FIXED_DIGITAL_HUMAN_WORKFLOW_ID,
        "concurrent_limit": _normalize_concurrent_limit(source.get("concurrent_limit")),
        "instance_type": DEFAULT_RUNNINGHUB_INSTANCE_TYPE if raw_instance_type is None else str(raw_instance_type).strip(),
    }


def _normalize_llm_settings(settings: Optional[dict[str, Any]] = None) -> dict[str, str]:
    source = settings or {}
    return {
        "base_url": str(source.get("base_url") or DEFAULT_LLM_BASE_URL).strip().rstrip("/"),
        "api_key": str(source.get("api_key") or "").strip(),
        "model": str(source.get("model") or "").strip(),
    }


def mask_api_key(api_key: str) -> str:
    value = str(api_key or "")
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * max(len(value) - 8, 4)}{value[-4:]}"


def _ensure_default_user(session: OrmSession) -> bool:
    now = _now_iso()
    user = session.get(User, DEFAULT_USER_ID)
    if user is None:
        session.add(
            User(
                id=DEFAULT_USER_ID,
                username=DEFAULT_USERNAME,
                display_name=DEFAULT_DISPLAY_NAME,
                role="user",
                password_hash="",
                password_salt="",
                password_iterations=0,
                is_default=1,
                created_at=now,
                updated_at=now,
            )
        )
        return True

    if not user.is_default:
        user.is_default = 1
        user.updated_at = now
    return False


def _namespace_has_settings(session: OrmSession, namespace: str) -> bool:
    count = session.scalar(
        select(func.count())
        .select_from(Setting)
        .where(Setting.user_id == DEFAULT_USER_ID, Setting.namespace == namespace)
    )
    return bool(count)


def _seed_runninghub_settings(session: OrmSession) -> None:
    if _namespace_has_settings(session, RUNNINGHUB_NAMESPACE):
        return

    settings = _normalize_runninghub_settings({})
    _orm_upsert_setting(
        session,
        user_id=DEFAULT_USER_ID,
        namespace=RUNNINGHUB_NAMESPACE,
        setting_name="api_key",
        value=settings["api_key"],
        is_secret=True,
    )
    _orm_upsert_setting(
        session,
        user_id=DEFAULT_USER_ID,
        namespace=RUNNINGHUB_NAMESPACE,
        setting_name="concurrent_limit",
        value=settings["concurrent_limit"],
        value_type="integer",
    )
    _orm_upsert_setting(
        session,
        user_id=DEFAULT_USER_ID,
        namespace=RUNNINGHUB_NAMESPACE,
        setting_name="instance_type",
        value=settings["instance_type"],
    )


def _seed_llm_from_config(
    session: OrmSession,
    config: Optional[dict[str, Any]],
) -> None:
    if _namespace_has_settings(session, LLM_NAMESPACE):
        return

    llm_config = (config or {}).get("llm") or {}
    settings = _normalize_llm_settings(llm_config)
    _orm_upsert_setting(
        session,
        user_id=DEFAULT_USER_ID,
        namespace=LLM_NAMESPACE,
        setting_name="base_url",
        value=settings["base_url"],
    )
    _orm_upsert_setting(
        session,
        user_id=DEFAULT_USER_ID,
        namespace=LLM_NAMESPACE,
        setting_name="api_key",
        value=settings["api_key"],
        is_secret=True,
    )
    _orm_upsert_setting(
        session,
        user_id=DEFAULT_USER_ID,
        namespace=LLM_NAMESPACE,
        setting_name="model",
        value=settings["model"],
    )


def init_db(config: Optional[dict[str, Any]] = None) -> None:
    require_postgresql_url(app_config)
    with _orm_session() as session:
        _ensure_default_user(session)
        _seed_runninghub_settings(session)
        _seed_llm_from_config(session, config)


def get_default_user() -> dict[str, Any]:
    init_db()
    with _orm_session() as session:
        user = session.get(User, DEFAULT_USER_ID)
    return _public_user_record(user)

def _get_namespace_settings(user_id: str, namespace: str) -> dict[str, str]:
    init_db()
    with _orm_session() as session:
        rows = session.scalars(
            select(Setting).where(
                Setting.user_id == user_id,
                Setting.namespace == namespace,
            )
        ).all()
    return {row.setting_name: row.value for row in rows}

def get_runninghub_settings(user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
    values = _get_namespace_settings(user_id, RUNNINGHUB_NAMESPACE)
    return _normalize_runninghub_settings(
        {
            "api_key": values.get("api_key"),
            "concurrent_limit": values.get("concurrent_limit"),
            "instance_type": values.get("instance_type"),
        }
    )


def update_runninghub_settings(
    *,
    user_id: str = DEFAULT_USER_ID,
    api_key: Optional[str] = None,
    concurrent_limit: Optional[int] = None,
    instance_type: Optional[str] = None,
) -> dict[str, Any]:
    current = get_runninghub_settings(user_id)
    next_settings = _normalize_runninghub_settings(
        {
            "api_key": current["api_key"] if api_key is None else api_key,
            "concurrent_limit": current["concurrent_limit"] if concurrent_limit is None else concurrent_limit,
            "instance_type": current["instance_type"] if instance_type is None else instance_type,
        }
    )

    with _orm_session() as session:
        _orm_upsert_setting(
            session,
            user_id=user_id,
            namespace=RUNNINGHUB_NAMESPACE,
            setting_name="api_key",
            value=next_settings["api_key"],
            is_secret=True,
        )
        _orm_upsert_setting(
            session,
            user_id=user_id,
            namespace=RUNNINGHUB_NAMESPACE,
            setting_name="concurrent_limit",
            value=next_settings["concurrent_limit"],
            value_type="integer",
        )
        _orm_upsert_setting(
            session,
            user_id=user_id,
            namespace=RUNNINGHUB_NAMESPACE,
            setting_name="instance_type",
            value=next_settings["instance_type"],
        )

    return next_settings

def public_runninghub_settings(
    settings: Optional[dict[str, Any]] = None,
    user: Optional[dict[str, Any]] = None,
    user_id: str = DEFAULT_USER_ID,
) -> dict[str, Any]:
    normalized = _normalize_runninghub_settings(settings or get_runninghub_settings(user_id))
    api_key = normalized["api_key"]
    public_user = user or get_default_user()

    return {
        "user": {
            "id": public_user["id"],
            "username": public_user["username"],
            "display_name": public_user["display_name"],
        },
        "api_key_configured": bool(api_key),
        "api_key_masked": mask_api_key(api_key),
        "concurrent_limit": normalized["concurrent_limit"],
        "instance_type": normalized["instance_type"],
    }


def get_llm_settings(user_id: str = DEFAULT_USER_ID) -> dict[str, str]:
    values = _get_namespace_settings(user_id, LLM_NAMESPACE)
    return _normalize_llm_settings(values)


def update_llm_settings(
    *,
    user_id: str = DEFAULT_USER_ID,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    clear_api_key: bool = False,
) -> dict[str, str]:
    current = get_llm_settings(user_id)
    next_api_key = current["api_key"]
    if clear_api_key:
        next_api_key = ""
    elif api_key is not None:
        next_api_key = api_key

    next_settings = _normalize_llm_settings(
        {
            "base_url": current["base_url"] if base_url is None else base_url,
            "api_key": next_api_key,
            "model": current["model"] if model is None else model,
        }
    )

    with _orm_session() as session:
        _orm_upsert_setting(
            session,
            user_id=user_id,
            namespace=LLM_NAMESPACE,
            setting_name="base_url",
            value=next_settings["base_url"],
        )
        _orm_upsert_setting(
            session,
            user_id=user_id,
            namespace=LLM_NAMESPACE,
            setting_name="api_key",
            value=next_settings["api_key"],
            is_secret=True,
        )
        _orm_upsert_setting(
            session,
            user_id=user_id,
            namespace=LLM_NAMESPACE,
            setting_name="model",
            value=next_settings["model"],
        )

    return next_settings

def public_llm_settings(
    settings: Optional[dict[str, Any]] = None,
    user_id: str = DEFAULT_USER_ID,
) -> dict[str, Any]:
    normalized = _normalize_llm_settings(settings or get_llm_settings(user_id))
    api_key = normalized["api_key"]
    return {
        "base_url": normalized["base_url"],
        "model": normalized["model"],
        "api_key_configured": bool(api_key),
        "api_key_masked": mask_api_key(api_key),
    }


def normalize_subtitle_replacement(source: Any, replacement: Any) -> tuple[str, str]:
    normalized_source = str(source or "").strip()
    normalized_replacement = str(replacement or "").strip()
    if not normalized_source or not normalized_replacement:
        raise ValueError("字幕替换规则需要填写原词和替换词")
    if "\n" in normalized_source or "\r" in normalized_source:
        raise ValueError("字幕替换规则不能包含换行")
    if "\n" in normalized_replacement or "\r" in normalized_replacement:
        raise ValueError("字幕替换规则不能包含换行")
    if (
        len(normalized_source) > MAX_SUBTITLE_REPLACEMENT_LENGTH
        or len(normalized_replacement) > MAX_SUBTITLE_REPLACEMENT_LENGTH
    ):
        raise ValueError(
            f"字幕替换规则的词语长度不能超过 {MAX_SUBTITLE_REPLACEMENT_LENGTH} 个字符"
        )
    if normalized_source == normalized_replacement:
        raise ValueError("字幕替换规则的原词和替换词不能相同")
    return normalized_source, normalized_replacement


def list_subtitle_replacements() -> list[dict[str, Any]]:
    init_db()
    with _orm_session() as session:
        rows = session.scalars(
            select(SubtitleReplacement).order_by(SubtitleReplacement.id.asc())
        ).all()
    return [_subtitle_replacement_record(row) for row in rows]

def create_subtitle_replacement(*, source: Any, replacement: Any) -> dict[str, Any]:
    normalized_source, normalized_replacement = normalize_subtitle_replacement(source, replacement)
    init_db()
    now = _now_iso()
    try:
        with _orm_session() as session:
            count = session.scalar(select(func.count()).select_from(SubtitleReplacement)) or 0
            if count >= MAX_SUBTITLE_REPLACEMENTS:
                raise ValueError(f"字幕替换规则最多添加 {MAX_SUBTITLE_REPLACEMENTS} 条")
            row = SubtitleReplacement(
                source=normalized_source,
                replacement=normalized_replacement,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            record = _subtitle_replacement_record(row)
    except SqlAlchemyIntegrityError as exc:
        raise SubtitleReplacementConflictError(f"字幕原词“{normalized_source}”已存在") from exc
    return record
def update_subtitle_replacement(
    replacement_id: int,
    *,
    source: Any,
    replacement: Any,
) -> dict[str, Any]:
    if replacement_id < 1:
        raise SubtitleReplacementNotFoundError("字幕替换规则不存在")
    normalized_source, normalized_replacement = normalize_subtitle_replacement(source, replacement)
    init_db()
    try:
        with _orm_session() as session:
            row = session.get(SubtitleReplacement, replacement_id)
            if row is None:
                raise SubtitleReplacementNotFoundError("字幕替换规则不存在")
            row.source = normalized_source
            row.replacement = normalized_replacement
            row.updated_at = _now_iso()
            session.flush()
            record = _subtitle_replacement_record(row)
    except SqlAlchemyIntegrityError as exc:
        raise SubtitleReplacementConflictError(f"字幕原词“{normalized_source}”已存在") from exc
    return record

def delete_subtitle_replacement(replacement_id: int) -> None:
    if replacement_id < 1:
        raise SubtitleReplacementNotFoundError("字幕替换规则不存在")
    init_db()
    with _orm_session() as session:
        row = session.get(SubtitleReplacement, replacement_id)
        if row is None:
            raise SubtitleReplacementNotFoundError("字幕替换规则不存在")
        session.delete(row)

def _fetch_bgm_track(session: OrmSession, bgm_id: str, user_id: str) -> Optional[BgmTrack]:
    return session.scalar(
        select(BgmTrack).where(
            BgmTrack.id == bgm_id,
            BgmTrack.user_id == user_id,
        )
    )

def list_bgm_tracks(user_id: str) -> list[dict[str, Any]]:
    init_db()
    with _orm_session() as session:
        rows = session.scalars(
            select(BgmTrack)
            .where(BgmTrack.user_id == user_id)
            .order_by(BgmTrack.created_at.asc())
        ).all()
    return [_bgm_track_record(row) for row in rows]

def get_bgm_track(user_id: str, bgm_id: str) -> dict[str, Any]:
    init_db()
    with _orm_session() as session:
        row = _fetch_bgm_track(session, bgm_id, user_id)
        if row is None:
            raise BgmTrackNotFoundError("背景音乐不存在")
        record = _bgm_track_record(row)
    return record

def create_bgm_track(
    *,
    user_id: str,
    bgm_id: str,
    name: str,
    relative_path: str,
    duration: float,
    file_size: int,
) -> dict[str, Any]:
    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise ValueError("背景音乐名称不能为空")
    normalized_path = str(relative_path or "").strip()
    if not normalized_path:
        raise ValueError("背景音乐文件路径不能为空")
    init_db()
    now = _now_iso()
    with _orm_session() as session:
        count = session.scalar(
            select(func.count()).select_from(BgmTrack).where(BgmTrack.user_id == user_id)
        ) or 0
        if count >= MAX_BGM_TRACKS_PER_USER:
            raise ValueError(f"每个用户最多保存 {MAX_BGM_TRACKS_PER_USER} 个背景音乐")
        row = BgmTrack(
            id=bgm_id,
            user_id=user_id,
            name=normalized_name,
            relative_path=normalized_path,
            duration=float(duration),
            file_size=int(file_size),
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        record = _bgm_track_record(row)
    return record

def delete_bgm_track(user_id: str, bgm_id: str) -> dict[str, Any]:
    init_db()
    with _orm_session() as session:
        row = _fetch_bgm_track(session, bgm_id, user_id)
        if row is None:
            raise BgmTrackNotFoundError("背景音乐不存在")
        record = _bgm_track_record(row)
        session.delete(row)
    return record
