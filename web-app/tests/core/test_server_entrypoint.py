from __future__ import annotations

import uvicorn


def test_run_server_leaves_proxy_headers_to_application_middleware(monkeypatch) -> None:
    import main as server_entrypoint

    captured: dict[str, object] = {}

    def fake_run(app: str, **options: object) -> None:
        captured["app"] = app
        captured.update(options)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setenv("VIDEO_FACTORY_HOST", "127.0.0.2")
    monkeypatch.setenv("VIDEO_FACTORY_PORT", "19999")
    monkeypatch.setenv("VIDEO_FACTORY_ENV", "production")
    monkeypatch.setenv("VIDEO_FACTORY_RELOAD", "0")

    server_entrypoint.run_server()

    assert captured == {
        "app": "main:app",
        "host": "127.0.0.2",
        "port": 19999,
        "reload": False,
        "proxy_headers": False,
    }
