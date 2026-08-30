from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import admin as admin_api
from app.api import auth as auth_api
from app.services import auth_store


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.include_router(admin_api.router, prefix="/api")
    return app


class OrganizationFlowTests(unittest.TestCase):
    def setUp(self):
        from app.core.config import app_config

        self._app_config = app_config
        self._original_auth = dict(app_config.get("auth") or {})
        app_config["auth"] = {**self._original_auth, "registration_enabled": True}
        auth_store.reset_rate_limits()
        self.app = _build_app()
        self.client = TestClient(self.app)

        # 超管（注册已改为审批制，直接用初始管理员通道）
        auth_store.create_initial_admin("rootadmin", "root-pass-123", display_name="超管")
        self.admin_login()

    def tearDown(self):
        self._app_config["auth"] = self._original_auth
        self.client.close()

    def admin_login(self):
        response = self.client.post("/api/auth/login", json={"username": "rootadmin", "password": "root-pass-123"})
        self.assertEqual(response.status_code, 200, response.text)

    def create_org(self, name: str) -> str:
        response = self.client.post("/api/admin/organizations", json={"name": name})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["organization"]["id"]

    def login_as(self, username: str, password: str) -> None:
        self.client.cookies.clear()
        response = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)

    def test_registration_requires_org_and_stays_pending(self):
        org_id = self.create_org("市场部")
        self.client.cookies.clear()

        response = self.client.post(
            "/api/auth/register",
            json={"username": "newmember", "password": "member-pass-123", "org_id": org_id},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["pending"])

        # 待审批用户无法登录
        response = self.client.post(
            "/api/auth/login", json={"username": "newmember", "password": "member-pass-123"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("审批", response.json()["detail"])

        # 未选组织的注册被拒绝
        response = self.client.post(
            "/api/auth/register", json={"username": "norguser", "password": "member-pass-123"}
        )
        self.assertEqual(response.status_code, 422)

    def test_org_admin_approval_flow(self):
        org_id = self.create_org("研发部")
        # 超管创建组织管理员
        member = auth_store.create_user("orgboss", "boss-pass-123", display_name="研发组长", org_id=org_id)
        auth_store.update_user_role(member["id"], "org_admin")
        self.login_as("orgboss", "boss-pass-123")

        # 组织管理员可以创建成员
        response = self.client.post(
            "/api/admin/users",
            json={"username": "newdev", "password": "dev-pass-123", "display_name": "开发同学"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user"]["org_id"], org_id)

        # 待审批注册出现在本组织列表中
        self.client.cookies.clear()
        pending_response = self.client.post(
            "/api/auth/register",
            json={"username": "applicant", "password": "apply-pass-123", "org_id": org_id},
        )
        self.assertEqual(pending_response.status_code, 200, pending_response.text)
        self.login_as("orgboss", "boss-pass-123")

        response = self.client.get("/api/admin/users", params={"status_filter": "pending"})
        self.assertEqual(response.status_code, 200, response.text)
        pending_ids = [u["id"] for u in response.json()["users"]["items"]]
        applicant_id = next(
            u["id"] for u in auth_store.list_users(status="pending")["items"] if u["username"] == "applicant"
        )
        self.assertIn(applicant_id, pending_ids)

        # 批准后可以登录
        response = self.client.put(f"/api/admin/users/{applicant_id}/status", json={"status": "active"})
        self.assertEqual(response.status_code, 200, response.text)
        self.login_as("applicant", "apply-pass-123")

    def test_org_admin_cannot_touch_other_orgs(self):
        org_a = self.create_org("组织A")
        org_b = self.create_org("组织B")
        boss = auth_store.create_user("bossa", "bossa-pass-123", org_id=org_a)
        auth_store.update_user_role(boss["id"], "org_admin")
        outsider = auth_store.create_user("memberb", "memberb-123", org_id=org_b)
        self.login_as("bossa", "bossa-pass-123")

        # 看不到其他组织成员
        response = self.client.get("/api/admin/users")
        self.assertEqual(response.status_code, 200, response.text)
        ids = [u["id"] for u in response.json()["users"]["items"]]
        self.assertNotIn(outsider["id"], ids)

        # 重置其他组织用户密码被拒
        response = self.client.put(f"/api/admin/users/{outsider['id']}/password", json={"password": "hacked-123"})
        self.assertEqual(response.status_code, 403)

        # 不能给自己创建的成员设为 admin
        response = self.client.put(
            f"/api/admin/users/{boss['id']}/role", json={"role": "admin"}
        )
        self.assertEqual(response.status_code, 403)

    def test_org_crud_guardrails(self):
        org_id = self.create_org("临时组织")
        response = self.client.post("/api/admin/organizations", json={"name": "临时组织"})
        self.assertEqual(response.status_code, 422)

        member = auth_store.create_user("someone", "some-pass-123", org_id=org_id)
        response = self.client.delete(f"/api/admin/organizations/{org_id}")
        self.assertEqual(response.status_code, 422)

        auth_store.update_user_org(member["id"], None)
        response = self.client.delete(f"/api/admin/organizations/{org_id}")
        self.assertEqual(response.status_code, 200, response.text)

    def test_regular_user_forbidden(self):
        auth_store.create_user("plainuser", "plain-pass-123")
        self.login_as("plainuser", "plain-pass-123")
        response = self.client.get("/api/admin/users")
        self.assertEqual(response.status_code, 403)
        response = self.client.get("/api/admin/organizations")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
