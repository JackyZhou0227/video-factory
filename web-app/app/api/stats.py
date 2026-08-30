from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.auth import require_current_user, require_org_scoped_admin
from app.services import stats_store

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/me")
def my_stats(
    created_from: Optional[str] = Query(default=None, description="开始日期 YYYY-MM-DD，留空不过滤"),
    created_to: Optional[str] = Query(default=None, description="结束日期 YYYY-MM-DD，留空不过滤"),
    user: dict = Depends(require_current_user),
):
    return stats_store.get_personal_stats(user["id"], created_from=created_from, created_to=created_to)


@router.get("/overview")
def overview_stats(
    created_from: Optional[str] = Query(default=None, description="开始日期 YYYY-MM-DD，留空不过滤"),
    created_to: Optional[str] = Query(default=None, description="结束日期 YYYY-MM-DD，留空不过滤"),
    org_id: Optional[str] = Query(default=None, description="按组织过滤（仅超管生效）"),
    admin_user: tuple = Depends(require_org_scoped_admin),
):
    scope_org_id = admin_user[1]
    effective_org = scope_org_id if scope_org_id is not None else (org_id or None)
    return stats_store.get_overview_stats(
        created_from=created_from, created_to=created_to, org_id=effective_org
    )
