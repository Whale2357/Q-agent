# STEIN (Q-Agent)

원티드 AI Championship 2026 — 회의 맥락 판독 & 질문 큐레이션 엔진 모노레포.

## 구조

```
apps/web              Next.js 프론트 + BFF (/api/health, /api/realtime/text|session)
services/realtime     마이크/텍스트 → STT → 맥락 → 질문 후보/검증
packages/contracts    공유 TypeScript 계약
fixtures/             샘플 회의록
scripts/smoke-test.mjs web ↔ realtime 통신 검증
```

활성 경로는 **웹 → realtime** 입니다. 예전 TypeScript `extract`/`engine` 서비스는 제거했습니다.

협업 규칙(역사): [`docs/KICKOFF.md`](docs/KICKOFF.md)  
최종 기획: [`docs/최종_기획안.md`](docs/최종_기획안.md)  
인프라·통신·배포: [`docs/INFRASTRUCTURE.md`](docs/INFRASTRUCTURE.md)  
오늘(2026-09-18) 작업 정리: [`docs/2026-09-18_작업정리.md`](docs/2026-09-18_작업정리.md)  
브랜치 메모(역사): [`docs/MVP2.md`](docs/MVP2.md)

## 로컬 실행 (웹 + realtime)

Node.js **22.18 이상**, Python **3.11 또는 3.12**가 필요합니다.

처음 한 번만 `services/realtime/.env.example`을 `services/realtime/.env`로
복사하고 `OPENAI_API_KEY=` 뒤에 발급받은 키를 입력합니다. 이 파일은 Git에
포함되지 않습니다.

```powershell
Copy-Item services/realtime/.env.example services/realtime/.env
notepad services/realtime/.env
```

이후 Windows에서는 [`apps/web/start-local.cmd`](apps/web/start-local.cmd)를
더블클릭하면 realtime API와 웹이 함께 실행됩니다. Python 가상환경과 패키지가
없으면 첫 실행 때 자동으로 준비합니다.

수동으로 실행하려면 다음 명령을 사용합니다.

```powershell
npm ci
cd services/realtime
python -m pip install -e .
cd ../..

# 터미널 2개에서 realtime과 web 실행
q-agent-realtime-server --host 127.0.0.1 --port 8765
npm run dev:web
```

- Web: http://localhost:3000  
- Realtime API: http://localhost:8765/health

웹의 녹음 모드는 브라우저 PCM을 realtime WebSocket으로 직접 전송하며,
텍스트 테스트는 web BFF를 거쳐 같은 OpenAI 생성·평가 파이프라인을 사용합니다.
제공자와 로컬 대체 실행에 관한 세부 설정은
[`services/realtime/README.md`](services/realtime/README.md)를 참고하세요.

실행 자원은 다음처럼 나뉩니다.

- 로컬 CPU/RAM: 브라우저·Next.js·FastAPI·WebSocket·VAD·오디오 버퍼·SQLite·주기 제어
- 외부 API: OpenAI Audio Transcriptions 전사, Responses API의 맥락·생성·평가 호출

즉 브라우저가 마이크를 캡처하고 realtime 서버가 오디오를 정리한 뒤, API 키를
노출하지 않고 OpenAI API를 서버 사이드에서 호출합니다.

### OpenAI API 기본 모드

realtime 서버는 기본적으로 OpenAI API를 사용합니다. 다음 환경변수 중
`OPENAI_API_KEY`는 필수이며, 나머지는 모델을 바꿀 때만 지정하면 됩니다.

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

### 선택 사항: 완전 로컬 모드

API 대신 Ollama와 faster-whisper를 사용하려면 provider를 명시하고 역할별
Qwen 모델을 설치합니다.

```powershell
python -m pip install -e "services/realtime[local]"
$env:LLM_PROVIDER="ollama"
$env:STT_PROVIDER="local"
ollama pull qwen3:1.7b
ollama pull qwen3:4b
ollama pull qwen3:8b
```

### 스모크 테스트

realtime이 떠 있는 상태에서:

```bash
npm run smoke
# web까지 포함하려면
WEB_URL=http://localhost:3000 npm run smoke
# 실제 모델 생성까지 검사 (API 비용 발생)
npm run smoke -- --with-models
```

## Docker Compose

텍스트·녹음 모두 같은 Compose 스택으로 올립니다.

```bash
# services/realtime/.env 에 OPENAI_API_KEY 필요
docker compose up --build
```

- Web: http://localhost:3000  
- Realtime: http://localhost:8765/health  
- 브라우저 WS: `ws://localhost:8765/v1/realtime` (HTTPS 배포 시 `wss://`)

공개 배포에서는 `CORS_ORIGIN`, `NEXT_PUBLIC_REALTIME_WS_URL`(wss),  
`REALTIME_API_KEY`(web·realtime 동일)를 설정하세요. 세부:
[`docs/INFRASTRUCTURE.md`](docs/INFRASTRUCTURE.md)

## 배포 요약

배포 전 [검증 결과와 잔여 운영 확인](docs/PREDEPLOY_REVIEW.md),
[실행 순서와 환경변수](docs/DEPLOYMENT.md)를 확인하세요.
실시간 서버는 현재 **단일 프로세스·단일 복제본**으로 운영해야 합니다.

```bash
npm test
npm run typecheck
npm run build
python -m unittest discover -s services/realtime/tests -v
```

| 모듈 | 권장 호스트 | 환경변수 |
| --- | --- | --- |
| web | Vercel 등 (`apps/web`) | `REALTIME_SERVICE_URL`, `NEXT_PUBLIC_REALTIME_WS_URL`, `REALTIME_API_KEY` |
| realtime | Docker/CPU 호스트 | `OPENAI_API_KEY`, `CORS_ORIGIN`, `REALTIME_API_KEY`, `MAX_AUDIO_SESSIONS` |

**비밀키는 커밋하지 마세요.** `.env`는 gitignore 대상입니다.
