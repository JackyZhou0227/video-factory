from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.services import auth_store, settings_store


class AuthSecurityTests(unittest.TestCase):
    ENV_NAMES = (
        "VF_AUTH_REGISTRATION_ENABLED",
        "VF_AUTH_ALLOW_FIRST_USER_ADMIN",
        "VF_AUTH_COOKIE_SECURE",
        "VF_AUTH_COOKIE_SAMESITE",
        "VF_AUTH_SESSION_MAX_AGE_SECONDS",
        "VF_AUTH_MAX_SESSIONS_PER_USER",
    )

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = settings_store._db_path
        self.original_limits = {
            name: getattr(auth_store, name)
            for name in (
                "LOGIN_IP_MAX_ATTEMPTS",
                "LOGIN_USERNAME_MAX_ATTEMPTS",
                "REGISTER_IP_MAX_ATTEMPTS",
                "REGISTER_USERNAME_MAX_ATTEMPTS",
            )
        }
        self.original_env = {name: os.environ.get(name) for name in self.ENV_NAMES}
        settings_store._db_path = lambda: Path(self.temp_dir.name) / "auth.db"
        settings_store.init_db()
        auth_store.init_auth_schema()
        auth_store.reset_rate_limits()

        self.app = FastAPI()
        self.app.include_router(auth_router, prefix="/api")
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        auth_store.reset_rate_limits()
        for name, value in self.original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        for name, value in self.original_limits.items():
            setattr(auth_store, name, value)
        settings_store._db_path = self.original_db_path
        self.temp_dir.cleanup()

    def set_env(self, name: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

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

        response = self.client.post(
            "/api/auth/register",
            json={"username": "newuser", "password": "correct-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["user"]["is_admin"])

        second_response = self.client.post(
            "/api/auth/register",
            json={"username": "seconduser", "password": "correct-password"},
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertFalse(second_response.json()["user"]["is_admin"])

    def test_cookie_security_attributes_are_configurable(self):
        self.set_env("VF_AUTH_REGISTRATION_ENABLED", "true")
        self.set_env("VF_AUTH_COOKIE_SECURE", "true")
        self.set_env("VF_AUTH_COOKIE_SAMESITE", "strict")

        response = self.client.post(
            "/api/auth/register",
            json={"username": "cookieuser", "password": "correct-password"},
        )

        cookie = response.headers["set-cookie"]
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)

    def test_cookie_secure_follows_local_http_by_default(self):
        self.set_env("VF_AUTH_REGISTRATION_ENABLED", "true")
        self.set_env("VF_AUTH_COOKIE_SECURE", None)

        response = self.client.post(
            "/api/auth/register",
            json={"username": "httpuser", "password": "correct-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Secure", response.headers["set-cookie"])

    def test_cookie_secure_follows_forwarded_https_by_default(self):
        self.set_env("VF_AUTH_REGISTRATION_ENABLED", "true")
        self.set_env("VF_AUTH_COOKIE_SECURE", None)

        response = self.client.post(
            "/api/auth/register",
            headers={"X-Forwarded-Proto": "https"},
            json={"username": "httpsuser", "password": "correct-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers["set-cookie"])

    def test_cookie_secure_environment_override_wins(self):
        self.set_env("VF_AUTH_REGISTRATION_ENABLED", "true")
        self.set_env("VF_AUTH_COOKIE_SECURE", "false")

        response = self.client.post(
            "/api/auth/register",
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

        with auth_store._connect() as conn:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                ("2000-01-01T00:00:00+00:00", auth_store._hash_token(expired_token)),
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

        with auth_store._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM sessions WHERE user_id = ?",
                (user["id"],),
            ).fetchone()

        self.assertEqual(row["total"], 2)


if __name__ == "__main__":
    unittest.main()
