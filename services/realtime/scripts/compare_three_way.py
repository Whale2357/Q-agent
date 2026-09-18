"""3-way qualitative comparison on a small fixture set.

A) Naive LLM — generic facilitation prompt
B) Eval-aligned LLM — single-shot prompt mirroring Q-Agent criteria/operators
C) Q-Agent pipeline — context → generate(8) → hybrid evaluate → select(≤3)

Usage (from repo root):
  services/realtime/.venv/Scripts/python.exe services/realtime/scripts/compare_three_way.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REALTIME_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REALTIME_DIR / "src"))

from q_agent_realtime.config import RuntimeConfig
from q_agent_realtime.openai_provider import OpenAILLMClient
from q_agent_realtime.server import RealtimeMeetingSession, RealtimeRuntime

FIXTURE_DIR = ROOT / "fixtures" / "quality_ab"

NAIVE_SYSTEM = """당신은 회의 도우미다.
주어진 대화에서 참가자에게 던질 좋은 질문 3개를 한국어로 만든다.
JSON만 반환한다: {"questions":[{"text":"...","why":"..."}]}"""

EVAL_ALIGNED_SYSTEM = """당신은 회의에서 '결정·다음 행동을 바꾸는' 개입 질문을 만든다.
촉진용 소프트 질문(의견 모으기, 장단점 정리, 분위기 확인)은 피한다.

각 질문은 아래를 만족해야 한다:
1) information_gain: 답이 결정/우선순위/다음 행동을 실제로 바꿀 수 있어야 함
2) assumption_surfacing: 암묵적 전제·기준 부재·성급한 합의를 드러내야 함
3) 대화에 근거가 있어야 하고, 이미 답이 나온 내용/일반론/특정인 비난은 금지
4) 길이 15~120자, 의문형, 한국어
5) 서로 다른 operator를 쓸 것. 후보 operator:
   - assumption_challenge
   - criterion_clarification
   - counterfactual
   - reframing
   - constraint_relaxation
6) category도 가능하면 다양하게: blind_spot / essence / expansion

정확히 3개만 만든다.
JSON만 반환:
{"questions":[{"text":"...","operator":"...","category":"...","why":"..."}]}"""

QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "why": {"type": "string"},
                    "operator": {"type": "string"},
                    "category": {"type": "string"},
                },
                "required": ["text", "why"],
            },
        }
    },
    "required": ["questions"],
}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


async def llm_questions(
    transcript: str,
    config: RuntimeConfig,
    system: str,
    *,
    temperature: float = 0.5,
) -> list[dict]:
    client = OpenAILLMClient(
        api_key=config.openai_api_key,
        base_url=config.openai_base_url,
        model=config.openai_generator_model,
    )
    await client.ensure_ready()
    result = await client.chat_json(
        system=system,
        user=transcript,
        schema=QUESTION_SCHEMA,
        think=False,
        temperature=temperature,
        num_predict=900,
    )
    await client.close()
    return list(result.get("questions", []))


async def qagent_questions(transcript: str) -> dict:
    runtime = RealtimeRuntime()
    await runtime.ensure_ready(audio=False)

    async def _ignore(_event: dict) -> None:
        return None

    session = RealtimeMeetingSession(runtime, _ignore, audio=False)
    try:
        return await session.add_text(transcript)
    finally:
        await session.close()
        await runtime.close()


def fixture_files() -> list[Path]:
    files = sorted(FIXTURE_DIR.glob("*.txt"))
    if not files:
        raise SystemExit(f"No fixtures in {FIXTURE_DIR}")
    return files


async def run_case(
    path: Path,
    config: RuntimeConfig,
    out,
) -> None:
    transcript = path.read_text(encoding="utf-8").strip()
    out("=" * 72)
    out(f"CASE: {path.name}")
    out("-" * 72)
    out(transcript)
    out()

    out("### A) Naive LLM")
    naive = await llm_questions(transcript, config, NAIVE_SYSTEM)
    for i, item in enumerate(naive, 1):
        out(f"{i}. {item.get('text')}")
        out(f"   why: {item.get('why')}")
    out()

    out("### B) Eval-aligned LLM (평가 기준 유사 프롬프트)")
    aligned = await llm_questions(transcript, config, EVAL_ALIGNED_SYSTEM, temperature=0.4)
    for i, item in enumerate(aligned, 1):
        op = item.get("operator") or "-"
        cat = item.get("category") or "-"
        out(f"{i}. [{op}/{cat}] {item.get('text')}")
        out(f"   why: {item.get('why')}")
    out()

    out("### C) Q-Agent pipeline")
    diagnosis = await qagent_questions(transcript)
    pipeline = diagnosis.get("pipeline") or {}
    out(
        f"status={diagnosis.get('status')} "
        f"generated={pipeline.get('candidates_generated')} "
        f"selected={pipeline.get('selected')} "
        f"rejected={diagnosis.get('rejected')}"
    )
    if diagnosis.get("reject_reason"):
        out(f"reject_reason: {diagnosis.get('reject_reason')}")
    questions = diagnosis.get("questions") or []
    if not questions:
        out("(eligible 질문 없음)")
    for i, q in enumerate(questions[:3], 1):
        scores = q.get("scores") or {}
        out(
            f"{i}. [{q.get('operator')}/{q.get('category')}] {q.get('text')}"
        )
        out(
            f"   final={scores.get('final')} badges={q.get('badges')} "
            f"rationale: {q.get('rationale')}"
        )
    if len(questions) < 3:
        out(f"(참고: pipeline 최종 eligible {len(questions)}개 — 최대 3)")
    out()


async def main() -> None:
    load_dotenv(REALTIME_DIR / ".env")
    config = RuntimeConfig.from_env()
    if not config.openai_api_key:
        raise SystemExit("OPENAI_API_KEY missing in services/realtime/.env")

    lines: list[str] = []

    def out(msg: str = "") -> None:
        lines.append(msg)
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("utf-8", errors="replace").decode("ascii", errors="replace"))

    out("Q-Agent 3-way question quality comparison")
    out("A=Naive LLM | B=Eval-aligned LLM | C=Q-Agent pipeline")
    out(f"model={config.openai_generator_model}")
    out()

    for path in fixture_files():
        await run_case(path, config, out)

    report = REALTIME_DIR / "scripts" / "compare_three_way.out.txt"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out(f"Wrote {report}")


if __name__ == "__main__":
    asyncio.run(main())
