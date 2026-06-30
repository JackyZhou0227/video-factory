from __future__ import annotations

from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class RunningHubSettingsUpdate(BaseModel):
    api_key: Optional[str] = None
    concurrent_limit: Optional[int] = Field(default=None, ge=1, le=10)
    instance_type: Optional[str] = None


def _get_config_refs():
    """Import config lazily to avoid circular imports."""
    from main import app_config, config_path

    return app_config, config_path


def _mask_api_key(api_key: str | None) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}{'*' * max(len(api_key) - 8, 4)}{api_key[-4:]}"


def _runninghub_payload(runninghub_config: dict) -> dict:
    api_key = runninghub_config.get("api_key") or ""
    return {
        "api_key_configured": bool(api_key),
        "masked_api_key": _mask_api_key(api_key),
        "concurrent_limit": runninghub_config.get("concurrent_limit", 1),
        "instance_type": runninghub_config.get("instance_type") or "",
    }


@router.get("/settings/runninghub")
def get_runninghub_settings():
    app_config, _ = _get_config_refs()
    runninghub_config = app_config.setdefault("runninghub", {})
    return _runninghub_payload(runninghub_config)


@router.put("/settings/runninghub")
def update_runninghub_settings(payload: RunningHubSettingsUpdate):
    app_config, path = _get_config_refs()
    runninghub_config = app_config.setdefault("runninghub", {})

    if payload.api_key is not None and payload.api_key.strip():
        runninghub_config["api_key"] = payload.api_key.strip()

    if payload.concurrent_limit is not None:
        runninghub_config["concurrent_limit"] = payload.concurrent_limit

    if payload.instance_type is not None:
        normalized_instance_type = payload.instance_type.strip()
        runninghub_config["instance_type"] = normalized_instance_type or None

    try:
        path.write_text(
            yaml.safe_dump(app_config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {exc}") from exc

    return _runninghub_payload(runninghub_config)
