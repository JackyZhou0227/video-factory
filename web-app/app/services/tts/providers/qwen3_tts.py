from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from app.services.tts.base import (
    QWEN3_TTS_BASE_MODEL,
    TTSRequest,
    TTSResult,
    TTSServiceError,
)


def _legacy_qwen_module():
    return importlib.import_module("app.services.tts_qwen")


def _is_supported_device(device: str) -> bool:
    if device in {"cpu", "cuda"}:
        return True
    return device.startswith("cuda:") and device.removeprefix("cuda:").isdigit()


def _normalize_concurrent_limit(value: object) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 1
    return min(max(limit, 1), 8)


_RUNTIME_CHECK_SCRIPT = """
import sys

import torch

device = sys.argv[1]
if device.startswith("cuda"):
    if not torch.cuda.is_available():
        raise SystemExit("PyTorch 当前无法使用 CUDA")
    try:
        torch.empty(0, device=device)
    except Exception as exc:
        raise SystemExit(f"无法使用设备 {device}: {exc}") from exc
    capability = torch.cuda.get_device_capability(device)
    if capability[0] < 8:
        raise SystemExit(f"设备 {device} 不支持当前加载器使用的 BF16，请改用 cpu")
print("ok")
"""


def _missing_dependencies() -> list[str]:
    dependencies = {
        "qwen_tts": "qwen-tts",
        "soundfile": "soundfile",
        "torch": "torch",
    }
    return [package for module, package in dependencies.items() if importlib.util.find_spec(module) is None]


def _runtime_validation_error(device: str) -> str | None:
    try:
        result = subprocess.run(
            [sys.executable, "-c", _RUNTIME_CHECK_SCRIPT, device],
            capture_output=True,
            text=True,
            check=False,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"本地 TTS 运行环境检查失败：{exc}"
    if result.returncode == 0:
        return None
    output = (result.stderr or result.stdout or "").strip()
    if "OMP: Error #15" in output and "libiomp5md.dll" in output:
        return "PyTorch 检测到重复的 libiomp5md.dll，请修复当前 Conda 环境中的 OpenMP 运行库冲突"
    detail = output
    detail = detail.splitlines()[-1] if detail else "未知错误"
    return f"本地 TTS 运行环境不可用：{detail[:300]}"


def _has_model_weights(model_path: Path) -> bool:
    patterns = ("*.safetensors", "pytorch_model*.bin")
    return any(next(model_path.glob(pattern), None) is not None for pattern in patterns)


def _model_config_error(model_path: Path) -> str | None:
    try:
        model_config = json.loads((model_path / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return f"无法读取模型 config.json：{exc}"
    architectures = model_config.get("architectures") or []
    if model_config.get("model_type") != "qwen3_tts":
        return "模型 config.json 不是 Qwen3-TTS 架构"
    if model_config.get("tts_model_type") != "base":
        return "当前模型不是支持音色克隆的 Qwen3-TTS Base"
    if "Qwen3TTSForConditionalGeneration" not in architectures:
        return "模型 config.json 缺少 Qwen3TTSForConditionalGeneration 架构"
    return None


def _probe_duration(path: Path) -> float:
    if shutil.which("ffprobe") is None:
        return 0.0
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return max(0.0, float(result.stdout.strip())) if result.returncode == 0 else 0.0
    except ValueError:
        return 0.0


class Qwen3TtsBaseProvider:
    provider_id = "qwen3_tts_base"
    model_name = QWEN3_TTS_BASE_MODEL
    capabilities = frozenset({"voice_clone", "reference_audio", "reference_text", "language"})

    def __init__(
        self,
        *,
        model_path: str,
        enabled: bool = False,
        device: str = "cpu",
        concurrent_limit: int = 1,
    ):
        self.enabled = enabled
        self.model_path = str(model_path or "")
        self.device = str(device or "cpu").strip().lower()
        self.concurrent_limit = _normalize_concurrent_limit(concurrent_limit)
        self._status_cache: dict | None = None
        self._status_lock = threading.Lock()
        self._resolved_model_path: Path | None = None
        self._inference_semaphores: dict[object, asyncio.Semaphore] = {}
        self._semaphore_lock = threading.Lock()

    def _inference_semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        with self._semaphore_lock:
            semaphore = self._inference_semaphores.get(loop)
            if semaphore is None:
                semaphore = asyncio.Semaphore(self.concurrent_limit)
                self._inference_semaphores[loop] = semaphore
            return semaphore

    def _status(self, status: str, reason: str | None, checks: dict[str, str]) -> dict:
        return {
            "id": self.provider_id,
            "model_name": self.model_name,
            "display_name": "音色克隆",
            "runtime": "local",
            "enabled": self.enabled,
            "available": status == "available",
            "status": status,
            "reason": reason,
            "validation": "skipped" if status == "disabled" else "lightweight",
            "concurrent_limit": self.concurrent_limit,
            "checks": checks,
        }

    def _validate(self) -> dict:
        checks = {
            "configuration": "skipped",
            "model_path": "skipped",
            "model_files": "skipped",
            "model_config": "skipped",
            "dependencies": "skipped",
            "device": "skipped",
            "model_load": "deferred",
        }
        self._resolved_model_path = None
        if not self.enabled:
            checks["configuration"] = "disabled"
            checks["model_load"] = "skipped"
            return self._status("disabled", "本地 Qwen3-TTS Base 已在配置中关闭", checks)

        checks["configuration"] = "passed"
        if not self.model_path.strip():
            checks["model_path"] = "failed"
            return self._status("unavailable", "未配置 Qwen3-TTS Base 模型路径", checks)

        try:
            model_path = Path(self.model_path).expanduser().resolve()
        except (OSError, ValueError) as exc:
            checks["model_path"] = "failed"
            return self._status("unavailable", f"Qwen3-TTS Base 模型路径无效：{exc}", checks)
        if not model_path.is_dir():
            checks["model_path"] = "failed"
            return self._status("unavailable", "Qwen3-TTS Base 模型目录不存在", checks)
        checks["model_path"] = "passed"

        if not (model_path / "config.json").is_file() or not _has_model_weights(model_path):
            checks["model_files"] = "failed"
            return self._status("unavailable", "Qwen3-TTS Base 模型目录缺少 config.json 或权重文件", checks)
        checks["model_files"] = "passed"

        model_config_error = _model_config_error(model_path)
        if model_config_error:
            checks["model_config"] = "failed"
            return self._status("unavailable", model_config_error, checks)
        checks["model_config"] = "passed"

        missing_dependencies = _missing_dependencies()
        if missing_dependencies:
            checks["dependencies"] = "failed"
            packages = "、".join(missing_dependencies)
            return self._status("unavailable", f"缺少本地 TTS 依赖：{packages}", checks)
        checks["dependencies"] = "passed"

        if not _is_supported_device(self.device):
            checks["device"] = "failed"
            return self._status("unavailable", f"不支持的本地 TTS 设备配置：{self.device or '<empty>'}", checks)

        runtime_error = _runtime_validation_error(self.device)
        if runtime_error:
            checks["device"] = "failed"
            return self._status("unavailable", runtime_error, checks)
        checks["device"] = "passed"
        self._resolved_model_path = model_path
        return self._status("available", None, checks)

    def status(self, *, refresh: bool = False) -> dict:
        if not refresh and self._status_cache is not None:
            return self._status_cache
        with self._status_lock:
            if refresh or self._status_cache is None:
                self._status_cache = self._validate()
            return self._status_cache

    def list_voices(self) -> list[dict]:
        return []

    async def synthesize(self, request: TTSRequest, output_path: Path) -> TTSResult:
        provider_status = await asyncio.to_thread(self.status)
        if not provider_status["available"]:
            raise TTSServiceError(provider_status["reason"] or "Qwen3-TTS Base 当前不可用")
        if request.reference_audio is None:
            raise TTSServiceError("Qwen3-TTS Base 需要参考音频")
        if not request.reference_text or not request.reference_text.strip():
            raise TTSServiceError("Qwen3-TTS Base 需要参考文本")

        module = await asyncio.to_thread(_legacy_qwen_module)
        try:
            async with self._inference_semaphore():
                await module.synthesize(
                    text=request.text.strip(),
                    output_path=output_path,
                    model_path=str(self._resolved_model_path),
                    device=self.device,
                    language=request.language,
                    ref_audio=request.reference_audio,
                    ref_text=request.reference_text,
                )
        except Exception as exc:
            raise TTSServiceError(f"{self.model_name} 生成失败：{exc}") from exc
        duration = await asyncio.to_thread(_probe_duration, output_path)
        return TTSResult(output_path, duration, self.model_name, None)
