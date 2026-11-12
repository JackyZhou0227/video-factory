from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.yaml"


def load_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


app_config = load_config()


def resolve_output_dir(config: dict[str, Any] | None = None) -> Path:
    cfg = config or app_config
    output_dir = Path(cfg["server"]["output_dir"])
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def get_comfyui_config() -> dict[str, str]:
    """
    Get ComfyUI configuration for self-hosted workflows

    Returns:
        {
            "url": ComfyUI server URL,
            "api_key": ComfyUI API key (optional)
        }
    """
    comfyui_config = app_config.get("comfyui") or {}
    return {
        "url": comfyui_config.get("url", "http://localhost:8188"),
        "api_key": comfyui_config.get("api_key", ""),
    }

