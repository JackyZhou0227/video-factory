from __future__ import annotations

import asyncio
import os
import unittest
from dataclasses import replace

from captchakit import MemoryStorage, TextChallengeFactory
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.api.auth import router as auth_router
from app.services import auth_store, settings_store
from tests.pg_test_utils import count_sessions, set_session_expires_at, with_captcha


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
        self.original_captcha_storage = auth_api.captcha_manager.storage
        auth_api.captcha_manager.storage = MemoryStorage()
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
        auth_api.captcha_manager.storage = self.original_captcha_storage
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

    def issue_captcha(self) -> tuple[str, str]:
        response = self.client.post("/api/auth/captcha/new")
        self.assertEqual(response.status_code, 200, response.text)
        challenge_id = response.json()["id"]
        challenge = asyncio.run(auth_api.captcha_manager.storage.get(challenge_id))
        return challenge_id, challenge.solution

    def auth_payload(self, username: str, password: str) -> dict[str, str]:
        return with_captcha(self.client, {"username": username, "password": password})

    def test_captcha_endpoint_returns_classic_png_data_url(self):
        response = self.client.post("/api/auth/captcha/new")
        self.assertEqual(response.status_code, 200, response.text)
        challenge = response.json()
        self.assertTrue(challenge["image"].startswith("data:image/png;base64,"))
        self.assertIn("id", challenge)

    def test_captcha_issue_is_rate_limited_by_client_ip(self):
        old_limit = auth_store.CAPTCHA_IP_MAX_ATTEMPTS
        auth_store.CAPTCHA_IP_MAX_ATTEMPTS = 1
        try:
            self.assertEqual(self.client.post("/api/auth/captcha/new").status_code, 200)

            response = self.client.post("/api/auth/captcha/new")

            self.assertEqual(response.status_code, 429)
            self.assertGreaterEqual(int(response.headers["Retry-After"]), 1)
        finally:
            auth_store.CAPTCHA_IP_MAX_ATTEMPTS = old_limit

    def test_expired_captcha_challenges_can_be_cleaned_without_new_requests(self):
        challenge_id, _ = self.issue_captcha()
        challenge = asyncio.run(auth_api.captcha_manager.storage.get(challenge_id))
        asyncio.run(
            auth_api.captcha_manager.storage.put(
                replace(challenge, expires_at=0)
            )
        )

        removed = asyncio.run(auth_api.cleanup_expired_captcha_challenges())

        self.assertEqual(removed, 1)
        self.assertEqual(asyncio.run(auth_api.captcha_manager.storage.size()), 0)

    def test_captcha_challenge_count_has_a_hard_cap(self):
        old_limit = auth_api.MAX_ACTIVE_CAPTCHA_CHALLENGES
        auth_api.MAX_ACTIVE_CAPTCHA_CHALLENGES = 1
        try:
            self.assertEqual(self.client.post("/api/auth/captcha/new").status_code, 200)

            response = self.client.post("/api/auth/captcha/new")

            self.assertEqual(response.status_code, 429)
            self.assertEqual(asyncio.run(auth_api.captcha_manager.storage.size()), 1)
        finally:
            auth_api.MAX_ACTIVE_CAPTCHA_CHALLENGES = old_limit

    def test_captcha_answer_is_case_insensitive(self):
        original_factory = auth_api.captcha_manager.factory
        auth_api.captcha_manager.factory = TextChallengeFactory(length=5, case_sensitive=True)
        try:
            challenge_id, answer = self.issue_captcha()
            response = self.client.post(
                "/api/auth/login",
                json={
                    "username": "nobody",
                    "password": "correct-password",
                    "captcha_id": challenge_id,
                    "captcha_answer": answer.swapcase(),
                },
            )
        finally:
            auth_api.captcha_manager.factory = original_factory

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "用户名或密码不正确")

    def test_login_rejects_missing_or_wrong_captcha(self):
        auth_store.create_user("captchauser", "correct-password")
        missing = self.client.post(
            "/api/auth/login",
            json={"username": "captchauser", "password": "correct-password"},
        )
        self.assertEqual(missing.status_code, 422)

        challenge_id, _ = self.issue_captcha()
        wrong = self.client.post(
            "/api/auth/login",
            json={
                "username": "captchauser",
                "password": "correct-password",
                "captcha_id": challenge_id,
                "captcha_answer": "WRONG",
            },
        )
        self.assertEqual(wrong.status_code, 403)
        self.assertNotIn("vf_session", wrong.headers.get("set-cookie", ""))
        self.assertEqual(count_sessions(auth_store.authenticate_user("captchauser", "correct-password")["id"]), 0)

    def test_login_requires_fresh_captcha_and_still_rejects_wrong_password(self):
        self.set_env("VF_AUTH_COOKIE_SECURE", "false")
        auth_store.create_user("captchauser", "correct-password")
        payload = self.auth_payload("captchauser", "correct-password")

        response = self.client.post(
            "/api/auth/login",
            json=payload,
        )
        self.assertEqual(response.status_code, 200, response.text)

        reused = self.client.post(
            "/api/auth/login",
            json=payload,
        )
        self.assertEqual(reused.status_code, 404)

        invalid_password = self.client.post(
            "/api/auth/login",
            json=self.auth_payload("captchauser", "wrong-password"),
        )
        self.assertEqual(invalid_password.status_code, 401)

    def test_register_rejects_invalid_captcha_without_creating_user(self):
        self.set_env("VF_AUTH_REGISTRATION_ENABLED", "true")
        org_id = auth_store.create_organization("验证码测试组")["id"]
        missing = self.client.post(
            "/api/auth/register",
            json={"username": "captcha-register", "password": "correct-password", "org_id": org_id},
        )
        self.assertEqual(missing.status_code, 422)

        challenge_id, _ = self.issue_captcha()

        response = self.client.post(
            "/api/auth/register",
            json={
                "username": "captcha-register",
                "password": "correct-password",
                "org_id": org_id,
                "captcha_id": challenge_id,
                "captcha_answer": "WRONG",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            any(user["username"] == "captcha-register" for user in auth_store.list_users()["items"])
        )

    def test_expired_and_exhausted_captcha_are_rejected(self):
        challenge_id, answer = self.issue_captcha()
        challenge = asyncio.run(auth_api.captcha_manager.storage.get(challenge_id))
        asyncio.run(
            auth_api.captcha_manager.storage.put(
                replace(challenge, expires_at=0)
            )
        )
        expired = self.client.post(
            "/api/auth/login",
            json={
                "username": "nobody",
                "password": "correct-password",
                "captcha_id": challenge_id,
                "captcha_answer": answer,
            },
        )
        self.assertEqual(expired.status_code, 410)

        challenge_id, _ = self.issue_captcha()
        for expected_status in (403, 403, 429):
            response = self.client.post(
                "/api/auth/login",
                json={
                    "username": "nobody",
                    "password": "correct-password",
                    "captcha_id": challenge_id,
                    "captcha_answer": "WRONG",
                },
            )
            self.assertEqual(response.status_code, expected_status)

    def test_registration_is_disabled_by_default(self):
        self.set_env("VF_AUTH_REGISTRATION_ENABLED", None)

        response = self.client.post(
            "/api/auth/register",
            json=with_captcha(self.client, {"username": "newuser", "password": "correct-password"}),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "当前未开放注册")

    def test_registration_can_be_enabled_and_first_user_is_not_admin(self):
        self.set_env("VF_AUTH_REGISTRATION_ENABLED", "true")
        self.set_env("VF_AUTH_COOKIE_SECURE", "false")

        org_id = auth_store.create_organization("默认组织")["id"]

        response = self.client.post(
            "/api/auth/register",
            json=with_captcha(
                self.client,
                {"username": "newuser", "password": "correct-password", "org_id": org_id},
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["pending"])
        self.assertFalse(response.json()["user"]["is_admin"])
        self.assertEqual(response.json()["user"]["status"], "pending")

        second_response = self.client.post(
            "/api/auth/register",
            json=with_captcha(
                self.client,
                {"username": "seconduser", "password": "correct-password", "org_id": org_id},
            ),
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
            json=self.auth_payload("cookieuser", "correct-password"),
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
            json=self.auth_payload("httpuser", "correct-password"),
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
            json=self.auth_payload("httpsuser", "correct-password"),
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
            json=self.auth_payload("overrideuser", "correct-password"),
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
                json=self.auth_payload("loginuser", "wrong-password"),
            )
            self.assertEqual(response.status_code, 401)

        response = self.client.post(
            "/api/auth/login",
            json=self.auth_payload(user["username"], "wrong-password"),
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
