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


def _soft_scores(**overrides: float) -> dict:
    base = {
        "clarity": 2,
        "specificity": 2,
        "purpose_fit": 2,
        "critical_push": 2,
        "contextual_fit": 2,
        "openness": 2,
        "follow_through": 2,
        "neutrality": 2,
        "non_redundancy": 2,
        "already_resolved": False,
        "stale_reason": "none",
        "reason": "ok",
    }
    base.update(overrides)
    return base


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
        self.assertNotIn("clarity", payload)
        self.assertNotIn("non_redundancy", payload)
        self.assertNotIn("final_score", payload)

    def test_core_scores_create_eligible_question(self) -> None:
        question = QuestionCandidate(
            id="q_test",
            meeting_id="mtg_test",
            text="월요일 출시 QA 완료 기준은 무엇인가요?",
            meeting_purpose="decision_making",
            detected_problem="판단 기준 부족",
            question_role="판단 기준 명료화",
            theory="Inquiry",
            evidence_segment_ids=[1],
            category="essence",
        )
        apply_evaluation(
            question,
            {
                "contextually_relevant": True,
                "has_transcript_evidence": True,
                "socially_safe": True,
                **_soft_scores(
                    clarity=3,
                    purpose_fit=3,
                    reason="결정 기준이 아직 비어 있음",
                ),
            },
        )
        self.assertEqual(question.status, QuestionStatus.ELIGIBLE)
        self.assertGreaterEqual(question.final_score, 2.0)

    def test_low_specificity_rejects_even_with_high_purpose_fit(self) -> None:
        question = QuestionCandidate(
            id="q_test",
            meeting_id="mtg_test",
            text="팀 방향을 어떻게 잡으면 좋을까요?",
            meeting_purpose="alignment",
            detected_problem="",
            question_role="",
            theory="",
            evidence_segment_ids=[1],
            non_redundancy=3.0,
            category="essence",
        )
        apply_soft_evaluation(
            question,
            _soft_scores(
                clarity=3,
                specificity=1,
                purpose_fit=3,
                critical_push=3,
                reason="추상적",
            ),
        )
        self.assertEqual(question.status, QuestionStatus.REJECTED)

    def test_rule_reject_flags_abstract_patterns(self) -> None:
        state = QuestionContextState(
            meeting_id="mtg",
            recent_transcript=[
                {"segment_id": 1, "text": "월요일 출시와 QA 일정을 논의합시다"}
            ],
        )
        abstract = QuestionCandidate(
            id="q_abs",
            meeting_id="mtg",
            text="이 부분에 대해 어떻게 생각하세요?",
            meeting_purpose="decision_making",
            detected_problem="",
            question_role="",
            theory="",
            evidence_segment_ids=[1],
        )
        self.assertEqual(
            rule_reject(abstract, state, []),
            "규칙: 일반론·추상 질문 패턴",
        )
        schedule = QuestionCandidate(
            id="q_sched",
            meeting_id="mtg",
            text="일정을 어떻게 조율하면 좋을까요?",
            meeting_purpose="decision_making",
            detected_problem="",
            question_role="",
            theory="",
            evidence_segment_ids=[1],
        )
        self.assertEqual(
            rule_reject(schedule, state, []),
            "규칙: 일반론·추상 질문 패턴",
        )

    def test_rule_reject_flags_resolved_overlap(self) -> None:
        state = QuestionContextState(
            meeting_id="mtg",
            discussion_state={
                "resolved_items": [
                    {
                        "content": "월요일 출시로 확정",
                        "status": "resolved",
                        "evidence_segment_ids": [1],
                    }
                ],
                "decisions": [],
                "open_issues": [
                    {
                        "content": "QA 담당자 미정",
                        "status": "open",
                        "evidence_segment_ids": [2],
                    }
                ],
                "assumptions": [],
                "uncertainties": [],
                "goals": [],
                "proposals": [],
                "alternatives": [],
                "decision_criteria": [],
                "evidence": [],
                "disagreements": [],
                "blockers": [],
                "action_items": [],
            },
            askable_focus=[
                {
                    "content": "QA 담당자 미정",
                    "source": "open_issues",
                    "evidence_segment_ids": [2],
                }
            ],
            recent_transcript=[
                {"segment_id": 1, "text": "월요일 출시로 확정합시다"},
                {"segment_id": 2, "text": "QA 담당자는 아직 정하지 못했어요"},
            ],
        )
        resolved_q = QuestionCandidate(
            id="q_res",
            meeting_id="mtg",
            text="월요일 출시로 확정하는 게 맞을까요?",
            meeting_purpose="decision_making",
            detected_problem="",
            question_role="",
            theory="",
            evidence_segment_ids=[1],
        )
        self.assertEqual(
            rule_reject(resolved_q, state, []),
            "규칙: 이미 결정·해결된 내용과 겹침",
        )

    def test_rule_reject_requires_askable_anchor(self) -> None:
        state = QuestionContextState(
            meeting_id="mtg",
            discussion_state={
                "open_issues": [
                    {
                        "content": "QA 잔여 이슈 목록",
                        "status": "open",
                        "evidence_segment_ids": [1],
                    }
                ],
                "resolved_items": [],
                "decisions": [],
                "assumptions": [],
                "uncertainties": [],
                "goals": [],
                "proposals": [],
                "alternatives": [],
                "decision_criteria": [],
                "evidence": [],
                "disagreements": [],
                "blockers": [],
                "action_items": [],
            },
            askable_focus=[
                {
                    "content": "QA 잔여 이슈 목록",
                    "source": "open_issues",
                    "evidence_segment_ids": [1],
                }
            ],
            recent_transcript=[
                {"segment_id": 1, "text": "QA 잔여 이슈 목록이 아직 없어요"}
            ],
        )
        drifting = QuestionCandidate(
            id="q_drift",
            meeting_id="mtg",
            text="마케팅 예산 상한을 얼마로 둘까요?",
            meeting_purpose="decision_making",
            detected_problem="",
            question_role="",
            theory="",
            evidence_segment_ids=[1],
        )
        self.assertEqual(
            rule_reject(drifting, state, []),
            "규칙: askable_focus·open_issues 앵커 없음",
        )
        grounded = QuestionCandidate(
            id="q_ok",
            meeting_id="mtg",
            text="QA 잔여 이슈 목록을 누가 오늘 공유할까요?",
            meeting_purpose="decision_making",
            detected_problem="",
            question_role="",
            theory="",
            evidence_segment_ids=[1],
        )
        self.assertIsNone(rule_reject(grounded, state, []))

    def test_rule_reject_flags_leading_patterns(self) -> None:
        state = QuestionContextState(
            meeting_id="mtg",
            recent_transcript=[
                {"segment_id": 1, "text": "월요일에 출시하는 게 맞다고 봅니다"}
            ],
        )
        leading = QuestionCandidate(
            id="q_lead",
            meeting_id="mtg",
            text="월요일 출시가 맞는 거 아닌가요?",
            meeting_purpose="decision_making",
            detected_problem="",
            question_role="",
            theory="",
            evidence_segment_ids=[1],
        )
        self.assertEqual(
            rule_reject(leading, state, []),
            "규칙: 유도·선입견 질문 패턴",
        )

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
                "socially_safe": True,
                **_soft_scores(
                    already_resolved=True,
                    stale_reason="resolved",
                    purpose_fit=3,
                    reason="최신 발화에서 해결됨",
                ),
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
            _soft_scores(
                purpose_fit=3,
                stale_reason="topic_changed",
                reason="주제가 일정 논의로 이동",
            ),
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
                    meeting_id="mtg",
                    text=f"질문 {index}번 내용이 충분히 길어야 합니다?",
                    meeting_purpose="decision_making",
                    detected_problem="",
                    question_role="",
                    theory="",
                    evidence_segment_ids=[1],
                    category=category,
                    status=QuestionStatus.ELIGIBLE,
                    final_score=3 - index * 0.1,
                )
            )
        select_top_questions(questions, max_questions=3)
        eligible = [q for q in questions if q.status is QuestionStatus.ELIGIBLE]
        parked = [q for q in questions if q.status is QuestionStatus.CANDIDATE]
        self.assertEqual(len(eligible), 3)
        self.assertEqual(len(parked), 2)

    def test_evaluator_state_payload_is_compact(self) -> None:
        from q_agent_realtime.questions import evaluator_state_payload, generator_state_payload

        state = QuestionContextState(
            meeting_id="mtg",
            discussion_state={
                "open_issues": [{"content": f"i{i}", "status": "open"} for i in range(20)],
                "assumptions": [],
                "decisions": [{"content": "출시일 확정", "status": "decided"}],
                "uncertainties": [],
                "goals": [],
                "proposals": [],
                "alternatives": [],
                "decision_criteria": [],
                "evidence": [],
                "disagreements": [],
                "blockers": [],
                "resolved_items": [{"content": "예산 한도 합의", "status": "resolved"}],
                "action_items": [],
            },
            recent_transcript=[{"segment_id": i, "text": f"t{i}"} for i in range(30)],
        )
        payload = evaluator_state_payload(state)
        self.assertLessEqual(len(payload["open_issues"]), 8)
        self.assertLessEqual(len(payload["recent_transcript"]), 12)
        self.assertIn("do_not_ask", payload)
        self.assertIn("출시일 확정", payload["do_not_ask"])
        self.assertIn("예산 한도 합의", payload["do_not_ask"])
        self.assertIn("resolved_items", payload)
        self.assertTrue(payload["askable_focus"])

        gen = generator_state_payload(state)
        self.assertIn("askable_focus", gen)
        self.assertIn("do_not_ask", gen)
        self.assertNotIn("global_summary", gen)


class ContextNormalizeTest(unittest.TestCase):
    def test_moves_resolved_open_issues_and_builds_focus(self) -> None:
        from q_agent_realtime.context import (
            build_askable_focus,
            build_do_not_ask,
            normalize_discussion_state,
        )

        raw = {
            "open_issues": [
                {
                    "content": "월요일 출시 여부",
                    "status": "resolved",
                    "evidence_segment_ids": [1],
                },
                {
                    "content": "QA 담당 미정",
                    "status": "open",
                    "evidence_segment_ids": [2],
                },
            ],
            "resolved_items": [],
            "decisions": [{"content": "예산 200 확정", "status": "decided", "evidence_segment_ids": []}],
            "uncertainties": [],
            "blockers": [],
            "decision_criteria": [],
            "goals": [],
            "proposals": [],
            "alternatives": [],
            "evidence": [],
            "assumptions": [],
            "disagreements": [],
            "action_items": [],
        }
        normalized = normalize_discussion_state(raw)
        open_contents = [item["content"] for item in normalized["open_issues"]]
        self.assertEqual(open_contents, ["QA 담당 미정"])
        resolved_contents = [item["content"] for item in normalized["resolved_items"]]
        self.assertIn("월요일 출시 여부", resolved_contents)
        focus = build_askable_focus(normalized)
        self.assertEqual(focus[0]["content"], "QA 담당 미정")
        banned = build_do_not_ask(normalized)
        self.assertIn("예산 200 확정", banned)
        self.assertIn("월요일 출시 여부", banned)


class PromptLoaderTest(unittest.TestCase):
    def test_load_generator_prompt_substitutes_count_and_purpose(self) -> None:
        from q_agent_realtime.prompt_loader import clear_prompt_cache, load_prompt

        clear_prompt_cache()
        text = load_prompt(
            "generator",
            GENERATOR_CANDIDATE_COUNT=5,
            PURPOSE_GUIDE=load_prompt("purpose_guide"),
        )
        self.assertIn("정확히 5개의 서로 다른 후보", text)
        self.assertIn("decision_making", text)
        self.assertIn("일반론", text)
        self.assertIn("월요일 출시", text)
        self.assertIn("askable_focus", text)
        self.assertIn("do_not_ask", text)

    def test_load_evaluator_prompt_injects_stale_guidance(self) -> None:
        from q_agent_realtime.prompt_loader import clear_prompt_cache, load_prompt

        clear_prompt_cache()
        text = load_prompt(
            "evaluator",
            STALE_GUIDANCE="재평가 모드다. 테스트 안내.",
        )
        self.assertIn("clarity", text)
        self.assertIn("purpose_fit", text)
        self.assertIn("openness", text)
        self.assertIn("neutrality", text)
        self.assertIn("재평가 모드다. 테스트 안내.", text)


class RepositoryTest(unittest.TestCase):
    def test_transcript_context_and_question_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Repository(Path(directory) / "test.db")
            meeting_id = repository.create_meeting("decide")
            segment = repository.add_segment(
                TranscriptSegment(
                    meeting_id=meeting_id,
                    start_ms=0,
                    end_ms=1000,
                    text="비용을 기준으로 정합시다",
                )
            )
            state = QuestionContextState(
                meeting_id=meeting_id,
                version=1,
                global_summary="비용 기준 논의",
                current_topic="비용",
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
                clarity=2.5,
                specificity=2.5,
                purpose_fit=2.5,
                final_score=2.5,
            )
            repository.save_questions([question])
            saved = repository.best_eligible_question(meeting_id)
            self.assertEqual(saved.id, "q_1")
            self.assertEqual(saved.context_version, 1)
            self.assertEqual(saved.category, "essence")
            self.assertAlmostEqual(saved.purpose_fit, 2.5)
            repository.update_question_status("q_1", QuestionStatus.DISPLAYED)
            self.assertIsNone(repository.best_eligible_question(meeting_id))
            repository.close()


if __name__ == "__main__":
    unittest.main()
