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
        comfyui_selfhost_limit: int = 1,
    ) -> None:
        self.max_active_jobs = max(1, int(max_active_jobs))
        self.max_queued_jobs = max(0, int(max_queued_jobs))
        self.capacity = self.max_active_jobs + self.max_queued_jobs
        self.qwen_limit = max(1, int(qwen_limit))
        self.comfyui_limit = max(1, int(comfyui_selfhost_limit))
        self.comfyui_capacity = self.comfyui_limit + self.max_queued_jobs
        self._queue: asyncio.Queue[tuple[str, TaskRunner, asyncio.Event]] = asyncio.Queue()
        self._comfyui_queue: asyncio.Queue[tuple[str, TaskRunner, asyncio.Event]] = asyncio.Queue()
        self._comfyui_reserved = 0
        self._comfyui_active = 0
        self._comfyui_workers: list[asyncio.Task[None]] = []
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
            "comfyui": {
                "active": self._comfyui_active,
                "queued": max(0, self._comfyui_reserved - self._comfyui_active),
                "limit": self.comfyui_limit,
            },
        }

    async def start(self) -> None:
        if self._accepting:
            return
        self._accepting = True
        self._workers = [
            asyncio.create_task(
                self._worker(index, self._queue, "default"),
                name=f"vf-task-worker-{index}",
            )
            for index in range(self.max_active_jobs)
        ]
        self._comfyui_workers = [
            asyncio.create_task(
                self._worker(index, self._comfyui_queue, "comfyui"),
                name=f"vf-comfyui-worker-{index}",
            )
            for index in range(self.comfyui_limit)
        ]

    def can_accept(self) -> bool:
        return self._accepting and self._reserved < self.capacity

    def submit(self, task_id: str, runner: TaskRunner, *, lane: str = "default") -> None:
        if lane not in {"default", "comfyui"}:
            raise ValueError(f"Unknown task lane: {lane}")
        if not self._accepting:
            raise TaskRuntimeCapacityError("任务执行器正在启动或停止，请稍后重试")
        if task_id in self._cancel_events:
            raise TaskRuntimeCapacityError("任务已经在执行队列中")
        queue = self._comfyui_queue if lane == "comfyui" else self._queue
        reserved = self._comfyui_reserved if lane == "comfyui" else self._reserved
        capacity = self.comfyui_capacity if lane == "comfyui" else self.capacity
        if reserved >= capacity:
            raise TaskRuntimeCapacityError("服务器任务队列已满，请等待已有任务完成后再试")
        cancel_event = asyncio.Event()
        self._cancel_events[task_id] = cancel_event
        if lane == "comfyui":
            self._comfyui_reserved += 1
        else:
            self._reserved += 1
        queue.put_nowait((task_id, runner, cancel_event))

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

    async def _worker(self, _index: int, queue: asyncio.Queue, lane: str = "default") -> None:
        while True:
            task_id, runner, cancel_event = await queue.get()
            if lane == "comfyui":
                self._comfyui_active += 1
            else:
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
                if lane == "comfyui":
                    self._comfyui_active -= 1
                    self._comfyui_reserved -= 1
                else:
                    self._active -= 1
                    self._reserved -= 1
                self._cancel_events.pop(task_id, None)
                queue.task_done()

    def _drain(self, queue: asyncio.Queue, lane: str) -> None:
        while not queue.empty():
            task_id, _runner, cancel_event = queue.get_nowait()
            cancel_event.set()
            self._transition(
                task_id,
                status="cancelled",
                message="服务停止时任务未开始执行",
                error="服务停止时任务未开始执行",
            )
            self._cancel_events.pop(task_id, None)
            if lane == "comfyui":
                self._comfyui_reserved -= 1
            else:
                self._reserved -= 1
            queue.task_done()

    async def stop(self) -> None:
        self._accepting = False
        self._drain(self._queue, "default")
        self._drain(self._comfyui_queue, "comfyui")
        workers = [*self._workers, *self._comfyui_workers]
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        self._workers.clear()
        self._comfyui_workers.clear()
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
