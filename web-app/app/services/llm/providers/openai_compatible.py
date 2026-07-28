from __future__ import annotations

import ssl
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
        try:
            parsed.port
        except ValueError as exc:
            raise LLMServiceError("LLM base_url 包含无效端口") from exc
        if value.endswith("/chat/completions"):
            return value
        return f"{value}/chat/completions"

    @staticmethod
    def _target_label(endpoint: str) -> str:
        parsed = urlparse(endpoint)
        host = parsed.hostname or "未知地址"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return f"{host}:{port}"

    @staticmethod
    def _exception_text(exc: BaseException) -> str:
        parts: list[str] = []
        current: BaseException | None = exc
        while current is not None and len(parts) < 6:
            parts.append(str(current).lower())
            current = current.__cause__
        return " ".join(parts)

    @classmethod
    def _connect_error_message(cls, exc: httpx.ConnectError, target: str) -> str:
        detail = cls._exception_text(exc)
        if isinstance(exc.__cause__, ssl.SSLError) or any(
            marker in detail for marker in ("certificate verify failed", "ssl", "tls")
        ):
            return f"LLM 服务 TLS 证书验证失败（{target}），请检查证书或服务地址"
        if any(marker in detail for marker in ("getaddrinfo", "name or service not known", "nodename nor servname")):
            return f"无法解析 LLM 服务域名（{target}），请检查 Base URL 或 DNS"
        if any(marker in detail for marker in ("connection refused", "actively refused", "winerror 10061")):
            return f"LLM 服务拒绝连接（{target}），请确认服务已启动且端口正确"
        if any(marker in detail for marker in ("network is unreachable", "no route to host", "winerror 10051", "winerror 10065")):
            return f"无法访问 LLM 服务所在网络（{target}），请检查网络或代理设置"
        return f"无法连接 LLM 服务（{target}），请检查 Base URL、服务端口、网络或后端代理设置"

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
        endpoint = self._endpoint(config.base_url)
        target = self._target_label(endpoint)

        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.ConnectTimeout as exc:
            raise LLMServiceError(
                f"连接 LLM 服务超时（{target}），请检查服务地址、网络或后端代理设置"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMServiceError(f"LLM 请求超时（{target}），请稍后重试") from exc
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                body = exc.response.json()
                detail = str(body.get("error", {}).get("message") or body.get("detail") or "")
            except (ValueError, AttributeError):
                detail = ""
            if config.api_key:
                detail = detail.replace(config.api_key, "***")
            suffix = f"：{detail[:300]}" if detail else ""
            raise LLMServiceError(f"LLM 服务返回 HTTP {exc.response.status_code}{suffix}") from exc
        except httpx.ProxyError as exc:
            raise LLMServiceError(
                f"LLM 代理连接失败（{target}），请检查后端进程的 HTTP_PROXY 或 HTTPS_PROXY"
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMServiceError(self._connect_error_message(exc, target)) from exc
        except httpx.RequestError as exc:
            raise LLMServiceError(f"LLM 网络请求失败（{target}）：{exc.__class__.__name__}") from exc

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMServiceError("LLM 响应缺少 choices[0].message.content") from exc

        result = str(content or "").strip()
        if not result:
            raise LLMServiceError("LLM 返回了空内容")
        return result
