from __future__ import annotations

import base64
import hashlib
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.services import settings_store

SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
PASSWORD_ITERATIONS = 390_000
MIN_PASSWORD_LENGTH = 8
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,32}$")
ROLE_ADMIN = "admin"
ROLE_USER = "user"
VALID_ROLES = {ROLE_ADMIN, ROLE_USER}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "is_admin": row["role"] == ROLE_ADMIN,
        "is_default": bool(row["is_default"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _connect() -> sqlite3.Connection:
    return settings_store._connect()


def _password_hash(password: str, salt: bytes, iterations: int = PASSWORD_ITERATIONS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def _validate_username(username: str) -> str:
    normalized = username.strip().lower()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("用户名只能包含 3-32 位英文字母、数字或下划线")
    return normalized


def _validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"密码至少需要 {MIN_PASSWORD_LENGTH} 位")


def init_auth_schema() -> None:
    settings_store.init_db()
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_token_hash
            ON sessions (token_hash)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_user_id
            ON sessions (user_id)
            """
        )
        _ensure_admin_user(conn)


def _password_user_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM users
        WHERE password_hash != ''
        """
    ).fetchone()
    return int(row["total"])


def _admin_user_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM users
        WHERE role = ? AND password_hash != ''
        """,
        (ROLE_ADMIN,),
    ).fetchone()
    return int(row["total"])


def _ensure_admin_user(conn: sqlite3.Connection) -> None:
    if _admin_user_count(conn) > 0:
        return

    row = conn.execute(
        """
        SELECT id
        FROM users
        WHERE password_hash != ''
        ORDER BY created_at ASC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return

    conn.execute(
        """
        UPDATE users
        SET role = ?, updated_at = ?
        WHERE id = ?
        """,
        (ROLE_ADMIN, _now_iso(), row["id"]),
    )


def _copy_default_settings(conn: sqlite3.Connection, user_id: str) -> None:
    now = _now_iso()
    rows = conn.execute(
        """
        SELECT namespace, setting_name, value, value_type, is_secret
        FROM settings
        WHERE user_id = ?
        """,
        (settings_store.DEFAULT_USER_ID,),
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO settings (
                user_id, namespace, setting_name, value, value_type, is_secret, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, namespace, setting_name) DO NOTHING
            """,
            (
                user_id,
                row["namespace"],
                row["setting_name"],
                row["value"],
                row["value_type"],
                row["is_secret"],
                now,
                now,
            ),
        )


def create_user(username: str, password: str, display_name: Optional[str] = None) -> dict[str, Any]:
    init_auth_schema()
    normalized_username = _validate_username(username)
    _validate_password(password)

    salt = secrets.token_bytes(16)
    password_hash = _password_hash(password, salt)
    user_id = uuid.uuid4().hex
    now = _now_iso()
    name = (display_name or normalized_username).strip() or normalized_username

    with _connect() as conn:
        first_password_user = _password_user_count(conn) == 0
        role = ROLE_ADMIN if first_password_user and _admin_user_count(conn) == 0 else ROLE_USER
        try:
            conn.execute(
                """
                INSERT INTO users (
                    id, username, display_name, password_hash, password_salt,
                    password_iterations, role, is_default, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    user_id,
                    normalized_username,
                    name,
                    _encode(password_hash),
                    _encode(salt),
                    PASSWORD_ITERATIONS,
                    role,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError:
            raise ValueError("用户名已存在") from None

        if first_password_user:
            _copy_default_settings(conn, user_id)

        row = conn.execute(
            f"SELECT {settings_store.USER_PUBLIC_COLUMNS} FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    return _public_user(row)


def create_initial_admin(
    username: str,
    password: str,
    display_name: Optional[str] = None,
) -> tuple[dict[str, Any], bool]:
    """Create an initial admin only when no real login user exists."""
    init_auth_schema()
    normalized_username = _validate_username(username)
    _validate_password(password)

    salt = secrets.token_bytes(16)
    password_hash = _password_hash(password, salt)
    user_id = uuid.uuid4().hex
    now = _now_iso()
    name = (display_name or normalized_username).strip() or normalized_username

    with _connect() as conn:
        if _password_user_count(conn) > 0:
            row = conn.execute(
                f"""
                SELECT {settings_store.USER_PUBLIC_COLUMNS}
                FROM users
                WHERE password_hash != ''
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            return _public_user(row), False

        try:
            conn.execute(
                """
                INSERT INTO users (
                    id, username, display_name, password_hash, password_salt,
                    password_iterations, role, is_default, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    user_id,
                    normalized_username,
                    name,
                    _encode(password_hash),
                    _encode(salt),
                    PASSWORD_ITERATIONS,
                    ROLE_ADMIN,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError:
            raise ValueError("用户名已存在") from None

        _copy_default_settings(conn, user_id)
        row = conn.execute(
            f"SELECT {settings_store.USER_PUBLIC_COLUMNS} FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    return _public_user(row), True


def authenticate_user(username: str, password: str) -> Optional[dict[str, Any]]:
    init_auth_schema()
    normalized_username = username.strip().lower()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, username, display_name, role, password_hash, password_salt,
                   password_iterations, is_default, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (normalized_username,),
        ).fetchone()

    if row is None or not row["password_hash"] or not row["password_salt"]:
        return None

    try:
        salt = _decode(row["password_salt"])
        expected = _decode(row["password_hash"])
        iterations = int(row["password_iterations"] or PASSWORD_ITERATIONS)
    except Exception:
        return None

    actual = _password_hash(password, salt, iterations)
    if not secrets.compare_digest(actual, expected):
        return None

    return _public_user(row)


def list_users() -> list[dict[str, Any]]:
    init_auth_schema()
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT {settings_store.USER_PUBLIC_COLUMNS}
            FROM users
            WHERE password_hash != ''
            ORDER BY created_at ASC
            """
        ).fetchall()
    return [_public_user(row) for row in rows]


def update_user_password(user_id: str, password: str) -> dict[str, Any]:
    init_auth_schema()
    _validate_password(password)

    salt = secrets.token_bytes(16)
    password_hash = _password_hash(password, salt)
    now = _now_iso()

    with _connect() as conn:
        row = conn.execute(
            f"SELECT {settings_store.USER_PUBLIC_COLUMNS} FROM users WHERE id = ? AND password_hash != ''",
            (user_id,),
        ).fetchone()
        if row is None:
            raise ValueError("User not found")

        conn.execute(
            """
            UPDATE users
            SET password_hash = ?,
                password_salt = ?,
                password_iterations = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (_encode(password_hash), _encode(salt), PASSWORD_ITERATIONS, now, user_id),
        )
        conn.execute(
            """
            UPDATE sessions
            SET revoked_at = ?
            WHERE user_id = ? AND revoked_at IS NULL
            """,
            (now, user_id),
        )
        updated = conn.execute(
            f"SELECT {settings_store.USER_PUBLIC_COLUMNS} FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    return _public_user(updated)


def update_user_role(user_id: str, role: str) -> dict[str, Any]:
    init_auth_schema()
    next_role = (role or "").strip().lower()
    if next_role not in VALID_ROLES:
        raise ValueError("Unsupported role")

    now = _now_iso()
    with _connect() as conn:
        row = conn.execute(
            f"SELECT {settings_store.USER_PUBLIC_COLUMNS} FROM users WHERE id = ? AND password_hash != ''",
            (user_id,),
        ).fetchone()
        if row is None:
            raise ValueError("User not found")

        if row["role"] == ROLE_ADMIN and next_role != ROLE_ADMIN and _admin_user_count(conn) <= 1:
            raise ValueError("At least one admin user is required")

        conn.execute(
            """
            UPDATE users
            SET role = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_role, now, user_id),
        )
        updated = conn.execute(
            f"SELECT {settings_store.USER_PUBLIC_COLUMNS} FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    return _public_user(updated)


def create_session(user_id: str) -> tuple[str, datetime]:
    init_auth_schema()
    token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(seconds=SESSION_MAX_AGE_SECONDS)
    now = _now_iso()

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at, revoked_at)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (uuid.uuid4().hex, user_id, _hash_token(token), now, expires_at.isoformat()),
        )

    return token, expires_at


def get_user_by_session_token(token: str) -> Optional[dict[str, Any]]:
    if not token:
        return None

    init_auth_schema()
    with _connect() as conn:
        row = conn.execute(
            f"""
            SELECT u.{settings_store.USER_PUBLIC_COLUMNS.replace(", ", ", u.")}
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
              AND s.revoked_at IS NULL
              AND s.expires_at > ?
            """,
            (_hash_token(token), _now_iso()),
        ).fetchone()

    return _public_user(row) if row else None


def revoke_session(token: str) -> None:
    if not token:
        return

    init_auth_schema()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET revoked_at = ?
            WHERE token_hash = ? AND revoked_at IS NULL
            """,
            (_now_iso(), _hash_token(token)),
        )
