from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


DISCUSSION_KEYS = (
    "goals",
    "proposals",
    "alternatives",
    "decision_criteria",
    "evidence",
    "assumptions",
    "uncertainties",
    "disagreements",
    "blockers",
    "decisions",
    "resolved_items",
    "open_issues",
    "action_items",
)

QUESTION_CATEGORIES = ("blind_spot", "essence", "expansion")
QUESTION_OPERATORS = (
    "assumption_challenge",
    "reframing",
    "criterion_clarification",
    "counterfactual",
    "constraint_relaxation",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def empty_discussion_state() -> dict[str, list[dict[str, Any] | str]]:
    return {key: [] for key in DISCUSSION_KEYS}


class QuestionStatus(StrEnum):
    CANDIDATE = "candidate"
    ELIGIBLE = "eligible"
    REJECTED = "rejected"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    DISPLAYED = "displayed"


@dataclass(slots=True)
class TranscriptSegment:
    meeting_id: str
    start_ms: int
    end_ms: int
    text: str
    id: int | None = None
    created_at: str = field(default_factory=utc_now)

    def prompt_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "text": self.text,
        }


@dataclass(slots=True)
class QuestionContextState:
    meeting_id: str
    meeting_objective: str = ""
    version: int = 0
    global_summary: str = ""
    current_topic: str = ""
    current_topic_summary: str = ""
    current_purpose: dict[str, Any] = field(
        default_factory=lambda: {"primary": "unknown", "secondary": [], "confidence": 0.0}
    )
    discussion_state: dict[str, list[dict[str, Any] | str]] = field(
        default_factory=empty_discussion_state
    )
    recent_transcript: list[dict[str, Any]] = field(default_factory=list)
    question_history: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {
            "active": [],
            "displayed": [],
            "resolved": [],
            "rejected": [],
        }
    )
    last_processed_segment_id: int = 0
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "QuestionContextState":
        discussion = empty_discussion_state()
        incoming_discussion = value.get("discussion_state") or {}
        for key in DISCUSSION_KEYS:
            items = incoming_discussion.get(key, [])
            discussion[key] = items if isinstance(items, list) else []

        history = {"active": [], "displayed": [], "resolved": [], "rejected": []}
        incoming_history = value.get("question_history") or {}
        for key in history:
            items = incoming_history.get(key, [])
            history[key] = items if isinstance(items, list) else []

        purpose = value.get("current_purpose") or {}
        return cls(
            meeting_id=str(value["meeting_id"]),
            meeting_objective=str(value.get("meeting_objective", "")),
            version=int(value.get("version", 0)),
            global_summary=str(value.get("global_summary", "")),
            current_topic=str(value.get("current_topic", "")),
            current_topic_summary=str(value.get("current_topic_summary", "")),
            current_purpose={
                "primary": str(purpose.get("primary", "unknown")),
                "secondary": purpose.get("secondary", [])
                if isinstance(purpose.get("secondary", []), list)
                else [],
                "confidence": float(purpose.get("confidence", 0.0)),
            },
            discussion_state=discussion,
            recent_transcript=value.get("recent_transcript", [])
            if isinstance(value.get("recent_transcript", []), list)
            else [],
            question_history=history,
            last_processed_segment_id=int(value.get("last_processed_segment_id", 0)),
            updated_at=str(value.get("updated_at", utc_now())),
        )


@dataclass(slots=True)
class QuestionCandidate:
    id: str
    meeting_id: str
    text: str
    meeting_purpose: str
    detected_problem: str
    question_role: str
    theory: str
    evidence_segment_ids: list[int]
    context_version: int = 0
    category: str = "essence"
    operator: str = "criterion_clarification"
    status: QuestionStatus = QuestionStatus.CANDIDATE
    information_gain: float = 0.0
    non_redundancy: float = 0.0
    assumption_surfacing: float = 0.0
    final_score: float = 0.0
    evaluation_reason: str = ""
    generated_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value
