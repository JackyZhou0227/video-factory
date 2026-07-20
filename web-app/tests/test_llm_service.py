from __future__ import annotations

import unittest

import httpx

from app.services.llm import LLMConfig, LLMMessage, LLMServiceError
from app.services.llm.providers.openai_compatible import OpenAICompatibleProvider


class OpenAICompatibleProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_joins_endpoint_and_sends_auth(self):
        captured = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization")
            captured["json"] = request.content.decode("utf-8")
            return httpx.Response(200, json={"choices": [{"message": {"content": "  OK  "}}]})

        provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handler))
        result = await provider.generate(
            LLMConfig(base_url="https://llm.example/v1/", api_key="secret", model="demo-model"),
            [LLMMessage(role="user", content="hello")],
        )

        self.assertEqual(result, "OK")
        self.assertEqual(captured["url"], "https://llm.example/v1/chat/completions")
        self.assertEqual(captured["auth"], "Bearer secret")
        self.assertIn('"model":"demo-model"', captured["json"].replace(" ", ""))

    async def test_invalid_url_is_rejected_without_request(self):
        provider = OpenAICompatibleProvider()
        with self.assertRaisesRegex(LLMServiceError, "base_url"):
            await provider.generate(
                LLMConfig(base_url="not-a-url", api_key="", model="demo"),
                [LLMMessage(role="user", content="hello")],
            )

    async def test_http_error_does_not_include_api_key(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": "invalid credential"}})

        provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handler))
        with self.assertRaises(LLMServiceError) as context:
            await provider.generate(
                LLMConfig(base_url="https://llm.example/v1", api_key="top-secret", model="demo"),
                [LLMMessage(role="user", content="hello")],
            )
        self.assertNotIn("top-secret", str(context.exception))


if __name__ == "__main__":
    unittest.main()
