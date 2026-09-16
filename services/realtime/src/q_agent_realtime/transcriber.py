from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from faster_whisper import WhisperModel


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str
    language_probability: float


class FasterWhisperTranscriber:
    def __init__(
        self,
        model_name: str = "turbo",
        language: str = "ko",
        compute_type: str = "int8_float16",
    ):
        self.language = language
        self.model = WhisperModel(model_name, device="cuda", compute_type=compute_type)

    def transcribe(self, samples: np.ndarray) -> TranscriptionResult:
        segments, info = self.model.transcribe(
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
