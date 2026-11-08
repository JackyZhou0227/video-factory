from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException

from app.services import settings_store

WORKFLOWS: tuple[dict[str, Any], ...] = (
    {
        "key": "digital-human-lipsync",
        "name": "数字人口播",
        "provider": "runninghub",
        "workflow_id": settings_store.FIXED_DIGITAL_HUMAN_WORKFLOW_ID,
        "inputs": (
            {
                "key": "image",
                "label": "人物形象图片",
                "type": "image",
                "required": True,
                "extensions": (".jpg", ".jpeg", ".png", ".webp", ".bmp"),
                "accept": "image/jpeg,image/png,image/webp,image/bmp",
                "runninghub_parameter": "videoimage",
            },
            {
                "key": "audio",
                "label": "口播音频",
                "type": "audio",
                "required": True,
                "extensions": (".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"),
                "accept": "audio/*",
                "runninghub_parameter": "audio",
            },
        ),
    },
)


def list_public_workflows() -> list[dict[str, Any]]:
    return [
        {
            "key": workflow["key"],
            "name": workflow["name"],
            "provider": workflow["provider"],
            "inputs": [
                {
                    key: list(value) if key == "extensions" else value
                    for key, value in field.items()
                    if key not in {"runninghub_parameter", "extensions"}
                }
                for field in workflow["inputs"]
            ],
        }
        for workflow in WORKFLOWS
    ]


def get_workflow(key: str) -> dict[str, Any]:
    for workflow in WORKFLOWS:
        if workflow["key"] == key:
            return workflow
    raise HTTPException(status_code=404, detail="工作流不存在")


def validate_scalar_inputs(
    workflow: dict[str, Any],
    values: dict[str, Any],
) -> dict[str, Any]:
    declarations = {
        field["key"]: field
        for field in workflow["inputs"]
        if field["type"] in {"text", "number", "select"}
    }
    unknown = set(values) - declarations.keys()
    if unknown:
        raise HTTPException(status_code=422, detail=f"未知工作流参数：{', '.join(sorted(unknown))}")

    normalized: dict[str, Any] = {}
    for key, field in declarations.items():
        value = values.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if field.get("required"):
                raise HTTPException(status_code=422, detail=f"请填写{field['label']}")
            if "default" in field:
                normalized[key] = field["default"]
            continue

        if field["type"] == "text":
            value = str(value)
            if len(value) > int(field.get("max_length", 10000)):
                raise HTTPException(status_code=422, detail=f"{field['label']}过长")
        elif field["type"] == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"{field['label']}必须是数字") from None
            if not math.isfinite(value):
                raise HTTPException(status_code=422, detail=f"{field['label']}必须是有限数字")
            if "min" in field and value < field["min"]:
                raise HTTPException(status_code=422, detail=f"{field['label']}不能小于 {field['min']}")
            if "max" in field and value > field["max"]:
                raise HTTPException(status_code=422, detail=f"{field['label']}不能大于 {field['max']}")
        elif field["type"] == "select":
            if value not in field.get("options", []):
                raise HTTPException(status_code=422, detail=f"{field['label']}选项无效")
        else:
            raise HTTPException(status_code=500, detail=f"工作流输入类型未实现：{field['type']}")
        normalized[key] = value

    return normalized
