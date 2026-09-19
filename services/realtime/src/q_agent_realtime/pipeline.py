from __future__ import annotations

import asyncio
import copy
import time
from datetime import datetime

from .audio import MicrophoneStream, UtteranceDetector
from .config import RuntimeConfig
from .context import ContextUpdater
from .database import Repository
from .domain import (
    QuestionCandidate,
    QuestionContextState,
    QuestionStatus,
    TranscriptSegment,
)
from .llm_roles import RoleLLMs
from .providers import ProviderError, SpeechTranscriber
from .questions import QuestionEvaluator, QuestionGenerator, select_top_questions


class MeetingPipeline:
    def __init__(
        self,
        config: RuntimeConfig,
        repository: Repository,
        llms: RoleLLMs,
        transcriber: SpeechTranscriber,
    ):
        self.config = config
        self.repository = repository
        self.llms = llms
        self.transcriber = transcriber
        self.context_updater = ContextUpdater(llms.context)
        self.question_generator = QuestionGenerator(llms.generator)
        self.question_evaluator = QuestionEvaluator(llms.evaluator)
        self.stop_event = asyncio.Event()
        self.state_lock = asyncio.Lock()
        self.meeting_id = ""
        self.state: QuestionContextState | None = None
        self.last_speech_at = time.monotonic()
        self.silence_question_emitted = False
        self.last_generated_context_version = 0
        self.last_generated_at = 0.0
        self.last_reeval_context_version = 0
        self.candidate_queue: asyncio.Queue[
            tuple[QuestionContextState, list[QuestionCandidate]]
        ] = asyncio.Queue(maxsize=2)

    async def run(self) -> None:
        await self.llms.ensure_ready()
        await self.transcriber.ensure_ready()
        await self.llms.preload()
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
            asyncio.create_task(
                self._candidate_evaluation_loop(), name="candidate-evaluation"
            ),
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
            await self.llms.close()
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
            if utterance is None:
                continue
            self.last_speech_at = time.monotonic()
            self.silence_question_emitted = False
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
                or state_snapshot.version <= self.last_generated_context_version
                or time.monotonic() - self.last_generated_at < self.config.generator_min_interval_seconds
            ):
                continue
            try:
                candidates = await self.question_generator.generate(state_snapshot)
                self.last_generated_context_version = state_snapshot.version
                self.last_generated_at = time.monotonic()
                if self.candidate_queue.full():
                    self.candidate_queue.get_nowait()
                    self.candidate_queue.task_done()
                await self.candidate_queue.put((state_snapshot, candidates))
                print(f"[generator] v{state_snapshot.version} 후보 {len(candidates)}개")
            except ProviderError as error:
                print(f"[generator:error] {error}")

    async def _candidate_evaluation_loop(self) -> None:
        while True:
            batch = await self.candidate_queue.get()
            try:
                state_snapshot, candidates = batch
                evaluated = await self.question_evaluator.evaluate(
                    state_snapshot, candidates
                )
                select_top_questions(evaluated, self.config.max_active_questions)
                if (await self._state_snapshot()).version != state_snapshot.version:
                    continue
                self.repository.expire_eligible_questions_before(
                    self.meeting_id, state_snapshot.version
                )
                self.repository.save_questions(evaluated)
                self.last_reeval_context_version = state_snapshot.version
                eligible = sum(q.status is QuestionStatus.ELIGIBLE for q in evaluated)
                print(f"[evaluator] 후보 {len(evaluated)}개 / 활성 {eligible}개")
            except ProviderError as error:
                print(f"[evaluator:error] {error}")
            finally:
                self.candidate_queue.task_done()

    async def _reevaluation_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.reevaluation_interval_seconds)
            await self._reevaluate_active()

    async def _reevaluate_active(self) -> None:
        active = self.repository.questions_by_status(
            self.meeting_id, [QuestionStatus.ELIGIBLE]
        )
        if not active:
            return
        state_snapshot = await self._state_snapshot(include_history=True)
        if (
            state_snapshot.version == 0
            or state_snapshot.version == self.last_reeval_context_version
        ):
            return
        try:
            evaluated = await self.question_evaluator.evaluate(
                state_snapshot, active, mode="reeval"
            )
            select_top_questions(evaluated, self.config.max_active_questions)
            if (await self._state_snapshot()).version != state_snapshot.version:
                return
            self.repository.save_questions(evaluated)
            self.last_reeval_context_version = state_snapshot.version
            print(f"[evaluator] 활성 질문 {len(evaluated)}개 재평가")
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
                await self._reevaluate_active()
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
            await self._reevaluate_active()
            self._display_best_question()

    def _display_best_question(self) -> bool:
        question = self.repository.best_eligible_question(self.meeting_id)
        if question is None:
            return False
        if self.state is None or self.last_reeval_context_version != self.state.version:
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
