from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import numpy as np
import uvicorn
from fastapi import FastAPI, Header, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .audio import AudioUtterance, UtteranceDetector
from .config import RuntimeConfig
from .context import ContextUpdater
from .database import Repository
from .domain import QuestionCandidate, QuestionContextState, QuestionStatus, TranscriptSegment
from .llm_roles import RoleLLMs, create_role_llms
from .openai_provider import OpenAITranscriber
from .providers import ProviderError, SpeechTranscriber
from .questions import QuestionEvaluator, QuestionGenerator, select_top_questions
from .session_gate import SessionGate
from .transcriber import FasterWhisperTranscriber


EventSender = Callable[[dict[str, Any]], Awaitable[None]]
logger = logging.getLogger(__name__)
MAX_PCM_MESSAGE_BYTES = 256 * 1024
MAX_CONTROL_MESSAGE_BYTES = 16 * 1024


class TextMeetingRequest(BaseModel):
    text: str = Field(min_length=8, max_length=100_000)
    language: str = Field(default="ko", min_length=2, max_length=16)


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "ok": False,
            "error": {
                "code": "UNAUTHORIZED",
                "message": "유효한 REALTIME_API_KEY Bearer 토큰이 필요합니다.",
                "retryable": False,
            },
        },
    )


def _session_limit() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "ok": False,
            "error": {
                "code": "SESSION_LIMIT",
                "message": "동시 녹음 세션이 가득 찼습니다. 잠시 후 다시 시도해 주세요.",
                "retryable": True,
            },
        },
    )


@dataclass(slots=True)
class CandidateBatch:
    state: QuestionContextState
    candidates: list[QuestionCandidate]


class RealtimeRuntime:
    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.llms: RoleLLMs = create_role_llms(self.config)
        self.repository = Repository(self.config.database_path)
        self.session_gate = SessionGate(
            api_key=self.config.api_key,
            max_audio_sessions=self.config.max_audio_sessions,
            session_ttl_seconds=self.config.session_ttl_seconds,
            max_pending_tickets=self.config.max_pending_tickets,
            max_text_sessions=self.config.max_text_sessions,
        )
        self.transcriber: SpeechTranscriber | None = None
        self._llm_ready = {role: False for role, _ in self.llms.items()}
        self._models_preloaded = False
        self._stt_ready = False
        self._ready_lock = asyncio.Lock()
        self._transcription_lock = asyncio.Lock()

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

    async def ensure_ready(self, *, audio: bool, preload: bool = True) -> None:
        async with self._ready_lock:
            if not all(self._llm_ready.values()):
                await self.llms.ensure_ready()
                self._llm_ready = {role: True for role, _ in self.llms.items()}
            if audio and self.transcriber is None:
                self.transcriber = await self._create_transcriber()
            if audio and not self._stt_ready:
                assert self.transcriber is not None
                await self.transcriber.ensure_ready()
                self._stt_ready = True
            if preload and not self._models_preloaded:
                await self.llms.preload()
                self._models_preloaded = True

    async def close(self) -> None:
        if self.transcriber is not None:
            await self.transcriber.close()
        await self.llms.close()
        self._models_preloaded = False
        self.repository.close()


class RealtimeMeetingSession:
    def __init__(
        self,
        runtime: RealtimeRuntime,
        send_event: EventSender,
        *,
        audio: bool,
        holds_audio_slot: bool = False,
        detector: UtteranceDetector | None = None,
    ):
        self.runtime = runtime
        self.config = runtime.config
        self.repository = runtime.repository
        self.send_event = send_event
        self.audio = audio
        self._holds_audio_slot = holds_audio_slot
        self.meeting_id = self.repository.create_meeting()
        self.state = QuestionContextState(meeting_id=self.meeting_id)
        self.context_updater = ContextUpdater(runtime.llms.context)
        self.question_generator = QuestionGenerator(runtime.llms.generator)
        self.question_evaluator = QuestionEvaluator(runtime.llms.evaluator)
        self.detector = (
            detector or UtteranceDetector(
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
        self._audio_samples_received = 0
        self._state_lock = asyncio.Lock()
        self._context_lock = asyncio.Lock()
        self._generation_lock = asyncio.Lock()
        self._evaluation_lock = asyncio.Lock()
        self._display_lock = asyncio.Lock()
        self._utterance_queue: asyncio.Queue[AudioUtterance] = asyncio.Queue(maxsize=8)
        self._candidate_queue: asyncio.Queue[CandidateBatch] = asyncio.Queue(maxsize=2)
        self._transcript_dirty = asyncio.Event()
        self._context_updated = asyncio.Event()
        self._transcript_lines: list[str] = []
        self._closed = False
        self._last_diagnosis: dict[str, Any] | None = None
        self._last_displayed_diagnosis: dict[str, Any] | None = None
        self._last_generated_context_version = 0
        self._last_generate_at = 0.0
        self._last_reeval_context_version = 0
        self._last_speech_at = time.monotonic()
        self._silence_question_emitted = False
        self._transcription_worker = (
            asyncio.create_task(
                self._transcription_loop(), name=f"transcribe:{self.meeting_id}"
            )
            if audio
            else None
        )
        self._agent_workers = (
            [
                asyncio.create_task(
                    self._context_loop(), name=f"context:{self.meeting_id}"
                ),
                asyncio.create_task(
                    self._question_loop(), name=f"generator:{self.meeting_id}"
                ),
                asyncio.create_task(
                    self._candidate_evaluation_loop(),
                    name=f"candidate-evaluator:{self.meeting_id}",
                ),
                asyncio.create_task(
                    self._reevaluation_loop(),
                    name=f"active-evaluator:{self.meeting_id}",
                ),
                asyncio.create_task(
                    self._silence_loop(), name=f"silence:{self.meeting_id}"
                ),
            ]
            if audio
            else []
        )
    async def feed_pcm(self, payload: bytes) -> None:
        if not self.audio or self.detector is None or not payload:
            return
        if len(payload) > MAX_PCM_MESSAGE_BYTES or len(payload) % 4:
            raise ValueError("오디오 프레임 크기 또는 Float32 PCM 형식이 올바르지 않습니다.")
        samples = np.frombuffer(payload, dtype="<f4").astype(np.float32)
        if not np.isfinite(samples).all():
            raise ValueError("오디오에는 유한한 PCM 값만 포함할 수 있습니다.")
        self._audio_samples_received += samples.size
        if self._audio_samples_received > self.config.max_session_seconds * self.config.sample_rate:
            raise ValueError("최대 회의 오디오 길이를 초과했습니다.")
        samples = np.clip(samples, -1.0, 1.0)
        utterances, speech_active = await asyncio.to_thread(self._process_samples, samples)
        if speech_active or utterances:
            self._last_speech_at = time.monotonic()
            self._silence_question_emitted = False
        for utterance in utterances:
            await self._enqueue_utterance(utterance)

    def _process_samples(self, samples: np.ndarray) -> tuple[list[AudioUtterance], bool]:
        assert self.detector is not None
        combined = np.concatenate((self._pcm_remainder, samples))
        frame_size = self.config.audio_block_size
        offset = 0
        utterances: list[AudioUtterance] = []
        speech_active = False
        while offset + frame_size <= len(combined):
            utterance = self.detector.push(combined[offset : offset + frame_size])
            offset += frame_size
            speech_active = speech_active or self.detector.active
            if utterance is not None:
                utterances.append(utterance)
        self._pcm_remainder = combined[offset:].copy()
        return utterances, speech_active

    async def _enqueue_utterance(self, utterance: AudioUtterance) -> None:
        # Backpressure must preserve uploaded audio instead of dropping speech.
        await asyncio.wait_for(self._utterance_queue.put(utterance), timeout=self.config.request_timeout_seconds)

    async def flush_audio(self) -> None:
        if not self.audio or self.detector is None:
            return
        flush_frames = max(
            4, int(1.5 * self.config.sample_rate / self.config.audio_block_size)
        )
        # Process the remaining partial PCM block before trailing silence.
        utterances, _ = await asyncio.to_thread(
            self._process_samples,
            np.zeros(flush_frames * self.config.audio_block_size, dtype=np.float32),
        )
        for utterance in utterances:
            await self._enqueue_utterance(utterance)

    async def finish_audio(self) -> None:
        """Drain final audio/context before selecting a current question."""
        await self.flush_audio()
        await self._utterance_queue.join()
        while await self._update_context_once():
            pass
        batch = await self._generate_once(enqueue=False, force=True)
        if batch is not None:
            await self._evaluate_batch(batch)
        await self._candidate_queue.join()
        await self._reevaluate_active_questions()
        await self.display_best_question(trigger="stop")

    async def display_best_question(self, *, trigger: str) -> dict[str, Any] | None:
        """Expose questions on silence/ask (one) or session stop (all eligible)."""
        if (
            trigger == "ask"
            and self.repository.best_eligible_question(self.meeting_id) is None
        ):
            await self.run_immediate_analysis()

        async with self._display_lock:
            question = self.repository.best_eligible_question(self.meeting_id)
            if question is not None and question.context_version != self.state.version and self._last_reeval_context_version != self.state.version:
                await self._reevaluate_active_questions()
                question = self.repository.best_eligible_question(self.meeting_id)

            if trigger == "stop":
                selected = self.repository.questions_by_status(
                    self.meeting_id, [QuestionStatus.ELIGIBLE]
                )
                if not selected:
                    diagnosis = self._last_diagnosis or self._diagnosis([], [])
                    self._last_displayed_diagnosis = diagnosis
                    return diagnosis if diagnosis.get("questions") else None
                for item in selected:
                    self.repository.update_question_status(
                        item.id, QuestionStatus.DISPLAYED
                    )
                diagnosis = self._diagnosis(selected, selected)
                self._last_diagnosis = diagnosis
                self._last_displayed_diagnosis = diagnosis
                await self.send_event(
                    {
                        "type": "final_question",
                        "meeting_id": self.meeting_id,
                        "trigger": trigger,
                        "transcript": self.transcript_text(),
                        "diagnosis": diagnosis,
                    }
                )
                return diagnosis

            if question is None:
                if trigger == "ask":
                    diagnosis = self._diagnosis([], [])
                    await self.send_event(
                        {
                            "type": "final_question",
                            "meeting_id": self.meeting_id,
                            "trigger": trigger,
                            "transcript": self.transcript_text(),
                            "diagnosis": diagnosis,
                        }
                    )
                    return diagnosis
                return None
            self.repository.update_question_status(
                question.id, QuestionStatus.DISPLAYED
            )
            diagnosis = self._diagnosis([question], [question])
            self._last_displayed_diagnosis = diagnosis
            if trigger == "silence":
                self._silence_question_emitted = True
            await self.send_event(
                {
                    "type": "final_question",
                    "meeting_id": self.meeting_id,
                    "trigger": trigger,
                    "transcript": self.transcript_text(),
                    "diagnosis": diagnosis,
                }
            )
            return diagnosis

    async def add_text(self, text: str) -> dict[str, Any]:
        lines = [
            line.strip()[offset:offset + 800]
            for line in text.replace("\r\n", "\n").split("\n")
            if line.strip()
            for offset in range(0, len(line.strip()), 800)
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
            self._transcript_lines.append(line)
            cursor_ms += 2_000
        return await self.run_immediate_analysis()

    async def _transcribe_utterance(
        self,
        samples: np.ndarray,
        start_ms: int,
        end_ms: int,
    ) -> None:
        if self.runtime.transcriber is None:
            raise RuntimeError("STT 제공자가 준비되지 않았습니다.")
        await self.send_event({"type": "status", "status": "extracting"})
        if self.runtime.config.stt_provider == "local":
            async with self.runtime._transcription_lock:
                result = await self.runtime.transcriber.transcribe(samples)
        else:
            result = await self.runtime.transcriber.transcribe(samples)
        if not result.text:
            return
        self._last_speech_at = time.monotonic()
        self._silence_question_emitted = False
        segment = self.repository.add_segment(
            TranscriptSegment(
                meeting_id=self.meeting_id,
                start_ms=start_ms,
                end_ms=end_ms,
                text=result.text,
            )
        )
        self._transcript_lines.append(result.text)
        self._transcript_dirty.set()
        await self.send_event(
            {
                "type": "transcript",
                "meeting_id": self.meeting_id,
                "segment": segment.prompt_dict(),
                "transcript": self.transcript_text(),
            }
        )

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
                await self._send_agent_error("transcriber", error)
            finally:
                self._utterance_queue.task_done()

    async def _context_loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    self._transcript_dirty.wait(),
                    timeout=self.config.context_interval_seconds,
                )
            except TimeoutError:
                pass
            self._transcript_dirty.clear()
            try:
                changed = await self._update_context_once()
                if changed:
                    self._context_updated.set()
            except Exception as error:
                await self._send_agent_error("context", error)

    async def _question_loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    self._context_updated.wait(),
                    timeout=self.config.question_interval_seconds,
                )
            except TimeoutError:
                pass
            self._context_updated.clear()
            try:
                await self._generate_once(enqueue=True)
            except Exception as error:
                await self._send_agent_error("generator", error)

    async def _candidate_evaluation_loop(self) -> None:
        while True:
            batch = await self._candidate_queue.get()
            try:
                await self._evaluate_batch(batch)
            except Exception as error:
                await self._send_agent_error("evaluator", error)
            finally:
                self._candidate_queue.task_done()

    async def _reevaluation_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.reevaluation_interval_seconds)
            async with self._state_lock:
                version = self.state.version
            if version == 0 or version == self._last_reeval_context_version:
                continue
            try:
                result = await self._reevaluate_active_questions()
                if result is not None:
                    self._last_reeval_context_version = version
            except Exception as error:
                await self._send_agent_error("evaluator", error)

    async def _silence_loop(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            silent_for = time.monotonic() - self._last_speech_at
            if (
                silent_for >= self.config.silence_trigger_seconds
                and not self._silence_question_emitted
            ):
                try:
                    displayed = await self.display_best_question(trigger="silence")
                except Exception as error:
                    await self._send_agent_error("evaluator", error)
                    displayed = None
                if displayed is not None:
                    self._silence_question_emitted = True
                else:
                    # Pool empty: backoff so we retry after more context accumulates
                    # instead of consuming the silence window forever.
                    self._last_speech_at = (
                        time.monotonic()
                        - (self.config.silence_trigger_seconds / 2)
                    )

    async def run_immediate_analysis(self) -> dict[str, Any]:
        while await self._update_context_once():
            pass
        batch = await self._generate_once(enqueue=False)
        if batch is not None:
            return await self._evaluate_batch(batch)
        if self._last_diagnosis is not None:
            return self._last_diagnosis
        return self._diagnosis([], [])

    async def _update_context_once(self) -> bool:
        async with self._context_lock:
            state_snapshot = await self._state_snapshot()
            base_version = state_snapshot.version
            new_segments = self.repository.segments_after(
                self.meeting_id, state_snapshot.last_processed_segment_id
            )
            if not new_segments:
                return False
            recent = self.repository.recent_segments(
                self.meeting_id, self.config.recent_transcript_seconds
            )
            history = self.repository.question_history(self.meeting_id)
            await self.send_event(
                {"type": "status", "status": "generating", "agent": "context"}
            )
            try:
                updated = await self.context_updater.update(
                    state_snapshot, new_segments, recent, history
                )
            except ProviderError as error:
                raise ProviderError(f"Context Agent 실패: {error}") from error
            async with self._state_lock:
                if self.state.version != base_version:
                    return False
                self.state = updated
            self.repository.save_context(updated)
            if self.repository.segments_after(self.meeting_id, updated.last_processed_segment_id):
                self._transcript_dirty.set()
            await self.send_event(
                {
                    "type": "context",
                    "meeting_id": self.meeting_id,
                    "version": updated.version,
                    "topic": updated.current_topic,
                    "purpose": updated.current_purpose,
                }
            )
            self._context_updated.set()
            return True

    async def _generate_once(self, *, enqueue: bool, force: bool = False) -> CandidateBatch | None:
        async with self._generation_lock:
            state_snapshot = await self._state_snapshot(include_history=True)
            if (
                state_snapshot.version == 0
                or state_snapshot.version <= self._last_generated_context_version
            ):
                return None
            now = time.monotonic()
            if (
                not force and self._last_generate_at > 0
                and now - self._last_generate_at
                < self.config.generator_min_interval_seconds
            ):
                return None
            await self.send_event(
                {"type": "status", "status": "generating", "agent": "generator"}
            )
            try:
                candidates = await self.question_generator.generate(state_snapshot)
            except ProviderError as error:
                raise ProviderError(f"Question Generator 실패: {error}") from error
            self._last_generated_context_version = state_snapshot.version
            self._last_generate_at = now
            batch = CandidateBatch(state=state_snapshot, candidates=candidates)
            if enqueue:
                if self._candidate_queue.full():
                    self._candidate_queue.get_nowait()
                    self._candidate_queue.task_done()
                await self._candidate_queue.put(batch)
            return batch

    async def _evaluate_batch(self, batch: CandidateBatch) -> dict[str, Any]:
        async with self._evaluation_lock:
            await self.send_event(
                {"type": "status", "status": "selecting", "agent": "evaluator"}
            )
            try:
                evaluated = await self.question_evaluator.evaluate(
                    batch.state, batch.candidates
                )
            except ProviderError as error:
                raise ProviderError(f"Question Evaluator 실패: {error}") from error
            select_top_questions(evaluated, self.config.max_active_questions)
            current_state = await self._state_snapshot()
            if current_state.version != batch.state.version:
                # Do not publish questions scored against an obsolete conversation.
                return self._last_diagnosis or self._diagnosis([], [])
            self.repository.expire_eligible_questions_before(
                self.meeting_id, batch.state.version
            )
            self.repository.save_questions(evaluated)
            self._last_reeval_context_version = batch.state.version
            selected = [
                question
                for question in evaluated
                if question.status is QuestionStatus.ELIGIBLE
            ]
            diagnosis = self._diagnosis(evaluated, selected)
            self._last_diagnosis = diagnosis
        await self._send_pool_update(diagnosis)
        return diagnosis

    async def _reevaluate_active_questions(self) -> dict[str, Any] | None:
        if self.state.version == self._last_reeval_context_version:
            return None
        active = self.repository.questions_by_status(
            self.meeting_id, [QuestionStatus.ELIGIBLE]
        )
        if not active:
            return None
        state_snapshot = await self._state_snapshot(include_history=True)
        async with self._evaluation_lock:
            await self.send_event(
                {"type": "status", "status": "selecting", "agent": "evaluator"}
            )
            try:
                evaluated = await self.question_evaluator.evaluate(
                    state_snapshot, active, mode="reeval"
                )
            except ProviderError as error:
                raise ProviderError(f"Question Evaluator 실패: {error}") from error
            select_top_questions(evaluated, self.config.max_active_questions)
            if (await self._state_snapshot()).version != state_snapshot.version:
                return None
            self.repository.save_questions(evaluated)
            selected = self.repository.questions_by_status(
                self.meeting_id, [QuestionStatus.ELIGIBLE]
            )
            diagnosis = self._diagnosis(evaluated, selected)
            self._last_diagnosis = diagnosis
            self._last_reeval_context_version = state_snapshot.version
        await self._send_pool_update(diagnosis)
        return diagnosis

    async def _state_snapshot(
        self, *, include_history: bool = False
    ) -> QuestionContextState:
        async with self._state_lock:
            snapshot = copy.deepcopy(self.state)
        if include_history:
            snapshot.question_history = self.repository.question_history(self.meeting_id)
        return snapshot

    async def _send_pool_update(self, diagnosis: dict[str, Any]) -> None:
        """Background eligible pool — not the final on-screen question."""
        await self.send_event(
            {
                "type": "pool_update",
                "meeting_id": self.meeting_id,
                "transcript": self.transcript_text(),
                "diagnosis": diagnosis,
                "pool_size": diagnosis.get("pipeline", {}).get("selected", 0),
            }
        )

    async def _send_agent_error(self, agent: str, error: Exception) -> None:
        logger.warning("%s agent failed", agent, exc_info=error)
        await self.send_event(
            {"type": "error", "agent": agent, "code": "AGENT_FAILED",
             "retryable": True, "message": "AI 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."}
        )

    def transcript_text(self) -> str:
        if self._transcript_lines:
            return "\n".join(self._transcript_lines)
        lines = [
            segment.text
            for segment in self.repository.segments_after(self.meeting_id, 0)
        ]
        self._transcript_lines = lines
        return "\n".join(lines)

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
        if question.purpose_fit >= 2:
            badges.append("info_gain")
        if question.non_redundancy >= 2:
            badges.append("non_redundant")
        if question.critical_push >= 2:
            badges.append("assumption")
        if question.specificity >= 2 or question.contextual_fit >= 2:
            badges.append("relevant")
        if question.openness >= 2 or question.follow_through >= 2 or question.final_score >= 2.4:
            badges.append("depth")
        if "relevant" not in badges:
            badges.append("relevant")
        return {
            "id": question.id,
            "text": question.text,
            "category": question.category,
            "operator": question.operator,
            "scores": {
                "info_gain": round(question.purpose_fit / 3, 3),
                "non_redundant": round(question.non_redundancy / 3, 3),
                "relevant": round(
                    (question.specificity + question.contextual_fit) / 6, 3
                ),
                "depth": round(
                    (question.critical_push + question.openness + question.follow_through)
                    / 9,
                    3,
                ),
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
            for worker in (self._transcription_worker, *self._agent_workers)
            if worker is not None
        ]
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        try:
            self.repository.end_meeting(self.meeting_id)
        finally:
            if self._holds_audio_slot:
                self.runtime.session_gate.release_audio_slot()
                self._holds_audio_slot = False


runtime = RealtimeRuntime()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await runtime.close()


app = FastAPI(title="Q-Agent Realtime", version="0.1.0", lifespan=lifespan)
allowed_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "CORS_ORIGIN", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",") if origin.strip()
]


class RequestBodyLimitMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 512 * 1024:
                response = JSONResponse(status_code=413, content={
                    "ok": False, "error": {"code": "INPUT_TOO_LARGE",
                    "message": "요청 크기가 512 KiB를 초과했습니다.", "retryable": False},
                })
                await response(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def limited_receive() -> Any:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, limited_receive, send)


app.add_middleware(RequestBodyLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, Any]:
    provider_error: str | None = None
    try:
        await asyncio.wait_for(
            runtime.ensure_ready(
                audio=runtime.config.stt_provider == "openai", preload=False
            ),
            timeout=5,
        )
    except (ProviderError, TimeoutError):
        provider_error = "AI 제공자에 연결할 수 없습니다. 서버 설정을 확인해 주세요."
    all_llms_ready = all(runtime._llm_ready.values())
    llm_error = provider_error if not all_llms_ready else None
    stt_error = (
        provider_error
        if runtime.config.stt_provider == "openai" and not runtime._stt_ready
        else None
    )
    return {
        "ok": provider_error is None,
        "service": "realtime",
        "provider": runtime.llms.generator.provider,
        "model": runtime.llms.generator.model,
        "models": runtime.llms.models(),
        "llm_ready": all_llms_ready,
        "llm_roles_ready": runtime._llm_ready,
        "models_preloaded": runtime._models_preloaded,
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
        "auth_required": runtime.session_gate.auth_required,
        "max_audio_sessions": runtime.config.max_audio_sessions,
        "active_audio_sessions": runtime.session_gate.active_audio_sessions,
        # Backward-compatible diagnostics for existing local tooling.
        "ollama_ready": (
            all_llms_ready if runtime.llms.generator.provider == "ollama" else None
        ),
        "ollama_error": (
            llm_error if runtime.llms.generator.provider == "ollama" else None
        ),
        "whisper_loaded": runtime.transcriber is not None,
        "whisper_device": getattr(runtime.transcriber, "device", None),
    }


@app.post("/v1/session", response_model=None)
async def create_session(
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    if not runtime.session_gate.check_api_key(authorization):
        return _unauthorized()
    if runtime.session_gate.active_audio_sessions >= runtime.config.max_audio_sessions:
        return _session_limit()
    try:
        ticket = runtime.session_gate.issue_ticket(kind="audio")
    except ValueError:
        return _session_limit()
    return {
        "ok": True,
        "token": ticket.token,
        "expires_in": int(runtime.config.session_ttl_seconds),
        "max_audio_sessions": runtime.config.max_audio_sessions,
        "active_audio_sessions": runtime.session_gate.active_audio_sessions,
    }


@app.post("/v1/text", response_model=None)
async def analyze_text(
    request: TextMeetingRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    if not runtime.session_gate.check_api_key(authorization):
        return _unauthorized()
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
    async def ignore_event(_event: dict[str, Any]) -> None:
        return None

    if not runtime.session_gate.try_acquire_text_slot():
        return JSONResponse(status_code=503, content={"ok": False, "error": {
            "code": "SESSION_LIMIT", "message": "분석 요청이 많습니다. 잠시 후 다시 시도해 주세요.",
            "retryable": True,
        }})
    session: RealtimeMeetingSession | None = None
    try:
        try:
            async with asyncio.timeout(runtime.config.request_timeout_seconds):
                await runtime.ensure_ready(audio=False)
                session = RealtimeMeetingSession(runtime, ignore_event, audio=False)
                diagnosis = await session.add_text(text)
            return {
                "ok": True,
                "meeting_id": session.meeting_id,
                "transcript": session.transcript_text(),
                "diagnosis": diagnosis,
            }
        except (ProviderError, TimeoutError) as error:
            logger.warning("Text analysis failed", exc_info=error)
            return JSONResponse(
                status_code=502,
                content={
                    "ok": False,
                    "error": {
                        "code": "MODEL_REQUEST_FAILED",
                        "message": "AI 분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.",
                        "retryable": True,
                    },
                },
            )
    finally:
        try:
            if session is not None:
                await session.close()
        finally:
            runtime.session_gate.release_text_slot()


@app.websocket("/v1/realtime")
async def realtime_socket(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if origin and origin.rstrip("/") not in allowed_origins and "*" not in allowed_origins:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    session: RealtimeMeetingSession | None = None
    send_lock = asyncio.Lock()
    ask_task: asyncio.Task[None] | None = None
    connected_at = time.monotonic()

    async def send_event(event: dict[str, Any]) -> None:
        async with send_lock:
            await asyncio.wait_for(websocket.send_json(event), timeout=10)

    async def answer_request(active_session: RealtimeMeetingSession) -> None:
        # Asking may run three model calls. Keep accepting PCM in the meantime.
        try:
            async with asyncio.timeout(runtime.config.request_timeout_seconds):
                await active_session.display_best_question(trigger="ask")
        except Exception as error:
            await active_session._send_agent_error("evaluator", error)

    try:
        while True:
            remaining = runtime.config.max_session_seconds - (time.monotonic() - connected_at)
            if remaining <= 0:
                raise ValueError("최대 회의 시간이 초과되었습니다.")
            message = await asyncio.wait_for(
                websocket.receive(),
                timeout=min(remaining, runtime.config.websocket_idle_seconds if session else 30),
            )
            if message.get("type") == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                if session is not None:
                    await session.feed_pcm(message["bytes"])
                continue

            raw = message.get("text")
            if raw is None:
                continue
            if len(raw.encode("utf-8")) > MAX_CONTROL_MESSAGE_BYTES:
                raise ValueError("제어 메시지가 너무 큽니다.")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("제어 메시지는 JSON 객체여야 합니다.")
            event_type = payload.get("type")

            if event_type == "start":
                if session is not None:
                    await send_event({"type": "error", "message": "이미 회의가 시작되었습니다."})
                    continue
                if payload.get("sample_rate") != runtime.config.sample_rate:
                    await send_event(
                        {
                            "type": "error",
                            "message": "오디오는 16 kHz mono Float32 PCM이어야 합니다.",
                        }
                    )
                    continue
                ticket = runtime.session_gate.consume_ticket(
                    payload.get("session_token")
                )
                if ticket is None or ticket.kind != "audio":
                    await send_event(
                        {
                            "type": "error",
                            "message": "유효한 녹음 세션 토큰이 필요합니다. 페이지를 새로고침한 뒤 다시 시작해 주세요.",
                        }
                    )
                    await websocket.close(code=4401)
                    return
                if not runtime.session_gate.try_acquire_audio_slot():
                    await send_event(
                        {
                            "type": "error",
                            "message": "동시 녹음 세션이 가득 찼습니다. 잠시 후 다시 시도해 주세요.",
                        }
                    )
                    await websocket.close(code=1013)
                    return
                try:
                    await send_event({"type": "status", "status": "loading"})
                    async with asyncio.timeout(runtime.config.request_timeout_seconds):
                        await runtime.ensure_ready(audio=True)
                        detector = await asyncio.to_thread(
                            UtteranceDetector, sample_rate=runtime.config.sample_rate,
                            threshold=runtime.config.vad_threshold,
                            min_silence_ms=runtime.config.min_silence_ms,
                            speech_pad_ms=runtime.config.speech_pad_ms,
                            max_utterance_seconds=runtime.config.max_utterance_seconds,
                        )
                    session = RealtimeMeetingSession(
                        runtime,
                        send_event,
                        audio=True,
                        holds_audio_slot=True,
                        detector=detector,
                    )
                except BaseException:
                    runtime.session_gate.release_audio_slot()
                    raise
                await send_event(
                    {
                        "type": "ready",
                        "meeting_id": session.meeting_id,
                        "sample_rate": runtime.config.sample_rate,
                    }
                )
            elif event_type == "ask":
                if session is None:
                    await send_event(
                        {"type": "error", "message": "회의가 시작되지 않았습니다."}
                    )
                    continue
                if ask_task is None or ask_task.done():
                    ask_task = asyncio.create_task(answer_request(session))
            elif event_type == "stop":
                if ask_task is not None:
                    ask_task.cancel()
                    await asyncio.gather(ask_task, return_exceptions=True)
                    ask_task = None
                if session is not None:
                    async with asyncio.timeout(runtime.config.request_timeout_seconds):
                        await session.finish_audio()
                    await send_event(
                        {
                            "type": "stopped",
                            "meeting_id": session.meeting_id,
                            "transcript": session.transcript_text(),
                            "diagnosis": session._last_displayed_diagnosis,
                        }
                    )
                    await session.close()
                    session = None
                await websocket.close()
                return
            else:
                raise ValueError("지원하지 않는 제어 메시지입니다.")
    except WebSocketDisconnect:
        pass
    except (ProviderError, ValueError, RuntimeError, TimeoutError) as error:
        logger.warning("Realtime session failed", exc_info=error)
        try:
            await send_event({"type": "error", "code": "SESSION_FAILED", "retryable": True,
                              "message": str(error) if isinstance(error, ValueError) else
                              "실시간 처리가 중단되었습니다. 잠시 후 다시 시도해 주세요."})
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if ask_task is not None:
            ask_task.cancel()
            await asyncio.gather(ask_task, return_exceptions=True)
        if session is not None:
            await session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Q-Agent realtime web server")
    parser.add_argument("--host", default=os.getenv("REALTIME_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT") or os.getenv("REALTIME_PORT", "8765")))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    uvicorn.run(app, host=args.host, port=args.port, ws_max_size=MAX_PCM_MESSAGE_BYTES, ws_max_queue=8)


if __name__ == "__main__":
    main()
