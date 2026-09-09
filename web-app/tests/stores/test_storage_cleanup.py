from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import admin as admin_api
from app.api import auth as auth_api
from app.core.config import app_config
from app.db.models import BgmTrack, GenerationTask
from app.services import auth_store, settings_store, storage_cleanup, task_store
from tests.pg_test_utils import ensure_test_user

NOW = datetime(2026, 9, 5, 8, 0, 0, tzinfo=timezone.utc)


def _backdate(path: Path, days: float, *, now: datetime = NOW) -> None:
    stamp = (now - timedelta(days=days)).timestamp()
    os.utime(path, (stamp, stamp))


def _old_finished_at(task_id: str, days: float) -> None:
    finished_at = (NOW - timedelta(days=days)).isoformat()
    with settings_store._orm_session() as session:
        session.query(GenerationTask).filter(GenerationTask.id == task_id).update(
            {"finished_at": finished_at, "status": "failed"}
        )


class StorageCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_root = Path(self.temp_dir.name) / "output"
        self.output_root.mkdir()
        settings_store.init_db()
        ensure_test_user("user-a", username="user_a", display_name="User A")
        self._original_tasks = dict(app_config.get("tasks") or {})
        app_config["tasks"] = {
            **self._original_tasks,
            "cleanup": {"enabled": True, "orphan_retention_days": 7, "failed_task_retention_days": 7},
        }
        self.user = {"id": "user-a", "username": "user_a", "display_name": "User A"}

    def tearDown(self):
        app_config["tasks"] = self._original_tasks
        self.temp_dir.cleanup()

    def create_task(self, **kwargs) -> dict:
        params = dict(
            user=self.user,
            task_type=task_store.TASK_TYPE_VOICE,
            generation_type="voice",
            requested_count=1,
            output_root=self.output_root,
        )
        params.update(kwargs)
        return task_store.create_task(**params)

    def orphan_dir(self, name: str = "orphan-task") -> Path:
        path = self.output_root / "tasks" / "2026" / "08" / "01" / "digital_human" / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "result.mp4").write_bytes(b"video")
        return path

    def test_scan_reports_orphan_dirs_and_known_counts(self):
        task = self.create_task()
        orphan = self.orphan_dir()
        report = storage_cleanup.scan(self.output_root, now=NOW)
        self.assertEqual(report["task_dirs"]["known"], 1)
        self.assertEqual(report["task_dirs"]["orphan_count"], 1)
        self.assertEqual(Path(report["task_dirs"]["orphan"][0]["path"]), orphan)
        self.assertFalse(report["task_dirs"]["orphan"][0]["deletable"])
        self.assertIn(str(Path(task["storage_path"]).name), str(task["storage_path"]))

    def test_scan_reports_missing_dirs_for_db_records(self):
        task = self.create_task()
        Path(task["storage_path"]).rmdir()
        report = storage_cleanup.scan(self.output_root, now=NOW)
        self.assertIn(str(Path(task["storage_path"])), report["missing_dirs"])

    def test_cleanup_removes_expired_orphans_but_respects_grace_period(self):
        orphan = self.orphan_dir()
        _backdate(orphan, days=10)
        dry = storage_cleanup.cleanup(dry_run=True, output_root=self.output_root, now=NOW)
        self.assertTrue(orphan.exists())
        self.assertEqual(dry["removed_dirs"], [str(orphan)])
        self.assertEqual(dry["freed_bytes"], len(b"video"))

        done = storage_cleanup.cleanup(dry_run=False, output_root=self.output_root, now=NOW)
        self.assertFalse(orphan.exists())
        self.assertIn(str(orphan), done["removed_dirs"])
        self.assertGreaterEqual(done["freed_bytes"], len(b"video"))

    def test_cleanup_keeps_young_orphans(self):
        orphan = self.orphan_dir()
        _backdate(orphan, days=1)
        storage_cleanup.cleanup(dry_run=False, output_root=self.output_root, now=NOW)
        self.assertTrue(orphan.exists())

    def test_failed_task_dir_removed_after_retention_record_kept(self):
        task = self.create_task(status="failed", message="任务执行失败")
        task_dir = Path(task["storage_path"])
        (task_dir / "out.mp4").write_bytes(b"data")
        _old_finished_at(task["id"], days=8)

        result = storage_cleanup.cleanup(dry_run=False, output_root=self.output_root, now=NOW)
        self.assertFalse(task_dir.exists())
        self.assertEqual(result["updated_tasks"][0]["task_id"], task["id"])

        loaded = task_store.get_task(task["id"], "user-a")
        self.assertEqual(loaded["status"], "failed")  # DB 记录保留
        self.assertEqual(loaded["artifacts"], [])
        self.assertEqual(loaded["message"], "产物已过期清理")

    def test_recent_failed_task_and_completed_task_dirs_are_kept(self):
        recent = self.create_task(status="failed", message="任务执行失败")
        _old_finished_at(recent["id"], days=1)  # status failed 但 finished_at 在保留期内
        completed = self.create_task(status="completed", message="完成")
        Path(completed["storage_path"]).mkdir(parents=True, exist_ok=True)

        storage_cleanup.cleanup(dry_run=False, output_root=self.output_root, now=NOW)
        self.assertTrue(Path(recent["storage_path"]).exists())
        self.assertTrue(Path(completed["storage_path"]).exists())

    def test_part_files_removed_only_when_expired(self):
        old_part = self.output_root / "bgm" / "user-a" / ".old.mp3.part"
        old_part.parent.mkdir(parents=True, exist_ok=True)
        old_part.write_bytes(b"x")
        _backdate(old_part, days=2)
        new_part = self.output_root / "bgm" / "user-a" / ".new.mp3.part"
        new_part.write_bytes(b"x")

        storage_cleanup.cleanup(dry_run=False, output_root=self.output_root, now=NOW)
        self.assertFalse(old_part.exists())
        self.assertTrue(new_part.exists())

    def test_bgm_orphans_reported_but_not_deleted(self):
        track_dir = self.output_root / "bgm" / "user-a"
        track_dir.mkdir(parents=True, exist_ok=True)
        known = track_dir / "bgm-1.mp3"
        known.write_bytes(b"music")
        orphan = track_dir / "bgm-orphan.mp3"
        orphan.write_bytes(b"music")
        now_iso = settings_store._now_iso()
        with settings_store._orm_session() as session:
            session.add(
                BgmTrack(
                    id="bgm-1",
                    user_id="user-a",
                    name="music",
                    relative_path="bgm/user-a/bgm-1.mp3",
                    duration=1.0,
                    file_size=5,
                    created_at=now_iso,
                    updated_at=now_iso,
                )
            )

        report = storage_cleanup.scan(self.output_root, now=NOW)
        self.assertEqual(len(report["bgm_orphans"]), 1)
        self.assertEqual(Path(report["bgm_orphans"][0]["path"]), orphan)

        storage_cleanup.cleanup(dry_run=False, output_root=self.output_root, now=NOW)
        self.assertTrue(known.exists())
        self.assertTrue(orphan.exists())  # 仅报告不删除

    def test_cleanup_disabled_leaves_everything(self):
        app_config["tasks"]["cleanup"]["enabled"] = False
        orphan = self.orphan_dir()
        _backdate(orphan, days=10)
        result = storage_cleanup.cleanup(dry_run=False, output_root=self.output_root, now=NOW)
        self.assertFalse(result["enabled"])
        self.assertTrue(orphan.exists())

    def test_disk_status_and_enforce(self):
        status = storage_cleanup.disk_status(self.output_root)
        self.assertGreater(status["total_bytes"], 0)
        self.assertIn("reject", status)

        fake = {
            "path": "fake", "total_bytes": 100, "free_bytes": 1,
            "free_percent": 1.0, "min_free_bytes": 10, "min_free_percent": 5.0,
            "reject": True,
        }
        with mock.patch.object(storage_cleanup, "disk_status", return_value=fake):
            with self.assertRaises(HTTPException) as ctx:
                storage_cleanup.enforce_disk_space()
            self.assertEqual(ctx.exception.status_code, 429)

    def test_create_task_rejected_when_disk_low(self):
        fake = {
            "path": "fake", "total_bytes": 100, "free_bytes": 1,
            "free_percent": 1.0, "min_free_bytes": 10, "min_free_percent": 5.0,
            "reject": True,
        }
        with mock.patch.object(storage_cleanup, "disk_status", return_value=fake):
            with self.assertRaises(HTTPException) as ctx:
                self.create_task()
            self.assertEqual(ctx.exception.status_code, 429)
        # 正常磁盘不受影响
        task = self.create_task()
        self.assertTrue(task["id"])


class StorageAdminApiTests(unittest.TestCase):
    def setUp(self):
        settings_store.init_db()
        auth_store.reset_rate_limits()
        self.app = FastAPI()
        self.app.include_router(auth_api.router, prefix="/api")
        self.app.include_router(admin_api.router, prefix="/api")
        self.client = TestClient(self.app)
        auth_store.create_initial_admin("rootadmin", "root-pass-123", display_name="超管")
        self.login("rootadmin", "root-pass-123")

    def tearDown(self):
        self.client.close()

    def login(self, username: str, password: str) -> None:
        self.client.cookies.clear()
        response = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)

    def test_admin_can_fetch_report_and_dry_run_cleanup(self):
        response = self.client.get("/api/admin/storage/report")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("task_dirs", body)
        self.assertIn("disk", body)

        response = self.client.post("/api/admin/storage/cleanup", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["dry_run"])

        response = self.client.post("/api/admin/storage/cleanup")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["dry_run"])

    def test_normal_user_forbidden(self):
        auth_store.create_user("plainuser", "plain-pass-123", display_name="普通用户")
        self.login("plainuser", "plain-pass-123")
        self.assertEqual(self.client.get("/api/admin/storage/report").status_code, 403)
        self.assertEqual(
            self.client.post("/api/admin/storage/cleanup", json={"dry_run": True}).status_code,
            403,
        )
