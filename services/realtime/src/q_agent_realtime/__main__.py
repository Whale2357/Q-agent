from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .audio import input_devices
from .config import DEFAULT_PROMPT_DIR, RuntimeConfig
from .database import Repository
from .ollama import OllamaClient, OllamaError
from .pipeline import MeetingPipeline
from .prompts import PromptLoadError, PromptTemplates
from .transcriber import FasterWhisperTranscriber


def parse_device(value: str | None) -> int | str | None:
    if value is None:
        return None
    return int(value) if value.isdigit() else value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Q-Agent local realtime pipeline")
    parser.add_argument("--list-devices", action="store_true", help="마이크 목록 출력")
    parser.add_argument("--device", help="마이크 장치 번호 또는 이름")
    parser.add_argument("--db", default="data/q-agent.db", help="SQLite DB 경로")
    parser.add_argument("--model", default="qwen3:8b", help="Ollama 모델")
    parser.add_argument(
        "--ollama-url", default="http://127.0.0.1:11434", help="Ollama 기본 URL"
    )
    parser.add_argument("--meeting-objective", default="", help="회의 전체 목적")
    parser.add_argument(
        "--prompt-dir",
        type=Path,
        default=DEFAULT_PROMPT_DIR,
        help="버전별 Markdown 프롬프트 폴더",
    )
    parser.add_argument("--silence-seconds", type=float, default=20.0)
    return parser


async def run(args: argparse.Namespace) -> None:
    config = RuntimeConfig(
        database_path=Path(args.db),
        ollama_base_url=args.ollama_url,
        ollama_model=args.model,
        meeting_objective=args.meeting_objective,
        microphone_device=parse_device(args.device),
        silence_trigger_seconds=args.silence_seconds,
        prompt_dir=args.prompt_dir,
    )
    try:
        prompts = PromptTemplates.from_directory(config.prompt_dir)
    except PromptLoadError as error:
        raise SystemExit(str(error)) from error
    print("[startup] Whisper turbo 모델을 GPU에 로드합니다...")
    transcriber = FasterWhisperTranscriber(language=config.language)
    repository = Repository(config.database_path)
    ollama = OllamaClient(
        base_url=config.ollama_base_url,
        model=config.ollama_model,
        num_ctx=config.context_window_tokens,
    )
    pipeline = MeetingPipeline(config, repository, ollama, transcriber, prompts)
    try:
        await pipeline.run()
    except OllamaError as error:
        repository.close()
        await ollama.close()
        raise SystemExit(str(error)) from error


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.list_devices:
        for index, name, channels in input_devices():
            print(f"{index}: {name} (입력 {channels}채널)")
        return
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n[meeting] 중단됨")


if __name__ == "__main__":
    main()
