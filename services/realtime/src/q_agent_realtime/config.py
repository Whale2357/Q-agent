from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RuntimeConfig:
    database_path: Path = Path("data/q-agent.db")
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    language: str = "ko"
    sample_rate: int = 16_000
    audio_block_size: int = 512
    vad_threshold: float = 0.5
    min_silence_ms: int = 800
    speech_pad_ms: int = 200
    max_utterance_seconds: float = 30.0
    context_interval_seconds: float = 5.0
    question_interval_seconds: float = 30.0
    reevaluation_interval_seconds: float = 60.0
    silence_trigger_seconds: float = 20.0
    recent_transcript_seconds: float = 120.0
    max_active_questions: int = 3
    context_window_tokens: int = 8192
    meeting_objective: str = ""
    microphone_device: int | str | None = None
    llm_provider: str = "ollama"
    stt_provider: str = "local"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_llm_model: str = "gpt-4o-mini"
    openai_stt_model: str = "gpt-4o-mini-transcribe"

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        return cls(
            database_path=Path(os.getenv("REALTIME_DB_PATH", "data/q-agent.db")),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
            language=os.getenv("REALTIME_LANGUAGE", "ko"),
            llm_provider=os.getenv("LLM_PROVIDER", "ollama").strip().lower(),
            stt_provider=os.getenv("STT_PROVIDER", "local").strip().lower(),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv(
                "OPENAI_BASE_URL", "https://api.openai.com/v1"
            ),
            openai_llm_model=os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini"),
            openai_stt_model=os.getenv(
                "OPENAI_STT_MODEL", "gpt-4o-mini-transcribe"
            ),
        )
