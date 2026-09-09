"""输出目录的孤儿文件扫描、过期清理与磁盘低水位保护。

对应运维清单 RESOURCE-04 / RESOURCE-02（磁盘部分）：

- ``scan``             生成只读扫描报告（孤儿任务目录、缺失目录、遗留 .part、BGM 孤儿）。
- ``cleanup``          执行清理：孤儿目录 / .part 临时文件 / 失败任务目录按保留期删除。
- ``disk_status``      输出目录所在磁盘的剩余空间与阈值判断。
- ``enforce_disk_space``  磁盘低于低水位时拒绝创建新任务（429）。

BGM 与公共音色库属于用户/公司资源，本轮只报告、不自动删除。
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from fastapi import HTTPException
from sqlalchemy import select, update

from app.core.config import app_config, resolve_output_dir
from app.db.models import BgmTrack, GenerationTask
from app.services import settings_store

logger = logging.getLogger(__name__)

PART_SUFFIX = ".part"
PART_MAX_AGE_SECONDS = 24 * 3600

DEFAULT_ORPHAN_RETENTION_DAYS = 7
DEFAULT_FAILED_TASK_RETENTION_DAYS = 7
DEFAULT_MIN_FREE_BYTES = 5 * 1024**3
DEFAULT_MIN_FREE_PERCENT = 5.0

CLEANABLE_TASK_STATUSES = ("failed", "cancelled")
# 需要修剪的空父目录层级（年/月/日/类型），task 目录本身之下不修剪。
_TASK_DIR_DEPTH = 5


# --- 配置 ---------------------------------------------------------------------


def _tasks_config() -> dict[str, Any]:
    return app_config.get("tasks") or {}


def _disk_config() -> dict[str, Any]:
    return _tasks_config().get("disk") or {}


def _cleanup_config() -> dict[str, Any]:
    return _tasks_config().get("cleanup") or {}


def _min_free_bytes() -> int:
    value = _disk_config().get("min_free_bytes", DEFAULT_MIN_FREE_BYTES)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return DEFAULT_MIN_FREE_BYTES


def _min_free_percent() -> float:
    value = _disk_config().get("min_free_percent", DEFAULT_MIN_FREE_PERCENT)
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return DEFAULT_MIN_FREE_PERCENT


def cleanup_enabled() -> bool:
    value = _cleanup_config().get("enabled", True)
    return bool(value)


def orphan_retention_days() -> int:
    value = _cleanup_config().get("orphan_retention_days", DEFAULT_ORPHAN_RETENTION_DAYS)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return DEFAULT_ORPHAN_RETENTION_DAYS


def failed_task_retention_days() -> int:
    value = _cleanup_config().get("failed_task_retention_days", DEFAULT_FAILED_TASK_RETENTION_DAYS)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return DEFAULT_FAILED_TASK_RETENTION_DAYS


# --- 基础工具 -------------------------------------------------------------------


def _coerce_now(value: Optional[datetime]) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_iso(value: Optional[str], fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _entry(path: Path, *, now: datetime) -> dict[str, Any]:
    try:
        stat_result = path.stat()
    except OSError:
        stat_result = None
    mtime = (
        datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc)
        if stat_result
        else now
    )
    size = _dir_size(path) if path.is_dir() else (stat_result.st_size if stat_result else 0)
    age_days = max(0.0, (now - mtime).total_seconds() / 86400)
    return {
        "path": str(path),
        "size_bytes": size,
        "mtime": mtime.isoformat(),
        "age_days": round(age_days, 2),
    }


def _iter_child_dirs(parent: Path) -> Iterator[Path]:
    if not parent.exists():
        return
    try:
        for child in sorted(parent.iterdir()):
            if child.is_dir():
                yield child
    except OSError:
        return


def _output_root(output_root: Optional[Path]) -> Path:
    return Path(output_root or resolve_output_dir(app_config)).resolve()


# --- 数据库记录集合 ---------------------------------------------------------------


def _known_task_paths() -> set[str]:
    with settings_store._orm_session() as session:
        rows = session.execute(select(GenerationTask.storage_path)).all()
    return {str(Path(str(row[0])).resolve()) for row in rows}


def _known_bgm_paths(output_root: Path) -> set[str]:
    with settings_store._orm_session() as session:
        rows = session.execute(select(BgmTrack.relative_path)).all()
    known: set[str] = set()
    for row in rows:
        try:
            known.add(str((output_root / str(row[0])).resolve()))
        except (OSError, ValueError):
            continue
    return known


# --- 磁盘状态 -------------------------------------------------------------------


def disk_status(output_root: Optional[Path] = None) -> dict[str, Any]:
    root = _output_root(output_root)
    usage = shutil.disk_usage(root)
    total = int(usage.total)
    free = int(usage.free)
    free_percent = (free / total * 100.0) if total > 0 else 0.0
    min_free_bytes = _min_free_bytes()
    min_free_percent = _min_free_percent()
    reject = free < min_free_bytes or free_percent < min_free_percent
    return {
        "path": str(root),
        "total_bytes": total,
        "free_bytes": free,
        "free_percent": round(free_percent, 2),
        "min_free_bytes": min_free_bytes,
        "min_free_percent": min_free_percent,
        "reject": reject,
    }


def enforce_disk_space(output_root: Optional[Path] = None) -> None:
    """磁盘剩余空间低于低水位时拒绝创建新任务（复用配额超额的 429 风格）。"""
    status = disk_status(output_root)
    if status["reject"]:
        raise HTTPException(
            status_code=429,
            detail="磁盘剩余空间不足，暂时无法创建新任务，请稍后重试",
        )


# --- 扫描 ----------------------------------------------------------------------


def scan(output_root: Optional[Path] = None, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """只读扫描输出目录，生成孤儿文件报告。"""
    root = _output_root(output_root)
    current = _coerce_now(now)
    tasks_root = root / "tasks"
    known_paths = _known_task_paths()
    known_bgm = _known_bgm_paths(root)

    known_count = 0
    orphan_dirs: list[dict[str, Any]] = []
    for year_dir in _iter_child_dirs(tasks_root):
        for month_dir in _iter_child_dirs(year_dir):
            for day_dir in _iter_child_dirs(month_dir):
                for type_dir in _iter_child_dirs(day_dir):
                    for task_dir in _iter_child_dirs(type_dir):
                        if str(task_dir.resolve()) in known_paths:
                            known_count += 1
                            continue
                        entry = _entry(task_dir, now=current)
                        entry["deletable"] = entry["age_days"] >= orphan_retention_days()
                        orphan_dirs.append(entry)

    missing_dirs: list[str] = []
    for known in sorted(known_paths):
        if not Path(known).exists():
            missing_dirs.append(known)

    part_files: list[dict[str, Any]] = []
    try:
        candidates = list(root.rglob(f"*{PART_SUFFIX}"))
    except OSError:
        candidates = []
    for part in candidates:
        if not part.is_file():
            continue
        entry = _entry(part, now=current)
        entry["deletable"] = entry["age_days"] * 86400 >= PART_MAX_AGE_SECONDS
        part_files.append(entry)

    bgm_orphans: list[dict[str, Any]] = []
    bgm_root = root / "bgm"
    if bgm_root.exists():
        for item in sorted(bgm_root.rglob("*")):
            if not item.is_file():
                continue
            if str(item.resolve()) in known_bgm:
                continue
            bgm_orphans.append(_entry(item, now=current))

    failed_tasks: list[dict[str, Any]] = []
    failed_cutoff = current - timedelta(days=failed_task_retention_days())
    with settings_store._orm_session() as session:
        rows = session.execute(
            select(GenerationTask.id, GenerationTask.storage_path, GenerationTask.finished_at)
            .where(
                GenerationTask.status.in_(CLEANABLE_TASK_STATUSES),
                GenerationTask.finished_at.is_not(None),
            )
        ).all()
    for task_id, storage_path, finished_at in rows:
        finished = _parse_iso(finished_at, current)
        if finished > failed_cutoff:
            continue
        path = Path(str(storage_path))
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if not path.exists():
            continue
        entry = _entry(path, now=current)
        entry.update({"task_id": str(task_id), "finished_at": finished.isoformat(), "deletable": True})
        failed_tasks.append(entry)

    reclaimable = sum(item["size_bytes"] for item in orphan_dirs if item["deletable"])
    reclaimable += sum(item["size_bytes"] for item in part_files if item["deletable"])
    reclaimable += sum(item["size_bytes"] for item in failed_tasks)

    return {
        "generated_at": current.isoformat(),
        "output_root": str(root),
        "disk": disk_status(root),
        "task_dirs": {
            "known": known_count,
            "orphan": orphan_dirs,
            "orphan_count": len(orphan_dirs),
        },
        "missing_dirs": missing_dirs,
        "part_files": part_files,
        "failed_tasks": failed_tasks,
        "bgm_orphans": bgm_orphans,
        "reclaimable_bytes": reclaimable,
        "retention": {
            "orphan_retention_days": orphan_retention_days(),
            "failed_task_retention_days": failed_task_retention_days(),
            "part_max_age_seconds": PART_MAX_AGE_SECONDS,
        },
    }


# --- 清理 ----------------------------------------------------------------------


def _remove_path(path: Path) -> tuple[int, bool]:
    """删除文件或目录，返回（释放的字节数，是否删除成功）。"""
    try:
        freed = _dir_size(path) if path.is_dir() else path.stat().st_size
    except OSError:
        return 0, False
    if path.is_dir():
        try:
            shutil.rmtree(path)
        except OSError:
            return 0, False
    else:
        try:
            path.unlink()
        except OSError:
            return 0, False
    return freed, not path.exists()


def _prune_empty_parents(tasks_root: Path, protected: Optional[set[str]] = None) -> list[str]:
    """清理孤儿目录后修剪空的年/月/日/类型父目录。

    ``protected`` 中的目录（数据库已知任务目录、宽限期内孤儿目录）即使为空也不删除。
    """
    protected = protected or set()
    pruned: list[str] = []
    for depth in range(_TASK_DIR_DEPTH - 1):
        changed = False
        for parent in _iter_child_dirs(tasks_root):
            stack = [parent]
            while stack:
                current = stack.pop()
                if str(current.resolve()) in protected:
                    continue
                children = list(_iter_child_dirs(current))
                if children:
                    stack.extend(children)
                    continue
                try:
                    current.rmdir()
                except OSError:
                    continue
                pruned.append(str(current))
                changed = True
        if not changed:
            break
    return pruned


def cleanup(
    dry_run: bool = False,
    output_root: Optional[Path] = None,
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """执行过期清理；``dry_run=True`` 只统计不删除。"""
    root = _output_root(output_root)
    current = _coerce_now(now)
    tasks_root = root / "tasks"

    if not cleanup_enabled():
        return {
            "dry_run": bool(dry_run),
            "enabled": False,
            "removed_dirs": [],
            "removed_files": [],
            "updated_tasks": [],
            "pruned_dirs": [],
            "freed_bytes": 0,
        }

    freed = 0
    removed_dirs: list[str] = []
    removed_files: list[str] = []
    pruned_dirs: list[str] = []

    # 1. 孤儿任务目录：宽限期后删除；2. 遗留 .part 临时文件：超过 1 天删除。
    report = scan(root, now=current)
    protected: set[str] = set()
    for entry in report["task_dirs"]["orphan"]:
        path = Path(entry["path"])
        if not entry["deletable"]:
            protected.add(str(path.resolve()))
            continue
        if not dry_run:
            removed_bytes, removed = _remove_path(path)
            if not removed:
                protected.add(str(path.resolve()))
                continue
            freed += removed_bytes
        else:
            freed += entry["size_bytes"]
        removed_dirs.append(str(path))

    for entry in report["part_files"]:
        if not entry["deletable"]:
            continue
        path = Path(entry["path"])
        if not dry_run:
            removed_bytes, removed = _remove_path(path)
            if not removed:
                continue
            freed += removed_bytes
        else:
            freed += entry["size_bytes"]
        removed_files.append(str(path))

    # 3. 失败/已取消任务目录：保留期后删文件、清空 artifacts、保留 DB 记录。
    cutoff = current - timedelta(days=failed_task_retention_days())
    updated_tasks: list[dict[str, str]] = []
    with settings_store._orm_session() as session:
        rows = session.execute(
            select(GenerationTask.id, GenerationTask.storage_path, GenerationTask.finished_at).where(
                GenerationTask.status.in_(CLEANABLE_TASK_STATUSES),
                GenerationTask.finished_at.is_not(None),
            )
        ).all()
    for task_id, storage_path, finished_at in rows:
        finished = _parse_iso(finished_at, current)
        if finished > cutoff:
            continue
        path = Path(str(storage_path))
        if not path.exists():
            continue
        try:
            path.relative_to(root)
        except ValueError:
            continue  # storage_path 异常时不碰
        if not dry_run:
            removed_bytes, removed = _remove_path(path)
            if not removed:
                continue
            freed += removed_bytes
            with settings_store._orm_session() as session:
                session.execute(
                    update(GenerationTask)
                    .where(GenerationTask.id == str(task_id))
                    .values(
                        artifacts_json="[]",
                        message="产物已过期清理",
                        updated_at=current.isoformat(),
                    )
                )
        else:
            freed += _dir_size(path)
        updated_tasks.append({"task_id": str(task_id), "storage_path": str(path)})
        removed_dirs.append(str(path))

    # 4. 修剪空的日期/类型父目录；数据库已知任务目录与宽限期内孤儿不被修剪。
    if not dry_run and tasks_root.exists():
        pruned_dirs = _prune_empty_parents(tasks_root, protected | _known_task_paths())

    return {
        "dry_run": bool(dry_run),
        "enabled": True,
        "removed_dirs": sorted(set(removed_dirs)),
        "removed_files": removed_files,
        "updated_tasks": updated_tasks,
        "pruned_dirs": pruned_dirs,
        "freed_bytes": freed,
    }


async def periodic_cleanup_loop(
    *,
    first_delay_seconds: int = 300,
    interval_seconds: int = 24 * 3600,
) -> None:
    """lifespan 后台循环：延迟首跑后每日清理一次；文件操作放线程避免阻塞事件循环。"""
    import asyncio

    await asyncio.sleep(max(0, first_delay_seconds))
    while True:
        try:
            result = await asyncio.to_thread(cleanup, False)
            if result.get("removed_dirs") or result.get("removed_files") or result.get("updated_tasks"):
                logger.info(
                    "Storage cleanup removed %s dirs / %s part files, freed %s bytes",
                    len(result.get("removed_dirs", [])),
                    len(result.get("removed_files", [])),
                    result.get("freed_bytes", 0),
                )
        except Exception:
            logger.exception("Periodic storage cleanup failed")
        await asyncio.sleep(max(60, interval_seconds))
