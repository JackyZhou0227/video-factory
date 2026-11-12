from __future__ import annotations

import asyncio
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from app.services.task_runtime import (
    TaskCancelledError,
    TaskExecutionManager,
    TaskRuntimeCapacityError,
    run_subprocess_cancellable,
)


class TaskExecutionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = TaskExecutionManager(
            max_active_jobs=1,
            max_queued_jobs=1,
            qwen_limit=1,
            comfyui_selfhost_limit=1,
        )
        self.task_update = patch("app.services.task_runtime.task_store.update_task").start()
        self.task_transition = patch(
            "app.services.task_runtime.task_store.transition_task_status",
            side_effect=lambda *args, **kwargs: {"status": kwargs.get("status")},
        ).start()
        self.addCleanup(patch.stopall)
        await self.manager.start()

    async def asyncTearDown(self):
        await self.manager.stop()

    async def test_limits_admission_and_reports_active_slots(self):
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        second_started = asyncio.Event()

        async def first():
            first_started.set()
            await release_first.wait()

        async def second():
            second_started.set()

        self.manager.submit("first", first)
        await asyncio.wait_for(first_started.wait(), timeout=1)
        self.manager.submit("second", second)
        self.assertEqual(
            self.manager.snapshot()["jobs"],
            {"active": 1, "queued": 1, "limit": 1, "capacity": 2},
        )
        with self.assertRaises(TaskRuntimeCapacityError):
            self.manager.submit("third", second)

        release_first.set()
        await asyncio.wait_for(second_started.wait(), timeout=1)

    async def test_comfyui_lane_waits_independently_of_the_default_lane(self):
        comfyui_started = asyncio.Event()
        release_comfyui = asyncio.Event()
        second_comfyui_started = asyncio.Event()
        default_started = asyncio.Event()
        release_default = asyncio.Event()

        async def hold_comfyui():
            comfyui_started.set()
            await release_comfyui.wait()

        async def second_comfyui():
            second_comfyui_started.set()

        async def default_job():
            default_started.set()
            await release_default.wait()

        self.manager.submit("comfyui-1", hold_comfyui, lane="comfyui")
        await asyncio.wait_for(comfyui_started.wait(), timeout=1)
        self.manager.submit("comfyui-2", second_comfyui, lane="comfyui")
        await asyncio.sleep(0)
        self.assertFalse(second_comfyui_started.is_set())

        self.manager.submit("default-1", default_job, lane="default")
        await asyncio.wait_for(default_started.wait(), timeout=1)
        self.assertFalse(second_comfyui_started.is_set())
        self.manager.submit("default-2", default_job, lane="default")

        with self.assertRaises(TaskRuntimeCapacityError):
            self.manager.submit("comfyui-3", second_comfyui, lane="comfyui")
        with self.assertRaises(TaskRuntimeCapacityError):
            self.manager.submit("default-3", default_job, lane="default")

        release_default.set()
        release_comfyui.set()
        await asyncio.wait_for(second_comfyui_started.wait(), timeout=1)

    async def test_run_blocking_tracks_lane_usage(self):
        def blocking():
            return "done"

        result = await self.manager.run_blocking("media", blocking)
        self.assertEqual(result, "done")
        self.assertEqual(self.manager.snapshot()["qwen"], {"active": 0, "limit": 1})

    async def test_cancelled_queued_task_never_starts(self):
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        queued_started = asyncio.Event()

        async def first(_cancel_event):
            first_started.set()
            await release_first.wait()

        async def queued(_cancel_event):
            queued_started.set()

        self.manager.submit("first", first)
        await asyncio.wait_for(first_started.wait(), timeout=1)
        self.manager.submit("queued", queued)

        self.assertTrue(self.manager.cancel("queued"))
        release_first.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        self.assertFalse(queued_started.is_set())
        self.assertFalse(self.manager.is_cancel_requested("queued"))

    async def test_running_task_receives_cancel_event(self):
        started = asyncio.Event()
        observed = asyncio.Event()

        async def runner(cancel_event):
            started.set()
            await cancel_event.wait()
            observed.set()

        self.manager.submit("running", runner)
        await asyncio.wait_for(started.wait(), timeout=1)

        self.assertTrue(self.manager.cancel("running"))
        await asyncio.wait_for(observed.wait(), timeout=1)
        self.assertFalse(self.manager.is_cancel_requested("running"))

    async def test_runtime_marks_cancelled_task_terminal_after_runner_returns(self):
        started = asyncio.Event()

        async def runner(cancel_event):
            started.set()
            await cancel_event.wait()

        self.manager.submit("cancel-me", runner)
        await asyncio.wait_for(started.wait(), timeout=1)
        self.manager.cancel("cancel-me")
        await asyncio.wait_for(self.manager._queue.join(), timeout=1)

        self.assertTrue(
            any(
                call.kwargs.get("status") == "cancelled"
                for call in self.task_transition.call_args_list
            )
        )

    async def test_runtime_cleanup_releases_reserved_capacity(self):
        started = asyncio.Event()

        async def runner(cancel_event):
            started.set()
            await cancel_event.wait()

        self.manager.submit("cleanup", runner)
        await asyncio.wait_for(started.wait(), timeout=1)
        self.manager.cancel("cleanup")
        await asyncio.wait_for(self.manager._queue.join(), timeout=1)

        self.assertEqual(
            self.manager.snapshot()["jobs"],
            {"active": 0, "queued": 0, "limit": 1, "capacity": 2},
        )


class RunSubprocessCancellableTests(unittest.IsolatedAsyncioTestCase):
    async def test_completes_normally_and_captures_output(self):
        cancel_event = asyncio.Event()
        completed = await asyncio.to_thread(
            run_subprocess_cancellable,
            [sys.executable, "-c", "print('hello')"],
            cancel_event=cancel_event,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.strip(), "hello")

    async def test_cancel_terminates_process_and_raises(self):
        cancel_event = asyncio.Event()
        started = time.monotonic()
        runner = asyncio.create_task(
            asyncio.to_thread(
                run_subprocess_cancellable,
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cancel_event=cancel_event,
                poll_interval=0.05,
                kill_grace_seconds=2.0,
            )
        )
        await asyncio.sleep(0.3)
        cancel_event.set()

        with self.assertRaises(TaskCancelledError):
            await runner
        self.assertLess(time.monotonic() - started, 10.0)

    async def test_non_zero_exit_raises_called_process_error(self):
        cancel_event = asyncio.Event()
        with self.assertRaises(subprocess.CalledProcessError):
            await asyncio.to_thread(
                run_subprocess_cancellable,
                [sys.executable, "-c", "import sys; sys.exit(3)"],
                cancel_event=cancel_event,
            )

    async def test_without_cancel_event_runs_to_completion(self):
        completed = await asyncio.to_thread(
            run_subprocess_cancellable,
            [sys.executable, "-c", "print('done')"],
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.strip(), "done")


if __name__ == "__main__":
    unittest.main()
