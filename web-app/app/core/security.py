from __future__ import annotations

import json
import os
import secrets
from collections.abc import Awaitable, Callable
from http.cookies import SimpleCookie
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

ASGIApp = Callable[[dict[str, Any], Callable[..., Awaitable[dict[str, Any]]], Callable[..., Awaitable[None]]], Awaitable[None]]

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DEFAULT_LOCAL_CORS_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return default
    return bool(value)


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _environment(config: dict[str, Any]) -> str:
    security = config.get("security") or {}
    server = config.get("server") or {}
    return (
        os.getenv("VIDEO_FACTORY_ENV")
        or security.get("environment")
        or server.get("environment")
        or "production"
    ).strip().lower()


def get_security_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Return normalized global security settings with safe defaults."""

    security = config.get("security") or {}
    environment = _environment(config)
    is_development = environment in {"dev", "development", "local"}

    configured_hosts = _as_list(security.get("allowed_hosts"))
    if configured_hosts:
        allowed_hosts = configured_hosts
    elif is_development:
        allowed_hosts = ["127.0.0.1", "localhost", "testserver"]
    else:
        # A public hostname must be explicitly configured. Binding to 0.0.0.0
        # is a listen address, not a valid Host header to trust.
        allowed_hosts = ["127.0.0.1", "localhost"]

    configured_origins = _as_list(security.get("cors_allowed_origins"))
    if configured_origins:
        cors_allowed_origins = configured_origins
    elif is_development:
        cors_allowed_origins = DEFAULT_LOCAL_CORS_ORIGINS.copy()
    else:
        # The bundled production frontend is same-origin, so it does not need
        # CORS. Public cross-origin clients must be explicitly allow-listed.
        cors_allowed_origins = []

    try:
        max_request_body_bytes = int(security.get("max_request_body_bytes", 512 * 1024 * 1024))
    except (TypeError, ValueError):
        max_request_body_bytes = 512 * 1024 * 1024
    max_request_body_bytes = max(1, max_request_body_bytes)

    csrf_exempt_paths = _as_list(security.get("csrf_exempt_paths")) or ["/api/health"]

    return {
        "environment": environment,
        "allowed_hosts": allowed_hosts,
        "cors_allowed_origins": cors_allowed_origins,
        "max_request_body_bytes": max_request_body_bytes,
        "csrf_enabled": _as_bool(security.get("csrf_enabled"), False),
        "csrf_cookie_name": str(security.get("csrf_cookie_name") or "vf_csrf"),
        "csrf_header_name": str(security.get("csrf_header_name") or "x-csrf-token").lower(),
        "csrf_cookie_secure": _as_bool(security.get("csrf_cookie_secure"), not is_development),
        "csrf_cookie_samesite": str(security.get("csrf_cookie_samesite") or "lax").lower(),
        "csrf_exempt_paths": csrf_exempt_paths,
        "hsts_enabled": _as_bool(security.get("hsts_enabled"), False),
        "content_security_policy": str(security.get("content_security_policy") or "").strip(),
    }


async def _send_json(send: Callable[..., Awaitable[None]], status_code: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestBodyTooLarge(Exception):
    pass


class RequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[dict[str, Any]]], send: Callable[..., Awaitable[None]]) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_body_bytes:
                    await _send_json(send, 413, "Request body is too large")
                    return
            except ValueError:
                pass

        received_bytes = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received_bytes
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body") or b"")
                if received_bytes > self.max_body_bytes:
                    raise RequestBodyTooLarge
            return message

        response_started = False

        async def tracked_send(message: dict[str, Any]) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if not response_started:
                await _send_json(send, 413, "Request body is too large")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts_enabled: bool = False, content_security_policy: str = "") -> None:
        self.app = app
        self.hsts_enabled = hsts_enabled
        self.content_security_policy = content_security_policy

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[dict[str, Any]]], send: Callable[..., Awaitable[None]]) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = MutableHeaders(scope=message)
                default_headers = {
                    "x-content-type-options": "nosniff",
                    "x-frame-options": "DENY",
                    "referrer-policy": "strict-origin-when-cross-origin",
                    "permissions-policy": "camera=(), microphone=(), geolocation=()",
                    "cross-origin-resource-policy": "same-origin",
                }
                if self.hsts_enabled:
                    default_headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
                if self.content_security_policy:
                    default_headers["content-security-policy"] = self.content_security_policy
                for name, value in default_headers.items():
                    if name not in headers:
                        headers.append(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _cookie_value(scope: dict[str, Any], name: str) -> str:
    cookie_header = Headers(scope=scope).get("cookie", "")
    cookies = SimpleCookie()
    cookies.load(cookie_header)
    morsel = cookies.get(name)
    return morsel.value if morsel else ""


class CSRFMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool,
        cookie_name: str,
        header_name: str,
        cookie_secure: bool,
        cookie_samesite: str,
        exempt_paths: list[str],
    ) -> None:
        self.app = app
        self.enabled = enabled
        self.cookie_name = cookie_name
        self.header_name = header_name
        self.cookie_secure = cookie_secure
        self.cookie_samesite = cookie_samesite if cookie_samesite in {"lax", "strict", "none"} else "lax"
        self.exempt_paths = set(exempt_paths)

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[dict[str, Any]]], send: Callable[..., Awaitable[None]]) -> None:
        if scope.get("type") != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "").upper()
        path = str(scope.get("path") or "")
        if method not in SAFE_METHODS and path not in self.exempt_paths:
            expected = _cookie_value(scope, self.cookie_name)
            provided = Headers(scope=scope).get(self.header_name, "")
            if not expected or not provided or not secrets.compare_digest(expected, provided):
                await _send_json(send, 403, "CSRF validation failed")
                return

        existing_token = _cookie_value(scope, self.cookie_name)
        token_to_set = existing_token or secrets.token_urlsafe(32)

        async def send_with_csrf_cookie(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start" and not existing_token and path not in self.exempt_paths:
                headers = MutableHeaders(scope=message)
                cookie = f"{self.cookie_name}={token_to_set}; Path=/; SameSite={self.cookie_samesite}"
                if self.cookie_secure:
                    cookie += "; Secure"
                headers.append("set-cookie", cookie)
            await send(message)

        await self.app(scope, receive, send_with_csrf_cookie)


def install_security_middleware(application: Any, config: dict[str, Any]) -> dict[str, Any]:
    settings = get_security_settings(config)

    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings["allowed_hosts"],
    )
    application.add_middleware(
        RequestSizeLimitMiddleware,
        max_body_bytes=settings["max_request_body_bytes"],
    )
    application.add_middleware(
        CSRFMiddleware,
        enabled=settings["csrf_enabled"],
        cookie_name=settings["csrf_cookie_name"],
        header_name=settings["csrf_header_name"],
        cookie_secure=settings["csrf_cookie_secure"],
        cookie_samesite=settings["csrf_cookie_samesite"],
        exempt_paths=settings["csrf_exempt_paths"],
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings["cors_allowed_origins"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "Authorization", "X-CSRF-Token"],
    )
    application.add_middleware(
        SecurityHeadersMiddleware,
        hsts_enabled=settings["hsts_enabled"],
        content_security_policy=settings["content_security_policy"],
    )
    return settings
