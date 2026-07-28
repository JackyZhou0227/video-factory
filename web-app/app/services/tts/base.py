from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

EDGE_TTS_MODEL = "Edge-TTS"
QWEN3_TTS_CUSTOM_VOICE_MODEL = "Qwen3-TTS-12Hz-1.7B-CustomVoice"
QWEN3_TTS_BASE_MODEL = "Qwen3-TTS-12Hz-1.7B-Base"


class TTSServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice_id: str | None = None
    language: str = "Chinese"
    speed: float = 1.0
    volume: int = 100
    instruct: str | None = None
    reference_audio: Path | None = None
    reference_text: str | None = None


@dataclass(frozen=True)
class TTSTiming:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class TTSResult:
    output_path: Path
    duration: float
    model_name: str
    voice_id: str | None = None
    timings: tuple[TTSTiming, ...] = ()


class TTSProvider(Protocol):
    model_name: str
    capabilities: frozenset[str]

    def list_voices(self) -> list[dict]: ...

    async def synthesize(self, request: TTSRequest, output_path: Path) -> TTSResult: ...
