from __future__ import annotations

import os
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.services import auth_store, settings_store
from tests.pg_test_utils import count_sessions, set_session_expires_at


class AuthSecurityTests(unittest.TestCase):
    # VF_AUTH_* 环境变量已迁入 config.yaml 的 auth 段；测试直接改写内存配置
    AUTH_KEYS = {
        "VF_AUTH_REGISTRATION_ENABLED": "registration_enabled",
        "VF_AUTH_ALLOW_FIRST_USER_ADMIN": "allow_first_user_admin",
        "VF_AUTH_COOKIE_SECURE": "cookie_secure",
        "VF_AUTH_COOKIE_SAMESITE": "cookie_samesite",
        "VF_AUTH_SESSION_MAX_AGE_SECONDS": "session_max_age_seconds",
        "VF_AUTH_MAX_SESSIONS_PER_USER": "max_sessions_per_user",
    }

    def setUp(self):
        self.original_limits = {
            name: getattr(auth_store, name)
            for name in (
                "LOGIN_IP_MAX_ATTEMPTS",
                "LOGIN_USERNAME_MAX_ATTEMPTS",
                "REGISTER_IP_MAX_ATTEMPTS",
                "REGISTER_USERNAME_MAX_ATTEMPTS",
            )
        }
        from app.core.config import app_config

        self._app_config = app_config
        self.original_auth = dict(app_config.get("auth") or {})
        app_config["auth"] = dict(self.original_auth)
        settings_store.init_db()
        auth_store.init_auth_schema()
        auth_store.reset_rate_limits()

        self.app = FastAPI()
        self.app.include_router(auth_router, prefix="/api")
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        auth_store.reset_rate_limits()
        self._app_config["auth"] = self.original_auth
        for name, value in self.original_limits.items():
            setattr(auth_store, name, value)

    def set_env(self, name: str, value: str | bool | None) -> None:
        key = self.AUTH_KEYS[name]
        if value is None:
            self._app_config["auth"].pop(key, None)
        elif isinstance(value, bool):
            self._app_config["auth"][key] = value
        else:
            text = str(value).strip().lower()
            if key in ("cookie_secure", "registration_enabled", "allow_first_user_admin"):
                self._app_config["auth"][key] = text in {"1", "true", "yes", "on"}
            elif key in ("session_max_age_seconds", "max_sessions_per_user"):
                self._app_config["auth"][key] = int(text)
            else:
                self._app_config["auth"][key] = text

    def test_registration_is_disabled_by_default(self):
        self.set_env("VF_AUTH_REGISTRATION_ENABLED", None)

        response = self.client.post(
            "/api/auth/register",
            json={"username": "newuser", "password": "correct-password"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "当前未开放注册")

    def test_registration_can_be_enabled_and_first_user_is_not_admin(self):
        self.set_env("VF_AUTH_REGISTRATION_ENABLED", "true")
        self.set_env("VF_AUTH_COOKIE_SECURE", "false")

        org_id = auth_store.create_organization("默认组织")["id"]

        response = self.client.post(
            "/api/auth/register",
            json={"username": "newuser", "password": "correct-password", "org_id": org_id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["pending"])
        self.assertFalse(response.json()["user"]["is_admin"])
        self.assertEqual(response.json()["user"]["status"], "pending")

        second_response = self.client.post(
            "/api/auth/register",
            json={"username": "seconduser", "password": "correct-password", "org_id": org_id},
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(second_response.json()["pending"])
        self.assertFalse(second_response.json()["user"]["is_admin"])

    def test_cookie_security_attributes_are_configurable(self):
        self.set_env("VF_AUTH_COOKIE_SECURE", None)
        self.set_env("VF_AUTH_COOKIE_SECURE", "true")
        self.set_env("VF_AUTH_COOKIE_SAMESITE", "strict")

        auth_store.create_user("cookieuser", "correct-password")

        response = self.client.post(
            "/api/auth/login",
            json={"username": "cookieuser", "password": "correct-password"},
        )

        cookie = response.headers["set-cookie"]
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)

    def test_cookie_secure_follows_local_http_by_default(self):
        self.set_env("VF_AUTH_COOKIE_SECURE", None)
        self.set_env("VF_AUTH_COOKIE_SECURE", None)

        auth_store.create_user("httpuser", "correct-password")
        response = self.client.post(
            "/api/auth/login",
            json={"username": "httpuser", "password": "correct-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Secure", response.headers["set-cookie"])

    def test_cookie_secure_follows_forwarded_https_by_default(self):
        self.set_env("VF_AUTH_COOKIE_SECURE", None)
        self.set_env("VF_AUTH_COOKIE_SECURE", None)

        auth_store.create_user("httpsuser", "correct-password")
        response = self.client.post(
            "/api/auth/login",
            headers={"X-Forwarded-Proto": "https"},
            json={"username": "httpsuser", "password": "correct-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers["set-cookie"])

    def test_cookie_secure_environment_override_wins(self):
        self.set_env("VF_AUTH_COOKIE_SECURE", None)
        self.set_env("VF_AUTH_COOKIE_SECURE", "false")

        auth_store.create_user("overrideuser", "correct-password")
        response = self.client.post(
            "/api/auth/login",
            headers={"X-Forwarded-Proto": "https"},
            json={"username": "overrideuser", "password": "correct-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Secure", response.headers["set-cookie"])

    def test_login_rate_limit_returns_retry_after(self):
        user = auth_store.create_user("loginuser", "correct-password")
        self.set_env("VF_AUTH_COOKIE_SECURE", "false")
        auth_store.LOGIN_IP_MAX_ATTEMPTS = 2
        auth_store.LOGIN_USERNAME_MAX_ATTEMPTS = 2

        for _ in range(2):
            response = self.client.post(
                "/api/auth/login",
                json={"username": "loginuser", "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 401)

        response = self.client.post(
            "/api/auth/login",
            json={"username": user["username"], "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 429)
        self.assertGreaterEqual(int(response.headers["Retry-After"]), 1)

    def test_expired_sessions_are_cleaned_without_schema_changes(self):
        user = auth_store.create_user("sessionuser", "correct-password")
        expired_token, _ = auth_store.create_session(user["id"])
        active_token, _ = auth_store.create_session(user["id"])

        set_session_expires_at(
            auth_store._hash_token(expired_token),
            "2000-01-01T00:00:00+00:00",
        )

        auth_store.cleanup_sessions(force=True)

        self.assertIsNone(auth_store.get_user_by_session_token(expired_token))
        self.assertIsNotNone(auth_store.get_user_by_session_token(active_token))

    def test_session_count_is_bounded_per_user(self):
        user = auth_store.create_user("boundeduser", "correct-password")
        self.set_env("VF_AUTH_MAX_SESSIONS_PER_USER", "2")

        auth_store.create_session(user["id"])
        auth_store.create_session(user["id"])
        auth_store.create_session(user["id"])

        self.assertEqual(count_sessions(user["id"]), 2)

    def test_user_can_change_password_and_old_sessions_are_revoked(self):
        self.set_env("VF_AUTH_COOKIE_SECURE", "false")
        user = auth_store.create_user("changeuser", "old-password")
        old_token, _ = auth_store.create_session(user["id"])
        self.client.cookies.set("vf_session", old_token)

        response = self.client.put(
            "/api/auth/password",
            json={"current_password": "old-password", "new_password": "new-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["reauthenticate"])
        self.assertIsNone(auth_store.get_user_by_session_token(old_token))
        self.assertIsNotNone(auth_store.authenticate_user("changeuser", "new-password"))
        self.assertIsNone(auth_store.authenticate_user("changeuser", "old-password"))

    def test_user_password_change_rejects_wrong_or_reused_password(self):
        self.set_env("VF_AUTH_COOKIE_SECURE", "false")
        user = auth_store.create_user("changeuser", "old-password")
        token, _ = auth_store.create_session(user["id"])
        self.client.cookies.set("vf_session", token)

        wrong = self.client.put(
            "/api/auth/password",
            json={"current_password": "wrong-password", "new_password": "new-password"},
        )
        self.assertEqual(wrong.status_code, 401)

        reused = self.client.put(
            "/api/auth/password",
            json={"current_password": "old-password", "new_password": "old-password"},
        )
        self.assertEqual(reused.status_code, 422)


if __name__ == "__main__":
    unittest.main()
