from __future__ import annotations

import base64
import hashlib
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from contextlib import AbstractContextManager
from typing import Any, Optional

from app.services import settings_store

SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
PASSWORD_ITERATIONS = 390_000
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,32}$")
ROLE_ADMIN = "admin"
ROLE_USER = "user"
VALID_ROLES = {ROLE_ADMIN, ROLE_USER}

LOGIN_IP_MAX_ATTEMPTS = 20
LOGIN_IP_WINDOW_SECONDS = 60
LOGIN_USERNAME_MAX_ATTEMPTS = 10
LOGIN_USERNAME_WINDOW_SECONDS = 300
REGISTER_IP_MAX_ATTEMPTS = 5
REGISTER_IP_WINDOW_SECONDS = 3600
REGISTER_USERNAME_MAX_ATTEMPTS = 3
REGISTER_USERNAME_WINDOW_SECONDS = 3600
MAX_RATE_LIMIT_KEYS = 4096
SESSION_CLEANUP_INTERVAL_SECONDS = 300
MAX_SESSIONS_PER_USER = 10

_DUMMY_PASSWORD_SALT = b"video-factory-dummy-salt"
_rate_limit_lock = threading.RLock()
_rate_limit_buckets: dict[str, deque[float]] = {}
_session_cleanup_lock = threading.Lock()
_last_session_cleanup_at = 0.0


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, int(retry_after))
        super().__init__("Too many authentication attempts")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return max(minimum, int(value))
    except ValueError:
        return default


def is_registration_enabled() -> bool:
    return _env_bool("VF_AUTH_REGISTRATION_ENABLED", False)


def allow_first_user_admin() -> bool:
    return _env_bool("VF_AUTH_ALLOW_FIRST_USER_ADMIN", False)


def get_session_max_age_seconds() -> int:
    return _env_int("VF_AUTH_SESSION_MAX_AGE_SECONDS", SESSION_MAX_AGE_SECONDS)


def get_max_sessions_per_user() -> int:
    return _env_int("VF_AUTH_MAX_SESSIONS_PER_USER", MAX_SESSIONS_PER_USER)


def cookie_secure_override() -> Optional[bool]:
    value = os.getenv("VF_AUTH_COOKIE_SECURE")
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def cookie_secure() -> bool:
    override = cookie_secure_override()
    return True if override is None else override


def cookie_samesite() -> str:
    value = (os.getenv("VF_AUTH_COOKIE_SAMESITE") or "lax").strip().lower()
    return value if value in {"lax", "strict", "none"} else "lax"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _rate_limit_key(scope: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
    return f"{scope}:{digest}"


def _prune_rate_limit_buckets(now: float) -> None:
    expired_keys = [key for key, bucket in _rate_limit_buckets.items() if not bucket]
    for key in expired_keys:
        _rate_limit_buckets.pop(key, None)

    while len(_rate_limit_buckets) > MAX_RATE_LIMIT_KEYS:
        oldest_key = min(
            _rate_limit_buckets,
            key=lambda key: _rate_limit_buckets[key][-1] if _rate_limit_buckets[key] else now,
        )
        _rate_limit_buckets.pop(oldest_key, None)


def _consume_rate_limit(key: str, maximum: int, window_seconds: int, now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    with _rate_limit_lock:
        bucket = _rate_limit_buckets.setdefault(key, deque())
        cutoff = current - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= maximum:
            retry_after = math.ceil(window_seconds - (current - bucket[0]))
            _prune_rate_limit_buckets(current)
            raise RateLimitExceeded(retry_after)

        bucket.append(current)
        _prune_rate_limit_buckets(current)


def _clear_rate_limit(scope: str, value: str) -> None:
    with _rate_limit_lock:
        _rate_limit_buckets.pop(_rate_limit_key(scope, value), None)


def reset_rate_limits() -> None:
    """Clear process-local authentication throttles, primarily for tests."""
    with _rate_limit_lock:
        _rate_limit_buckets.clear()


def check_login_rate_limit(client_ip: str, username: str) -> None:
    normalized = username.strip().lower()
    _consume_rate_limit(
        _rate_limit_key("login-ip", client_ip or "unknown"),
        LOGIN_IP_MAX_ATTEMPTS,
        LOGIN_IP_WINDOW_SECONDS,
    )
    _consume_rate_limit(
        _rate_limit_key("login-user", normalized),
        LOGIN_USERNAME_MAX_ATTEMPTS,
        LOGIN_USERNAME_WINDOW_SECONDS,
    )


def clear_login_rate_limit(username: str) -> None:
    _clear_rate_limit("login-user", username.strip().lower())


def check_registration_rate_limit(client_ip: str, username: str) -> None:
    normalized = username.strip().lower()
    _consume_rate_limit(
        _rate_limit_key("register-ip", client_ip or "unknown"),
        REGISTER_IP_MAX_ATTEMPTS,
        REGISTER_IP_WINDOW_SECONDS,
    )
    _consume_rate_limit(
        _rate_limit_key("register-user", normalized),
        REGISTER_USERNAME_MAX_ATTEMPTS,
        REGISTER_USERNAME_WINDOW_SECONDS,
    )


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


def _connect() -> AbstractContextManager[sqlite3.Connection]:
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
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"密码不能超过 {MAX_PASSWORD_LENGTH} 位")


def init_auth_schema() -> None:
    global _last_session_cleanup_at

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
        now_monotonic = time.monotonic()
        with _session_cleanup_lock:
            should_cleanup = (
                now_monotonic - _last_session_cleanup_at >= SESSION_CLEANUP_INTERVAL_SECONDS
            )
            if should_cleanup:
                _last_session_cleanup_at = now_monotonic
        if should_cleanup:
            _delete_expired_sessions(conn)


def _delete_expired_sessions(conn: sqlite3.Connection) -> None:
    now = _now_iso()
    revoked_cutoff = (_now() - timedelta(days=1)).isoformat()
    conn.execute(
        """
        DELETE FROM sessions
        WHERE expires_at <= ?
           OR (revoked_at IS NOT NULL AND revoked_at <= ?)
        """,
        (now, revoked_cutoff),
    )


def cleanup_sessions(force: bool = False) -> None:
    global _last_session_cleanup_at

    init_auth_schema()
    if force:
        with _session_cleanup_lock:
            _last_session_cleanup_at = 0.0
    with _connect() as conn:
        _delete_expired_sessions(conn)
    with _session_cleanup_lock:
        _last_session_cleanup_at = time.monotonic()


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
    if not allow_first_user_admin():
        return
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
        role = (
            ROLE_ADMIN
            if allow_first_user_admin() and first_password_user and _admin_user_count(conn) == 0
            else ROLE_USER
        )
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
        _password_hash(password, _DUMMY_PASSWORD_SALT, PASSWORD_ITERATIONS)
        return None

    try:
        salt = _decode(row["password_salt"])
        expected = _decode(row["password_hash"])
        iterations = int(row["password_iterations"] or PASSWORD_ITERATIONS)
    except Exception:
        _password_hash(password, _DUMMY_PASSWORD_SALT, PASSWORD_ITERATIONS)
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
    expires_at = _now() + timedelta(seconds=get_session_max_age_seconds())
    now = _now_iso()

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at, revoked_at)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (uuid.uuid4().hex, user_id, _hash_token(token), now, expires_at.isoformat()),
        )
        conn.execute(
            """
            DELETE FROM sessions
            WHERE user_id = ?
              AND id NOT IN (
                  SELECT id
                  FROM sessions
                  WHERE user_id = ?
                  ORDER BY created_at DESC
                  LIMIT ?
              )
            """,
            (user_id, user_id, get_max_sessions_per_user()),
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
