from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .domain import DISCUSSION_KEYS, QuestionContextState, TranscriptSegment, utc_now
from .prompt_loader import load_prompt

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
    for value in item.get("evidence_segment_ids", []) or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
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
    return normalized


def build_do_not_ask(
    discussion: dict[str, list[Any]] | None, *, limit: int = 12
) -> list[str]:
    discussion = discussion or {}
    texts: list[str] = []
    seen: set[str] = set()
    for key in ("resolved_items", "decisions"):
        for item in discussion.get(key, []) or []:
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
    do_not = {text.casefold() for text in build_do_not_ask(discussion, limit=24)}
    focus: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append(content: str, source: str, evidence: list[int]) -> None:
        key = content.casefold()
        if not content or key in seen or key in do_not:
            return
        # Soft skip if content is nearly identical to a do_not_ask line.
        for blocked in do_not:
            if blocked and (blocked in key or key in blocked):
                return
        seen.add(key)
        focus.append(
            {
                "content": content,
                "source": source,
                "evidence_segment_ids": evidence,
            }
        )

    if isinstance(llm_focus, list):
        for item in llm_focus:
            if len(focus) >= limit:
                break
            if isinstance(item, dict):
                _append(
                    item_content(item),
                    str(item.get("source") or "open_issues"),
                    item_evidence_ids(item),
                )
            else:
                _append(item_content(item), "open_issues", [])

    if len(focus) < limit:
        for source in _ASKABLE_SOURCE_KEYS:
            for item in discussion.get(source, []) or []:
                if len(focus) >= limit:
                    break
                status = item_status(item)
                if not is_open_status(status) and status not in {""}:
                    if is_resolved_status(status):
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
        system = load_prompt("context")
        user = json.dumps(
            {
                "meeting_objective": state.meeting_objective,
                "previous_context": {
                    "global_summary": state.global_summary,
                    "current_topic": state.current_topic,
                    "current_topic_summary": state.current_topic_summary,
                    "current_purpose": state.current_purpose,
                    "discussion_state": state.discussion_state,
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

        state.version += 1
        state.global_summary = str(result.get("global_summary", state.global_summary))
        state.current_topic = str(result.get("current_topic", state.current_topic))
        state.current_topic_summary = str(
            result.get("current_topic_summary", state.current_topic_summary)
        )
        state.current_purpose = result.get("current_purpose", state.current_purpose)
        incoming_discussion = result.get("discussion_state") or {}
        raw_discussion = {
            key: incoming_discussion.get(key, [])
            if isinstance(incoming_discussion.get(key, []), list)
            else []
            for key in DISCUSSION_KEYS
        }
        state.discussion_state = normalize_discussion_state(raw_discussion)
        state.askable_focus = build_askable_focus(
            state.discussion_state, result.get("askable_focus")
        )
        state.recent_transcript = [segment.prompt_dict() for segment in recent_segments]
        state.question_history = question_history
        state.last_processed_segment_id = max(
            segment.id or 0 for segment in new_segments
        )
        state.updated_at = utc_now()
        return state
