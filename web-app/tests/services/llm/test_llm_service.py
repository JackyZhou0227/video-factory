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

    async def test_private_ip_target_is_rejected(self):
        provider = OpenAICompatibleProvider(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
        with self.assertRaisesRegex(LLMServiceError, "不允许访问回环、私网"):
            await provider.generate(
                LLMConfig(base_url="http://127.0.0.1:8080/v1", api_key="", model="demo"),
                [LLMMessage(role="user", content="hello")],
            )

    async def test_private_hostname_is_rejected(self):
        provider = OpenAICompatibleProvider(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
        with self.assertRaisesRegex(LLMServiceError, "不允许使用本机或局域网"):
            await provider.generate(
                LLMConfig(base_url="http://localhost:8080/v1", api_key="", model="demo"),
                [LLMMessage(role="user", content="hello")],
            )

    async def test_url_credentials_are_rejected(self):
        provider = OpenAICompatibleProvider(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
        with self.assertRaisesRegex(LLMServiceError, "不允许包含用户名或密码"):
            await provider.generate(
                LLMConfig(base_url="https://user:password@example.com/v1", api_key="", model="demo"),
                [LLMMessage(role="user", content="hello")],
            )

    async def test_http_error_does_not_include_api_key(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": "invalid credential: top-secret"}})

        provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handler))
        with self.assertRaises(LLMServiceError) as context:
            await provider.generate(
                LLMConfig(base_url="https://llm.example/v1", api_key="top-secret", model="demo"),
                [LLMMessage(role="user", content="hello")],
            )
        self.assertNotIn("top-secret", str(context.exception))

    async def test_connection_refused_has_actionable_safe_message(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("[WinError 10061] connection refused", request=request)

        provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handler))
        with self.assertRaises(LLMServiceError) as context:
            await provider.generate(
                LLMConfig(base_url="https://llm.example/v1", api_key="top-secret", model="demo"),
                [LLMMessage(role="user", content="hello")],
            )

        message = str(context.exception)
        self.assertIn("拒绝连接", message)
        self.assertIn("llm.example:443", message)
        self.assertNotIn("top-secret", message)

    async def test_dns_failure_is_identified(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=request)

        provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handler))
        with self.assertRaisesRegex(LLMServiceError, "无法解析 LLM 服务域名"):
            await provider.generate(
                LLMConfig(base_url="https://missing.example/v1", api_key="", model="demo"),
                [LLMMessage(role="user", content="hello")],
            )

    async def test_connect_timeout_mentions_network_and_proxy(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("", request=request)

        provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handler))
        with self.assertRaises(LLMServiceError) as context:
            await provider.generate(
                LLMConfig(base_url="https://slow.example/v1", api_key="", model="demo"),
                [LLMMessage(role="user", content="hello")],
            )

        self.assertIn("连接 LLM 服务超时", str(context.exception))
        self.assertIn("代理", str(context.exception))


if __name__ == "__main__":
    unittest.main()
