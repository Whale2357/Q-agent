from __future__ import annotations

import json
import uuid
from typing import Any

from .context import PURPOSES
from .domain import (
    QUESTION_CATEGORIES,
    QUESTION_OPERATORS,
    QuestionCandidate,
    QuestionContextState,
    QuestionStatus,
    utc_now,
)
from .ollama import OllamaClient
from .prompts import PromptTemplates


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


class QuestionGenerator:
    def __init__(self, client: OllamaClient, prompts: PromptTemplates):
        self.client = client
        self.prompts = prompts

    async def generate(self, state: QuestionContextState) -> list[QuestionCandidate]:
        user = json.dumps(state.to_dict(), ensure_ascii=False)
        result = await self.client.chat_json(
            system=self.prompts.generator,
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
    def __init__(self, client: OllamaClient, prompts: PromptTemplates):
        self.client = client
        self.prompts = prompts

    async def evaluate(
        self,
        state: QuestionContextState,
        questions: list[QuestionCandidate],
    ) -> list[QuestionCandidate]:
        if not questions:
            return []
        user = json.dumps(
            {
                "question_context_state": state.to_dict(),
                "questions": [question.to_dict() for question in questions],
            },
            ensure_ascii=False,
        )
        result = await self.client.chat_json(
            system=self.prompts.evaluator,
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
