from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import stats as stats_api
from app.api.auth import router as auth_router
from app.db.models import GenerationTask
from app.services import auth_store, settings_store


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _seed_task(user_id: str, username: str, display_name: str, task_type: str, *, success: int = 1, failed: int = 0, days_ago: int = 0, status: str = "completed") -> None:
    now = _iso(days_ago)
    with settings_store._orm_session() as session:
        session.add(
            GenerationTask(
                id=f"task-{username}-{task_type}-{days_ago}-{success}-{failed}-{now[-6:]}",
                user_id=user_id,
                creator_username=username,
                creator_display_name=display_name,
                task_type=task_type,
                generation_type="video",
                requested_count=success + failed,
                success_count=success,
                failed_count=failed,
                status=status,
                progress=100,
                message="",
                storage_path="",
                created_at=now,
                started_at=now,
                finished_at=now,
                updated_at=now,
            )
        )
        session.commit()


class StatsApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(auth_router, prefix="/api")
        self.app.include_router(stats_api.router, prefix="/api")
        self.client = TestClient(self.app)

        auth_store.create_initial_admin("rootadmin", "root-pass-123", display_name="超管")
        self.org_a = auth_store.create_organization("组织A")["id"]
        self.org_b = auth_store.create_organization("组织B")["id"]

        self.admin = auth_store.list_users()["items"][0]
        boss = auth_store.create_user("bossa", "bossa-pass-123", display_name="组长A", org_id=self.org_a)
        auth_store.update_user_role(boss["id"], "org_admin")
        self.boss = auth_store.get_user_by_id(boss["id"])
        member_a1 = auth_store.create_user("member_a1", "member-123", display_name="成员A1", org_id=self.org_a)
        member_a2 = auth_store.create_user("member_a2", "member-123", display_name="成员A2", org_id=self.org_a)
        self.member_b = auth_store.create_user("member_b", "member-123", display_name="成员B", org_id=self.org_b)
        self.member_a1 = auth_store.get_user_by_id(member_a1["id"])
        self.member_a2 = auth_store.get_user_by_id(member_a2["id"])

        from app.services import task_store

        # 组织A 成员A1：3 个数字人任务（40 天前 1 个 + 5 天前 2 个），成片 5、失败 1
        _seed_task(self.member_a1["id"], "member_a1", "成员A1", task_store.TASK_TYPE_DIGITAL_HUMAN, success=2, failed=1, days_ago=40)
        _seed_task(self.member_a1["id"], "member_a1", "成员A1", task_store.TASK_TYPE_DIGITAL_HUMAN, success=3, failed=0, days_ago=5)
        # 组织A 成员A2：5 天前 2 个语音任务
        _seed_task(self.member_a2["id"], "member_a2", "成员A2", task_store.TASK_TYPE_VOICE, success=2, failed=0, days_ago=5)
        # 组织B 成员B：5 天前 1 个大字报任务
        _seed_task(self.member_b["id"], "member_b", "成员B", task_store.TASK_TYPE_POSTER, success=1, failed=0, days_ago=5)

    def tearDown(self):
        self.client.close()

    def login(self, username: str, password: str):
        self.client.cookies.clear()
        response = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)

    def test_personal_stats_only_own_tasks(self):
        self.login("member_a1", "member-123")
        response = self.client.get("/api/stats/me")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["totals"]["task_count"], 2)
        self.assertEqual(data["totals"]["output_count"], 5)
        self.assertEqual(data["totals"]["failed_count"], 1)
        # 近 7 天时排除 40 天前的任务
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        response = self.client.get("/api/stats/me", params={"created_from": week_ago})
        data = response.json()
        self.assertEqual(data["totals"]["task_count"], 1)
        self.assertEqual(data["totals"]["output_count"], 3)

    def test_overview_scoped_to_org_for_org_admin(self):
        self.login("bossa", "bossa-pass-123")
        response = self.client.get("/api/stats/overview")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        # 仅组织A：成员A1 + 成员A2 的任务
        self.assertEqual(data["totals"]["task_count"], 3)
        self.assertEqual(data["totals"]["output_count"], 7)
        orgs = {row["org"]: row["tasks"] for row in data["by_org"]}
        self.assertEqual(set(orgs), {"组织A"})
        self.assertEqual(data["top_members"][0]["username"], "member_a1")

    def test_admin_overview_covers_all_orgs_and_filters(self):
        self.login("rootadmin", "root-pass-123")
        response = self.client.get("/api/stats/overview")
        data = response.json()
        self.assertEqual(data["totals"]["task_count"], 4)
        orgs = {row["org"]: row["tasks"] for row in data["by_org"]}
        self.assertEqual(orgs, {"组织A": 3, "组织B": 1})

        response = self.client.get("/api/stats/overview", params={"org_id": self.org_b})
        data = response.json()
        self.assertEqual(data["totals"]["task_count"], 1)
        self.assertEqual(data["totals"]["output_count"], 1)

    def test_regular_user_forbidden_on_overview(self):
        self.login("member_a1", "member-123")
        response = self.client.get("/api/stats/overview")
        self.assertEqual(response.status_code, 403)

    def test_days_all_returns_everything(self):
        self.login("member_a1", "member-123")
        response = self.client.get("/api/stats/me")  # 不传 days = 全部
        data = response.json()
        self.assertEqual(data["totals"]["task_count"], 2)


if __name__ == "__main__":
    unittest.main()
