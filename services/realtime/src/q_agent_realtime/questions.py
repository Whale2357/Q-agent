from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from .context import PURPOSES
from .domain import (
    QUESTION_CATEGORIES,
    QUESTION_OPERATORS,
    QuestionCandidate,
    QuestionContextState,
    QuestionStatus,
    utc_now,
)

if TYPE_CHECKING:
    from .ollama import OllamaClient


GENERATOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "meeting_purpose": {"type": "string", "enum": list(PURPOSES)},
        "problem_signals": {"type": "array", "items": {"type": "string"}},
        "candidates": {
            "type": "array",
            "minItems": 8,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "detected_problem": {"type": "string"},
                    "question_role": {"type": "string"},
                    "theory": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": list(QUESTION_CATEGORIES),
                    },
                    "operator": {
                        "type": "string",
                        "enum": list(QUESTION_OPERATORS),
                    },
                    "evidence_segment_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": [
                    "text",
                    "detected_problem",
                    "question_role",
                    "theory",
                    "category",
                    "operator",
                    "evidence_segment_ids",
                ],
            },
        },
    },
    "required": ["meeting_purpose", "problem_signals", "candidates"],
}


EVALUATOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "evaluations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string"},
                    "contextually_relevant": {"type": "boolean"},
                    "has_transcript_evidence": {"type": "boolean"},
                    "already_resolved": {"type": "boolean"},
                    "socially_safe": {"type": "boolean"},
                    "information_gain": {"type": "number", "minimum": 0, "maximum": 3},
                    "non_redundancy": {"type": "number", "minimum": 0, "maximum": 3},
                    "assumption_surfacing": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 3,
                    },
                    "reason": {"type": "string"},
                    "stale_reason": {
                        "type": "string",
                        "enum": ["none", "resolved", "topic_changed"],
                    },
                },
                "required": [
                    "question_id",
                    "contextually_relevant",
                    "has_transcript_evidence",
                    "already_resolved",
                    "socially_safe",
                    "information_gain",
                    "non_redundancy",
                    "assumption_surfacing",
                    "reason",
                    "stale_reason",
                ],
            },
        }
    },
    "required": ["evaluations"],
}


PURPOSE_GUIDE = """
progress_coordination: Team Reflexivity로 병목과 계획 관성을 점검
idea_exploration: Representational Change로 제약 완화와 탐색 공간 확장
decision_making: Inquiry와 Constructive Controversy로 기준·대안·증거 검증
problem_solving: Double-loop Learning과 Reframing으로 원인·문제 정의 재검토
planning_strategy: Team Reflexivity와 Pre-mortem으로 목표·전제·위험 검증
performance_review: Team Learning과 Double-loop Learning으로 예상-실제 차이 학습
alignment: Constructive Controversy와 Psychological Safety로 관점 차이를 안전하게 표면화
""".strip()


class QuestionGenerator:
    def __init__(self, client: OllamaClient):
        self.client = client

    async def generate(self, state: QuestionContextState) -> list[QuestionCandidate]:
        system = f"""당신은 Q-Agent의 질문 생성기다.
질문은 회의 흐름을 방해하는 장식이 아니라 실제 병목을 해소하는 개입이어야 한다.
먼저 현재 회의 목적과 문제 신호를 판단한 뒤 정확히 8개의 서로 다른 후보를 만든다.
category는 blind_spot, essence, expansion을 각각 최소 1개 포함한다.
operator는 assumption_challenge, reframing, criterion_clarification,
counterfactual, constraint_relaxation을 각각 최소 1개 포함한다.
근거가 없거나 이미 답이 나온 질문, 일반론, 특정인을 공격하는 질문은 만들지 않는다.
말하지 않은 사람의 감정이나 반대를 단정하지 말고 안전한 초대형 질문으로 표현한다.
각 후보는 recent_transcript의 실제 segment id를 하나 이상 근거로 가져야 한다.

목적별 이론 가이드:
{PURPOSE_GUIDE}

JSON 스키마에 맞는 객체만 반환한다."""
        user = json.dumps(state.to_dict(), ensure_ascii=False)
        result = await self.client.chat_json(
            system=system,
            user=user,
            schema=GENERATOR_SCHEMA,
            think=True,
            temperature=0.5,
            num_predict=3200,
        )
        valid_segment_ids = {
            int(item["segment_id"])
            for item in state.recent_transcript
            if item.get("segment_id") is not None
        }
        purpose = str(result.get("meeting_purpose", "unknown"))
        candidates: list[QuestionCandidate] = []
        for item in result.get("candidates", [])[:8]:
            evidence_ids: list[int] = []
            for segment_id in item.get("evidence_segment_ids", []):
                try:
                    parsed_id = int(segment_id)
                except (TypeError, ValueError):
                    continue
                if parsed_id in valid_segment_ids:
                    evidence_ids.append(parsed_id)
            text = str(item.get("text", "")).strip()
            if not text or not evidence_ids:
                continue
            candidates.append(
                QuestionCandidate(
                    id=f"q_{uuid.uuid4().hex[:12]}",
                    meeting_id=state.meeting_id,
                    text=text,
                    meeting_purpose=purpose,
                    detected_problem=str(item.get("detected_problem", "")),
                    question_role=str(item.get("question_role", "")),
                    theory=str(item.get("theory", "")),
                    evidence_segment_ids=evidence_ids,
                    context_version=state.version,
                    category=str(item.get("category", "essence")),
                    operator=str(item.get("operator", "criterion_clarification")),
                )
            )
        return candidates


class QuestionEvaluator:
    def __init__(self, client: OllamaClient):
        self.client = client

    async def evaluate(
        self,
        state: QuestionContextState,
        questions: list[QuestionCandidate],
    ) -> list[QuestionCandidate]:
        if not questions:
            return []
        system = """당신은 Q-Agent의 엄격한 질문 평가기다.
최신 Question Context State에서 질문의 현재 가치를 평가한다.
먼저 관련성, 원문 근거, 이미 해결됨, 사회적 안전성을 사실대로 판정한다.
그 다음 PDF 핵심 기준인 정보 이득, 비중복성, 암묵적 가정 노출을 각각 0~3점으로 평가한다.
정보 이득은 답이 실제 결정이나 다음 행동을 바꿀 가능성이다.
비중복성은 기존 논의와 질문 이력에 같은 답이 없는 정도다.
가정 노출은 검증되지 않은 전제를 드러내는 정도다.
현재 주제가 바뀌었으면 topic_changed, 대화에서 답이 나왔으면 resolved로 표시한다.
JSON 스키마에 맞는 객체만 반환한다. /no_think"""
        user = json.dumps(
            {
                "question_context_state": state.to_dict(),
                "questions": [question.to_dict() for question in questions],
            },
            ensure_ascii=False,
        )
        result = await self.client.chat_json(
            system=system,
            user=user,
            schema=EVALUATOR_SCHEMA,
            think=False,
            temperature=0.0,
            num_predict=2600,
        )
        evaluations = {
            str(item.get("question_id")): item for item in result.get("evaluations", [])
        }
        for question in questions:
            item = evaluations.get(question.id)
            if not item:
                question.status = QuestionStatus.REJECTED
                question.evaluation_reason = "평가 결과가 누락됨"
                question.updated_at = utc_now()
                continue
            apply_evaluation(question, item)
        return questions


def apply_evaluation(question: QuestionCandidate, evaluation: dict[str, Any]) -> None:
    question.information_gain = _score(evaluation.get("information_gain", 0))
    question.non_redundancy = _score(evaluation.get("non_redundancy", 0))
    question.assumption_surfacing = _score(evaluation.get("assumption_surfacing", 0))
    question.final_score = round(
        (
            question.information_gain
            + question.non_redundancy
            + question.assumption_surfacing
        )
        / 3,
        3,
    )
    question.evaluation_reason = str(evaluation.get("reason", ""))
    stale_reason = str(evaluation.get("stale_reason", "none"))

    if bool(evaluation.get("already_resolved")) or stale_reason == "resolved":
        question.status = QuestionStatus.RESOLVED
    elif stale_reason == "topic_changed":
        question.status = QuestionStatus.EXPIRED
    else:
        hard_filters_pass = (
            bool(evaluation.get("contextually_relevant"))
            and bool(evaluation.get("has_transcript_evidence"))
            and not bool(evaluation.get("already_resolved"))
            and bool(evaluation.get("socially_safe"))
        )
        core_threshold_pass = (
            question.information_gain >= 2
            and question.non_redundancy >= 2
            and question.final_score >= 2
        )
        question.status = (
            QuestionStatus.ELIGIBLE
            if hard_filters_pass and core_threshold_pass
            else QuestionStatus.REJECTED
        )
    question.updated_at = utc_now()


def _score(value: Any) -> float:
    try:
        return max(0.0, min(3.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def select_top_questions(
    questions: list[QuestionCandidate], max_questions: int = 3
) -> list[QuestionCandidate]:
    """Keep at most max_questions eligible, preferring category diversity."""
    eligible = sorted(
        (question for question in questions if question.status is QuestionStatus.ELIGIBLE),
        key=lambda question: (-question.final_score, question.generated_at),
    )
    selected: list[QuestionCandidate] = []
    selected_ids: set[str] = set()

    for category in QUESTION_CATEGORIES:
        match = next((question for question in eligible if question.category == category), None)
        if match is None or len(selected) >= max_questions:
            continue
        selected.append(match)
        selected_ids.add(match.id)

    for question in eligible:
        if len(selected) >= max_questions:
            break
        if question.id not in selected_ids:
            selected.append(question)
            selected_ids.add(question.id)

    for question in eligible:
        if question.id in selected_ids:
            continue
        question.status = QuestionStatus.REJECTED
        suffix = "최종 활성 질문 상한에서 제외됨"
        question.evaluation_reason = (
            f"{question.evaluation_reason}; {suffix}"
            if question.evaluation_reason
            else suffix
        )
        question.updated_at = utc_now()
    return questions
