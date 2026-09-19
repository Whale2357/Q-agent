from __future__ import annotations

import os
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RuntimeConfig:
    database_path: Path = Path("data/q-agent.db")
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_context_model: str = "qwen3:4b"
    ollama_generator_model: str = "qwen3:8b"
    ollama_evaluator_model: str = "qwen3:1.7b"
    language: str = "ko"
    sample_rate: int = 16_000
    audio_block_size: int = 512
    vad_threshold: float = 0.5
    min_silence_ms: int = 800
    speech_pad_ms: int = 200
    max_utterance_seconds: float = 30.0
    context_interval_seconds: float = 5.0
    question_interval_seconds: float = 5.0
    generator_min_interval_seconds: float = 25.0
    reevaluation_interval_seconds: float = 60.0
    silence_trigger_seconds: float = 20.0
    recent_transcript_seconds: float = 120.0
    max_active_questions: int = 3
    context_window_tokens: int = 8192
    context_model_window_tokens: int = 4096
    generator_model_window_tokens: int = 8192
    evaluator_model_window_tokens: int = 4096
    meeting_objective: str = ""
    microphone_device: int | str | None = None
    llm_provider: str = "openai"
    stt_provider: str = "openai"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_llm_model: str = "gpt-4o-mini"
    openai_context_model: str = "gpt-4o-mini"
    openai_generator_model: str = "gpt-4o-mini"
    openai_evaluator_model: str = "gpt-4o-mini"
    openai_stt_model: str = "gpt-4o-mini-transcribe"
    api_key: str = ""
    max_audio_sessions: int = 2
    session_ttl_seconds: float = 120.0
    max_text_sessions: int = 2
    max_pending_tickets: int = 128
    max_session_seconds: float = 7200.0
    request_timeout_seconds: float = 180.0
    websocket_idle_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.llm_provider not in {"openai", "ollama"}:
            raise ValueError("LLM_PROVIDER must be openai or ollama")
        if self.stt_provider not in {"openai", "local"}:
            raise ValueError("STT_PROVIDER must be openai or local")
        for name in (
            "context_interval_seconds", "question_interval_seconds",
            "reevaluation_interval_seconds", "silence_trigger_seconds",
            "max_utterance_seconds", "recent_transcript_seconds", "session_ttl_seconds",
            "max_session_seconds", "request_timeout_seconds", "websocket_idle_seconds",
            "max_audio_sessions", "max_text_sessions", "max_pending_tickets",
            "context_model_window_tokens", "generator_model_window_tokens",
            "evaluator_model_window_tokens", "max_active_questions",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not math.isfinite(self.generator_min_interval_seconds) or self.generator_min_interval_seconds < 0:
            raise ValueError("generator_min_interval_seconds must be finite and nonnegative")
        if self.sample_rate != 16000 or self.audio_block_size != 512:
            raise ValueError("Audio must use 16000 Hz and 512-sample VAD blocks")
        if not 0 < self.vad_threshold < 1:
            raise ValueError("vad_threshold must be between 0 and 1")

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        ollama_model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
        openai_model = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")
        return cls(
            database_path=Path(os.getenv("REALTIME_DB_PATH", "data/q-agent.db")),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            ollama_model=ollama_model,
            ollama_context_model=os.getenv("OLLAMA_CONTEXT_MODEL", "qwen3:4b"),
            ollama_generator_model=os.getenv(
                "OLLAMA_GENERATOR_MODEL", ollama_model
            ),
            ollama_evaluator_model=os.getenv("OLLAMA_EVALUATOR_MODEL", "qwen3:1.7b"),
            language=os.getenv("REALTIME_LANGUAGE", "ko"),
            llm_provider=os.getenv("LLM_PROVIDER", "openai").strip().lower(),
            stt_provider=os.getenv("STT_PROVIDER", "openai").strip().lower(),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv(
                "OPENAI_BASE_URL", "https://api.openai.com/v1"
            ),
            openai_llm_model=openai_model,
            openai_context_model=os.getenv("OPENAI_CONTEXT_MODEL", openai_model),
            openai_generator_model=os.getenv("OPENAI_GENERATOR_MODEL", openai_model),
            openai_evaluator_model=os.getenv("OPENAI_EVALUATOR_MODEL", openai_model),
            openai_stt_model=os.getenv(
                "OPENAI_STT_MODEL", "gpt-4o-mini-transcribe"
            ),
            context_interval_seconds=float(
                os.getenv("CONTEXT_INTERVAL_SECONDS", "5")
            ),
            question_interval_seconds=float(
                os.getenv("QUESTION_INTERVAL_SECONDS", "5")
            ),
            generator_min_interval_seconds=float(
                os.getenv("GENERATOR_MIN_INTERVAL_SECONDS", "25")
            ),
            reevaluation_interval_seconds=float(
                os.getenv("REEVALUATION_INTERVAL_SECONDS", "60")
            ),
            silence_trigger_seconds=float(
                os.getenv("SILENCE_TRIGGER_SECONDS", "20")
            ),
            context_model_window_tokens=int(
                os.getenv("CONTEXT_NUM_CTX", "4096")
            ),
            generator_model_window_tokens=int(
                os.getenv("GENERATOR_NUM_CTX", "8192")
            ),
            evaluator_model_window_tokens=int(
                os.getenv("EVALUATOR_NUM_CTX", "4096")
            ),
            api_key=os.getenv("REALTIME_API_KEY", ""),
            max_audio_sessions=int(os.getenv("MAX_AUDIO_SESSIONS", "2")),
            session_ttl_seconds=float(os.getenv("SESSION_TTL_SECONDS", "120")),
            max_text_sessions=int(os.getenv("MAX_TEXT_SESSIONS", "2")),
            max_pending_tickets=int(os.getenv("MAX_PENDING_TICKETS", "128")),
            max_session_seconds=float(os.getenv("REALTIME_MAX_SESSION_SECONDS", "7200")),
            request_timeout_seconds=float(os.getenv("REALTIME_REQUEST_TIMEOUT_SECONDS", "180")),
            websocket_idle_seconds=float(os.getenv("REALTIME_WEBSOCKET_IDLE_SECONDS", "60")),
        )
