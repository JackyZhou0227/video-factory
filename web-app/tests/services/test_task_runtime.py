from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.services.task_runtime import TaskExecutionManager, TaskRuntimeCapacityError


class TaskExecutionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = TaskExecutionManager(
            max_active_jobs=1,
            max_queued_jobs=1,
            qwen_limit=1,
        )
        self.task_update = patch("app.services.task_runtime.task_store.update_task").start()
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

    async def test_run_blocking_tracks_lane_usage(self):
        def blocking():
            return "done"

        result = await self.manager.run_blocking("media", blocking)
        self.assertEqual(result, "done")
        self.assertEqual(self.manager.snapshot()["qwen"], {"active": 0, "limit": 1})


if __name__ == "__main__":
    unittest.main()
