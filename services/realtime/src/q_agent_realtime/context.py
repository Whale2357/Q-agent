from __future__ import annotations

import json
from typing import Any

from .domain import DISCUSSION_KEYS, QuestionContextState, TranscriptSegment, utc_now
from .ollama import OllamaClient
from .prompts import PromptTemplates


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
    def __init__(self, client: OllamaClient, prompts: PromptTemplates):
        self.client = client
        self.prompts = prompts

    async def update(
        self,
        state: QuestionContextState,
        new_segments: list[TranscriptSegment],
        recent_segments: list[TranscriptSegment],
        question_history: dict[str, list[dict[str, object]]],
    ) -> QuestionContextState:
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
            system=self.prompts.context,
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
