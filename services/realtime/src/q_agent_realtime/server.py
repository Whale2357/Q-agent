from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .audio import AudioUtterance, UtteranceDetector
from .config import RuntimeConfig
from .context import ContextUpdater
from .database import Repository
from .domain import QuestionCandidate, QuestionContextState, QuestionStatus, TranscriptSegment
from .ollama import OllamaClient
from .openai_provider import OpenAILLMClient, OpenAITranscriber
from .providers import ProviderError, SpeechTranscriber, StructuredLLMClient
from .questions import QuestionEvaluator, QuestionGenerator, select_top_questions
from .transcriber import FasterWhisperTranscriber


EventSender = Callable[[dict[str, Any]], Awaitable[None]]


class TextMeetingRequest(BaseModel):
    text: str
    language: str = "ko"


class RealtimeRuntime:
    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.llm = self._create_llm()
        self.repository = Repository(self.config.database_path)
        self.transcriber: SpeechTranscriber | None = None
        self._llm_ready = False
        self._stt_ready = False
        self._ready_lock = asyncio.Lock()
        self._transcription_lock = asyncio.Lock()

    def _create_llm(self) -> StructuredLLMClient:
        if self.config.llm_provider == "ollama":
            return OllamaClient(
                base_url=self.config.ollama_base_url,
                model=self.config.ollama_model,
                num_ctx=self.config.context_window_tokens,
            )
        if self.config.llm_provider == "openai":
            return OpenAILLMClient(
                api_key=self.config.openai_api_key,
                base_url=self.config.openai_base_url,
                model=self.config.openai_llm_model,
            )
        raise ValueError(
            f"지원하지 않는 LLM_PROVIDER입니다: {self.config.llm_provider}"
        )

    async def _create_transcriber(self) -> SpeechTranscriber:
        if self.config.stt_provider == "local":
            return await asyncio.to_thread(
                FasterWhisperTranscriber,
                language=self.config.language,
            )
        if self.config.stt_provider == "openai":
            return OpenAITranscriber(
                api_key=self.config.openai_api_key,
                base_url=self.config.openai_base_url,
                model=self.config.openai_stt_model,
                language=self.config.language,
                sample_rate=self.config.sample_rate,
            )
        raise ValueError(
            f"지원하지 않는 STT_PROVIDER입니다: {self.config.stt_provider}"
        )

    async def ensure_ready(self, *, audio: bool) -> None:
        async with self._ready_lock:
            if not self._llm_ready:
                await self.llm.ensure_ready()
                self._llm_ready = True
            if audio and self.transcriber is None:
                self.transcriber = await self._create_transcriber()
            if audio and not self._stt_ready:
                assert self.transcriber is not None
                await self.transcriber.ensure_ready()
                self._stt_ready = True

    async def close(self) -> None:
        if self.transcriber is not None:
            await self.transcriber.close()
        await self.llm.close()
        self.repository.close()


class RealtimeMeetingSession:
    def __init__(self, runtime: RealtimeRuntime, send_event: EventSender, *, audio: bool):
        self.runtime = runtime
        self.config = runtime.config
        self.repository = runtime.repository
        self.send_event = send_event
        self.audio = audio
        self.meeting_id = self.repository.create_meeting()
        self.state = QuestionContextState(meeting_id=self.meeting_id)
        self.context_updater = ContextUpdater(runtime.llm)
        self.question_generator = QuestionGenerator(runtime.llm)
        self.question_evaluator = QuestionEvaluator(runtime.llm)
        self.detector = (
            UtteranceDetector(
                sample_rate=self.config.sample_rate,
                threshold=self.config.vad_threshold,
                min_silence_ms=self.config.min_silence_ms,
                speech_pad_ms=self.config.speech_pad_ms,
                max_utterance_seconds=self.config.max_utterance_seconds,
            )
            if audio
            else None
        )
        self._pcm_remainder = np.empty(0, dtype=np.float32)
        self._analysis_lock = asyncio.Lock()
        self._utterance_queue: asyncio.Queue[AudioUtterance] = asyncio.Queue()
        self._analysis_queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        self._transcription_worker = (
            asyncio.create_task(
                self._transcription_loop(), name=f"transcribe:{self.meeting_id}"
            )
            if audio
            else None
        )
        self._analysis_worker = (
            asyncio.create_task(self._analysis_loop(), name=f"analyze:{self.meeting_id}")
            if audio
            else None
        )
        self._closed = False
        self._last_diagnosis: dict[str, Any] | None = None

    async def feed_pcm(self, payload: bytes) -> None:
        if not self.audio or self.detector is None or not payload:
            return
        usable_length = len(payload) - (len(payload) % 4)
        if usable_length <= 0:
            return
        samples = np.frombuffer(payload[:usable_length], dtype="<f4").astype(np.float32)
        samples = np.clip(samples, -1.0, 1.0)
        combined = np.concatenate((self._pcm_remainder, samples))
        frame_size = self.config.audio_block_size
        offset = 0
        while offset + frame_size <= len(combined):
            utterance = self.detector.push(combined[offset : offset + frame_size])
            offset += frame_size
            if utterance is not None:
                await self._utterance_queue.put(utterance)
        self._pcm_remainder = combined[offset:].copy()

    async def flush_audio(self) -> None:
        if not self.audio or self.detector is None:
            return
        flush_frames = max(
            4, int(1.5 * self.config.sample_rate / self.config.audio_block_size)
        )
        for _ in range(flush_frames):
            utterance = self.detector.push(
                np.zeros(self.config.audio_block_size, dtype=np.float32)
            )
            if utterance is not None:
                await self._utterance_queue.put(utterance)
                break

    async def finish_audio(self) -> None:
        """Flush the final utterance and wait until transcript/question work is done."""
        await self.flush_audio()
        await self._utterance_queue.join()
        await self._analysis_queue.join()

    async def add_text(self, text: str) -> dict[str, Any]:
        lines = [
            line.strip()
            for line in text.replace("\r\n", "\n").split("\n")
            if line.strip()
        ]
        cursor_ms = 0
        for line in lines:
            self.repository.add_segment(
                TranscriptSegment(
                    meeting_id=self.meeting_id,
                    start_ms=cursor_ms,
                    end_ms=cursor_ms + 2_000,
                    text=line,
                )
            )
            cursor_ms += 2_000
        return await self.refresh_questions()

    async def _transcribe_utterance(
        self,
        samples: np.ndarray,
        start_ms: int,
        end_ms: int,
    ) -> None:
        if self.runtime.transcriber is None:
            raise RuntimeError("STT 제공자가 준비되지 않았습니다.")
        await self.send_event({"type": "status", "status": "extracting"})
        async with self.runtime._transcription_lock:
            result = await self.runtime.transcriber.transcribe(samples)
        if not result.text:
            return
        segment = self.repository.add_segment(
            TranscriptSegment(
                meeting_id=self.meeting_id,
                start_ms=start_ms,
                end_ms=end_ms,
                text=result.text,
            )
        )
        await self.send_event(
            {
                "type": "transcript",
                "meeting_id": self.meeting_id,
                "segment": segment.prompt_dict(),
                "transcript": self.transcript_text(),
            }
        )
        if self._analysis_queue.empty():
            self._analysis_queue.put_nowait(None)

    async def _transcription_loop(self) -> None:
        while True:
            utterance = await self._utterance_queue.get()
            try:
                await self._transcribe_utterance(
                    utterance.samples,
                    utterance.start_ms,
                    utterance.end_ms,
                )
            except Exception as error:
                await self.send_event({"type": "error", "message": str(error)})
            finally:
                self._utterance_queue.task_done()

    async def _analysis_loop(self) -> None:
        while True:
            await self._analysis_queue.get()
            try:
                await self.refresh_questions()
            except Exception as error:
                await self.send_event({"type": "error", "message": str(error)})
            finally:
                self._analysis_queue.task_done()

    async def refresh_questions(self) -> dict[str, Any]:
        async with self._analysis_lock:
            new_segments = self.repository.segments_after(
                self.meeting_id, self.state.last_processed_segment_id
            )
            if not new_segments and self._last_diagnosis is not None:
                return self._last_diagnosis

            if new_segments:
                await self.send_event({"type": "status", "status": "generating"})
                recent = self.repository.recent_segments(
                    self.meeting_id, self.config.recent_transcript_seconds
                )
                history = self.repository.question_history(self.meeting_id)
                self.state = await self.context_updater.update(
                    self.state, new_segments, recent, history
                )
                self.repository.save_context(self.state)
            elif self.state.version == 0:
                return self._diagnosis([], [])

            candidates = await self.question_generator.generate(self.state)
            await self.send_event({"type": "status", "status": "selecting"})
            evaluated = await self.question_evaluator.evaluate(self.state, candidates)
            select_top_questions(evaluated, self.config.max_active_questions)
            self.repository.expire_eligible_questions_before(
                self.meeting_id, self.state.version
            )
            self.repository.save_questions(evaluated)

            selected = [
                question
                for question in evaluated
                if question.status is QuestionStatus.ELIGIBLE
            ]
            diagnosis = self._diagnosis(evaluated, selected)
            self._last_diagnosis = diagnosis
            await self.send_event(
                {
                    "type": "questions",
                    "meeting_id": self.meeting_id,
                    "transcript": self.transcript_text(),
                    "diagnosis": diagnosis,
                }
            )
            return diagnosis

    def transcript_text(self) -> str:
        return "\n".join(
            segment.text for segment in self.repository.segments_after(self.meeting_id, 0)
        )

    def _diagnosis(
        self,
        evaluated: list[QuestionCandidate],
        selected: list[QuestionCandidate],
    ) -> dict[str, Any]:
        purpose = str(self.state.current_purpose.get("primary", "unknown"))
        preset = "problem" if purpose == "problem_solving" else "decision"
        questions = [self._question_payload(question) for question in selected]
        rejected = not questions
        return {
            "ok": True,
            "status": "rejected" if rejected else "done",
            "preset": preset,
            "tone": 2,
            "questions": questions,
            "rejected": rejected,
            "reject_reason": (
                "현재 맥락에서 평가 기준을 통과한 질문이 없습니다."
                if rejected
                else None
            ),
            "pipeline": {
                "candidates_generated": len(evaluated),
                "candidates_after_filter": len(selected),
                "selected": len(selected),
            },
        }

    @staticmethod
    def _question_payload(question: QuestionCandidate) -> dict[str, Any]:
        badges: list[str] = []
        if question.information_gain >= 2:
            badges.append("info_gain")
        if question.non_redundancy >= 2:
            badges.append("non_redundant")
        if question.assumption_surfacing >= 2:
            badges.append("assumption")
        if question.final_score >= 2.4:
            badges.append("depth")
        badges.append("relevant")
        return {
            "id": question.id,
            "text": question.text,
            "category": question.category,
            "operator": question.operator,
            "scores": {
                "info_gain": round(question.information_gain / 3, 3),
                "non_redundant": round(question.non_redundancy / 3, 3),
                "relevant": 1.0,
                "depth": round(question.assumption_surfacing / 3, 3),
                "final": round(question.final_score / 3, 3),
            },
            "badges": list(dict.fromkeys(badges)),
            "rationale": question.evaluation_reason,
            "hypothetical_answer_summary": question.detected_problem,
        }

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        workers = [
            worker
            for worker in (self._transcription_worker, self._analysis_worker)
            if worker is not None
        ]
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        self.repository.end_meeting(self.meeting_id)


runtime = RealtimeRuntime()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await runtime.close()


app = FastAPI(title="Q-Agent Realtime", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("CORS_ORIGIN", "http://localhost:3000").split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, Any]:
    provider_error: str | None = None
    try:
        await asyncio.wait_for(
            runtime.ensure_ready(audio=runtime.config.stt_provider == "openai"),
            timeout=5,
        )
    except (ProviderError, TimeoutError) as error:
        provider_error = str(error) or "AI 제공자 상태 확인 시간이 초과되었습니다."
    llm_error = provider_error if not runtime._llm_ready else None
    stt_error = (
        provider_error
        if runtime.config.stt_provider == "openai" and not runtime._stt_ready
        else None
    )
    return {
        "ok": provider_error is None,
        "service": "realtime",
        "provider": runtime.llm.provider,
        "model": runtime.llm.model,
        "llm_ready": runtime._llm_ready,
        "llm_error": llm_error,
        "stt_provider": runtime.config.stt_provider,
        "stt_model": (
            runtime.transcriber.model
            if runtime.transcriber is not None
            else (
                runtime.config.openai_stt_model
                if runtime.config.stt_provider == "openai"
                else os.getenv("WHISPER_MODEL", "turbo")
            )
        ),
        "stt_loaded": runtime.transcriber is not None,
        "stt_ready": runtime._stt_ready,
        "stt_error": stt_error,
        # Backward-compatible diagnostics for existing local tooling.
        "ollama_ready": (
            runtime._llm_ready if runtime.llm.provider == "ollama" else None
        ),
        "ollama_error": llm_error if runtime.llm.provider == "ollama" else None,
        "whisper_loaded": runtime.transcriber is not None,
        "whisper_device": getattr(runtime.transcriber, "device", None),
    }


@app.post("/v1/text", response_model=None)
async def analyze_text(request: TextMeetingRequest) -> dict[str, Any] | JSONResponse:
    text = request.text.strip()
    if len(text) < 8:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": {
                    "code": "INVALID_INPUT",
                    "message": "분석할 텍스트를 8자 이상 입력해 주세요.",
                    "retryable": False,
                },
            },
        )
    try:
        await runtime.ensure_ready(audio=False)
    except ProviderError as error:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": {
                    "code": "LLM_UNAVAILABLE",
                    "message": str(error),
                    "retryable": True,
                },
            },
        )

    async def ignore_event(_event: dict[str, Any]) -> None:
        return None

    session = RealtimeMeetingSession(runtime, ignore_event, audio=False)
    try:
        try:
            diagnosis = await session.add_text(text)
            return {
                "ok": True,
                "meeting_id": session.meeting_id,
                "transcript": session.transcript_text(),
                "diagnosis": diagnosis,
            }
        except ProviderError as error:
            return JSONResponse(
                status_code=502,
                content={
                    "ok": False,
                    "error": {
                        "code": "MODEL_REQUEST_FAILED",
                        "message": str(error),
                        "retryable": True,
                    },
                },
            )
    finally:
        await session.close()


@app.websocket("/v1/realtime")
async def realtime_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    session: RealtimeMeetingSession | None = None
    send_lock = asyncio.Lock()

    async def send_event(event: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(event)

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                if session is not None:
                    await session.feed_pcm(message["bytes"])
                continue

            raw = message.get("text")
            if raw is None:
                continue
            payload = json.loads(raw)
            event_type = payload.get("type")

            if event_type == "start":
                if session is not None:
                    await send_event({"type": "error", "message": "이미 회의가 시작되었습니다."})
                    continue
                if int(payload.get("sample_rate", 0)) != runtime.config.sample_rate:
                    await send_event(
                        {
                            "type": "error",
                            "message": "오디오는 16 kHz mono Float32 PCM이어야 합니다.",
                        }
                    )
                    continue
                await send_event({"type": "status", "status": "loading"})
                await runtime.ensure_ready(audio=True)
                session = RealtimeMeetingSession(runtime, send_event, audio=True)
                await send_event(
                    {
                        "type": "ready",
                        "meeting_id": session.meeting_id,
                        "sample_rate": runtime.config.sample_rate,
                    }
                )
            elif event_type == "stop":
                if session is not None:
                    await session.finish_audio()
                    await send_event(
                        {
                            "type": "stopped",
                            "meeting_id": session.meeting_id,
                            "transcript": session.transcript_text(),
                            "diagnosis": session._last_diagnosis,
                        }
                    )
                    await session.close()
                await websocket.close()
                return
    except WebSocketDisconnect:
        pass
    except (ProviderError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        try:
            await send_event({"type": "error", "message": str(error)})
        except Exception:
            pass
    finally:
        if session is not None:
            await session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Q-Agent realtime web server")
    parser.add_argument("--host", default=os.getenv("REALTIME_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("REALTIME_PORT", "8765")))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
