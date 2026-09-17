# Q-Agent

원티드 AI Championship 2026 — 회의 맥락 판독 & 질문 큐레이션 엔진 모노레포.

## 구조

```
apps/web              Next.js 프론트 + BFF (/api/*)
services/extract      음성/텍스트 → Transcript
services/engine       질문 생성 + 선발
services/realtime     로컬 마이크 → Whisper → 맥락 상태 → 질문 후보/검증
packages/contracts    공유 TypeScript 계약
fixtures/             샘플 회의록
scripts/smoke-test.mjs 모듈 통신 검증
```

협업 규칙: [`docs/KICKOFF.md`](docs/KICKOFF.md)  
최종 기획: [`docs/최종_기획안.md`](docs/최종_기획안.md)  
인프라·통신 검증: [`docs/INFRASTRUCTURE.md`](docs/INFRASTRUCTURE.md)  
MVP2 범위·브랜치 운영 (`develop_2`): [`docs/MVP2.md`](docs/MVP2.md)

## 로컬 실행 (웹 + realtime)

```powershell
npm install
cd services/realtime
python -m pip install -e .
cd ../..

# 기본 로컬 모드: 역할별 Qwen 모델 3개 설치
ollama pull qwen3:1.7b
ollama pull qwen3:4b
ollama pull qwen3:8b

# 터미널 2개에서 realtime과 web 실행
q-agent-realtime-server --host 127.0.0.1 --port 8765
npm run dev:web
```

- Web: http://localhost:3000  
- Realtime API: http://localhost:8765/health

웹의 녹음 모드는 브라우저 PCM을 realtime WebSocket으로 직접 전송하며,
텍스트 테스트는 web BFF를 거쳐 같은 Qwen 생성·평가 파이프라인을 사용합니다.
Python/GPU/Ollama 세부 설정은
[`services/realtime/README.md`](services/realtime/README.md)를 참고하세요.

실행 자원은 다음처럼 나뉩니다.

- CPU/RAM: 브라우저·Next.js·FastAPI·WebSocket·VAD·오디오 버퍼·SQLite·주기 제어
- GPU/VRAM: faster-whisper 전사 추론, Ollama의 Qwen3 4B/8B 추론

즉 브라우저가 마이크를 캡처하고 서버 CPU가 오디오를 정리하며, 실제 Whisper와
Qwen 신경망 계산만 GPU로 전달합니다.

### CPU 서버 + OpenAI API 배포 모드

공개 배포에서는 realtime 서버에 다음 환경변수를 설정하면 같은 프런트와
WebSocket 계약을 유지한 채 로컬 Whisper/Ollama 대신 API를 사용합니다.

```dotenv
LLM_PROVIDER=openai
STT_PROVIDER=openai
OPENAI_API_KEY=서버_비밀키
OPENAI_CONTEXT_MODEL=gpt-4o-mini
OPENAI_GENERATOR_MODEL=gpt-4o-mini
OPENAI_EVALUATOR_MODEL=gpt-4o-mini
OPENAI_STT_MODEL=gpt-4o-mini-transcribe
```

API 키는 realtime 백엔드에만 저장하고 프런트 환경변수에는 넣지 않습니다.

### 레거시 extract/engine 확인

기존 `extract`/`engine`은 데모 및 계약 스모크 테스트용으로 남아 있으며 현재
웹 화면에서는 호출하지 않습니다.

```bash
npm run dev:extract
npm run dev:engine
npm run smoke
```

## Docker Compose

```bash
docker compose up --build
```

현재 Compose는 레거시 TypeScript 서비스 묶음이며 realtime GPU 서버는 별도로
실행해야 합니다.

## 배포 요약

| 모듈 | 권장 호스트 | 환경변수 |
| --- | --- | --- |
| web | Next.js 호스트 (`apps/web`) | `REALTIME_SERVICE_URL`, `NEXT_PUBLIC_REALTIME_WS_URL` |
| realtime | CPU API 호스트 또는 GPU/로컬 PC | `LLM_PROVIDER`, `STT_PROVIDER`, `OPENAI_API_KEY` 또는 `OLLAMA_*` |
| extract / engine | 레거시 데모 | `EXTRACT_SERVICE_URL`, `ENGINE_SERVICE_URL` |

**비밀키는 커밋하지 마세요.** `.env`는 gitignore 대상입니다.
