from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


REQUIRED_PROMPT_FILES = (
    "_shared_v1.md",
    "context_v1.md",
    "evaluator_v1.md",
    "generator_v1.md",
    "purpose_guide_v1.md",
)

STALE_GUIDANCE = """
`question_history`와 최신 `question_context_state`를 함께 확인한다.
후보 질문의 답이 이미 나왔으면 `already_resolved`를 true로 하고
`stale_reason`을 `resolved`로 지정한다. 현재 주제가 바뀌어 더 이상 적절하지
않으면 `stale_reason`을 `topic_changed`로 지정한다.
""".strip()

_UNRESOLVED_PLACEHOLDER = re.compile(r"\{\{[A-Z0-9_]+\}\}")


class PromptLoadError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PromptTemplates:
    context: str
    generator: str
    evaluator: str
    directory: Path

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        *,
        generator_candidate_count: int = 8,
    ) -> "PromptTemplates":
        directory = directory.expanduser().resolve()
        missing = [name for name in REQUIRED_PROMPT_FILES if not (directory / name).is_file()]
        if missing:
            joined = ", ".join(missing)
            raise PromptLoadError(
                f"프롬프트 폴더 '{directory}'에 필수 파일이 없습니다: {joined}"
            )

        values = {
            name: (directory / name).read_text(encoding="utf-8-sig").strip()
            for name in REQUIRED_PROMPT_FILES
        }
        shared = values["_shared_v1.md"]
        generator = values["generator_v1.md"].replace(
            "{{GENERATOR_CANDIDATE_COUNT}}", str(generator_candidate_count)
        ).replace("{{PURPOSE_GUIDE}}", values["purpose_guide_v1.md"])
        evaluator = values["evaluator_v1.md"].replace(
            "{{STALE_GUIDANCE}}", STALE_GUIDANCE
        )

        generator = _with_shared_rules(generator, shared)
        evaluator = _with_shared_rules(evaluator, shared)
        _ensure_rendered("generator_v1.md", generator)
        _ensure_rendered("evaluator_v1.md", evaluator)

        return cls(
            context=values["context_v1.md"],
            generator=generator,
            evaluator=evaluator,
            directory=directory,
        )


def _with_shared_rules(prompt: str, shared: str) -> str:
    return f"{prompt}\n\n{shared}" if shared else prompt


def _ensure_rendered(name: str, prompt: str) -> None:
    placeholders = sorted(set(_UNRESOLVED_PLACEHOLDER.findall(prompt)))
    if placeholders:
        joined = ", ".join(placeholders)
        raise PromptLoadError(f"{name}에 치환되지 않은 변수가 있습니다: {joined}")
