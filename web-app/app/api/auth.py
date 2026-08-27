from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.services import auth_store

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE_NAME = "vf_session"


class AuthPayload(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=auth_store.MAX_PASSWORD_LENGTH)
    display_name: Optional[str] = Field(default=None, max_length=64)


class LoginPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=auth_store.MAX_PASSWORD_LENGTH)


class ChangePasswordPayload(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=auth_store.MAX_PASSWORD_LENGTH)
    new_password: str = Field(..., min_length=8, max_length=auth_store.MAX_PASSWORD_LENGTH)


def _request_is_secure(request: Request) -> bool:
    override = auth_store.cookie_secure_override()
    if override is not None:
        return override

    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    if forwarded_proto:
        return forwarded_proto == "https"
    return request.url.scheme == "https"


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=auth_store.get_session_max_age_seconds(),
        httponly=True,
        secure=_request_is_secure(request),
        samesite=auth_store.cookie_samesite(),
        path="/",
    )


def _clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=_request_is_secure(request),
        samesite=auth_store.cookie_samesite(),
        path="/",
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limit_error(exc: auth_store.RateLimitExceeded) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="请求过于频繁，请稍后再试",
        headers={"Retry-After": str(exc.retry_after)},
    )


def get_current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    return auth_store.get_user_by_session_token(token)


def require_current_user(request: Request) -> dict:
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return user


def require_admin_user(request: Request) -> dict:
    user = require_current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


@router.post("/register")
def register(payload: AuthPayload, request: Request, response: Response):
    if not auth_store.is_registration_enabled():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前未开放注册")

    try:
        auth_store.check_registration_rate_limit(_client_ip(request), payload.username)
    except auth_store.RateLimitExceeded as exc:
        raise _rate_limit_error(exc) from None

    try:
        user = auth_store.create_user(
            username=payload.username,
            password=payload.password,
            display_name=payload.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None

    token, _ = auth_store.create_session(user["id"])
    _set_session_cookie(response, request, token)
    return {"user": user}


@router.post("/login")
def login(payload: LoginPayload, request: Request, response: Response):
    try:
        auth_store.check_login_rate_limit(_client_ip(request), payload.username)
    except auth_store.RateLimitExceeded as exc:
        raise _rate_limit_error(exc) from None

    user = auth_store.authenticate_user(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码不正确")

    auth_store.clear_login_rate_limit(payload.username)
    token, _ = auth_store.create_session(user["id"])
    _set_session_cookie(response, request, token)
    return {"user": user}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    auth_store.revoke_session(token)
    _clear_session_cookie(response, request)
    return {"ok": True}


@router.put("/password")
def change_password(payload: ChangePasswordPayload, user: dict = Depends(require_current_user)):
    try:
        changed_user = auth_store.change_user_password(
            user["id"], payload.current_password, payload.new_password
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_401_UNAUTHORIZED
            if detail == "当前密码不正确"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=detail) from None

    return {"user": changed_user, "reauthenticate": True}


@router.get("/me")
def me(request: Request):
    user = get_current_user(request)
    return {"authenticated": user is not None, "user": user}
