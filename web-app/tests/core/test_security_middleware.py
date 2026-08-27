from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import install_security_middleware


def make_app(**security_overrides: object) -> FastAPI:
    application = FastAPI()
    config = {
        "server": {"environment": "development"},
        "security": {
            "allowed_hosts": ["testserver"],
            "cors_allowed_origins": ["http://localhost:5173"],
            "max_request_body_bytes": 1024,
            **security_overrides,
        },
    }
    install_security_middleware(application, config)

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/csrf-token")
    def csrf_token() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/echo")
    async def echo(payload: dict[str, str]) -> dict[str, str]:
        return payload

    return application


def test_security_headers_and_trusted_host() -> None:
    client = TestClient(make_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400


def test_cors_is_allow_listed() -> None:
    client = TestClient(make_app())

    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_request_body_limit_returns_413() -> None:
    client = TestClient(make_app(max_request_body_bytes=4))

    response = client.post("/echo", json={"value": "too large"})

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body is too large"


def test_csrf_validates_unsafe_requests() -> None:
    client = TestClient(make_app(csrf_enabled=True, max_request_body_bytes=4096))

    token_response = client.get("/csrf-token")
    csrf_token = token_response.cookies["vf_csrf"]

    assert client.post("/echo", json={"value": "blocked"}).status_code == 403
    accepted = client.post(
        "/echo",
        json={"value": "accepted"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert accepted.status_code == 200
    assert accepted.json() == {"value": "accepted"}
