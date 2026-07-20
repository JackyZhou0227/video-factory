from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


class LLMServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


class LLMProvider(Protocol):
    provider_id: str

    async def generate(
        self,
        config: LLMConfig,
        messages: Sequence[LLMMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str: ...
