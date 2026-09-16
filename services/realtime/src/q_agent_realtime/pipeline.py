from __future__ import annotations

import asyncio
import copy
import time
from datetime import datetime

from .audio import MicrophoneStream, UtteranceDetector
from .config import RuntimeConfig
from .context import ContextUpdater
from .database import Repository
from .domain import QuestionContextState, QuestionStatus, TranscriptSegment
from .providers import ProviderError, SpeechTranscriber, StructuredLLMClient
from .questions import QuestionEvaluator, QuestionGenerator, select_top_questions


class MeetingPipeline:
    def __init__(
        self,
        config: RuntimeConfig,
        repository: Repository,
        llm: StructuredLLMClient,
        transcriber: SpeechTranscriber,
    ):
        self.config = config
        self.repository = repository
        self.llm = llm
        self.transcriber = transcriber
        self.context_updater = ContextUpdater(llm)
        self.question_generator = QuestionGenerator(llm)
        self.question_evaluator = QuestionEvaluator(llm)
        self.stop_event = asyncio.Event()
        self.state_lock = asyncio.Lock()
        self.meeting_id = ""
        self.state: QuestionContextState | None = None
        self.last_speech_at = time.monotonic()
        self.silence_question_emitted = False
        self.last_generated_context_version = 0

    async def run(self) -> None:
        await self.llm.ensure_ready()
        await self.transcriber.ensure_ready()
        self.meeting_id = self.repository.create_meeting(self.config.meeting_objective)
        self.state = QuestionContextState(
            meeting_id=self.meeting_id,
            meeting_objective=self.config.meeting_objective,
        )
        print(f"[meeting] {self.meeting_id}")
        print("[control] Enter: 질문 요청 / q + Enter: 종료")

        tasks = [
            asyncio.create_task(self._audio_loop(), name="audio"),
            asyncio.create_task(self._context_loop(), name="context"),
            asyncio.create_task(self._question_loop(), name="question"),
            asyncio.create_task(self._reevaluation_loop(), name="reevaluation"),
            asyncio.create_task(self._silence_loop(), name="silence"),
            asyncio.create_task(self._command_loop(), name="command"),
        ]
        for task in tasks:
            task.add_done_callback(self._on_task_finished)
        try:
            await self.stop_event.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.repository.end_meeting(self.meeting_id)
            await self.transcriber.close()
            await self.llm.close()
            self.repository.close()
            print("[meeting] 종료 및 저장 완료")

    def _on_task_finished(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            print(f"[{task.get_name()}:fatal] {error}")
            self.stop_event.set()

    async def _audio_loop(self) -> None:
        microphone = MicrophoneStream(
            sample_rate=self.config.sample_rate,
            block_size=self.config.audio_block_size,
            device=self.config.microphone_device,
        )
        detector = UtteranceDetector(
            sample_rate=self.config.sample_rate,
            threshold=self.config.vad_threshold,
            min_silence_ms=self.config.min_silence_ms,
            speech_pad_ms=self.config.speech_pad_ms,
            max_utterance_seconds=self.config.max_utterance_seconds,
        )
        async for frame in microphone.frames():
            utterance = detector.push(frame)
            if detector.active:
                self.last_speech_at = time.monotonic()
                self.silence_question_emitted = False
            if utterance is None:
                continue
            try:
                result = await self.transcriber.transcribe(utterance.samples)
            except Exception as error:
                print(f"[asr:error] {error}")
                continue
            if not result.text:
                continue
            segment = self.repository.add_segment(
                TranscriptSegment(
                    meeting_id=self.meeting_id,
                    start_ms=utterance.start_ms,
                    end_ms=utterance.end_ms,
                    text=result.text,
                )
            )
            clock = datetime.now().strftime("%H:%M:%S")
            print(f"[{clock}] {segment.text}")

    async def _context_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.context_interval_seconds)
            state_snapshot = await self._state_snapshot()
            new_segments = self.repository.segments_after(
                self.meeting_id, state_snapshot.last_processed_segment_id
            )
            if not new_segments:
                continue
            recent = self.repository.recent_segments(
                self.meeting_id, self.config.recent_transcript_seconds
            )
            history = self.repository.question_history(self.meeting_id)
            try:
                base_version = state_snapshot.version
                updated_state = await self.context_updater.update(
                    state_snapshot, new_segments, recent, history
                )
                async with self.state_lock:
                    assert self.state is not None
                    if self.state.version != base_version:
                        print("[context] 더 최신 상태가 있어 갱신 결과를 폐기합니다")
                        continue
                    self.state = updated_state
                self.repository.save_context(updated_state)
                print(
                    f"[context] v{updated_state.version} / "
                    f"{updated_state.current_purpose.get('primary', 'unknown')} / "
                    f"{updated_state.current_topic}"
                )
            except ProviderError as error:
                print(f"[context:error] {error}")

    async def _question_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.question_interval_seconds)
            state_snapshot = await self._state_snapshot(include_history=True)
            if (
                state_snapshot.version == 0
                or state_snapshot.version == self.last_generated_context_version
            ):
                continue
            try:
                candidates = await self.question_generator.generate(state_snapshot)
                evaluated = await self.question_evaluator.evaluate(
                    state_snapshot, candidates
                )
                select_top_questions(evaluated, self.config.max_active_questions)
                if not await self._is_current_version(state_snapshot.version):
                    print("[questions] 맥락이 갱신되어 오래된 질문 결과를 폐기합니다")
                    continue
                self.repository.expire_eligible_questions_before(
                    self.meeting_id, state_snapshot.version
                )
                self.repository.save_questions(evaluated)
                self.last_generated_context_version = state_snapshot.version
                eligible = sum(q.status is QuestionStatus.ELIGIBLE for q in evaluated)
                print(f"[questions] 후보 {len(evaluated)}개 / 활성 {eligible}개")
            except ProviderError as error:
                print(f"[questions:error] {error}")

    async def _reevaluation_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.reevaluation_interval_seconds)
            active = self.repository.questions_by_status(
                self.meeting_id, [QuestionStatus.ELIGIBLE]
            )
            if not active:
                continue
            state_snapshot = await self._state_snapshot(include_history=True)
            try:
                evaluated = await self.question_evaluator.evaluate(state_snapshot, active)
                select_top_questions(evaluated, self.config.max_active_questions)
                if not await self._is_current_version(state_snapshot.version):
                    print("[questions] 맥락이 갱신되어 재평가 결과를 폐기합니다")
                    continue
                self.repository.save_questions(evaluated)
                print(f"[questions] 활성 질문 {len(evaluated)}개 재평가")
            except ProviderError as error:
                print(f"[reevaluation:error] {error}")

    async def _silence_loop(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            silent_for = time.monotonic() - self.last_speech_at
            if (
                silent_for >= self.config.silence_trigger_seconds
                and not self.silence_question_emitted
            ):
                displayed = self._display_best_question()
                if displayed:
                    self.silence_question_emitted = True

    async def _command_loop(self) -> None:
        while True:
            try:
                command = await asyncio.to_thread(input)
            except (EOFError, KeyboardInterrupt):
                self.stop_event.set()
                return
            if command.strip().lower() == "q":
                self.stop_event.set()
                return
            self._display_best_question()

    def _display_best_question(self) -> bool:
        question = self.repository.best_eligible_question(self.meeting_id)
        if question is None:
            return False
        print(f"\n{question.text}\n")
        self.repository.update_question_status(question.id, QuestionStatus.DISPLAYED)
        return True

    async def _state_snapshot(
        self, *, include_history: bool = False
    ) -> QuestionContextState:
        async with self.state_lock:
            assert self.state is not None
            snapshot = copy.deepcopy(self.state)
        if include_history:
            snapshot.question_history = self.repository.question_history(self.meeting_id)
        return snapshot

    async def _is_current_version(self, version: int) -> bool:
        async with self.state_lock:
            return self.state is not None and self.state.version == version
