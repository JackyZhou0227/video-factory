from __future__ import annotations

import asyncio
import inspect
import logging
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Awaitable, Callable, Literal, TypeVar

from app.services import task_store

logger = logging.getLogger(__name__)

T = TypeVar("T")
TaskRunner = Callable[..., Awaitable[None]]
ExecutorLane = Literal["media", "qwen"]


class TaskRuntimeCapacityError(RuntimeError):
    pass


class TaskCancelledError(RuntimeError):
    """Raised when a cancellable subprocess is terminated by user request."""


def run_subprocess_cancellable(
    command: list[str],
    *,
    cancel_event: asyncio.Event | None = None,
    capture_output: bool = True,
    text: bool = True,
    check: bool = True,
    kill_grace_seconds: float = 3.0,
    poll_interval: float = 0.25,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess that can be terminated when ``cancel_event`` is set.

    Must be called from a worker thread (e.g. via ``run_blocking``) because it
    blocks while polling. On cancellation the child process is terminated and
    ``TaskCancelledError`` is raised; the runner discards any partial output.
    """
    creationflags = 0
    if threading.current_thread() is threading.main_thread() and hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=text,
        errors="replace" if text else None,
        creationflags=creationflags,
    )

    stdout_data: str | None = None
    stderr_data: str | None = None
    cancelled = False

    # Reader threads avoid pipe-buffer deadlock while the main loop polls for
    # cancellation.
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    def _drain(stream, sink: list[str]) -> None:
        if stream is None:
            return
        try:
            for chunk in iter(lambda: stream.read(65536), ""):
                sink.append(chunk)
        except ValueError:
            pass

    readers = []
    if capture_output:
        readers = [
            threading.Thread(target=_drain, args=(process.stdout, stdout_chunks), daemon=True),
            threading.Thread(target=_drain, args=(process.stderr, stderr_chunks), daemon=True),
        ]
        for reader in readers:
            reader.start()

    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            if process.poll() is not None:
                break
            time.sleep(poll_interval)

        if cancelled:
            process.terminate()
            try:
                process.wait(timeout=kill_grace_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise TaskCancelledError("任务已取消")

        returncode = process.wait()
    finally:
        for reader in readers:
            reader.join(timeout=1.0)
        if capture_output:
            stdout_data = "".join(stdout_chunks)
            stderr_data = "".join(stderr_chunks)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()

    completed = subprocess.CompletedProcess(
        command,
        returncode,
        stdout=stdout_data,
        stderr=stderr_data,
    )
    if check and returncode != 0:
        raise subprocess.CalledProcessError(returncode, command, output=stdout_data, stderr=stderr_data)
    return completed


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
        self._queue: asyncio.Queue[tuple[str, TaskRunner, asyncio.Event]] = asyncio.Queue()
        self._cancel_events: dict[str, asyncio.Event] = {}
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
        if task_id in self._cancel_events:
            raise TaskRuntimeCapacityError("任务已经在执行队列中")
        cancel_event = asyncio.Event()
        self._cancel_events[task_id] = cancel_event
        self._reserved += 1
        self._queue.put_nowait((task_id, runner, cancel_event))

    def cancel(self, task_id: str) -> bool:
        """Signal one queued or running task without touching other work."""
        event = self._cancel_events.get(str(task_id))
        if event is None:
            return False
        event.set()
        return True

    def can_cancel(self, task_id: str) -> bool:
        return str(task_id) in self._cancel_events

    def is_cancel_requested(self, task_id: str) -> bool:
        event = self._cancel_events.get(str(task_id))
        return bool(event and event.is_set())

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

    @staticmethod
    async def _invoke_runner(runner: TaskRunner, cancel_event: asyncio.Event) -> None:
        try:
            signature = inspect.signature(runner)
            accepts_event = any(
                parameter.kind in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.VAR_POSITIONAL,
                }
                for parameter in signature.parameters.values()
            )
        except (TypeError, ValueError):
            accepts_event = False
        if accepts_event:
            await runner(cancel_event)
        else:
            await runner()

    @staticmethod
    def _transition(
        task_id: str,
        *,
        status: str,
        message: str,
        error: str,
        finished: bool = True,
    ) -> None:
        task_store.transition_task_status(
            task_id,
            expected_statuses=("pending", "running", "cancelling"),
            status=status,
            message=message,
            error=error,
            finished=finished,
        )

    async def _worker(self, _index: int) -> None:
        while True:
            task_id, runner, cancel_event = await self._queue.get()
            self._active += 1
            try:
                if cancel_event.is_set():
                    self._transition(
                        task_id,
                        status="cancelled",
                        message="任务已取消",
                        error="用户主动取消任务",
                    )
                    continue

                started = task_store.transition_task_status(
                    task_id,
                    expected_statuses=("pending",),
                    status="running",
                    message="任务正在处理",
                    started=True,
                )
                if started is None:
                    if cancel_event.is_set():
                        self._transition(
                            task_id,
                            status="cancelled",
                            message="任务已取消",
                            error="用户主动取消任务",
                        )
                    continue
                if cancel_event.is_set():
                    self._transition(
                        task_id,
                        status="cancelled",
                        message="任务已取消",
                        error="用户主动取消任务",
                    )
                    continue

                await self._invoke_runner(runner, cancel_event)
                if cancel_event.is_set():
                    self._transition(
                        task_id,
                        status="cancelled",
                        message="任务已取消",
                        error="用户主动取消任务",
                    )
            except asyncio.CancelledError:
                self._transition(
                    task_id,
                    status="cancelled",
                    message="服务停止时任务已取消",
                    error="服务停止时任务已取消",
                )
                raise
            except Exception:
                if cancel_event.is_set():
                    self._transition(
                        task_id,
                        status="cancelled",
                        message="任务已取消",
                        error="用户主动取消任务",
                    )
                    continue
                logger.exception("Background task failed: %s", task_id)
                task_store.transition_task_status(
                    task_id,
                    expected_statuses=("running", "cancelling"),
                    status="failed",
                    message="任务执行失败",
                    error="服务器执行任务时发生未处理异常",
                    finished=True,
                )
            finally:
                self._active -= 1
                self._reserved -= 1
                self._cancel_events.pop(task_id, None)
                self._queue.task_done()

    async def stop(self) -> None:
        self._accepting = False
        while not self._queue.empty():
            task_id, _runner, cancel_event = self._queue.get_nowait()
            cancel_event.set()
            self._transition(
                task_id,
                status="cancelled",
                message="服务停止时任务未开始执行",
                error="服务停止时任务未开始执行",
            )
            self._cancel_events.pop(task_id, None)
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
