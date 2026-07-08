from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.services import auth_store

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE_NAME = "vf_session"


class AuthPayload(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8)
    display_name: Optional[str] = Field(default=None, max_length=64)


class LoginPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=auth_store.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
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
def register(payload: AuthPayload, response: Response):
    try:
        user = auth_store.create_user(
            username=payload.username,
            password=payload.password,
            display_name=payload.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None

    token, _ = auth_store.create_session(user["id"])
    _set_session_cookie(response, token)
    return {"user": user}


@router.post("/login")
def login(payload: LoginPayload, response: Response):
    user = auth_store.authenticate_user(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码不正确")

    token, _ = auth_store.create_session(user["id"])
    _set_session_cookie(response, token)
    return {"user": user}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    auth_store.revoke_session(token)
    _clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    user = get_current_user(request)
    return {"authenticated": user is not None, "user": user}
