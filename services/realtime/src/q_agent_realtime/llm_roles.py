from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .config import RuntimeConfig
from .ollama import OllamaClient
from .openai_provider import OpenAILLMClient
from .providers import ProviderError, StructuredLLMClient


ROLE_LABELS = {
    "context": "Context Agent",
    "generator": "Question Generator",
    "evaluator": "Question Evaluator",
}


@dataclass(slots=True)
class RoleLLMs:
    context: StructuredLLMClient
    generator: StructuredLLMClient
    evaluator: StructuredLLMClient

    def items(self) -> tuple[tuple[str, StructuredLLMClient], ...]:
        return (
            ("context", self.context),
            ("generator", self.generator),
            ("evaluator", self.evaluator),
        )

    async def ensure_ready(self) -> None:
        results = await asyncio.gather(
            *(client.ensure_ready() for _, client in self.items()),
            return_exceptions=True,
        )
        failures = [
            f"{ROLE_LABELS[role]}: {result}"
            for (role, _), result in zip(self.items(), results, strict=True)
            if isinstance(result, BaseException)
        ]
        if failures:
            raise ProviderError("; ".join(failures))

    async def close(self) -> None:
        await asyncio.gather(
            *(client.close() for _, client in self.items()),
            return_exceptions=True,
        )

    async def preload(self) -> None:
        ollama_clients = [
            client for _, client in self.items() if isinstance(client, OllamaClient)
        ]
        if not ollama_clients:
            return
        results = await asyncio.gather(
            *(client.preload() for client in ollama_clients),
            return_exceptions=True,
        )
        failures = [
            str(result) for result in results if isinstance(result, BaseException)
        ]
        if failures:
            raise ProviderError("; ".join(failures))

    def models(self) -> dict[str, str]:
        return {role: client.model for role, client in self.items()}


def create_role_llms(config: RuntimeConfig) -> RoleLLMs:
    if config.llm_provider == "ollama":
        return RoleLLMs(
            context=OllamaClient(
                base_url=config.ollama_base_url,
                model=config.ollama_context_model,
                num_ctx=config.context_model_window_tokens,
                role=ROLE_LABELS["context"],
            ),
            generator=OllamaClient(
                base_url=config.ollama_base_url,
                model=config.ollama_generator_model,
                num_ctx=config.generator_model_window_tokens,
                role=ROLE_LABELS["generator"],
            ),
            evaluator=OllamaClient(
                base_url=config.ollama_base_url,
                model=config.ollama_evaluator_model,
                num_ctx=config.evaluator_model_window_tokens,
                role=ROLE_LABELS["evaluator"],
            ),
        )
    if config.llm_provider == "openai":
        common = {
            "api_key": config.openai_api_key,
            "base_url": config.openai_base_url,
        }
        return RoleLLMs(
            context=OpenAILLMClient(model=config.openai_context_model, **common),
            generator=OpenAILLMClient(model=config.openai_generator_model, **common),
            evaluator=OpenAILLMClient(model=config.openai_evaluator_model, **common),
        )
    raise ValueError(f"지원하지 않는 LLM_PROVIDER입니다: {config.llm_provider}")
