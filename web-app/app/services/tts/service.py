from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.services.tts.base import (
    EDGE_TTS_MODEL,
    QWEN3_TTS_BASE_MODEL,
    QWEN3_TTS_CUSTOM_VOICE_MODEL,
    TTSProvider,
    TTSRequest,
    TTSResult,
    TTSServiceError,
)
from app.services.tts.providers.edge_tts import EdgeTtsProvider
from app.services.tts.providers.qwen3_tts import Qwen3TtsBaseProvider, Qwen3TtsCustomVoiceProvider


class TTSService:
    def __init__(self):
        self._factories: dict[str, Callable[[], TTSProvider]] = {}
        self._providers: dict[str, TTSProvider] = {}

    def register(self, model_name: str, factory: Callable[[], TTSProvider]) -> None:
        self._factories[model_name] = factory
        self._providers.pop(model_name, None)

    def model_names(self) -> list[str]:
        return list(self._factories)

    def get_provider(self, model_name: str) -> TTSProvider:
        if model_name not in self._factories:
            raise TTSServiceError(f"未知的 TTS 模型或服务：{model_name}")
        if model_name not in self._providers:
            self._providers[model_name] = self._factories[model_name]()
        return self._providers[model_name]

    def list_voices(self, model_name: str) -> list[dict]:
        return self.get_provider(model_name).list_voices()

    async def synthesize(self, model_name: str, request: TTSRequest, output_path: Path) -> TTSResult:
        return await self.get_provider(model_name).synthesize(request, output_path)


def create_tts_service(config: dict | None = None) -> TTSService:
    if config is None:
        from app.core.config import app_config

        config = app_config

    tts_config = config.get("tts") or {}
    service = TTSService()
    service.register(
        EDGE_TTS_MODEL,
        lambda: EdgeTtsProvider(default_voice=tts_config.get("edge_default_voice") or "zh-CN-XiaoxiaoNeural"),
    )
    service.register(
        QWEN3_TTS_CUSTOM_VOICE_MODEL,
        lambda: Qwen3TtsCustomVoiceProvider(
            model_path=tts_config.get("customvoice_model_path") or tts_config.get("model_path") or "",
            device=tts_config.get("device") or "cpu",
            default_voice=tts_config.get("default_speaker") or "Uncle_Fu",
        ),
    )
    service.register(
        QWEN3_TTS_BASE_MODEL,
        lambda: Qwen3TtsBaseProvider(
            model_path=tts_config.get("base_model_path") or "",
            device=tts_config.get("device") or "cpu",
        ),
    )
    return service


tts_service = create_tts_service()
