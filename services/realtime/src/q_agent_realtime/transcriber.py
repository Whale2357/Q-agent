from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str
    language_probability: float


class FasterWhisperTranscriber:
    provider = "local"

    def __init__(
        self,
        model_name: str | None = None,
        language: str = "ko",
        device: str | None = None,
        compute_type: str | None = None,
    ):
        import ctranslate2
        from faster_whisper import WhisperModel

        selected_device = device or os.getenv("WHISPER_DEVICE", "auto")
        if selected_device == "auto":
            selected_device = (
                "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            )
        selected_compute_type = compute_type or os.getenv(
            "WHISPER_COMPUTE_TYPE",
            "int8_float16" if selected_device == "cuda" else "int8",
        )
        self.language = language
        self.model_name = model_name or os.getenv("WHISPER_MODEL", "turbo")
        self.model = self.model_name
        self.device = selected_device
        self._whisper = WhisperModel(
            self.model_name,
            device=selected_device,
            compute_type=selected_compute_type,
        )

    async def ensure_ready(self) -> None:
        return None

    async def transcribe(self, samples: np.ndarray) -> TranscriptionResult:
        return await asyncio.to_thread(self._transcribe_sync, samples)

    def _transcribe_sync(self, samples: np.ndarray) -> TranscriptionResult:
        segments, info = self._whisper.transcribe(
            samples,
            language=self.language,
            beam_size=1,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        return TranscriptionResult(
            text=text.strip(),
            language=info.language,
            language_probability=float(info.language_probability),
        )

    async def close(self) -> None:
        return None
