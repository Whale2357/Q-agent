from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .providers import ProviderError


class OllamaError(ProviderError):
    pass


class OllamaClient:
    provider = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        num_ctx: int = 8192,
        timeout_seconds: float = 180.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self._client = httpx.AsyncClient(timeout=timeout_seconds)
        self._lock = asyncio.Lock()

    async def ensure_ready(self) -> None:
        try:
            response = await self._client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise OllamaError(
                f"Ollama에 연결할 수 없습니다: {self.base_url}. Ollama가 실행 중인지 확인하세요."
            ) from error

        models = {item.get("name", "") for item in response.json().get("models", [])}
        if not any(name == self.model or name.startswith(f"{self.model}:") for name in models):
            raise OllamaError(f"Ollama 모델 '{self.model}'을 찾을 수 없습니다.")

    async def chat_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        think: bool,
        temperature: float,
        num_predict: int,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "think": think,
            "format": schema,
            "keep_alive": "30m",
            "options": {
                "num_ctx": self.num_ctx,
                "temperature": temperature,
                "num_predict": num_predict,
            },
        }
        async with self._lock:
            try:
                response = await self._client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                content = response.json()["message"]["content"]
                value = json.loads(content)
            except (httpx.HTTPError, KeyError, TypeError, json.JSONDecodeError) as error:
                raise OllamaError(f"Ollama JSON 응답 처리에 실패했습니다: {error}") from error
        if not isinstance(value, dict):
            raise OllamaError("Ollama가 JSON 객체가 아닌 응답을 반환했습니다.")
        return value

    async def close(self) -> None:
        await self._client.aclose()
