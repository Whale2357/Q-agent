from __future__ import annotations

import io
import json
import wave
from copy import deepcopy
from typing import Any

import httpx
import numpy as np

from .providers import ProviderError
from .transcriber import TranscriptionResult


class OpenAIProviderError(ProviderError):
    pass


def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return an OpenAI Structured Outputs-compatible strict schema."""
    value = deepcopy(schema)

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties)
                node["additionalProperties"] = False
                for child in properties.values():
                    visit(child)
        if node.get("type") == "array":
            visit(node.get("items"))
        for key in ("anyOf", "oneOf", "allOf"):
            choices = node.get(key)
            if isinstance(choices, list):
                for choice in choices:
                    visit(choice)

    visit(value)
    return value


def _response_output_text(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise OpenAIProviderError("OpenAI 응답이 JSON 객체가 아닙니다.")
    if payload.get("status") in ("incomplete", "failed", "cancelled"):
        raise OpenAIProviderError("OpenAI 응답이 완료되지 않았습니다. 출력 한도와 모델 설정을 확인해 주세요.")
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    output = payload.get("output", [])
    if not isinstance(output, list):
        raise OpenAIProviderError("OpenAI 응답의 output 형식이 올바르지 않습니다.")
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        contents = item.get("content", [])
        if not isinstance(contents, list):
            continue
        for content in contents:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "refusal":
                raise OpenAIProviderError(
                    f"OpenAI가 요청 처리를 거절했습니다: {content.get('refusal', '')}"
                )
            if content.get("type") == "output_text" and isinstance(
                content.get("text"), str
            ):
                return content["text"]
    raise OpenAIProviderError("OpenAI 응답에서 구조화된 텍스트를 찾을 수 없습니다.")


def _wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    normalized = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (normalized * 32767.0).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()


class OpenAILLMClient:
    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 180.0,
        client: httpx.AsyncClient | None = None,
    ):
        self.api_key = api_key.strip()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def ensure_ready(self) -> None:
        if not self.api_key:
            raise OpenAIProviderError("OPENAI_API_KEY가 설정되지 않았습니다.")
        try:
            response = await self._client.get(
                f"{self.base_url}/models/{self.model}", headers=self._headers
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise OpenAIProviderError(
                _http_error_message("LLM", error.response)
            ) from error
        except httpx.HTTPError as error:
            raise OpenAIProviderError(f"OpenAI LLM에 연결할 수 없습니다: {error}") from error

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
        del think  # Reasoning behavior is model-specific; output shape remains provider-neutral.
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": user,
            "max_output_tokens": num_predict,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "q_agent_result",
                    "strict": True,
                    "schema": _strict_json_schema(schema),
                }
            },
        }
        # Current GPT-5/6 reasoning models may reject temperature. Smaller omni
        # models accept it and benefit from the role-specific values used here.
        if not self.model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
            request["temperature"] = temperature
        try:
            response = await self._client.post(
                f"{self.base_url}/responses",
                headers={**self._headers, "Content-Type": "application/json"},
                json=request,
            )
            response.raise_for_status()
            raw = _response_output_text(response.json())
            value = json.loads(raw)
        except httpx.HTTPStatusError as error:
            raise OpenAIProviderError(
                _http_error_message("LLM", error.response)
            ) from error
        except httpx.HTTPError as error:
            raise OpenAIProviderError(f"OpenAI LLM 요청에 실패했습니다: {error}") from error
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise OpenAIProviderError(
                f"OpenAI 구조화 응답 처리에 실패했습니다: {error}"
            ) from error
        if not isinstance(value, dict):
            raise OpenAIProviderError("OpenAI가 JSON 객체가 아닌 응답을 반환했습니다.")
        return value

    async def close(self) -> None:
        await self._client.aclose()


class OpenAITranscriber:
    provider = "openai"
    device = "cloud"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        language: str = "ko",
        sample_rate: int = 16_000,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ):
        self.api_key = api_key.strip()
        self.model = model
        self.language = language
        self.sample_rate = sample_rate
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def ensure_ready(self) -> None:
        if not self.api_key:
            raise OpenAIProviderError("OPENAI_API_KEY가 설정되지 않았습니다.")
        try:
            response = await self._client.get(
                f"{self.base_url}/models/{self.model}", headers=self._headers
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise OpenAIProviderError(
                _http_error_message("STT", error.response)
            ) from error
        except httpx.HTTPError as error:
            raise OpenAIProviderError(f"OpenAI STT에 연결할 수 없습니다: {error}") from error

    async def transcribe(self, samples: np.ndarray) -> TranscriptionResult:
        if samples.size == 0:
            return TranscriptionResult("", self.language, 0.0)
        data = {
            "model": self.model,
            "response_format": "json",
            "language": self.language,
        }
        try:
            response = await self._client.post(
                f"{self.base_url}/audio/transcriptions",
                headers=self._headers,
                data=data,
                files={
                    "file": (
                        "utterance.wav",
                        _wav_bytes(samples, self.sample_rate),
                        "audio/wav",
                    )
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
                raise OpenAIProviderError("OpenAI STT 응답에 유효한 text가 없습니다.")
            text = payload["text"].strip()
        except httpx.HTTPStatusError as error:
            raise OpenAIProviderError(
                _http_error_message("STT", error.response)
            ) from error
        except httpx.HTTPError as error:
            raise OpenAIProviderError(f"OpenAI STT 요청에 실패했습니다: {error}") from error
        except (TypeError, ValueError) as error:
            raise OpenAIProviderError(f"OpenAI STT 응답 처리에 실패했습니다: {error}") from error
        return TranscriptionResult(text, self.language, 0.0)

    async def close(self) -> None:
        await self._client.aclose()


def _http_error_message(component: str, response: httpx.Response) -> str:
    detail = ""
    try:
        payload = response.json()
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        detail = str(error.get("message", "")).strip() if isinstance(error, dict) else ""
    except (TypeError, ValueError):
        pass
    suffix = f": {detail}" if detail else ""
    return f"OpenAI {component} 요청이 실패했습니다 (HTTP {response.status_code}){suffix}"
