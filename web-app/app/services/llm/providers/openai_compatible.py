from __future__ import annotations

from typing import Sequence
from urllib.parse import urlparse

import httpx

from app.services.llm.base import LLMConfig, LLMMessage, LLMServiceError


class OpenAICompatibleProvider:
    provider_id = "openai_compatible"

    def __init__(self, *, timeout_seconds: float = 90.0, transport: httpx.AsyncBaseTransport | None = None):
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    @staticmethod
    def _endpoint(base_url: str) -> str:
        value = str(base_url or "").strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise LLMServiceError("LLM base_url 必须是有效的 HTTP 或 HTTPS 地址")
        if value.endswith("/chat/completions"):
            return value
        return f"{value}/chat/completions"

    async def generate(
        self,
        config: LLMConfig,
        messages: Sequence[LLMMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        if not config.model.strip():
            raise LLMServiceError("请先配置 LLM 模型名称")
        if not messages:
            raise LLMServiceError("LLM 消息不能为空")

        headers = {"Content-Type": "application/json"}
        if config.api_key.strip():
            headers["Authorization"] = f"Bearer {config.api_key.strip()}"

        payload = {
            "model": config.model.strip(),
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "temperature": max(0.0, min(2.0, float(temperature))),
            "max_tokens": max(1, min(8192, int(max_tokens))),
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(self._endpoint(config.base_url), headers=headers, json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMServiceError("LLM 请求超时，请检查服务地址或稍后重试") from exc
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                body = exc.response.json()
                detail = str(body.get("error", {}).get("message") or body.get("detail") or "")
            except (ValueError, AttributeError):
                detail = ""
            suffix = f"：{detail[:300]}" if detail else ""
            raise LLMServiceError(f"LLM 服务返回 HTTP {exc.response.status_code}{suffix}") from exc
        except httpx.HTTPError as exc:
            raise LLMServiceError(f"无法连接 LLM 服务：{exc.__class__.__name__}") from exc

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMServiceError("LLM 响应缺少 choices[0].message.content") from exc

        result = str(content or "").strip()
        if not result:
            raise LLMServiceError("LLM 返回了空内容")
        return result
