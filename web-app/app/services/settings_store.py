from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError as SqlAlchemyIntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.core.config import app_config
from app.db.engine import get_database_url, sqlite_url_for_path
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


def _root() -> Path:
    from app.core.config import ROOT

    return ROOT


def _db_path() -> Path:
    return _root() / "data" / "video_factory.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _orm_database_url() -> str:
    if os.getenv("DATABASE_URL", "").strip():
        return get_database_url()
    configured_url = str((app_config.get("database") or {}).get("url") or "").strip()
    if configured_url:
        return configured_url
    return sqlite_url_for_path(_db_path())


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


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _ensure_default_user(conn: sqlite3.Connection) -> None:
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO users (id, username, display_name, is_default, created_at, updated_at)
        VALUES (?, ?, ?, 1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            is_default = 1,
            updated_at = excluded.updated_at
        """,
        (DEFAULT_USER_ID, DEFAULT_USERNAME, DEFAULT_DISPLAY_NAME, now, now),
    )


def _upsert_setting(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    namespace: str,
    setting_name: str,
    value: Any,
    value_type: str = "string",
    is_secret: bool = False,
) -> None:
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO settings (
            user_id, namespace, setting_name, value, value_type, is_secret, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, namespace, setting_name) DO UPDATE SET
            value = excluded.value,
            value_type = excluded.value_type,
            is_secret = excluded.is_secret,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            namespace,
            setting_name,
            str(value or ""),
            value_type,
            1 if is_secret else 0,
            now,
            now,
        ),
    )


def _migrate_legacy_runninghub_settings(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "runninghub_settings"):
        return

    row = conn.execute(
        """
        SELECT api_key, concurrent_limit, instance_type
        FROM runninghub_settings
        WHERE id = 1
        """
    ).fetchone()
    if row:
        settings = _normalize_runninghub_settings(dict(row))
        _upsert_setting(
            conn,
            user_id=DEFAULT_USER_ID,
            namespace=RUNNINGHUB_NAMESPACE,
            setting_name="api_key",
            value=settings["api_key"],
            is_secret=True,
        )
        _upsert_setting(
            conn,
            user_id=DEFAULT_USER_ID,
            namespace=RUNNINGHUB_NAMESPACE,
            setting_name="concurrent_limit",
            value=settings["concurrent_limit"],
            value_type="integer",
        )
        _upsert_setting(
            conn,
            user_id=DEFAULT_USER_ID,
            namespace=RUNNINGHUB_NAMESPACE,
            setting_name="instance_type",
            value=settings["instance_type"],
        )

    conn.execute("DROP TABLE runninghub_settings")


def _seed_from_config(conn: sqlite3.Connection, config: Optional[dict[str, Any]]) -> None:
    existing = conn.execute(
        """
        SELECT 1
        FROM settings
        WHERE user_id = ? AND namespace = ?
        LIMIT 1
        """,
        (DEFAULT_USER_ID, RUNNINGHUB_NAMESPACE),
    ).fetchone()
    if existing:
        return

    config = config or {}
    runninghub_config = config.get("runninghub") or {}
    settings = _normalize_runninghub_settings(
        {
            "api_key": runninghub_config.get("api_key"),
            "concurrent_limit": runninghub_config.get("concurrent_limit"),
            "instance_type": runninghub_config.get("instance_type"),
        }
    )
    _upsert_setting(
        conn,
        user_id=DEFAULT_USER_ID,
        namespace=RUNNINGHUB_NAMESPACE,
        setting_name="api_key",
        value=settings["api_key"],
        is_secret=True,
    )
    _upsert_setting(
        conn,
        user_id=DEFAULT_USER_ID,
        namespace=RUNNINGHUB_NAMESPACE,
        setting_name="concurrent_limit",
        value=settings["concurrent_limit"],
        value_type="integer",
    )
    _upsert_setting(
        conn,
        user_id=DEFAULT_USER_ID,
        namespace=RUNNINGHUB_NAMESPACE,
        setting_name="instance_type",
        value=settings["instance_type"],
    )


def _seed_llm_from_config(conn: sqlite3.Connection, config: Optional[dict[str, Any]]) -> None:
    existing = conn.execute(
        """
        SELECT 1
        FROM settings
        WHERE user_id = ? AND namespace = ?
        LIMIT 1
        """,
        (DEFAULT_USER_ID, LLM_NAMESPACE),
    ).fetchone()
    if existing:
        return

    llm_config = (config or {}).get("llm") or {}
    settings = _normalize_llm_settings(llm_config)
    _upsert_setting(
        conn,
        user_id=DEFAULT_USER_ID,
        namespace=LLM_NAMESPACE,
        setting_name="base_url",
        value=settings["base_url"],
    )
    _upsert_setting(
        conn,
        user_id=DEFAULT_USER_ID,
        namespace=LLM_NAMESPACE,
        setting_name="api_key",
        value=settings["api_key"],
        is_secret=True,
    )
    _upsert_setting(
        conn,
        user_id=DEFAULT_USER_ID,
        namespace=LLM_NAMESPACE,
        setting_name="model",
        value=settings["model"],
    )


def _create_settings_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            namespace TEXT NOT NULL,
            setting_name TEXT NOT NULL,
            value TEXT NOT NULL DEFAULT '',
            value_type TEXT NOT NULL DEFAULT 'string',
            is_secret INTEGER NOT NULL DEFAULT 0 CHECK (is_secret IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE (user_id, namespace, setting_name)
        )
        """
    )


def _ensure_users_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
            password_hash TEXT NOT NULL DEFAULT '',
            password_salt TEXT NOT NULL DEFAULT '',
            password_iterations INTEGER NOT NULL DEFAULT 0,
            is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    migrations = {
        "role": "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'",
        "password_hash": "ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''",
        "password_salt": "ALTER TABLE users ADD COLUMN password_salt TEXT NOT NULL DEFAULT ''",
        "password_iterations": "ALTER TABLE users ADD COLUMN password_iterations INTEGER NOT NULL DEFAULT 0",
    }
    for column, statement in migrations.items():
        if column not in columns:
            conn.execute(statement)


def _ensure_settings_schema(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "settings"):
        _create_settings_table(conn)
        return

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    if "setting_name" in columns:
        return

    if "key" not in columns:
        conn.execute("DROP TABLE settings")
        _create_settings_table(conn)
        return

    conn.execute("ALTER TABLE settings RENAME TO settings_legacy_key")
    _create_settings_table(conn)
    conn.execute(
        """
        INSERT INTO settings (
            id, user_id, namespace, setting_name, value, value_type, is_secret, created_at, updated_at
        )
        SELECT id, user_id, namespace, "key", value, value_type, is_secret, created_at, updated_at
        FROM settings_legacy_key
        """
    )
    conn.execute("DROP TABLE settings_legacy_key")


def _ensure_subtitle_replacements_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subtitle_replacements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL UNIQUE,
            replacement TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _ensure_bgm_tracks_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bgm_tracks (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            duration REAL NOT NULL DEFAULT 0,
            file_size INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bgm_tracks_user ON bgm_tracks (user_id)"
    )


def init_db(config: Optional[dict[str, Any]] = None) -> None:
    database_url = _orm_database_url()
    if not make_url(database_url).drivername.startswith("sqlite"):
        return
    with _connect() as conn:
        _ensure_users_schema(conn)
        _ensure_settings_schema(conn)
        _ensure_subtitle_replacements_schema(conn)
        _ensure_bgm_tracks_schema(conn)
        from app.services import task_store

        task_store.ensure_schema(conn)
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_settings_user_namespace
            ON settings (user_id, namespace)
            """
        )

        _ensure_default_user(conn)
        _migrate_legacy_runninghub_settings(conn)
        _seed_from_config(conn, config)
        _seed_llm_from_config(conn, config)


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
    except (SqlAlchemyIntegrityError, sqlite3.IntegrityError) as exc:
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
    except (SqlAlchemyIntegrityError, sqlite3.IntegrityError) as exc:
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
