from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_USER_ID = "local-default"
DEFAULT_USERNAME = "local"
DEFAULT_DISPLAY_NAME = "本机用户"
RUNNINGHUB_NAMESPACE = "runninghub"
FIXED_DIGITAL_HUMAN_WORKFLOW_ID = "2003717471859294210"
USER_PUBLIC_COLUMNS = "id, username, display_name, role, is_default, created_at, updated_at"


def _root() -> Path:
    from app.core.config import ROOT

    return ROOT


def _db_path() -> Path:
    return _root() / "data" / "video_factory.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _normalize_concurrent_limit(value: Any) -> int:
    try:
        concurrent_limit = int(value or 1)
    except (TypeError, ValueError):
        concurrent_limit = 1
    return min(max(concurrent_limit, 1), 10)


def _normalize_runninghub_settings(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    source = settings or {}
    return {
        "api_key": str(source.get("api_key") or "").strip(),
        "workflow_id": FIXED_DIGITAL_HUMAN_WORKFLOW_ID,
        "concurrent_limit": _normalize_concurrent_limit(source.get("concurrent_limit")),
        "instance_type": str(source.get("instance_type") or "").strip(),
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


def init_db(config: Optional[dict[str, Any]] = None) -> None:
    with _connect() as conn:
        _ensure_users_schema(conn)
        _ensure_settings_schema(conn)
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_settings_user_namespace
            ON settings (user_id, namespace)
            """
        )

        _ensure_default_user(conn)
        _migrate_legacy_runninghub_settings(conn)
        _seed_from_config(conn, config)


def get_default_user() -> dict[str, Any]:
    init_db()

    with _connect() as conn:
        row = conn.execute(
            f"SELECT {USER_PUBLIC_COLUMNS} FROM users WHERE id = ?",
            (DEFAULT_USER_ID,),
        ).fetchone()

    return dict(row)


def _get_namespace_settings(user_id: str, namespace: str) -> dict[str, str]:
    init_db()

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT setting_name, value
            FROM settings
            WHERE user_id = ? AND namespace = ?
            """,
            (user_id, namespace),
        ).fetchall()

    return {row["setting_name"]: row["value"] for row in rows}


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

    with _connect() as conn:
        _upsert_setting(
            conn,
            user_id=user_id,
            namespace=RUNNINGHUB_NAMESPACE,
            setting_name="api_key",
            value=next_settings["api_key"],
            is_secret=True,
        )
        _upsert_setting(
            conn,
            user_id=user_id,
            namespace=RUNNINGHUB_NAMESPACE,
            setting_name="concurrent_limit",
            value=next_settings["concurrent_limit"],
            value_type="integer",
        )
        _upsert_setting(
            conn,
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
        "workflow_id": FIXED_DIGITAL_HUMAN_WORKFLOW_ID,
        "workflow_fixed": True,
        "concurrent_limit": normalized["concurrent_limit"],
        "instance_type": normalized["instance_type"],
    }
