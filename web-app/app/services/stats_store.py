"""Aggregated task statistics for personal stats and the admin dashboard."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select

from app.db.models import GenerationTask, Organization, User
from app.services import settings_store, task_store

_orm_session = settings_store._orm_session

VALID_DAY_RANGES = {None, 7, 30, 90}

TASK_TYPE_LABELS = {
    task_store.TASK_TYPE_DIGITAL_HUMAN: "数字人口播",
    task_store.TASK_TYPE_VOICE: "语音合成",
    task_store.TASK_TYPE_TEMPLATE: "模板量产",
    task_store.TASK_TYPE_POSTER: "大字报视频",
    task_store.TASK_TYPE_SMART_EDITING: "智能剪辑",
}


DATE_FMT = "%Y-%m-%d"


def parse_date_bounds(created_from: Optional[str], created_to: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """校验并规整起止日期（YYYY-MM-DD）；两者都可为空表示不过滤。

    返回 (from_iso, to_exclusive_iso)：to 转换为次日凌晨的 ISO，便于与
    created_at 文本做字典序比较且包含当天全部时间。
    """
    def _parse(value: Optional[str]) -> Optional[date]:
        if not value:
            return None
        try:
            return datetime.strptime(value.strip()[:10], DATE_FMT).date()
        except ValueError:
            return None

    from_day = _parse(created_from)
    to_day = _parse(created_to)
    from_iso = from_day.isoformat() if from_day else None
    to_iso = (to_day + timedelta(days=1)).isoformat() if to_day else None
    return from_iso, to_iso


def _base_conditions(
    user_id: Optional[str],
    org_id: Optional[str],
    from_iso: Optional[str],
    to_exclusive_iso: Optional[str],
) -> list[Any]:
    conditions = []
    if user_id is not None:
        conditions.append(GenerationTask.user_id == user_id)
    if org_id is not None:
        conditions.append(User.org_id == org_id)
    if from_iso is not None:
        # created_at 为 ISO 文本，字典序比较等价于时间比较
        conditions.append(GenerationTask.created_at >= from_iso)
    if to_exclusive_iso is not None:
        conditions.append(GenerationTask.created_at < to_exclusive_iso)
    return conditions


def _scope_query(session, conditions: list[Any]):
    return session.query(GenerationTask).join(User, User.id == GenerationTask.user_id).filter(*conditions)


def _totals(session, conditions: list[Any]) -> dict[str, Any]:
    row = (
        _scope_query(session, conditions)
        .with_entities(
            func.count(GenerationTask.id),
            func.coalesce(func.sum(GenerationTask.success_count), 0),
            func.coalesce(func.sum(GenerationTask.failed_count), 0),
        )
        .one()
    )
    task_count = int(row[0] or 0)
    outputs = int(row[1] or 0)
    failed_pieces = int(row[2] or 0)
    return {
        "task_count": task_count,
        "output_count": outputs,
        "failed_count": failed_pieces,
        "success_rate": round(outputs / (outputs + failed_pieces), 4) if (outputs + failed_pieces) > 0 else None,
    }


def _daily(session, conditions: list[Any]) -> list[dict[str, Any]]:
    day = func.substring(GenerationTask.created_at, 1, 10).label("day")
    rows = (
        _scope_query(session, conditions)
        .with_entities(
            day,
            func.count(GenerationTask.id),
            func.coalesce(func.sum(GenerationTask.success_count), 0),
        )
        .group_by(day)
        .order_by(day.asc())
        .all()
    )
    return [{"date": row[0], "tasks": int(row[1] or 0), "outputs": int(row[2] or 0)} for row in rows]


def _by_type(session, conditions: list[Any]) -> list[dict[str, Any]]:
    rows = (
        _scope_query(session, conditions)
        .with_entities(
            GenerationTask.task_type,
            func.count(GenerationTask.id),
            func.coalesce(func.sum(GenerationTask.success_count), 0),
        )
        .group_by(GenerationTask.task_type)
        .order_by(func.count(GenerationTask.id).desc())
        .all()
    )
    return [
        {
            "task_type": row[0],
            "label": TASK_TYPE_LABELS.get(row[0], str(row[0])),
            "tasks": int(row[1] or 0),
            "outputs": int(row[2] or 0),
        }
        for row in rows
    ]


def get_personal_stats(
    user_id: str,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
) -> dict[str, Any]:
    settings_store.init_db()
    from_iso, to_iso = parse_date_bounds(created_from, created_to)
    with _orm_session() as session:
        conditions = _base_conditions(user_id, None, from_iso, to_iso)
        return {
            "created_from": from_iso,
            "created_to": to_iso,
            "totals": _totals(session, conditions),
            "daily": _daily(session, conditions),
            "by_type": _by_type(session, conditions),
        }


def get_overview_stats(
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    org_id: Optional[str] = None,
) -> dict[str, Any]:
    settings_store.init_db()
    from_iso, to_iso = parse_date_bounds(created_from, created_to)
    with _orm_session() as session:
        conditions = _base_conditions(None, org_id, from_iso, to_iso)
        totals = _totals(session, conditions)
        daily = _daily(session, conditions)
        by_type = _by_type(session, conditions)

        org_name = func.coalesce(Organization.name, "未分配").label("org_name")
        org_rows = (
            _scope_query(session, conditions)
            .outerjoin(Organization, Organization.id == User.org_id)
            .with_entities(
                org_name,
                func.count(GenerationTask.id),
                func.coalesce(func.sum(GenerationTask.success_count), 0),
            )
            .group_by(org_name)
            .order_by(func.count(GenerationTask.id).desc())
            .all()
        )
        by_org = [
            {"org": row[0], "tasks": int(row[1] or 0), "outputs": int(row[2] or 0)}
            for row in org_rows
        ]

        member_rows = (
            _scope_query(session, conditions)
            .with_entities(
                User.display_name,
                User.username,
                func.count(GenerationTask.id),
                func.coalesce(func.sum(GenerationTask.success_count), 0),
            )
            .group_by(User.id, User.display_name, User.username)
            .order_by(func.count(GenerationTask.id).desc())
            .limit(10)
            .all()
        )
        top_members = [
            {
                "display_name": row[0],
                "username": row[1],
                "tasks": int(row[2] or 0),
                "outputs": int(row[3] or 0),
            }
            for row in member_rows
        ]

    return {
        "created_from": from_iso,
        "created_to": to_iso,
        "org_id": org_id,
        "totals": totals,
        "daily": daily,
        "by_type": by_type,
        "by_org": by_org,
        "top_members": top_members,
    }
