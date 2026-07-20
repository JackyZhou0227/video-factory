from __future__ import annotations

from collections.abc import Callable, Sequence

from app.services.llm.base import LLMConfig, LLMMessage, LLMProvider, LLMServiceError
from app.services.llm.providers.openai_compatible import OpenAICompatibleProvider


class LLMService:
    def __init__(self):
        self._factories: dict[str, Callable[[], LLMProvider]] = {}
        self._providers: dict[str, LLMProvider] = {}

    def register(self, provider_id: str, factory: Callable[[], LLMProvider]) -> None:
        self._factories[provider_id] = factory
        self._providers.pop(provider_id, None)

    def get_provider(self, provider_id: str) -> LLMProvider:
        if provider_id not in self._factories:
            raise LLMServiceError(f"未知的 LLM provider：{provider_id}")
        if provider_id not in self._providers:
            self._providers[provider_id] = self._factories[provider_id]()
        return self._providers[provider_id]

    async def generate(
        self,
        config: LLMConfig,
        messages: Sequence[LLMMessage],
        *,
        provider_id: str = "openai_compatible",
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        return await self.get_provider(provider_id).generate(
            config,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def test_connection(
        self,
        config: LLMConfig,
        *,
        provider_id: str = "openai_compatible",
    ) -> str:
        return await self.generate(
            config,
            [LLMMessage(role="user", content="只回复 OK")],
            provider_id=provider_id,
            temperature=0,
            max_tokens=8,
        )


def create_llm_service() -> LLMService:
    service = LLMService()
    service.register(OpenAICompatibleProvider.provider_id, OpenAICompatibleProvider)
    return service


llm_service = create_llm_service()
