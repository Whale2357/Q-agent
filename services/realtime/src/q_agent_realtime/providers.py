from __future__ import annotations

from typing import Any, Protocol

import numpy as np


class ProviderError(RuntimeError):
    """Raised when a configured AI provider cannot serve a request."""


class StructuredLLMClient(Protocol):
    provider: str
    model: str

    async def ensure_ready(self) -> None: ...

    async def chat_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        think: bool,
        temperature: float,
        num_predict: int,
    ) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class SpeechTranscriber(Protocol):
    provider: str
    model: str
    device: str

    async def ensure_ready(self) -> None: ...

    async def transcribe(self, samples: np.ndarray) -> Any: ...

    async def close(self) -> None: ...
