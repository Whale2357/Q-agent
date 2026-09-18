from __future__ import annotations

import json
import re
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
    from .providers import StructuredLLMClient


GENERATOR_CANDIDATE_COUNT = 5
# Re-eval retires questions whose birth context is this many versions behind.
MAX_QUESTION_CONTEXT_LAG = 3

GENERATOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "meeting_purpose": {"type": "string", "enum": list(PURPOSES)},
        "problem_signals": {"type": "array", "items": {"type": "string"}},
        "candidates": {
            "type": "array",
            "minItems": GENERATOR_CANDIDATE_COUNT,
            "maxItems": GENERATOR_CANDIDATE_COUNT,
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


# Soft scores only — hard filters are applied in code (hybrid evaluator).
EVALUATOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "evaluations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "string"},
                    "already_resolved": {"type": "boolean"},
                    "information_gain": {
                        "type": "integer",
                        "enum": [0, 1, 2, 3],
                    },
                    "assumption_surfacing": {
                        "type": "integer",
                        "enum": [0, 1, 2, 3],
                    },
                    "reason": {"type": "string"},
                    "stale_reason": {
                        "type": "string",
                        "enum": ["none", "resolved", "topic_changed"],
                    },
                },
                "required": [
                    "question_id",
                    "already_resolved",
                    "information_gain",
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

_UNSAFE_PATTERNS = (
    re.compile(r"(바보|멍청|한심|쓰레기|꺼져|죽어)"),
    re.compile(r"(당신|너)\s*(잘못|탓|책임)"),
)
_INTERROGATIVE = re.compile(r"[?？]|까\s*$|나요\s*$|습니까\s*$|인가요\s*$|을까요\s*$|할까요\s*$")
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")


class QuestionGenerator:
    def __init__(self, client: StructuredLLMClient):
        self.client = client

    async def generate(self, state: QuestionContextState) -> list[QuestionCandidate]:
        system = f"""당신은 Q-Agent의 질문 생성기다.
질문은 회의 흐름을 방해하는 장식이 아니라 실제 병목을 해소하는 개입이어야 한다.
먼저 현재 회의 목적과 문제 신호를 판단한 뒤 정확히 {GENERATOR_CANDIDATE_COUNT}개의 서로 다른 후보를 만든다.
category는 blind_spot, essence, expansion을 각각 최소 1개 포함한다.
operator는 assumption_challenge, reframing, criterion_clarification,
counterfactual, constraint_relaxation을 가능한 한 고르게 사용한다.
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
            num_predict=2400,
        )
        valid_segment_ids = {
            int(item["segment_id"])
            for item in state.recent_transcript
            if item.get("segment_id") is not None
        }
        purpose = str(result.get("meeting_purpose", "unknown"))
        candidates: list[QuestionCandidate] = []
        for item in result.get("candidates", [])[:GENERATOR_CANDIDATE_COUNT]:
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
    """Hybrid evaluator: code hard-filters + LLM soft scores."""

    def __init__(self, client: StructuredLLMClient):
        self.client = client

    async def evaluate(
        self,
        state: QuestionContextState,
        questions: list[QuestionCandidate],
        *,
        mode: str = "initial",
        max_context_lag: int = MAX_QUESTION_CONTEXT_LAG,
    ) -> list[QuestionCandidate]:
        if not questions:
            return []

        history_texts = _history_texts(state)
        survivors: list[QuestionCandidate] = []
        for question in questions:
            if mode == "reeval":
                lag = state.version - int(question.context_version or 0)
                if lag >= max_context_lag:
                    question.status = QuestionStatus.EXPIRED
                    question.evaluation_reason = (
                        f"맥락 버전이 {lag}단계 이동해 만료됨"
                    )
                    question.updated_at = utc_now()
                    continue
            reject_reason = rule_reject(
                question, state, history_texts, mode=mode
            )
            if reject_reason:
                question.status = QuestionStatus.REJECTED
                question.evaluation_reason = reject_reason
                question.non_redundancy = _non_redundancy_score(
                    question.text, history_texts
                )
                question.updated_at = utc_now()
                continue
            question.non_redundancy = _non_redundancy_score(question.text, history_texts)
            survivors.append(question)
            history_texts.append(question.text)

        if not survivors:
            return questions

        stale_guidance = (
            "재평가 모드다. 근거 segment가 최근 창에서 빠져도 그것만으로 탈락시키지 않는다. "
            "주제가 바뀌었으면 stale_reason=topic_changed, 이미 답이 나왔으면 already_resolved/"
            "stale_reason=resolved로 만료·해결 처리한다."
            if mode == "reeval"
            else "최초 평가 모드다. 후보가 현재 맥락에 맞는지만 본다."
        )
        system = f"""당신은 Q-Agent의 질문 소프트 평가기다.
규칙 필터를 통과한 후보만 받는다. 다음만 판정한다.
- information_gain: 답이 결정/다음 행동을 바꾸는 정도 (정수 0~3)
- assumption_surfacing: 암묵적 전제를 드러내는 정도 (정수 0~3)
- already_resolved / stale_reason: 이미 해결됨 또는 주제 변경
비중복·형식·금칙·근거 segment는 코드가 이미 검사했으므로 반복하지 않는다.
{stale_guidance}
JSON 스키마에 맞는 객체만 반환한다. /no_think"""
        user = json.dumps(
            {
                "question_context_state": evaluator_state_payload(state),
                "questions": [
                    _evaluation_prompt_question(question) for question in survivors
                ],
            },
            ensure_ascii=False,
        )
        result = await self.client.chat_json(
            system=system,
            user=user,
            schema=EVALUATOR_SCHEMA,
            think=False,
            temperature=0.0,
            num_predict=2000,
        )
        evaluations = {
            str(item.get("question_id")): item for item in result.get("evaluations", [])
        }
        for question in survivors:
            item = evaluations.get(question.id)
            if not item:
                question.status = QuestionStatus.REJECTED
                question.evaluation_reason = "소프트 평가 결과가 누락됨"
                question.updated_at = utc_now()
                continue
            apply_soft_evaluation(question, item)
        return questions


def rule_reject(
    question: QuestionCandidate,
    state: QuestionContextState,
    history_texts: list[str],
    *,
    mode: str = "initial",
) -> str | None:
    text = question.text.strip()
    if len(text) < 15 or len(text) > 120:
        return "규칙: 질문 길이가 허용 범위(15~120자)를 벗어남"
    if not _INTERROGATIVE.search(text):
        return "규칙: 의문 형태가 아님"
    if not question.evidence_segment_ids:
        return "규칙: transcript 근거 segment가 없음"
    # Birth-time only: evidence must still sit in the recent window.
    # Re-eval keeps birth evidence and retires via lag / LLM stale instead.
    if mode == "initial":
        valid_ids = {
            int(item["segment_id"])
            for item in state.recent_transcript
            if item.get("segment_id") is not None
        }
        if not any(
            segment_id in valid_ids for segment_id in question.evidence_segment_ids
        ):
            return "규칙: 근거 segment가 최근 transcript에 없음"
    for pattern in _UNSAFE_PATTERNS:
        if pattern.search(text):
            return "규칙: 사회적 안전성(비난·추궁) 위반"
    max_sim = max((_jaccard(text, other) for other in history_texts), default=0.0)
    if max_sim >= 0.72:
        return "규칙: 기존 질문/이력과 과도하게 중복"
    if mode == "initial":
        recent_blob = " ".join(
            str(item.get("text", "")) for item in state.recent_transcript
        )
        if (
            recent_blob
            and _jaccard(text, recent_blob) < 0.02
            and len(recent_blob) > 40
        ):
            tokens_q = _tokens(text)
            tokens_r = _tokens(recent_blob)
            if tokens_q and tokens_r.isdisjoint(tokens_q):
                return "규칙: 최근 발화와 관련 토큰이 없음"
    return None


def _history_texts(state: QuestionContextState) -> list[str]:
    texts: list[str] = []
    for bucket in ("active", "displayed", "resolved", "rejected", "parked"):
        for item in state.question_history.get(bucket, []):
            text = str(item.get("text", "")).strip()
            if text:
                texts.append(text)
    return texts


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def _jaccard(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _non_redundancy_score(text: str, history_texts: list[str]) -> float:
    max_sim = max((_jaccard(text, other) for other in history_texts), default=0.0)
    return round(max(0.0, min(3.0, 3.0 * (1.0 - max_sim))), 3)


def _evaluation_prompt_question(question: QuestionCandidate) -> dict[str, Any]:
    """Exclude default/previous scores so the evaluator cannot anchor on them."""
    return {
        "question_id": question.id,
        "text": question.text,
        "meeting_purpose": question.meeting_purpose,
        "detected_problem": question.detected_problem,
        "question_role": question.question_role,
        "theory": question.theory,
        "evidence_segment_ids": question.evidence_segment_ids,
        "context_version": question.context_version,
        "category": question.category,
        "operator": question.operator,
        "rule_non_redundancy": question.non_redundancy,
    }


def apply_soft_evaluation(question: QuestionCandidate, evaluation: dict[str, Any]) -> None:
    question.information_gain = _score(evaluation.get("information_gain", 0))
    question.assumption_surfacing = _score(evaluation.get("assumption_surfacing", 0))
    # Keep rule-computed non_redundancy unless explicitly provided for tests.
    if "non_redundancy" in evaluation:
        question.non_redundancy = _score(evaluation.get("non_redundancy", 0))
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
        core_threshold_pass = (
            question.information_gain >= 2
            and question.non_redundancy >= 2
            and question.final_score >= 2
        )
        question.status = (
            QuestionStatus.ELIGIBLE if core_threshold_pass else QuestionStatus.REJECTED
        )
    question.updated_at = utc_now()


def apply_evaluation(question: QuestionCandidate, evaluation: dict[str, Any]) -> None:
    """Backward-compatible full payload (rules+soft fields) used by unit tests."""
    if "has_transcript_evidence" in evaluation or "socially_safe" in evaluation:
        hard_fail = not (
            bool(evaluation.get("contextually_relevant", True))
            and bool(evaluation.get("has_transcript_evidence", True))
            and not bool(evaluation.get("already_resolved", False))
            and bool(evaluation.get("socially_safe", True))
        )
        if hard_fail and not (
            bool(evaluation.get("already_resolved"))
            or str(evaluation.get("stale_reason", "none")) in {"resolved", "topic_changed"}
        ):
            question.status = QuestionStatus.REJECTED
            question.evaluation_reason = str(
                evaluation.get("reason", "하드 필터 실패")
            )
            question.information_gain = _score(evaluation.get("information_gain", 0))
            question.non_redundancy = _score(evaluation.get("non_redundancy", 0))
            question.assumption_surfacing = _score(
                evaluation.get("assumption_surfacing", 0)
            )
            question.final_score = round(
                (
                    question.information_gain
                    + question.non_redundancy
                    + question.assumption_surfacing
                )
                / 3,
                3,
            )
            question.updated_at = utc_now()
            return
    apply_soft_evaluation(question, evaluation)


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
        # Park overflow instead of permanent REJECT so later generators can still
        # explore nearby angles without Jaccard blacklisting.
        question.status = QuestionStatus.CANDIDATE
        suffix = "활성 상한으로 대기(parked)"
        question.evaluation_reason = (
            f"{question.evaluation_reason}; {suffix}"
            if question.evaluation_reason
            else suffix
        )
        question.updated_at = utc_now()
    return questions


def evaluator_state_payload(state: QuestionContextState) -> dict[str, Any]:
    """Compact context for soft scoring — avoids shipping full discussion dumps."""
    discussion = state.discussion_state or {}

    def _take(key: str, limit: int = 8) -> list[Any]:
        items = discussion.get(key, [])
        return items[:limit] if isinstance(items, list) else []

    history = state.question_history or {}
    return {
        "meeting_id": state.meeting_id,
        "version": state.version,
        "global_summary": state.global_summary,
        "current_topic": state.current_topic,
        "current_topic_summary": state.current_topic_summary,
        "current_purpose": state.current_purpose,
        "open_issues": _take("open_issues"),
        "assumptions": _take("assumptions"),
        "decisions": _take("decisions"),
        "uncertainties": _take("uncertainties"),
        "recent_transcript": list(state.recent_transcript[-12:]),
        "question_history": {
            "active": list(history.get("active", [])[:5]),
            "displayed": list(history.get("displayed", [])[:5]),
            "parked": list(history.get("parked", [])[:5]),
        },
    }