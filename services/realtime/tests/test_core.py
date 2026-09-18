from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from q_agent_realtime.database import Repository
from q_agent_realtime.domain import (
    QuestionCandidate,
    QuestionContextState,
    QuestionStatus,
    TranscriptSegment,
)
from q_agent_realtime.questions import (
    _evaluation_prompt_question,
    apply_evaluation,
    apply_soft_evaluation,
    rule_reject,
    select_top_questions,
)


class EvaluationPolicyTest(unittest.TestCase):
    def test_evaluator_prompt_excludes_default_scores_and_status(self) -> None:
        question = QuestionCandidate(
            id="q_test",
            meeting_id="mtg_test",
            text="판단 기준은 무엇인가요?",
            meeting_purpose="decision_making",
            detected_problem="판단 기준 부족",
            question_role="판단 기준 명료화",
            theory="Inquiry",
            evidence_segment_ids=[1],
        )

        payload = _evaluation_prompt_question(question)

        self.assertEqual(payload["question_id"], "q_test")
        self.assertNotIn("status", payload)
        self.assertNotIn("information_gain", payload)
        self.assertNotIn("non_redundancy", payload)
        self.assertNotIn("assumption_surfacing", payload)
        self.assertNotIn("final_score", payload)

    def test_three_core_scores_create_eligible_question(self) -> None:
        question = QuestionCandidate(
            id="q_test",
            meeting_id="mtg_test",
            text="이 결정을 바꿀 수 있는 정보는 무엇인가요?",
            meeting_purpose="decision_making",
            detected_problem="판단 기준 부족",
            question_role="판단 기준 명료화",
            theory="Inquiry",
            evidence_segment_ids=[1],
        )
        apply_evaluation(
            question,
            {
                "contextually_relevant": True,
                "has_transcript_evidence": True,
                "already_resolved": False,
                "socially_safe": True,
                "information_gain": 3,
                "non_redundancy": 2,
                "assumption_surfacing": 2,
                "reason": "결정 기준이 아직 비어 있음",
                "stale_reason": "none",
            },
        )
        self.assertEqual(question.status, QuestionStatus.ELIGIBLE)
        self.assertAlmostEqual(question.final_score, 2.333)

    def test_resolved_question_is_not_eligible(self) -> None:
        question = QuestionCandidate(
            id="q_test",
            meeting_id="mtg_test",
            text="이미 답이 나온 질문",
            meeting_purpose="decision_making",
            detected_problem="",
            question_role="",
            theory="",
            evidence_segment_ids=[1],
        )
        apply_evaluation(
            question,
            {
                "contextually_relevant": True,
                "has_transcript_evidence": True,
                "already_resolved": True,
                "socially_safe": True,
                "information_gain": 3,
                "non_redundancy": 3,
                "assumption_surfacing": 3,
                "reason": "최신 발화에서 해결됨",
                "stale_reason": "resolved",
            },
        )
        self.assertEqual(question.status, QuestionStatus.RESOLVED)

    def test_rule_reject_flags_non_question_and_missing_evidence(self) -> None:
        state = QuestionContextState(
            meeting_id="mtg",
            recent_transcript=[{"segment_id": 1, "text": "비용을 기준으로 정합시다"}],
        )
        plain = QuestionCandidate(
            id="q1",
            meeting_id="mtg",
            text="이건 질문이 아니라 평서문입니다 길게",
            meeting_purpose="decision_making",
            detected_problem="",
            question_role="",
            theory="",
            evidence_segment_ids=[1],
        )
        self.assertIsNotNone(rule_reject(plain, state, []))

        no_evidence = QuestionCandidate(
            id="q2",
            meeting_id="mtg",
            text="지금 결정을 가를 핵심 기준은 무엇인가요?",
            meeting_purpose="decision_making",
            detected_problem="",
            question_role="",
            theory="",
            evidence_segment_ids=[],
        )
        self.assertEqual(rule_reject(no_evidence, state, []), "규칙: transcript 근거 segment가 없음")

        drifted = QuestionCandidate(
            id="q3",
            meeting_id="mtg",
            text="예산 한도를 다시 확인할 기준은 무엇인가요?",
            meeting_purpose="decision_making",
            detected_problem="",
            question_role="",
            theory="",
            evidence_segment_ids=[99],
            context_version=1,
        )
        self.assertEqual(
            rule_reject(drifted, state, []),
            "규칙: 근거 segment가 최근 transcript에 없음",
        )
        self.assertIsNone(rule_reject(drifted, state, [], mode="reeval"))

    def test_reeval_expires_on_topic_change_not_missing_window(self) -> None:
        question = QuestionCandidate(
            id="q_old",
            meeting_id="mtg",
            text="예산 한도를 다시 확인할 기준은 무엇인가요?",
            meeting_purpose="decision_making",
            detected_problem="",
            question_role="",
            theory="",
            evidence_segment_ids=[1],
            context_version=1,
            status=QuestionStatus.ELIGIBLE,
        )
        apply_soft_evaluation(
            question,
            {
                "information_gain": 3,
                "assumption_surfacing": 2,
                "already_resolved": False,
                "stale_reason": "topic_changed",
                "reason": "주제가 일정 논의로 이동",
            },
        )
        self.assertEqual(question.status, QuestionStatus.EXPIRED)

    def test_context_lag_threshold(self) -> None:
        from q_agent_realtime.questions import MAX_QUESTION_CONTEXT_LAG

        self.assertEqual(MAX_QUESTION_CONTEXT_LAG, 3)
        self.assertGreaterEqual(5 - 1, MAX_QUESTION_CONTEXT_LAG)

    def test_selector_parks_overflow_instead_of_reject(self) -> None:
        questions = []
        for index, category in enumerate(
            ["essence", "essence", "blind_spot", "expansion", "blind_spot"]
        ):
            questions.append(
                QuestionCandidate(
                    id=f"q_{index}",
                    meeting_id="mtg_test",
                    text=f"질문 {index}은 무엇인가요?",
                    meeting_purpose="decision_making",
                    detected_problem="판단 기준 부족",
                    question_role="판단 기준 명료화",
                    theory="Inquiry",
                    evidence_segment_ids=[1],
                    context_version=2,
                    category=category,
                    status=QuestionStatus.ELIGIBLE,
                    final_score=3 - index * 0.1,
                )
            )

        selected = select_top_questions(questions, max_questions=3)
        active = [q for q in selected if q.status is QuestionStatus.ELIGIBLE]
        parked = [q for q in selected if q.status is QuestionStatus.CANDIDATE]
        self.assertEqual(len(active), 3)
        self.assertEqual(len(parked), 2)
        self.assertEqual({q.category for q in active}, {"essence", "blind_spot", "expansion"})

    def test_evaluator_state_payload_is_compact(self) -> None:
        from q_agent_realtime.questions import evaluator_state_payload

        state = QuestionContextState(
            meeting_id="mtg",
            version=2,
            global_summary="요약",
            current_topic="예산",
            recent_transcript=[{"segment_id": i, "text": f"말 {i}"} for i in range(30)],
            discussion_state={
                "open_issues": [f"이슈{i}" for i in range(20)],
                "goals": ["목표"],
            },
        )
        payload = evaluator_state_payload(state)
        self.assertEqual(len(payload["recent_transcript"]), 12)
        self.assertEqual(len(payload["open_issues"]), 8)
        self.assertNotIn("goals", payload)
        self.assertIn("current_topic", payload)


class RepositoryTest(unittest.TestCase):
    def test_transcript_context_and_question_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Repository(Path(directory) / "test.db")
            meeting_id = repository.create_meeting("테스트 회의")
            segment = repository.add_segment(
                TranscriptSegment(
                    meeting_id=meeting_id,
                    start_ms=0,
                    end_ms=2000,
                    text="판단 기준이 아직 정해지지 않았습니다.",
                )
            )
            self.assertEqual(repository.segments_after(meeting_id, 0)[0].id, segment.id)

            state = QuestionContextState(
                meeting_id=meeting_id,
                meeting_objective="테스트 회의",
                version=1,
                global_summary="판단 기준을 논의 중이다.",
                last_processed_segment_id=segment.id or 0,
            )
            repository.save_context(state)
            loaded = repository.latest_context(meeting_id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.global_summary, state.global_summary)

            question = QuestionCandidate(
                id="q_1",
                meeting_id=meeting_id,
                text="어떤 판단 기준이 가장 중요한가요?",
                meeting_purpose="decision_making",
                detected_problem="판단 기준 부족",
                question_role="판단 기준 명료화",
                theory="Inquiry",
                evidence_segment_ids=[segment.id or 0],
                context_version=1,
                category="essence",
                operator="criterion_clarification",
                status=QuestionStatus.ELIGIBLE,
                final_score=2.5,
            )
            repository.save_questions([question])
            saved = repository.best_eligible_question(meeting_id)
            self.assertEqual(saved.id, "q_1")
            self.assertEqual(saved.context_version, 1)
            self.assertEqual(saved.category, "essence")
            repository.update_question_status("q_1", QuestionStatus.DISPLAYED)
            self.assertIsNone(repository.best_eligible_question(meeting_id))
            repository.close()


if __name__ == "__main__":
    unittest.main()
