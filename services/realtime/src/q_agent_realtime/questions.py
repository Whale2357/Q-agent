from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING, Any

from .context import (
    PURPOSES,
    build_askable_focus,
    build_do_not_ask,
    item_content,
)
from .domain import (
    QUESTION_CATEGORIES,
    QUESTION_OPERATORS,
    QuestionCandidate,
    QuestionContextState,
    QuestionStatus,
    utc_now,
)
from .prompt_loader import load_prompt

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
                    "target_focus": {"type": "string"},
                    "anchor_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
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
                    "target_focus",
                    "anchor_terms",
                ],
            },
        },
    },
    "required": ["meeting_purpose", "problem_signals", "candidates"],
}


# Soft scores only — hard filters are applied in code (hybrid evaluator).
_SOFT_SCORE_KEYS = (
    "clarity",
    "specificity",
    "purpose_fit",
    "critical_push",
    "contextual_fit",
    "openness",
    "follow_through",
    "neutrality",
)

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
                    **{
                        key: {"type": "integer", "enum": [0, 1, 2, 3]}
                        for key in _SOFT_SCORE_KEYS
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
                    *_SOFT_SCORE_KEYS,
                    "reason",
                    "stale_reason",
                ],
            },
        }
    },
    "required": ["evaluations"],
}

# category → soft+NR weights (sum ≈ 1.0). Core axes dominate; aux is role-tilted.
CATEGORY_SCORE_WEIGHTS: dict[str, dict[str, float]] = {
    "essence": {
        "clarity": 0.16,
        "specificity": 0.16,
        "purpose_fit": 0.16,
        "contextual_fit": 0.14,
        "non_redundancy": 0.12,
        "critical_push": 0.08,
        "openness": 0.04,
        "follow_through": 0.06,
        "neutrality": 0.08,
    },
    "blind_spot": {
        "clarity": 0.12,
        "specificity": 0.14,
        "purpose_fit": 0.14,
        "contextual_fit": 0.12,
        "non_redundancy": 0.10,
        "critical_push": 0.16,
        "openness": 0.10,
        "follow_through": 0.06,
        "neutrality": 0.06,
    },
    "expansion": {
        "clarity": 0.12,
        "specificity": 0.12,
        "purpose_fit": 0.14,
        "contextual_fit": 0.12,
        "non_redundancy": 0.10,
        "critical_push": 0.08,
        "openness": 0.14,
        "follow_through": 0.12,
        "neutrality": 0.06,
    },
}


_UNSAFE_PATTERNS = (
    re.compile(r"(바보|멍청|한심|쓰레기|꺼져|죽어)"),
    re.compile(r"(당신|너)\s*(잘못|탓|책임)"),
)
_ABSTRACT_PATTERNS = (
    re.compile(r"어떻게\s*생각하(세|시)요"),
    re.compile(r"중요(한가요|할까|할까요|합니까)"),
    re.compile(r"(소통|커뮤니케이션).{0,12}(개선|원활)"),
    re.compile(r"(방향|비전|전략).{0,16}(어떻|무엇).{0,8}(좋|바뀌|잡)"),
    re.compile(r"^(그럼|그러면)?\s*(어떻게|무엇을)\s*(하면|할까요|하죠)"),
    re.compile(r"의견을?\s*(듣|공유|나눠)"),
    re.compile(r"(일정|스케줄).{0,12}(조율|맞추).{0,10}(어떻|할까|하면)"),
    re.compile(r"(개선|향상).{0,12}(어떻|무엇|방안)"),
    re.compile(r"(리스크|위험).{0,8}(없|있).{0,8}(나요|습니까|을까|을까요)"),
    re.compile(r"^(무엇을|뭘)\s*(해야|하면|논의)"),
)
_RESOLVED_OVERLAP_THRESHOLD = 0.36
_STOPWORDS = {
    "그리고",
    "그래서",
    "그러나",
    "그런",
    "이것",
    "저것",
    "오늘",
    "내일",
    "우리",
    "저희",
    "관련",
    "대해",
    "위한",
    "있는",
    "없는",
    "하는",
    "해야",
    "하면",
    "무엇",
    "어떻게",
    "어느",
    "누가",
    "언제",
    "어디",
    "기준",
    "결정",
    "논의",
    "확인",
    "검토",
    "생각",
    "부분",
    "내용",
    "문제",
    "사항",
}
_LEADING_PATTERNS = (
    re.compile(r"(맞지\s*않|그렇지\s*않|해야\s*하는\s*거\s*아니|당연하)"),
    re.compile(r"(이미|당연히|분명히)\s*.{0,12}(아닌가요|죠\s*\?)"),
    re.compile(r"(맞|그렇).{0,8}(아닌가요|않나요)"),
    re.compile(r"동의해\s*(주|하실|하시)"),
)
_INTERROGATIVE = re.compile(r"[?？]|까\s*$|나요\s*$|습니까\s*$|인가요\s*$|을까요\s*$|할까요\s*$")
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")


class QuestionGenerator:
    def __init__(self, client: StructuredLLMClient):
        self.client = client

    async def generate(self, state: QuestionContextState) -> list[QuestionCandidate]:
        system = load_prompt(
            "generator",
            GENERATOR_CANDIDATE_COUNT=GENERATOR_CANDIDATE_COUNT,
            PURPOSE_GUIDE=load_prompt("purpose_guide"),
        )
        payload = generator_state_payload(state)
        user = json.dumps(payload, ensure_ascii=False)
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
        anchor_corpus = _anchor_corpus_tokens(state)
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
            anchors = [
                str(term).strip()
                for term in item.get("anchor_terms", [])
                if str(term).strip()
            ]
            if not _anchors_grounded(text, anchors, anchor_corpus):
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
            "stale_reason=resolved로 만료·해결 처리한다. do_not_ask·resolved_items·decisions와 "
            "겹치면 resolved로 처리한다."
            if mode == "reeval"
            else (
                "최초 평가 모드다. do_not_ask·resolved_items·decisions와 의미가 겹치면 "
                "already_resolved=true, stale_reason=resolved로 처리한다. "
                "askable_focus 밖이거나 고유명·기한·수치가 없으면 specificity를 1 이하로 준다."
            )
        )
        system = load_prompt("evaluator", STALE_GUIDANCE=stale_guidance)
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
    for pattern in _ABSTRACT_PATTERNS:
        if pattern.search(text):
            return "규칙: 일반론·추상 질문 패턴"
    for pattern in _LEADING_PATTERNS:
        if pattern.search(text):
            return "규칙: 유도·선입견 질문 패턴"
    max_sim = max((_jaccard(text, other) for other in history_texts), default=0.0)
    if max_sim >= 0.72:
        return "규칙: 기존 질문/이력과 과도하게 중복"

    do_not_ask = build_do_not_ask(state.discussion_state)
    for blocked in do_not_ask:
        if _jaccard(text, blocked) >= _RESOLVED_OVERLAP_THRESHOLD:
            return "규칙: 이미 결정·해결된 내용과 겹침"
        blocked_tokens = _content_tokens(blocked)
        question_tokens = _content_tokens(text)
        if (
            blocked_tokens
            and question_tokens
            and blocked_tokens.issubset(question_tokens)
            and len(blocked_tokens) >= 2
        ):
            return "규칙: 이미 결정·해결된 내용과 겹침"

    if mode == "initial":
        focus_tokens = _askable_tokens(state)
        recent_blob = " ".join(
            str(item.get("text", "")) for item in state.recent_transcript
        )
        if focus_tokens:
            question_tokens = _content_tokens(text)
            if not question_tokens.intersection(focus_tokens):
                return "규칙: askable_focus·open_issues 앵커 없음"
        elif recent_blob:
            if (
                _jaccard(text, recent_blob) < 0.02
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


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in _tokens(text)
        if token not in _STOPWORDS and len(token) >= 2
    }


def _askable_tokens(state: QuestionContextState) -> set[str]:
    focus = state.askable_focus or build_askable_focus(state.discussion_state)
    tokens: set[str] = set()
    for item in focus:
        tokens |= _content_tokens(item_content(item))
    discussion = state.discussion_state or {}
    for key in ("open_issues", "uncertainties", "blockers", "decision_criteria"):
        for item in discussion.get(key, []) or []:
            tokens |= _content_tokens(item_content(item))
    return tokens


def _anchor_corpus_tokens(state: QuestionContextState) -> set[str]:
    tokens = _askable_tokens(state)
    for item in state.recent_transcript:
        tokens |= _content_tokens(str(item.get("text", "")))
    return tokens


def _anchors_grounded(
    text: str, anchors: list[str], corpus: set[str]
) -> bool:
    if not anchors:
        return False
    text_cf = text.casefold()
    for anchor in anchors:
        anchor = anchor.strip()
        if len(anchor) < 2:
            continue
        if anchor.casefold() not in text_cf:
            continue
        anchor_tokens = _content_tokens(anchor) or _tokens(anchor)
        if not corpus:
            return True
        if anchor_tokens.intersection(corpus):
            return True
        # Allow multi-char anchors that appear verbatim in corpus texts via token match
        if any(token in corpus for token in _tokens(anchor)):
            return True
    return False


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
    # Legacy field aliases from older evaluator payloads / tests.
    legacy_map = {
        "information_gain": "purpose_fit",
        "assumption_surfacing": "critical_push",
        "actionability": "follow_through",
    }
    normalized = dict(evaluation)
    for old_key, new_key in legacy_map.items():
        if old_key in normalized and new_key not in normalized:
            normalized[new_key] = normalized[old_key]

    question.clarity = _score(normalized.get("clarity", 0))
    question.specificity = _score(normalized.get("specificity", 0))
    question.purpose_fit = _score(normalized.get("purpose_fit", 0))
    question.critical_push = _score(normalized.get("critical_push", 0))
    question.contextual_fit = _score(normalized.get("contextual_fit", 0))
    question.openness = _score(normalized.get("openness", 0))
    question.follow_through = _score(normalized.get("follow_through", 0))
    question.neutrality = _score(normalized.get("neutrality", 0))
    if "non_redundancy" in normalized:
        question.non_redundancy = _score(normalized.get("non_redundancy", 0))

    question.final_score = _weighted_final_score(question)
    question.evaluation_reason = str(normalized.get("reason", ""))
    stale_reason = str(normalized.get("stale_reason", "none"))

    if bool(normalized.get("already_resolved")) or stale_reason == "resolved":
        question.status = QuestionStatus.RESOLVED
    elif stale_reason == "topic_changed":
        question.status = QuestionStatus.EXPIRED
    else:
        core_threshold_pass = (
            question.clarity >= 2
            and question.specificity >= 2
            and question.purpose_fit >= 2
            and question.contextual_fit >= 2
            and question.non_redundancy >= 2
            and question.final_score >= 2
        )
        question.status = (
            QuestionStatus.ELIGIBLE if core_threshold_pass else QuestionStatus.REJECTED
        )
    question.updated_at = utc_now()


def _weighted_final_score(question: QuestionCandidate) -> float:
    weights = CATEGORY_SCORE_WEIGHTS.get(
        question.category, CATEGORY_SCORE_WEIGHTS["essence"]
    )
    scores = {
        "clarity": question.clarity,
        "specificity": question.specificity,
        "purpose_fit": question.purpose_fit,
        "critical_push": question.critical_push,
        "contextual_fit": question.contextual_fit,
        "openness": question.openness,
        "follow_through": question.follow_through,
        "neutrality": question.neutrality,
        "non_redundancy": question.non_redundancy,
    }
    total_weight = sum(weights.values()) or 1.0
    weighted = sum(scores[key] * weight for key, weight in weights.items())
    return round(weighted / total_weight, 3)


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
            apply_soft_evaluation(question, evaluation)
            question.status = QuestionStatus.REJECTED
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


def generator_state_payload(state: QuestionContextState) -> dict[str, Any]:
    """Compact generator input: askable focus + bans + recent transcript."""
    discussion = state.discussion_state or {}
    focus = state.askable_focus or build_askable_focus(discussion)
    history = state.question_history or {}

    def _take(key: str, limit: int = 6) -> list[Any]:
        items = discussion.get(key, [])
        return items[:limit] if isinstance(items, list) else []

    return {
        "meeting_id": state.meeting_id,
        "meeting_objective": state.meeting_objective,
        "version": state.version,
        "current_topic": state.current_topic,
        "current_topic_summary": state.current_topic_summary,
        "current_purpose": state.current_purpose,
        "askable_focus": focus[:5],
        "do_not_ask": build_do_not_ask(discussion),
        "open_issues": _take("open_issues"),
        "uncertainties": _take("uncertainties"),
        "blockers": _take("blockers"),
        "decision_criteria": _take("decision_criteria"),
        "decisions": _take("decisions"),
        "resolved_items": _take("resolved_items"),
        "recent_transcript": list(state.recent_transcript[-12:]),
        "question_history": {
            "active": list(history.get("active", [])[:5]),
            "displayed": list(history.get("displayed", [])[:5]),
            "parked": list(history.get("parked", [])[:5]),
        },
    }


def evaluator_state_payload(state: QuestionContextState) -> dict[str, Any]:
    """Compact context for soft scoring — avoids shipping full discussion dumps."""
    discussion = state.discussion_state or {}
    focus = state.askable_focus or build_askable_focus(discussion)

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
        "askable_focus": focus[:5],
        "do_not_ask": build_do_not_ask(discussion),
        "open_issues": _take("open_issues"),
        "assumptions": _take("assumptions"),
        "decisions": _take("decisions"),
        "resolved_items": _take("resolved_items"),
        "uncertainties": _take("uncertainties"),
        "recent_transcript": list(state.recent_transcript[-12:]),
        "question_history": {
            "active": list(history.get("active", [])[:5]),
            "displayed": list(history.get("displayed", [])[:5]),
            "parked": list(history.get("parked", [])[:5]),
        },
    }