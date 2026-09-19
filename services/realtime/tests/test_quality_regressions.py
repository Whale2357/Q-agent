from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from q_agent_realtime.context import ContextUpdater, build_askable_focus, normalize_discussion_state
from q_agent_realtime.database import Repository
from q_agent_realtime.domain import DISCUSSION_KEYS, QuestionCandidate, QuestionContextState, QuestionStatus, TranscriptSegment
from q_agent_realtime.questions import QuestionEvaluator, QuestionGenerator, _score, select_top_questions
from q_agent_realtime.providers import ProviderError


def candidate(meeting_id="meeting", **changes):
    values = dict(id="q1", meeting_id=meeting_id, text="QA 완료 여부는 어떤 기준으로 확인할까요?",
        meeting_purpose="decision_making", detected_problem="QA 기준 미정", question_role="기준 확인",
        theory="Inquiry", evidence_segment_ids=[1], context_version=1)
    return QuestionCandidate(**(values | changes))


def state():
    result = QuestionContextState(meeting_id="meeting", version=1,
        recent_transcript=[{"segment_id": 1, "text": "QA 완료 기준이 아직 정해지지 않았습니다."}])
    result.discussion_state["open_issues"] = [{"content": "QA 완료 기준", "status": "open", "evidence_segment_ids": [1]}]
    return result


def scores(**changes):
    return dict(question_id="q1", clarity=3, specificity=3, purpose_fit=3, critical_push=3,
        contextual_fit=3, openness=3, follow_through=3, neutrality=3, already_resolved=False,
        stale_reason="none", reason="QA 기준의 답에 따라 출시 결정이 달라집니다.") | changes


class QualityRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_reevaluation_does_not_reject_itself(self):
        snapshot = state()
        q = candidate()
        snapshot.question_history["active"] = [{"id": q.id, "text": q.text}]
        client = AsyncMock()
        client.chat_json.return_value = {"evaluations": [scores()]}
        await QuestionEvaluator(client).evaluate(snapshot, [q], mode="reeval")
        self.assertEqual(q.status, QuestionStatus.ELIGIBLE)
        sent = json.loads(client.chat_json.call_args.kwargs["user"])
        self.assertEqual(sent["question_context_state"]["question_history"]["active"], [])

    async def test_displayed_question_is_rejected_as_duplicate(self):
        snapshot = state()
        q = candidate()
        snapshot.question_history["displayed"] = [{"id": "older", "text": q.text}]
        client = AsyncMock()
        await QuestionEvaluator(client).evaluate(snapshot, [q])
        self.assertEqual(q.status, QuestionStatus.REJECTED)
        client.chat_json.assert_not_called()

    async def test_parked_question_can_be_generated_again(self):
        snapshot = state()
        q = candidate()
        snapshot.question_history["parked"] = [{"id": "older", "text": q.text}]
        client = AsyncMock()
        client.chat_json.return_value = {"evaluations": [scores()]}
        await QuestionEvaluator(client).evaluate(snapshot, [q])
        self.assertEqual(q.status, QuestionStatus.ELIGIBLE)

    async def test_malformed_or_unsafe_scores_never_pass(self):
        for payload in [scores(clarity=True), scores(clarity=float("nan")), scores(already_resolved="false"), scores(neutrality=1), scores(stale_reason=[]), scores(stale_reason={})]:
            q = candidate()
            client = AsyncMock()
            client.chat_json.return_value = {"evaluations": [payload]}
            await QuestionEvaluator(client).evaluate(state(), [q])
            self.assertEqual(q.status, QuestionStatus.REJECTED)
        for value in [True, math.inf, -math.inf, math.nan, "NaN"]:
            self.assertEqual(_score(value), 0)

    async def test_duplicate_evaluation_ids_fail_closed(self):
        client = AsyncMock()
        client.chat_json.return_value = {"evaluations": [scores(), scores()]}
        q = candidate()
        await QuestionEvaluator(client).evaluate(state(), [q])
        self.assertEqual(q.status, QuestionStatus.REJECTED)

    async def test_fabricated_generator_evidence_is_filtered(self):
        client = AsyncMock()
        client.chat_json.return_value = {"meeting_purpose": "decision_making", "candidates": [
            {"text": "QA 완료 여부는 어떤 기준으로 확인할까요?", "evidence_segment_ids": [999], "anchor_terms": ["QA"], "category": "essence", "operator": "criterion_clarification"},
            {"text": "QA 비용 100만원은 어떤 기준으로 확인할까요?", "evidence_segment_ids": [1], "anchor_terms": ["QA", "100만원"], "category": "essence", "operator": "criterion_clarification"},
        ]}
        self.assertEqual(await QuestionGenerator(client).generate(state()), [])

    async def test_empty_context_does_not_spend_generation_call(self):
        client = AsyncMock()
        self.assertEqual(await QuestionGenerator(client).generate(QuestionContextState(meeting_id="empty")), [])
        client.chat_json.assert_not_called()

    async def test_invalid_context_does_not_advance_transcript_cursor(self):
        client = AsyncMock()
        client.chat_json.return_value = {}
        snapshot = state()
        previous = copy.deepcopy(snapshot)
        with self.assertRaises(ProviderError):
            await ContextUpdater(client).update(snapshot, [TranscriptSegment("meeting", 0, 2000, "QA 기준", id=2)], [], {})
        self.assertEqual(snapshot, previous)

    def test_focus_must_be_an_existing_open_row(self):
        discussion = normalize_discussion_state(state().discussion_state)
        focus = build_askable_focus(discussion, [{"content": "만들어낸 예산", "source": "open_issues", "evidence_segment_ids": [999]}])
        self.assertEqual([item["content"] for item in focus], ["QA 완료 기준"])

    async def test_context_batches_advance_only_sent_segments(self):
        for provider, expected_count in [("openai", 15), ("ollama", 2)]:
            client = AsyncMock()
            client.provider = provider
            client.chat_json.return_value = dict(global_summary="요약", current_topic="QA", current_topic_summary="QA 논의",
                current_purpose={"primary": "decision_making", "secondary": [], "confidence": .8},
                discussion_state={key: [] for key in DISCUSSION_KEYS}, askable_focus=[])
            segments = [TranscriptSegment("meeting", i * 1000, (i+1) * 1000, "가" * 800, id=i+1) for i in range(20)]
            snapshot = QuestionContextState(meeting_id="meeting")
            updater = ContextUpdater(client)
            await updater.update(snapshot, segments, segments[-12:], {})
            self.assertEqual(snapshot.last_processed_segment_id, expected_count)
            request = json.loads(client.chat_json.call_args.kwargs["user"])
            self.assertEqual(len(request["new_transcript"]), expected_count)
            self.assertTrue(all(row["segment_id"] <= expected_count for row in request["recent_transcript"]))
            while snapshot.last_processed_segment_id < 20:
                await updater.update(snapshot, segments[snapshot.last_processed_segment_id:], segments[-12:], {})
            self.assertEqual(snapshot.last_processed_segment_id, 20)

    def test_open_followup_can_reference_a_closed_decision(self):
        discussion = {key: [] for key in DISCUSSION_KEYS}
        discussion["decisions"] = [{"content": "금요일 출시", "status": "decided", "evidence_segment_ids": [1]}]
        discussion["open_issues"] = [{"content": "금요일 출시 이후 장애 담당자", "status": "open", "evidence_segment_ids": [2]}]
        self.assertEqual(len(build_askable_focus(discussion)), 1)

    def test_single_selection_uses_best_score_not_category_order(self):
        low = candidate(id="low", category="blind_spot", final_score=2, status=QuestionStatus.ELIGIBLE)
        high = candidate(id="high", category="expansion", final_score=3, status=QuestionStatus.ELIGIBLE)
        select_top_questions([low, high], 1)
        self.assertEqual(high.status, QuestionStatus.ELIGIBLE)
        self.assertEqual(low.status, QuestionStatus.CANDIDATE)

    def test_late_evaluation_cannot_resurrect_displayed_question(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(Path(directory) / "test.db")
            try:
                meeting = repo.create_meeting()
                q = candidate(meeting, status=QuestionStatus.ELIGIBLE)
                repo.save_questions([q])
                repo.update_question_status(q.id, QuestionStatus.DISPLAYED)
                repo.save_questions([q])
                self.assertIsNone(repo.best_eligible_question(meeting))
                self.assertEqual(len(repo.question_history(meeting)["displayed"]), 1)
            finally:
                repo.close()


if __name__ == "__main__":
    unittest.main()
