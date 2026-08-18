"""Compatibility entry point for `uvicorn main:app`."""

from __future__ import annotations

import os

from app.core.config import app_config
from app.main import app, create_app


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    import uvicorn

    cfg = app_config.get("server") or {}
    environment = (
        os.getenv("VIDEO_FACTORY_ENV")
        or cfg.get("environment")
        or "production"
    ).strip().lower()
    is_development = environment in {"dev", "development", "local"}
    configured_reload = _as_bool(
        os.getenv("VIDEO_FACTORY_RELOAD"),
        _as_bool(str(cfg.get("reload", "false"))),
    )
    uvicorn.run(
        "main:app",
        host=os.getenv("VIDEO_FACTORY_HOST") or cfg.get("host", "127.0.0.1"),
        port=cfg.get("port", 18888),
        reload=is_development and configured_reload,
    )
