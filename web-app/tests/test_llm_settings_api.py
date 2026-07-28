from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import digital_human as settings_api
from app.api.auth import require_current_user


class LLMSettingsApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(settings_api.router, prefix="/api")
        app.dependency_overrides[require_current_user] = lambda: {
            "id": "admin-id",
            "username": "admin",
            "display_name": "管理员",
        }
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_connection_uses_unsaved_form_values(self):
        test_connection = AsyncMock(return_value="OK")
        with patch.object(
            settings_api.settings_store,
            "get_llm_settings",
            return_value={
                "base_url": "https://saved.example/v1",
                "api_key": "saved-key",
                "model": "saved-model",
            },
        ), patch.object(settings_api.llm_service, "test_connection", test_connection):
            response = self.client.post(
                "/api/settings/llm/test",
                json={
                    "base_url": "https://draft.example/v1",
                    "api_key": "draft-key",
                    "model": "draft-model",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        config = test_connection.await_args.args[0]
        self.assertEqual(config.base_url, "https://draft.example/v1")
        self.assertEqual(config.api_key, "draft-key")
        self.assertEqual(config.model, "draft-model")

    def test_connection_reuses_saved_key_when_key_field_is_empty(self):
        test_connection = AsyncMock(return_value="OK")
        with patch.object(
            settings_api.settings_store,
            "get_llm_settings",
            return_value={
                "base_url": "https://saved.example/v1",
                "api_key": "saved-key",
                "model": "saved-model",
            },
        ), patch.object(settings_api.llm_service, "test_connection", test_connection):
            response = self.client.post(
                "/api/settings/llm/test",
                json={
                    "base_url": "https://draft.example/v1",
                    "model": "draft-model",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        config = test_connection.await_args.args[0]
        self.assertEqual(config.api_key, "saved-key")


if __name__ == "__main__":
    unittest.main()
