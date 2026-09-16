from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .domain import DISCUSSION_KEYS, QuestionContextState, TranscriptSegment, utc_now

if TYPE_CHECKING:
    from .ollama import OllamaClient


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
    },
    "required": [
        "global_summary",
        "current_topic",
        "current_topic_summary",
        "current_purpose",
        "discussion_state",
    ],
}


class ContextUpdater:
    def __init__(self, client: OllamaClient):
        self.client = client

    async def update(
        self,
        state: QuestionContextState,
        new_segments: list[TranscriptSegment],
        recent_segments: list[TranscriptSegment],
        question_history: dict[str, list[dict[str, object]]],
    ) -> QuestionContextState:
        system = """당신은 Q-Agent의 회의 맥락 갱신기다.
이전 상태와 새 발화를 합쳐 질문 생성용 맥락을 한국어로 갱신한다.
결론만 압축하지 말고 논의의 변화, 제안의 이유, 대안, 근거, 반론, 미해결 사항을 보존한다.
새 발화가 기존 내용을 해결하거나 뒤집으면 항목을 삭제하지 말고 status를 resolved 또는 superseded로 바꾼다.
발화에 없는 사실, 감정, 합의, 발화자 의도를 추측하지 않는다.
모든 구조화 항목에는 실제 근거 segment id만 연결한다.
현재 1~2분의 활동을 기준으로 current_purpose를 판단한다.
JSON 스키마에 맞는 객체만 반환한다. /no_think"""
        user = json.dumps(
            {
                "meeting_objective": state.meeting_objective,
                "previous_context": {
                    "global_summary": state.global_summary,
                    "current_topic": state.current_topic,
                    "current_topic_summary": state.current_topic_summary,
                    "current_purpose": state.current_purpose,
                    "discussion_state": state.discussion_state,
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
            num_predict=1600,
        )

        state.version += 1
        state.global_summary = str(result.get("global_summary", state.global_summary))
        state.current_topic = str(result.get("current_topic", state.current_topic))
        state.current_topic_summary = str(
            result.get("current_topic_summary", state.current_topic_summary)
        )
        state.current_purpose = result.get("current_purpose", state.current_purpose)
        incoming_discussion = result.get("discussion_state") or {}
        state.discussion_state = {
            key: incoming_discussion.get(key, [])
            if isinstance(incoming_discussion.get(key, []), list)
            else []
            for key in DISCUSSION_KEYS
        }
        state.recent_transcript = [segment.prompt_dict() for segment in recent_segments]
        state.question_history = question_history
        state.last_processed_segment_id = max(
            segment.id or 0 for segment in new_segments
        )
        state.updated_at = utc_now()
        return state
