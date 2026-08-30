from __future__ import annotations

import base64
import hashlib
import math
import os
import re
import secrets
import threading
import time
import uuid
from collections import deque
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Session as DbSession
from app.db.models import Organization, Setting, User
from app.services import settings_store

SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
PASSWORD_ITERATIONS = 390_000
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,32}$")
ROLE_ADMIN = "admin"
ROLE_ORG_ADMIN = "org_admin"
ROLE_USER = "user"
VALID_ROLES = {ROLE_ADMIN, ROLE_ORG_ADMIN, ROLE_USER}
STATUS_ACTIVE = "active"
STATUS_PENDING = "pending"
VALID_STATUSES = {STATUS_ACTIVE, STATUS_PENDING}

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
    return _auth_flag("registration_enabled", False)


def allow_first_user_admin() -> bool:
    return _auth_flag("allow_first_user_admin", False)


def get_session_max_age_seconds() -> int:
    return _auth_int("session_max_age_seconds", SESSION_MAX_AGE_SECONDS)


def get_max_sessions_per_user() -> int:
    return _auth_int("max_sessions_per_user", MAX_SESSIONS_PER_USER)


def cookie_secure_override() -> Optional[bool]:
    # config.yaml 的 auth.cookie_secure；未配置返回 None，按请求协议判断
    value = _auth_setting("cookie_secure")
    return value if isinstance(value, bool) else None


def cookie_secure() -> bool:
    override = cookie_secure_override()
    return True if override is None else override


def cookie_samesite() -> str:
    value = str(_auth_setting("cookie_samesite") or "").strip().lower()
    return value if value in {"lax", "strict", "none"} else "lax"


def _auth_setting(name: str) -> Any:
    from app.core.config import app_config

    auth_cfg = app_config.get("auth")
    return auth_cfg.get(name) if isinstance(auth_cfg, dict) else None


def _auth_flag(name: str, default: bool) -> bool:
    value = _auth_setting(name)
    return value if isinstance(value, bool) else default


def _auth_int(name: str, default: int) -> int:
    value = _auth_setting(name)
    if isinstance(value, int) and value > 0:
        return value
    return default


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


def _public_user(user: User, org_name: Optional[str] = None) -> dict[str, Any]:
    role = user.role
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": role,
        "is_admin": role == ROLE_ADMIN,
        "is_org_admin": role == ROLE_ORG_ADMIN,
        "status": user.status if hasattr(user, "status") else STATUS_ACTIVE,
        "org_id": user.org_id if hasattr(user, "org_id") else None,
        "org_name": org_name,
        "is_default": bool(user.is_default),
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def _org_names_by_id(session: OrmSession) -> dict[str, str]:
    rows = session.execute(select(Organization.id, Organization.name)).all()
    return {row[0]: row[1] for row in rows}


def _org_name_for(session: OrmSession, org_id: Optional[str]) -> Optional[str]:
    if not org_id:
        return None
    return session.scalar(select(Organization.name).where(Organization.id == org_id))


def _orm_session() -> AbstractContextManager[OrmSession]:
    return settings_store._orm_session()


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
    with _orm_session() as session:
        _ensure_admin_user(session)

    now_monotonic = time.monotonic()
    with _session_cleanup_lock:
        should_cleanup = (
            now_monotonic - _last_session_cleanup_at >= SESSION_CLEANUP_INTERVAL_SECONDS
        )
        if should_cleanup:
            _last_session_cleanup_at = now_monotonic
    if should_cleanup:
        with _orm_session() as session:
            _delete_expired_sessions(session)


def _delete_expired_sessions(session: OrmSession) -> None:
    now = _now_iso()
    revoked_cutoff = (_now() - timedelta(days=1)).isoformat()
    session.execute(
        delete(DbSession).where(
            (DbSession.expires_at <= now)
            | (
                DbSession.revoked_at.is_not(None)
                & (DbSession.revoked_at <= revoked_cutoff)
            )
        )
    )


def cleanup_sessions(force: bool = False) -> None:
    global _last_session_cleanup_at

    init_auth_schema()
    if force:
        with _session_cleanup_lock:
            _last_session_cleanup_at = 0.0
    with _orm_session() as session:
        _delete_expired_sessions(session)
    with _session_cleanup_lock:
        _last_session_cleanup_at = time.monotonic()


def _password_user_count(session: OrmSession) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(User).where(User.password_hash != "")
        )
        or 0
    )


def _admin_user_count(session: OrmSession) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == ROLE_ADMIN, User.password_hash != "")
        )
        or 0
    )


def _ensure_admin_user(session: OrmSession) -> None:
    if not allow_first_user_admin() or _admin_user_count(session) > 0:
        return

    user = session.scalar(
        select(User)
        .where(User.password_hash != "")
        .order_by(User.created_at.asc())
        .limit(1)
    )
    if user is not None:
        user.role = ROLE_ADMIN
        user.updated_at = _now_iso()


def _copy_default_settings(session: OrmSession, user_id: str) -> None:
    now = _now_iso()
    rows = session.scalars(
        select(Setting).where(Setting.user_id == settings_store.DEFAULT_USER_ID)
    ).all()
    for row in rows:
        existing = session.scalar(
            select(Setting).where(
                Setting.user_id == user_id,
                Setting.namespace == row.namespace,
                Setting.setting_name == row.setting_name,
            )
        )
        if existing is None:
            session.add(
                Setting(
                    user_id=user_id,
                    namespace=row.namespace,
                    setting_name=row.setting_name,
                    value=row.value,
                    value_type=row.value_type,
                    is_secret=row.is_secret,
                    created_at=now,
                    updated_at=now,
                )
            )


def create_user(
    username: str,
    password: str,
    display_name: Optional[str] = None,
    org_id: Optional[str] = None,
    status: str = STATUS_ACTIVE,
) -> dict[str, Any]:
    init_auth_schema()
    normalized_username = _validate_username(username)
    _validate_password(password)
    if status not in VALID_STATUSES:
        raise ValueError("Unsupported user status")

    salt = secrets.token_bytes(16)
    password_hash = _password_hash(password, salt)
    user_id = uuid.uuid4().hex
    now = _now_iso()
    name = (display_name or normalized_username).strip() or normalized_username

    try:
        with _orm_session() as session:
            if org_id is not None and session.scalar(
                select(Organization.id).where(Organization.id == org_id)
            ) is None:
                raise ValueError("组织不存在")
            first_password_user = _password_user_count(session) == 0
            role = (
                ROLE_ADMIN
                if allow_first_user_admin()
                and first_password_user
                and _admin_user_count(session) == 0
                else ROLE_USER
            )
            user = User(
                id=user_id,
                username=normalized_username,
                display_name=name,
                password_hash=_encode(password_hash),
                password_salt=_encode(salt),
                password_iterations=PASSWORD_ITERATIONS,
                role=role,
                status=status,
                org_id=org_id,
                is_default=0,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            session.flush()
            if first_password_user:
                _copy_default_settings(session, user_id)
            org_name = _org_name_for(session, org_id)
    except IntegrityError:
        raise ValueError("用户名已存在") from None

    return _public_user(user, org_name)


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

    try:
        with _orm_session() as session:
            existing = session.scalar(
                select(User)
                .where(User.password_hash != "")
                .order_by(User.created_at.asc())
                .limit(1)
            )
            if existing is not None:
                return _public_user(existing), False

            user = User(
                id=user_id,
                username=normalized_username,
                display_name=name,
                password_hash=_encode(password_hash),
                password_salt=_encode(salt),
                password_iterations=PASSWORD_ITERATIONS,
                role=ROLE_ADMIN,
                is_default=0,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            session.flush()
            _copy_default_settings(session, user_id)
    except IntegrityError:
        raise ValueError("用户名已存在") from None

    return _public_user(user), True


def authenticate_user(username: str, password: str) -> Optional[dict[str, Any]]:
    init_auth_schema()
    normalized_username = username.strip().lower()

    with _orm_session() as session:
        user = session.scalar(select(User).where(User.username == normalized_username))

    if user is None or not user.password_hash or not user.password_salt:
        _password_hash(password, _DUMMY_PASSWORD_SALT, PASSWORD_ITERATIONS)
        return None

    try:
        salt = _decode(user.password_salt)
        expected = _decode(user.password_hash)
        iterations = int(user.password_iterations or PASSWORD_ITERATIONS)
    except Exception:
        _password_hash(password, _DUMMY_PASSWORD_SALT, PASSWORD_ITERATIONS)
        return None

    actual = _password_hash(password, salt, iterations)
    if not secrets.compare_digest(actual, expected):
        return None

    with _orm_session() as session:
        org_name = _org_name_for(session, user.org_id)
    return _public_user(user, org_name)


def update_user_profile(user_id: str, display_name: str) -> dict[str, Any]:
    init_auth_schema()
    normalized_display_name = display_name.strip()
    if not normalized_display_name:
        raise ValueError("显示名称不能为空")
    if len(normalized_display_name) > 64:
        raise ValueError("显示名称不能超过 64 个字符")

    with _orm_session() as session:
        user = session.scalar(select(User).where(User.id == user_id, User.password_hash != ""))
        if user is None:
            raise ValueError("User not found")
        user.display_name = normalized_display_name
        user.updated_at = _now_iso()

    return _public_user(user)


def list_users(
    name: str = "",
    username: str = "",
    page: int = 1,
    page_size: int = 20,
    org_id: Optional[str] = None,
    status: Optional[str] = None,
) -> dict[str, Any]:
    init_auth_schema()
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))

    conditions = [User.password_hash != ""]
    name = (name or "").strip()
    username = (username or "").strip()
    if name:
        conditions.append(User.display_name.ilike(f"%{name}%"))
    if username:
        conditions.append(User.username.ilike(f"%{username}%"))
    if org_id is not None:
        conditions.append(User.org_id == org_id)
    if status is not None:
        conditions.append(User.status == status)

    with _orm_session() as session:
        total = session.scalar(select(func.count()).select_from(User).where(*conditions)) or 0
        users = session.scalars(
            select(User)
            .where(*conditions)
            .order_by(User.created_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        org_names = _org_names_by_id(session)
    return {
        "items": [_public_user(user, org_names.get(user.org_id)) for user in users],
        "total": int(total),
        "page": page,
        "pages": max(1, (int(total) + page_size - 1) // page_size),
    }


def update_user_password(user_id: str, password: str) -> dict[str, Any]:
    init_auth_schema()
    _validate_password(password)

    salt = secrets.token_bytes(16)
    password_hash = _password_hash(password, salt)
    now = _now_iso()

    with _orm_session() as session:
        user = session.scalar(
            select(User).where(User.id == user_id, User.password_hash != "")
        )
        if user is None:
            raise ValueError("User not found")

        user.password_hash = _encode(password_hash)
        user.password_salt = _encode(salt)
        user.password_iterations = PASSWORD_ITERATIONS
        user.updated_at = now
        session.execute(
            update(DbSession)
            .where(DbSession.user_id == user_id, DbSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    return _public_user(user)


def change_user_password(
    user_id: str,
    current_password: str,
    new_password: str,
) -> dict[str, Any]:
    """Change a user's password after verifying the current password."""
    init_auth_schema()
    _validate_password(current_password)
    _validate_password(new_password)

    with _orm_session() as session:
        user = session.scalar(
            select(User).where(User.id == user_id, User.password_hash != "")
        )
        if user is None:
            raise ValueError("User not found")

        try:
            salt = _decode(user.password_salt)
            expected = _decode(user.password_hash)
            iterations = int(user.password_iterations or PASSWORD_ITERATIONS)
        except Exception:
            raise ValueError("当前密码不正确") from None

        actual = _password_hash(current_password, salt, iterations)
        if not secrets.compare_digest(actual, expected):
            raise ValueError("当前密码不正确")
        if secrets.compare_digest(
            _password_hash(new_password, salt, iterations), expected
        ):
            raise ValueError("新密码不能与当前密码相同")

        new_salt = secrets.token_bytes(16)
        user.password_hash = _encode(_password_hash(new_password, new_salt))
        user.password_salt = _encode(new_salt)
        user.password_iterations = PASSWORD_ITERATIONS
        now = _now_iso()
        user.updated_at = now
        session.execute(
            update(DbSession)
            .where(DbSession.user_id == user_id, DbSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    return _public_user(user)


def update_user_role(user_id: str, role: str) -> dict[str, Any]:
    init_auth_schema()
    next_role = (role or "").strip().lower()
    if next_role not in VALID_ROLES:
        raise ValueError("Unsupported role")

    now = _now_iso()
    with _orm_session() as session:
        user = session.scalar(
            select(User).where(User.id == user_id, User.password_hash != "")
        )
        if user is None:
            raise ValueError("User not found")

        if (
            user.role == ROLE_ADMIN
            and next_role != ROLE_ADMIN
            and _admin_user_count(session) <= 1
        ):
            raise ValueError("At least one admin user is required")
        if next_role == ROLE_ORG_ADMIN and not user.org_id:
            raise ValueError("组织管理员必须先归属一个组织")

        user.role = next_role
        user.updated_at = now
        org_name = _org_name_for(session, user.org_id)

    return _public_user(user, org_name)


def create_session(user_id: str) -> tuple[str, datetime]:
    init_auth_schema()
    token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(seconds=get_session_max_age_seconds())
    now = _now_iso()

    with _orm_session() as session:
        session.add(
            DbSession(
                id=uuid.uuid4().hex,
                user_id=user_id,
                token_hash=_hash_token(token),
                created_at=now,
                expires_at=expires_at.isoformat(),
                revoked_at=None,
            )
        )
        session.flush()
        recent_sessions = session.scalars(
            select(DbSession.id)
            .where(DbSession.user_id == user_id)
            .order_by(DbSession.created_at.desc())
            .limit(get_max_sessions_per_user())
        ).all()
        session.execute(
            delete(DbSession).where(
                DbSession.user_id == user_id,
                DbSession.id.not_in(recent_sessions),
            )
        )

    return token, expires_at


def get_user_by_session_token(token: str) -> Optional[dict[str, Any]]:
    if not token:
        return None

    init_auth_schema()
    with _orm_session() as session:
        user = session.scalar(
            select(User)
            .join(DbSession, DbSession.user_id == User.id)
            .where(
                DbSession.token_hash == _hash_token(token),
                DbSession.revoked_at.is_(None),
                    DbSession.expires_at > _now_iso(),
                )
            )

    if user is None:
        return None
    with _orm_session() as session:
        org_name = _org_name_for(session, user.org_id)
    return _public_user(user, org_name)


def revoke_session(token: str) -> None:
    if not token:
        return

    init_auth_schema()
    with _orm_session() as session:
        session.execute(
            update(DbSession)
            .where(
                DbSession.token_hash == _hash_token(token),
                DbSession.revoked_at.is_(None),
            )
            .values(revoked_at=_now_iso())
        )


# --- Organizations -----------------------------------------------------------


def list_organizations() -> list[dict[str, Any]]:
    init_auth_schema()
    with _orm_session() as session:
        rows = session.execute(
            select(
                Organization.id,
                Organization.name,
                Organization.created_at,
                Organization.updated_at,
                func.count(User.id).label("member_count"),
            )
            .outerjoin(User, (User.org_id == Organization.id) & (User.password_hash != ""))
            .group_by(Organization.id)
            .order_by(Organization.created_at.asc())
        ).all()
    return [
        {
            "id": row[0],
            "name": row[1],
            "created_at": row[2],
            "updated_at": row[3],
            "member_count": int(row[4] or 0),
        }
        for row in rows
    ]


def create_organization(name: str) -> dict[str, Any]:
    init_auth_schema()
    normalized = (name or "").strip()
    if not normalized:
        raise ValueError("组织名称不能为空")
    if len(normalized) > 64:
        raise ValueError("组织名称不能超过 64 个字符")

    org_id = uuid.uuid4().hex
    now = _now_iso()
    try:
        with _orm_session() as session:
            org = Organization(id=org_id, name=normalized, created_at=now, updated_at=now)
            session.add(org)
            session.flush()
            return {"id": org.id, "name": org.name, "created_at": org.created_at, "updated_at": org.updated_at, "member_count": 0}
    except IntegrityError:
        raise ValueError("组织名称已存在") from None


def rename_organization(org_id: str, name: str) -> dict[str, Any]:
    init_auth_schema()
    normalized = (name or "").strip()
    if not normalized:
        raise ValueError("组织名称不能为空")
    if len(normalized) > 64:
        raise ValueError("组织名称不能超过 64 个字符")

    with _orm_session() as session:
        org = session.scalar(select(Organization).where(Organization.id == org_id))
        if org is None:
            raise ValueError("组织不存在")
        org.name = normalized
        org.updated_at = _now_iso()
        member_count = int(
            session.scalar(
                select(func.count()).select_from(User).where(
                    User.org_id == org_id, User.password_hash != ""
                )
            )
            or 0
        )
    return {"id": org_id, "name": normalized, "member_count": member_count, "created_at": org.created_at, "updated_at": org.updated_at}


def delete_organization(org_id: str) -> None:
    init_auth_schema()
    with _orm_session() as session:
        org = session.scalar(select(Organization).where(Organization.id == org_id))
        if org is None:
            raise ValueError("组织不存在")
        member_count = int(
            session.scalar(
                select(func.count()).select_from(User).where(User.org_id == org_id)
            )
            or 0
        )
        if member_count > 0:
            raise ValueError("组织下仍有成员，请先移出全部成员")
        session.delete(org)


def get_user_by_id(user_id: str) -> Optional[dict[str, Any]]:
    init_auth_schema()
    with _orm_session() as session:
        user = session.scalar(select(User).where(User.id == user_id, User.password_hash != ""))
        if user is None:
            return None
        org_name = _org_name_for(session, user.org_id)
        return _public_user(user, org_name)


def update_user_org(user_id: str, org_id: Optional[str]) -> dict[str, Any]:
    init_auth_schema()
    with _orm_session() as session:
        user = session.scalar(select(User).where(User.id == user_id, User.password_hash != ""))
        if user is None:
            raise ValueError("User not found")
        if org_id is not None and session.scalar(
            select(Organization.id).where(Organization.id == org_id)
        ) is None:
            raise ValueError("组织不存在")
        if user.role == ROLE_ORG_ADMIN and org_id != user.org_id:
            raise ValueError("请先调整该组织管理员的角色，再变更其组织归属")
        user.org_id = org_id
        user.updated_at = _now_iso()
        org_name = _org_name_for(session, org_id)
        return _public_user(user, org_name)


def update_user_status(user_id: str, status: str) -> dict[str, Any]:
    init_auth_schema()
    next_status = (status or "").strip().lower()
    if next_status not in VALID_STATUSES:
        raise ValueError("Unsupported user status")

    now = _now_iso()
    with _orm_session() as session:
        user = session.scalar(select(User).where(User.id == user_id, User.password_hash != ""))
        if user is None:
            raise ValueError("User not found")
        user.status = next_status
        user.updated_at = now
        if next_status == STATUS_PENDING:
            session.execute(
                update(DbSession)
                .where(DbSession.user_id == user_id, DbSession.revoked_at.is_(None))
                .values(revoked_at=now)
            )
        org_name = _org_name_for(session, user.org_id)

    return _public_user(user, org_name)


def delete_pending_user(user_id: str) -> None:
    """Remove a pending registration entirely (rejection)."""
    init_auth_schema()
    with _orm_session() as session:
        user = session.scalar(
            select(User).where(User.id == user_id, User.status == STATUS_PENDING)
        )
        if user is None:
            raise ValueError("待审批用户不存在")
        session.delete(user)
