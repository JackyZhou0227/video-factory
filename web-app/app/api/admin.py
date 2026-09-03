from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.auth import (
    ensure_org_scoped_target,
    require_admin_user,
    require_org_scoped_admin,
)
from app.services import auth_store

router = APIRouter(prefix="/admin", tags=["admin"])


class ResetPasswordPayload(BaseModel):
    password: str = Field(..., min_length=8)


class UpdateRolePayload(BaseModel):
    role: str = Field(..., pattern="^(admin|org_admin|user)$")


class CreateUserPayload(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8)
    display_name: Optional[str] = Field(default=None, max_length=64)
    org_id: Optional[str] = Field(default=None, max_length=64)


class UpdateOrgPayload(BaseModel):
    org_id: Optional[str] = Field(default=None, max_length=64)


class UpdateStatusPayload(BaseModel):
    status: str = Field(..., pattern="^(active|pending)$")


class OrganizationPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


def _http_error(exc: ValueError, code: int = status.HTTP_422_UNPROCESSABLE_CONTENT) -> HTTPException:
    return HTTPException(status_code=code, detail=str(exc))


# --- Organizations（仅超管） --------------------------------------------------


@router.get("/organizations")
def list_organizations(_: dict = Depends(require_admin_user)):
    return {"organizations": auth_store.list_organizations()}


@router.post("/organizations")
def create_organization(payload: OrganizationPayload, _: dict = Depends(require_admin_user)):
    try:
        org = auth_store.create_organization(payload.name)
    except ValueError as exc:
        raise _http_error(exc) from None
    return {"organization": org}


@router.put("/organizations/{org_id}")
def rename_organization(org_id: str, payload: OrganizationPayload, _: dict = Depends(require_admin_user)):
    try:
        org = auth_store.rename_organization(org_id, payload.name)
    except ValueError as exc:
        raise _http_error(exc) from None
    return {"organization": org}


@router.delete("/organizations/{org_id}")
def delete_organization(org_id: str, _: dict = Depends(require_admin_user)):
    try:
        auth_store.delete_organization(org_id)
    except ValueError as exc:
        raise _http_error(exc) from None
    return {"ok": True}


# --- Users（admin 全局 / org_admin 限本组织） ---------------------------------


@router.get("/users")
def list_users(
    name: str = "",
    username: str = "",
    page: int = 1,
    page_size: int = 20,
    org_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    admin_user: dict = Depends(require_org_scoped_admin),
):
    scope_org_id = admin_user[1]
    effective_org = scope_org_id if scope_org_id is not None else org_id
    result = auth_store.list_users(
        name=name,
        username=username,
        page=page,
        page_size=page_size,
        org_id=effective_org,
        status=status_filter,
    )
    if scope_org_id is not None:
        result["items"] = [u for u in result["items"] if not u["is_admin"]]
    return {"users": result}


@router.post("/users")
def create_member(payload: CreateUserPayload, admin_user: dict = Depends(require_org_scoped_admin)):
    scope_org_id = admin_user[1]
    org_id = payload.org_id
    if scope_org_id is not None:
        org_id = scope_org_id  # 组织管理员创建的成员固定归属本组织
    try:
        user = auth_store.create_user(
            username=payload.username,
            password=payload.password,
            display_name=payload.display_name,
            org_id=org_id,
            status=auth_store.STATUS_ACTIVE,
        )
    except ValueError as exc:
        raise _http_error(exc) from None
    return {"user": user}


@router.put("/users/{user_id}/password")
def reset_user_password(
    user_id: str, payload: ResetPasswordPayload, admin_user: dict = Depends(require_org_scoped_admin)
):
    scope_org_id = admin_user[1]
    target = auth_store.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    ensure_org_scoped_target(admin_user[0], scope_org_id, target)
    try:
        user = auth_store.update_user_password(user_id, payload.password)
    except ValueError as exc:
        raise _http_error(exc, status.HTTP_404_NOT_FOUND) from None
    return {"user": user}


@router.put("/users/{user_id}/role")
def update_user_role(
    user_id: str, payload: UpdateRolePayload, admin_user: dict = Depends(require_admin_user)
):
    if user_id == admin_user["id"] and payload.role != "admin":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="不能修改自己的管理员角色")

    try:
        user = auth_store.update_user_role(user_id, payload.role)
    except ValueError as exc:
        raise _http_error(exc) from None
    return {"user": user}


@router.put("/users/{user_id}/org")
def update_user_org(
    user_id: str, payload: UpdateOrgPayload, admin_user: dict = Depends(require_org_scoped_admin)
):
    scope_org_id = admin_user[1]
    target = auth_store.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    ensure_org_scoped_target(admin_user[0], scope_org_id, target)
    if scope_org_id is not None and payload.org_id != scope_org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="组织管理员只能将成员留在本组织")
    try:
        user = auth_store.update_user_org(user_id, payload.org_id)
    except ValueError as exc:
        raise _http_error(exc) from None
    return {"user": user}


# --- 注册审批 -----------------------------------------------------------------


@router.put("/users/{user_id}/status")
def update_user_status(
    user_id: str, payload: UpdateStatusPayload, admin_user: dict = Depends(require_org_scoped_admin)
):
    scope_org_id = admin_user[1]
    target = auth_store.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    ensure_org_scoped_target(admin_user[0], scope_org_id, target)
    try:
        user = auth_store.update_user_status(user_id, payload.status)
    except ValueError as exc:
        raise _http_error(exc) from None
    return {"user": user}


@router.delete("/users/{user_id}/pending")
def reject_pending_user(
    user_id: str, admin_user: dict = Depends(require_org_scoped_admin)
):
    scope_org_id = admin_user[1]
    target = auth_store.get_user_by_id(user_id)
    if target is None:
        # 待审批用户可能尚未完全初始化，直接尝试按 pending 删除
        try:
            auth_store.delete_pending_user(user_id)
            return {"ok": True}
        except ValueError as exc:
            raise _http_error(exc, status.HTTP_404_NOT_FOUND) from None
    ensure_org_scoped_target(admin_user[0], scope_org_id, target)
    try:
        auth_store.delete_pending_user(user_id)
    except ValueError as exc:
        raise _http_error(exc, status.HTTP_404_NOT_FOUND) from None
    return {"ok": True}
