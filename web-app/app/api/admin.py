from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.auth import require_admin_user
from app.services import auth_store

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_user)])


class ResetPasswordPayload(BaseModel):
    password: str = Field(..., min_length=8)


class UpdateRolePayload(BaseModel):
    role: str = Field(..., pattern="^(admin|user)$")


@router.get("/users")
def list_users(
    name: str = "",
    username: str = "",
    page: int = 1,
    page_size: int = 20,
):
    return {"users": auth_store.list_users(name=name, username=username, page=page, page_size=page_size)}


@router.put("/users/{user_id}/password")
def reset_user_password(user_id: str, payload: ResetPasswordPayload):
    try:
        user = auth_store.update_user_password(user_id, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from None

    return {"user": user}


@router.put("/users/{user_id}/role")
def update_user_role(user_id: str, payload: UpdateRolePayload, admin_user: dict = Depends(require_admin_user)):
    if user_id == admin_user["id"] and payload.role != "admin":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="不能修改自己的管理员角色")

    try:
        user = auth_store.update_user_role(user_id, payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None

    return {"user": user}
