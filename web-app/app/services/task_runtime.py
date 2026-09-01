from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Awaitable, Callable, Literal, TypeVar

from app.services import task_store

logger = logging.getLogger(__name__)

T = TypeVar("T")
TaskRunner = Callable[[], Awaitable[None]]
ExecutorLane = Literal["media", "qwen"]


class TaskRuntimeCapacityError(RuntimeError):
    pass


class TaskExecutionManager:
    """Single-process scheduler for persisted background generation tasks."""

    def __init__(
        self,
        *,
        max_active_jobs: int,
        max_queued_jobs: int,
        qwen_limit: int,
    ) -> None:
        self.max_active_jobs = max(1, int(max_active_jobs))
        self.max_queued_jobs = max(0, int(max_queued_jobs))
        self.capacity = self.max_active_jobs + self.max_queued_jobs
        self.qwen_limit = max(1, int(qwen_limit))
        self._queue: asyncio.Queue[tuple[str, TaskRunner]] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._blocking_executor = ThreadPoolExecutor(
            max_workers=self.max_active_jobs,
            thread_name_prefix="vf-blocking",
        )
        self._qwen_executor = ThreadPoolExecutor(
            max_workers=self.qwen_limit,
            thread_name_prefix="vf-qwen",
        )
        self._accepting = False
        self._reserved = 0
        self._active = 0
        self._lane_active = {"media": 0, "qwen": 0}

    @property
    def accepting(self) -> bool:
        return self._accepting

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {
            "jobs": {
                "active": self._active,
                "queued": max(0, self._reserved - self._active),
                "limit": self.max_active_jobs,
                "capacity": self.capacity,
            },
            "qwen": {"active": self._lane_active["qwen"], "limit": self.qwen_limit},
        }

    async def start(self) -> None:
        if self._accepting:
            return
        self._accepting = True
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"vf-task-worker-{index}")
            for index in range(self.max_active_jobs)
        ]

    def can_accept(self) -> bool:
        return self._accepting and self._reserved < self.capacity

    def submit(self, task_id: str, runner: TaskRunner) -> None:
        if not self._accepting:
            raise TaskRuntimeCapacityError("任务执行器正在启动或停止，请稍后重试")
        if self._reserved >= self.capacity:
            raise TaskRuntimeCapacityError("服务器任务队列已满，请等待已有任务完成后再试")
        self._reserved += 1
        self._queue.put_nowait((task_id, runner))

    async def run_blocking(
        self,
        lane: ExecutorLane,
        func: Callable[..., T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> T:
        loop = asyncio.get_running_loop()
        self._lane_active[lane] += 1
        try:
            executor = self._blocking_executor if lane == "media" else self._qwen_executor
            return await loop.run_in_executor(executor, partial(func, *args, **kwargs))
        finally:
            self._lane_active[lane] -= 1

    async def _worker(self, _index: int) -> None:
        while True:
            task_id, runner = await self._queue.get()
            self._active += 1
            try:
                task_store.update_task(
                    task_id,
                    status="running",
                    message="任务正在处理",
                    started=True,
                )
                await runner()
            except asyncio.CancelledError:
                task_store.update_task(
                    task_id,
                    status="cancelled",
                    message="服务停止时任务已取消",
                    error="服务停止时任务已取消",
                    finished=True,
                )
                raise
            except Exception:
                logger.exception("Background task failed: %s", task_id)
                task_store.update_task(
                    task_id,
                    status="failed",
                    message="任务执行失败",
                    error="服务器执行任务时发生未处理异常",
                    finished=True,
                )
            finally:
                self._active -= 1
                self._reserved -= 1
                self._queue.task_done()

    async def stop(self) -> None:
        self._accepting = False
        while not self._queue.empty():
            task_id, _runner = self._queue.get_nowait()
            task_store.update_task(
                task_id,
                status="cancelled",
                message="服务停止时任务未开始执行",
                error="服务停止时任务未开始执行",
                finished=True,
            )
            self._reserved -= 1
            self._queue.task_done()
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._blocking_executor.shutdown(wait=False, cancel_futures=True)
        self._qwen_executor.shutdown(wait=False, cancel_futures=True)


_runtime: TaskExecutionManager | None = None


def configure_task_runtime(manager: TaskExecutionManager | None) -> None:
    global _runtime
    _runtime = manager


def get_task_runtime() -> TaskExecutionManager:
    if _runtime is None:
        raise RuntimeError("Task execution runtime is not initialized")
    return _runtime


async def run_blocking(
    lane: ExecutorLane,
    func: Callable[..., T],
    /,
    *args: Any,
    **kwargs: Any,
) -> T:
    try:
        runtime = get_task_runtime()
    except RuntimeError:
        return await asyncio.to_thread(func, *args, **kwargs)
    return await runtime.run_blocking(lane, func, *args, **kwargs)
