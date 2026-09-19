from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, Any

from .domain import DISCUSSION_KEYS, QuestionContextState, TranscriptSegment, utc_now
from .prompt_loader import load_prompt
from .providers import ProviderError

if TYPE_CHECKING:
    from .providers import StructuredLLMClient


PURPOSES = (
    "progress_coordination",
    "idea_exploration",
    "decision_making",
    "problem_solving",
    "planning_strategy",
    "performance_review",
    "alignment",
    "unknown",
)

_ASKABLE_SOURCE_KEYS = (
    "open_issues",
    "uncertainties",
    "blockers",
    "decision_criteria",
)
_OPEN_STATUSES = {"", "open", "active", "unresolved", "pending", "in_progress"}
_RESOLVED_STATUSES = {
    "resolved",
    "superseded",
    "closed",
    "done",
    "decided",
    "agreed",
}


_FOCUS_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "content": {"type": "string"},
        "source": {"type": "string"},
        "evidence_segment_ids": {
            "type": "array",
            "items": {"type": "integer"},
        },
    },
    "required": ["content", "source", "evidence_segment_ids"],
}


CONTEXT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "global_summary": {"type": "string"},
        "current_topic": {"type": "string"},
        "current_topic_summary": {"type": "string"},
        "current_purpose": {
            "type": "object",
            "properties": {
                "primary": {"type": "string", "enum": list(PURPOSES)},
                "secondary": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["primary", "secondary", "confidence"],
        },
        "discussion_state": {
            "type": "object",
            "properties": {
                key: {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {"type": "string"},
                            "evidence_segment_ids": {
                                "type": "array",
                                "items": {"type": "integer"},
                            },
                        },
                        "required": ["content", "status", "evidence_segment_ids"],
                    },
                }
                for key in DISCUSSION_KEYS
            },
            "required": list(DISCUSSION_KEYS),
        },
        "askable_focus": {
            "type": "array",
            "maxItems": 5,
            "items": _FOCUS_ITEM_SCHEMA,
        },
    },
    "required": [
        "global_summary",
        "current_topic",
        "current_topic_summary",
        "current_purpose",
        "discussion_state",
        "askable_focus",
    ],
}


def item_content(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("content") or item.get("text") or "").strip()
    return ""


def item_status(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("status", "open")).strip().lower()
    return "open"


def item_evidence_ids(item: Any) -> list[int]:
    if not isinstance(item, dict):
        return []
    ids: list[int] = []
    raw = item.get("evidence_segment_ids", [])
    if not isinstance(raw, list):
        return []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in ids:
            ids.append(parsed)
    return ids


def is_open_status(status: str) -> bool:
    return status in _OPEN_STATUSES


def is_resolved_status(status: str) -> bool:
    return status in _RESOLVED_STATUSES


def normalize_discussion_state(
    discussion: dict[str, list[Any]],
) -> dict[str, list[Any]]:
    """Keep open buckets open-only; move resolved-status rows into resolved_items."""
    normalized = {key: [] for key in DISCUSSION_KEYS}
    for key in DISCUSSION_KEYS:
        raw = discussion.get(key, [])
        items = raw if isinstance(raw, list) else []
        if key in {"decisions", "resolved_items"}:
            for item in items:
                content = item_content(item)
                if not content:
                    continue
                if key == "decisions" and item_status(item) == "superseded":
                    normalized["resolved_items"].append({
                        "content": content, "status": "superseded",
                        "evidence_segment_ids": item_evidence_ids(item),
                    })
                    continue
                if isinstance(item, dict):
                    row = dict(item)
                    row.setdefault("status", "resolved" if key == "resolved_items" else "decided")
                    row["content"] = content
                    normalized[key].append(row)
                else:
                    normalized[key].append(
                        {
                            "content": content,
                            "status": "resolved" if key == "resolved_items" else "decided",
                            "evidence_segment_ids": [],
                        }
                    )
            continue

        for item in items:
            content = item_content(item)
            if not content:
                continue
            status = item_status(item)
            if key in _ASKABLE_SOURCE_KEYS and is_resolved_status(status):
                normalized["resolved_items"].append(
                    {
                        "content": content,
                        "status": status,
                        "evidence_segment_ids": item_evidence_ids(item),
                    }
                )
                continue
            if key in _ASKABLE_SOURCE_KEYS and not is_open_status(status):
                continue
            if isinstance(item, dict):
                row = dict(item)
                row["content"] = content
                if key in _ASKABLE_SOURCE_KEYS and not status:
                    row["status"] = "open"
                normalized[key].append(row)
            else:
                normalized[key].append(
                    {
                        "content": content,
                        "status": "open",
                        "evidence_segment_ids": [],
                    }
                )
    # A model can retain a row in its old bucket while also resolving it.
    # Prefer the resolved copy and keep only one copy per bucket.
    closed = {item_content(item).casefold() for key in ("decisions", "resolved_items")
              for item in normalized[key] if item_status(item) != "superseded"}
    for key, items in normalized.items():
        seen: set[str] = set()
        normalized[key] = []
        for item in items:
            content = item_content(item).casefold()
            if content in seen or (key in _ASKABLE_SOURCE_KEYS and content in closed):
                continue
            seen.add(content)
            normalized[key].append(item)
    return normalized


def build_do_not_ask(
    discussion: dict[str, list[Any]] | None, *, limit: int = 12
) -> list[str]:
    discussion = discussion or {}
    if limit <= 0:
        return []
    texts: list[str] = []
    seen: set[str] = set()
    for key in ("resolved_items", "decisions"):
        for item in discussion.get(key, []) or []:
            if item_status(item) == "superseded":
                continue
            content = item_content(item)
            if not content:
                continue
            key_norm = content.casefold()
            if key_norm in seen:
                continue
            seen.add(key_norm)
            texts.append(content)
            if len(texts) >= limit:
                return texts
    return texts


def build_askable_focus(
    discussion: dict[str, list[Any]] | None,
    llm_focus: list[Any] | None = None,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    discussion = discussion or {}
    if limit <= 0:
        return []
    do_not = {text.casefold() for text in build_do_not_ask(discussion, limit=24)}
    focus: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append(content: str, source: str, evidence: list[int]) -> None:
        key = content.casefold()
        if not content or key in seen or key in do_not:
            return
        # A follow-up may name a prior decision while asking about an open
        # implementation detail. Only exclude the exact resolved issue here.
        seen.add(key)
        focus.append(
            {
                "content": content,
                "source": source,
                "evidence_segment_ids": evidence,
            }
        )

    # Focus is a ranking of existing open rows, not a separate source of facts.
    # Only trust an LLM focus row when its source and text match an open row.
    open_rows = {
        (source, item_content(item).casefold()): item
        for source in _ASKABLE_SOURCE_KEYS
        for item in discussion.get(source, []) or []
        if is_open_status(item_status(item)) and item_content(item)
    }
    if isinstance(llm_focus, list):
        for item in llm_focus:
            if len(focus) >= limit:
                break
            if isinstance(item, dict):
                source = str(item.get("source") or "open_issues")
                canonical = open_rows.get((source, item_content(item).casefold()))
                if canonical is None:
                    continue
                _append(
                    item_content(canonical), source, item_evidence_ids(canonical),
                )

    if len(focus) < limit:
        for source in _ASKABLE_SOURCE_KEYS:
            for item in discussion.get(source, []) or []:
                if len(focus) >= limit:
                    break
                status = item_status(item)
                if not is_open_status(status):
                    continue
                _append(item_content(item), source, item_evidence_ids(item))
            if len(focus) >= limit:
                break

    return focus[:limit]


class ContextUpdater:
    def __init__(self, client: StructuredLLMClient):
        self.client = client

    async def update(
        self,
        state: QuestionContextState,
        new_segments: list[TranscriptSegment],
        recent_segments: list[TranscriptSegment],
        question_history: dict[str, list[dict[str, object]]],
    ) -> QuestionContextState:
        if not new_segments:
            return state
        # Bound each update and only advance through the segments actually sent.
        # Audio loops continue from this cursor; one-shot analysis drains batches.
        budget = 2000 if getattr(self.client, "provider", "") == "ollama" else 12000
        batch: list[TranscriptSegment] = []
        used = 0
        for segment in new_segments:
            if batch and used + len(segment.text) > budget:
                break
            batch.append(segment)
            used += len(segment.text)
        new_segments = batch
        last_id = new_segments[-1].id or 0
        visible = {segment.id: segment for segment in recent_segments if (segment.id or 0) <= last_id}
        visible.update({segment.id: segment for segment in new_segments})
        recent_segments = sorted(visible.values(), key=lambda segment: segment.id or 0)[-12:]
        system = load_prompt("context")
        user = json.dumps(
            {
                "meeting_objective": state.meeting_objective,
                "previous_context": {
                    "global_summary": state.global_summary,
                    "current_topic": state.current_topic,
                    "current_topic_summary": state.current_topic_summary,
                    "current_purpose": state.current_purpose,
                    "discussion_state": {key: rows[-8:] for key, rows in state.discussion_state.items()},
                    "askable_focus": state.askable_focus,
                },
                "new_transcript": [segment.prompt_dict() for segment in new_segments],
                "recent_transcript": [segment.prompt_dict() for segment in recent_segments],
                "question_history": question_history,
            },
            ensure_ascii=False,
        )
        result = await self.client.chat_json(
            system=system,
            user=user,
            schema=CONTEXT_SCHEMA,
            think=False,
            temperature=0.1,
            num_predict=1800,
        )

        # Reject malformed model responses before changing the last-processed
        # marker, otherwise the transcript can be silently lost on the next run.
        if not isinstance(result, dict) or not all(
            isinstance(result.get(key), str)
            for key in ("global_summary", "current_topic", "current_topic_summary")
        ):
            raise ProviderError("맥락 응답의 요약 형식이 올바르지 않습니다")
        purpose = result.get("current_purpose")
        incoming_discussion = result.get("discussion_state")
        if (not isinstance(purpose, dict)
            or purpose.get("primary") not in PURPOSES
            or not isinstance(purpose.get("secondary"), list)
            or not isinstance(incoming_discussion, dict)
            or not all(isinstance(incoming_discussion.get(key), list) for key in DISCUSSION_KEYS)
            or not isinstance(result.get("askable_focus"), list)):
            raise ProviderError("맥락 응답의 구조가 올바르지 않습니다")
        confidence = purpose.get("confidence")
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ProviderError("맥락 응답의 confidence가 올바르지 않습니다")
        valid_ids = {segment.id for segment in (*new_segments, *recent_segments) if segment.id is not None}
        previous_contents: set[str] = set()
        for items in state.discussion_state.values():
            for item in items:
                valid_ids.update(item_evidence_ids(item))
                previous_contents.add(item_content(item).casefold())
        raw_discussion: dict[str, list[Any]] = {}
        for key in DISCUSSION_KEYS:
            rows: list[Any] = []
            for item in incoming_discussion[key]:
                if not isinstance(item, dict) or not isinstance(item.get("content"), str):
                    continue
                evidence = [value for value in item_evidence_ids(item) if value in valid_ids]
                if evidence or item_content(item).casefold() in previous_contents:
                    rows.append({**item, "evidence_segment_ids": evidence})
            raw_discussion[key] = rows
        discussion = normalize_discussion_state(raw_discussion)
        focus = build_askable_focus(discussion, result["askable_focus"])

        state.version += 1
        state.global_summary = str(result.get("global_summary", state.global_summary))
        state.current_topic = str(result.get("current_topic", state.current_topic))
        state.current_topic_summary = str(
            result.get("current_topic_summary", state.current_topic_summary)
        )
        state.current_purpose = {
            "primary": purpose["primary"],
            "secondary": [value for value in purpose["secondary"] if value in PURPOSES and value != purpose["primary"]],
            "confidence": confidence,
        }
        state.discussion_state = discussion
        state.askable_focus = focus
        state.recent_transcript = [segment.prompt_dict() for segment in recent_segments]
        state.question_history = question_history
        state.last_processed_segment_id = max(state.last_processed_segment_id, *(segment.id or 0 for segment in new_segments))
        state.updated_at = utc_now()
        return state
