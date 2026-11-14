from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.core.config import ROOT

# Workflow key -> selfhost workflow filename (without .json)
SELFHOST_WORKFLOW_MAPPING = {
    "text-to-image": "image_moss_image_t2i",
    "image-edit": "image_moss_image_edit",
}

WORKFLOWS: tuple[dict[str, Any], ...] = (
    {
        "key": "digital-human-lipsync",
        "name": "数字人对口型",
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
                "label": "对口型音频",
                "type": "audio",
                "required": True,
                "extensions": (".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"),
                "accept": "audio/*",
                "runninghub_parameter": "audio",
            },
        ),
    },
    {
        "key": "text-to-image",
        "name": "文生图",
        "generation_type": "image",
        "inputs": (
            {
                "key": "prompt",
                "label": "提示词",
                "type": "textarea",
                "required": True,
                "placeholder": "描述你想生成的图片...",
                "runninghub_parameter": "prompt",
                "selfhost_node_id": "18:17",
                "selfhost_input_key": "value",
            },
            {
                "key": "resolution",
                "label": "清晰度",
                "type": "select",
                "required": False,
                "default": "720p",
                "options": ("480p", "720p", "1080p"),
                # Standard 16:9 frames are 854x480, 1280x720 and 1920x1080.
                # megapixels keeps that pixel count: width * height / (1024 * 1024).
                # multiple=16, so 16:9 lands on 848x480, 1280x720 and 1920x1088.
                # 480p: 640x640, 736x560, 560x736, 784x528, 528x784, 848x480, 976x416, 480x848
                # 720p: 960x960, 1104x832, 832x1104, 1168x784, 784x1168, 1280x720, 1472x624, 720x1280
                # 1080p: 1440x1440, 1664x1248, 1248x1664, 1760x1168, 1168x1760, 1920x1088, 2192x944, 1088x1920
                "selfhost_node_id": "19",
                "selfhost_input_key": "megapixels",
                "selfhost_value_map": {
                    "480p": 854 * 480 / (1024 * 1024),
                    "720p": 1280 * 720 / (1024 * 1024),
                    "1080p": 1920 * 1080 / (1024 * 1024),
                },
            },
            {
                "key": "aspect_ratio",
                "label": "比例",
                "type": "select",
                "required": False,
                "default": "9:16",
                "options": ("1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "21:9", "9:16"),
                "selfhost_node_id": "19",
                "selfhost_input_key": "aspect_ratio",
                "selfhost_value_map": {
                    "1:1": "1:1 (Square)",
                    "4:3": "4:3 (Standard)",
                    "3:4": "3:4 (Portrait Standard)",
                    "3:2": "3:2 (Photo)",
                    "2:3": "2:3 (Portrait Photo)",
                    "16:9": "16:9 (Widescreen)",
                    "21:9": "21:9 (Ultrawide)",
                    "9:16": "9:16 (Portrait Widescreen)",
                },
            },
        ),
    },
    {
        "key": "image-edit",
        "name": "图片编辑",
        "generation_type": "image",
        "inputs": (
            {
                "key": "image",
                "label": "上传图片",
                "type": "image",
                "required": True,
                "extensions": (".jpg", ".jpeg", ".png", ".webp", ".bmp"),
                "accept": "image/jpeg,image/png,image/webp,image/bmp",
                "selfhost_node_id": "8",
                "selfhost_input_key": "image",
            },
            {
                "key": "prompt",
                "label": "提示词",
                "type": "textarea",
                "required": True,
                "placeholder": "描述要怎么改这张图片...",
                "selfhost_node_id": "39",
                "selfhost_input_key": "prompt",
            },
        ),
    },
)


def _scan_workflow_sources(workflow_key: str) -> dict[str, dict[str, Any]]:
    """
    Scan workflows/ directory to detect available sources for a workflow

    Args:
        workflow_key: Workflow key to scan

    Returns:
        {
            "runninghub": {"workflow_id": "xxx"} or None,
            "selfhost": {"workflow_path": "workflows/selfhost/xxx.json"} or None,
        }
    """
    sources: dict[str, dict[str, Any]] = {}
    workflows_dir = ROOT / "workflows"

    # Check RunningHub
    rh_path = workflows_dir / "runninghub" / f"{workflow_key}.json"
    if rh_path.exists():
        try:
            data = json.loads(rh_path.read_text(encoding="utf-8"))
            if data.get("source") == "runninghub" and "workflow_id" in data:
                sources["runninghub"] = {"workflow_id": data["workflow_id"]}
        except (json.JSONDecodeError, OSError):
            pass

    # Check Selfhost
    selfhost_filename = SELFHOST_WORKFLOW_MAPPING.get(workflow_key)
    if selfhost_filename:
        sf_path = workflows_dir / "selfhost" / f"{selfhost_filename}.json"
        if sf_path.exists():
            sources["selfhost"] = {"workflow_path": str(sf_path.relative_to(ROOT))}

    return sources


def list_public_workflows() -> list[dict[str, Any]]:
    """
    List all public workflows with their available sources

    Returns:
        [
            {
                "key": "digital-human-lipsync",
                "name": "数字人对口型",
                "sources": ["runninghub"],  # or ["runninghub", "selfhost"]
                "inputs": [...]
            }
        ]
    """
    workflows = []
    for workflow in WORKFLOWS:
        # Scan available sources
        source_configs = _scan_workflow_sources(workflow["key"])
        available_sources = list(source_configs.keys())
        if not available_sources:
            continue  # 没有任何可用来源的工作流不展示

        workflows.append(
            {
                "key": workflow["key"],
                "name": workflow["name"],
                "sources": available_sources,
                "inputs": [
                    {
                        key: list(value) if key == "extensions" else value
                        for key, value in field.items()
                        if key
                        not in {
                            "runninghub_parameter",
                            "selfhost_node_id",
                            "selfhost_input_key",
                            "selfhost_value_map",
                            "extensions",
                        }
                    }
                    for field in workflow["inputs"]
                ],
            }
        )

    return workflows


def get_workflow(key: str) -> dict[str, Any]:
    for workflow in WORKFLOWS:
        if workflow["key"] == key:
            return workflow
    raise HTTPException(status_code=404, detail="工作流不存在")


def get_workflow_source_config(workflow_key: str, source: str) -> dict[str, Any]:
    """
    Get source-specific configuration for a workflow

    Args:
        workflow_key: Workflow key
        source: "runninghub" or "selfhost"

    Returns:
        {"workflow_id": "xxx"} for runninghub
        {"workflow_path": "workflows/selfhost/xxx.json"} for selfhost

    Raises:
        HTTPException: Workflow doesn't exist or doesn't support the source
    """
    # Verify workflow exists
    get_workflow(workflow_key)

    # Scan sources
    sources = _scan_workflow_sources(workflow_key)

    if source not in sources:
        raise HTTPException(
            status_code=404, detail=f"工作流 {workflow_key} 不支持 {source} 来源"
        )

    return sources[source]


def validate_scalar_inputs(
    workflow: dict[str, Any],
    values: dict[str, Any],
) -> dict[str, Any]:
    declarations = {
        field["key"]: field
        for field in workflow["inputs"]
        if field["type"] in {"text", "textarea", "number", "select"}
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

        if field["type"] in {"text", "textarea"}:
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
