"""Compatibility entry point for `uvicorn main:app`."""

from __future__ import annotations

from app.core.config import app_config
from app.main import app, create_app


if __name__ == "__main__":
    import uvicorn

    cfg = app_config["server"]
    uvicorn.run(
        "main:app",
        host=cfg.get("host", "0.0.0.0"),
        port=cfg.get("port", 18888),
        reload=True,
    )
