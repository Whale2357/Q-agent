"""One-off qualitative comparison: naive LLM vs Q-Agent pipeline.

Usage (from repo root, with services/realtime/.env set):
  services/realtime/.venv/Scripts/python.exe services/realtime/scripts/compare_question_quality.py
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


FIXTURE = ROOT / "fixtures" / "decision.sample.txt"

NAIVE_SYSTEM = """당신은 회의 도우미다.
주어진 대화에서 참가자에게 던질 좋은 질문 3개를 한국어로 만든다.
JSON만 반환한다: {"questions":[{"text":"...","why":"..."}]}"""


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


async def naive_llm_questions(transcript: str, config: RuntimeConfig) -> list[dict]:
    client = OpenAILLMClient(
        api_key=config.openai_api_key,
        base_url=config.openai_base_url,
        model=config.openai_generator_model,
    )
    await client.ensure_ready()
    schema = {
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
                    },
                    "required": ["text", "why"],
                },
            }
        },
        "required": ["questions"],
    }
    result = await client.chat_json(
        system=NAIVE_SYSTEM,
        user=transcript,
        schema=schema,
        think=False,
        temperature=0.5,
        num_predict=800,
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
        diagnosis = await session.add_text(transcript)
        return diagnosis
    finally:
        await session.close()
        await runtime.close()


async def main() -> None:
    load_dotenv(REALTIME_DIR / ".env")
    config = RuntimeConfig.from_env()
    if not config.openai_api_key:
        raise SystemExit("OPENAI_API_KEY missing in services/realtime/.env")

    transcript = FIXTURE.read_text(encoding="utf-8").strip()
    lines: list[str] = []

    def out(msg: str = "") -> None:
        lines.append(msg)
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("utf-8", errors="replace").decode("ascii", errors="replace"))

    out("=== FIXTURE ===")
    out(transcript)
    out()

    out("=== A) Naive LLM (single-shot 3 questions) ===")
    naive = await naive_llm_questions(transcript, config)
    for i, item in enumerate(naive, 1):
        out(f"{i}. {item.get('text')}")
        out(f"   why: {item.get('why')}")
    out()

    out("=== B) Q-Agent pipeline (context → generate → hybrid evaluate → select) ===")
    diagnosis = await qagent_questions(transcript)
    out(
        json.dumps(
            {
                "status": diagnosis.get("status"),
                "rejected": diagnosis.get("rejected"),
                "reject_reason": diagnosis.get("reject_reason"),
                "pipeline": diagnosis.get("pipeline"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    for i, q in enumerate(diagnosis.get("questions") or [], 1):
        out(f"{i}. {q.get('text')}")
        out(f"   category={q.get('category')} operator={q.get('operator')}")
        out(f"   badges={q.get('badges')} final={q.get('scores', {}).get('final')}")
        out(f"   rationale: {q.get('rationale')}")

    report = REALTIME_DIR / "scripts" / "compare_question_quality.out.txt"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out(f"\nWrote {report}")


if __name__ == "__main__":
    asyncio.run(main())
