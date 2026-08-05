from __future__ import annotations

import asyncio
import importlib
import shutil
import subprocess
from pathlib import Path

from app.services.tts.base import (
    QWEN3_TTS_BASE_MODEL,
    TTSRequest,
    TTSResult,
    TTSServiceError,
)


def _legacy_qwen_module():
    return importlib.import_module("app.services.tts_qwen")


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
    model_name = QWEN3_TTS_BASE_MODEL
    capabilities = frozenset({"voice_clone", "reference_audio", "reference_text", "language"})

    def __init__(self, *, model_path: str, device: str = "cpu"):
        self.model_path = model_path
        self.device = device

    def list_voices(self) -> list[dict]:
        return []

    async def synthesize(self, request: TTSRequest, output_path: Path) -> TTSResult:
        if not self.model_path:
            raise TTSServiceError("未配置 Qwen3-TTS Base 模型路径")
        if request.reference_audio is None:
            raise TTSServiceError("Qwen3-TTS Base 需要参考音频")
        if not request.reference_text or not request.reference_text.strip():
            raise TTSServiceError("Qwen3-TTS Base 需要参考文本")

        module = _legacy_qwen_module()
        try:
            await module.synthesize(
                text=request.text.strip(),
                output_path=output_path,
                model_path=self.model_path,
                device=self.device,
                language=request.language,
                ref_audio=request.reference_audio,
                ref_text=request.reference_text,
            )
        except Exception as exc:
            raise TTSServiceError(f"{self.model_name} 生成失败：{exc}") from exc
        duration = await asyncio.to_thread(_probe_duration, output_path)
        return TTSResult(output_path, duration, self.model_name, None)
