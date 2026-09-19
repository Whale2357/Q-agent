# Q-Agent 인프라 · 레포 구조 · 통신 검증

> 업데이트: 2026-09-19 — **web → realtime** 단일 경로. 실제 배포 순서와
> 운영 제한은 [DEPLOYMENT.md](DEPLOYMENT.md), 검증 결과는
> [PREDEPLOY_REVIEW.md](PREDEPLOY_REVIEW.md)를 우선 참고하세요.

---

## 1. 레포 구조

```
Q-agent/
├── apps/web/                 # Next.js UI + BFF
│   ├── Dockerfile
│   └── src/app/api/          # /api/health, /api/realtime/{text,session}
├── services/realtime/        # FastAPI :8765
│   └── Dockerfile
├── packages/contracts/
├── docker-compose.yml        # web + realtime 이미지
├── scripts/smoke-test.mjs
└── docs/
```

### 통신 토폴로지

```
Browser
   ├── WebSocket + session_token ──► realtime WS /v1/realtime
   └── same-origin fetch
          ▼
       apps/web BFF
          ├── GET  /api/health
          ├── POST /api/realtime/session  → POST /v1/session
          └── POST /api/realtime/text     → POST /v1/text
                 (Authorization: Bearer REALTIME_API_KEY when set)
```

---

## 2. Docker (텍스트 + 녹음)

```bash
# services/realtime/.env 에 OPENAI_API_KEY 설정 후
docker compose up --build
```

| 서비스 | 이미지 | 포트 | 역할 |
| --- | --- | --- | --- |
| realtime | `services/realtime/Dockerfile` | 8765 | HTTP 텍스트 + WSS 녹음 |
| web | `apps/web/Dockerfile` | 3000 | UI + BFF |

브라우저 WS는 호스트로 나가므로 Compose 기본값은:

- `NEXT_PUBLIC_REALTIME_WS_URL=ws://localhost:8765/v1/realtime`
- BFF는 `REALTIME_SERVICE_URL=http://realtime:8765`

프로덕션(HTTPS)에서는:

```dotenv
CORS_ORIGIN=https://your-app.vercel.app
REALTIME_SERVICE_URL=https://realtime.example.com
NEXT_PUBLIC_REALTIME_WS_URL=wss://realtime.example.com/v1/realtime
REALTIME_API_KEY=long-random-secret
```

`REALTIME_API_KEY`는 web·realtime에 **같은 값**을 넣습니다. 비우면 로컬 오픈 모드(HTTP 인증 없음). WS는 항상 `/v1/session` 티켓이 필요합니다.

---

## 3. 세션·남용 방어 (3-B)

| 장치 | 동작 |
| --- | --- |
| `REALTIME_API_KEY` | `/v1/text`, `/v1/session` Bearer 필수(설정 시) |
| `POST /v1/session` | 단회용 `session_token` 발급 (TTL `SESSION_TTL_SECONDS`) |
| WS `start.session_token` | 티켓 소비 후 오디오 슬롯 획득 |
| `MAX_AUDIO_SESSIONS` | 동시 녹음 상한(기본 2). 초과 시 503 / WS error |
| `MAX_TEXT_SESSIONS` | 동시 텍스트 분석 상한(기본 2) |
| `MAX_PENDING_TICKETS` | 미사용 티켓 최대 128개 |
| `REALTIME_MAX_SESSION_SECONDS` | 최대 녹음 세션 시간(기본 7200초) |
| `REALTIME_REQUEST_TIMEOUT_SECONDS` | 분석/종료 제한 시간(기본 180초) |

현재 티켓·슬롯은 서버 메모리에 있으므로 **1 worker / 1 replica**가 필수입니다.

---

## 4. 로컬(비 Docker)

```powershell
q-agent-realtime-server --host 127.0.0.1 --port 8765
npm run dev:web
```

또는 `apps/web/start-local.cmd`.

```bash
npm run smoke
WEB_URL=http://localhost:3000 npm run smoke
```

---

## 5. 배포 체크리스트

- [ ] realtime 이미지 배포 + `/health` JSON `ok: true` 확인 (HTTP 200만으로 판단 금지)
- [ ] `CORS_ORIGIN` = 실제 web origin
- [ ] Vercel `REALTIME_SERVICE_URL` + `NEXT_PUBLIC_REALTIME_WS_URL`(wss) + `REALTIME_API_KEY`
- [ ] 텍스트 E2E: `/api/realtime/text`
- [ ] 녹음 E2E: session → WSS `start` → `final_question`

---

## 6. 문서 상태

| 문서 | 상태 |
| --- | --- |
| README / INFRASTRUCTURE | **현행** |
| KICKOFF / MVP2 | 역사 기록 — extract/engine 경로는 폐기됨 |
| contracts `0.2.0` | Diagnosis + RealtimeSession (Extract API 타입 제거) |
