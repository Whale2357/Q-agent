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
        role: str = "llm",
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.role = role
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._lock = asyncio.Lock()
        self._preloaded = False

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

    async def preload(self) -> None:
        """Load this role's model and keep its runner resident until shutdown."""
        try:
            response = await self._client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [],
                    "stream": False,
                    "keep_alive": -1,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise OllamaError(
                f"{self.role}: 모델 '{self.model}' 사전 로드에 실패했습니다: {error}"
            ) from error
        self._preloaded = True

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
            "keep_alive": -1,
            "options": {
                "num_ctx": self.num_ctx,
                "temperature": temperature,
                "num_predict": num_predict,
            },
        }
        async with self._lock:
            value = await self._request_json(payload, num_predict)
        if not isinstance(value, dict):
            raise OllamaError(
                f"{self.role}: Ollama가 JSON 객체가 아닌 응답을 반환했습니다."
            )
        return value

    async def _request_json(
        self, payload: dict[str, Any], num_predict: int
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        last_reason = "unknown"
        for attempt in range(2):
            request = dict(payload)
            request["options"] = dict(payload["options"])
            if attempt:
                request["think"] = False
                request["options"]["temperature"] = 0
                request["options"]["num_predict"] = min(
                    max(num_predict * 2, 4096), 8192
                )
            try:
                response = await self._client.post(
                    f"{self.base_url}/api/chat", json=request
                )
                response.raise_for_status()
                body = response.json()
                last_reason = str(body.get("done_reason", "unknown"))
                content = body["message"]["content"]
                value = json.loads(content)
                if not isinstance(value, dict):
                    raise TypeError("응답 최상위 값이 JSON 객체가 아닙니다")
                return value
            except json.JSONDecodeError as error:
                last_error = error
                continue
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                raise OllamaError(
                    f"{self.role}: Ollama 요청 처리에 실패했습니다: {error}"
                ) from error
        assert last_error is not None
        raise OllamaError(
            f"{self.role}: Ollama JSON 응답을 재시도 후에도 해석하지 못했습니다 "
            f"(done_reason={last_reason}): {last_error}"
        ) from last_error

    async def close(self) -> None:
        if self._preloaded:
            try:
                await self._client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [],
                        "stream": False,
                        "keep_alive": 0,
                    },
                )
            except httpx.HTTPError:
                pass
            self._preloaded = False
        await self._client.aclose()
