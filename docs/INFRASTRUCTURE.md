# Q-Agent 인프라 · 레포 구조 · 모듈 통신 검증

> 작성일: 2026-09-14  
> 관련: `docs/KICKOFF.md`, `docs/최종_기획안.md`, `README.md`

---

## 1. 레포 구조 (배포 가능 모노레포)

```
Q-agent/
├── apps/
│   └── web/                      # Next.js 프론트 + BFF
│       ├── src/app/              # UI
│       ├── src/app/api/          # /api/extract, /api/diagnose, /api/health
│       ├── vercel.json
│       └── Dockerfile (선택: compose 개발용은 볼륨 마운트)
├── services/
│   ├── extract/                  # Express :4001
│   │   ├── src/index.ts
│   │   └── Dockerfile
│   └── engine/                   # Express :4002
│       ├── src/index.ts
│       └── Dockerfile
├── packages/
│   └── contracts/                # 공유 타입/계약 (진실의 원천 코드)
├── fixtures/                     # 샘플 Transcript/텍스트
├── scripts/
│   └── smoke-test.mjs            # E2E 통신 스모크
├── docker-compose.yml
├── package.json                  # npm workspaces
├── .env.example
├── README.md
└── docs/
    ├── INFRASTRUCTURE.md         # 본 문서
    ├── KICKOFF.md                # 3인 킥오프·역할·계약
    └── 최종_기획안.md             # 통합 기획
```

### 통신 토폴로지

```
Browser
   │  (same-origin only)
   ▼
apps/web  Next.js BFF
   │
   ├── EXTRACT_SERVICE_URL ──► services/extract  POST /v1/extract
   │
   └── ENGINE_SERVICE_URL  ──► services/engine   POST /v1/diagnose
```

- 브라우저는 **서비스 URL을 직접 호출하지 않는다.** (키·내부망 보호)
- 계약 JSON은 `@q-agent/contracts` + `docs/KICKOFF.md` 3절과 동일해야 한다.

---

## 2. 모듈별 골격 현황

| 모듈 | 런타임 | 포트 | 필수 엔드포인트 | 현재 골격 |
| --- | --- | --- | --- | --- |
| **web** | Next.js 15 | 3000 | `/`, `/api/extract`, `/api/diagnose`, `/api/health` | UI + BFF 프록시 |
| **extract** | Express | 4001 | `GET /health`, `POST /v1/extract` | 텍스트 정규화 + 오디오 STT **스텁** |
| **engine** | Express | 4002 | `GET /health`, `POST /v1/diagnose` | 생성+선발 **mock 파이프라인** |
| **contracts** | TS 패키지 | — | 타입 export | v0.1.0 |

> LLM/Whisper 실연동 전에도 **모듈 간 계약 통신이 성립**하도록 mock/stub으로 뼈대를 고정했다.

---

## 3. 로컬 개발

### 3.1 npm (권장, 역할별 터미널)

```bash
cp .env.example .env
npm install          # postinstall 로 contracts 빌드

npm run dev:extract  # :4001
npm run dev:engine   # :4002
npm run dev:web      # :3000
```

`apps/web` 환경변수 (로컬 기본값 내장):

- `EXTRACT_SERVICE_URL=http://localhost:4001`
- `ENGINE_SERVICE_URL=http://localhost:4002`

### 3.2 Docker Compose

```bash
docker compose up --build
```

- extract / engine: 이미지 빌드 후 healthcheck  
- web: 개발 편의상 소스 볼륨 마운트 + `next dev`  
- compose 네트워크 내부 DNS: `http://extract:4001`, `http://engine:4002`

### 3.3 스모크 테스트

```bash
npm run smoke
```

검증 순서:

1. extract `/health`, engine `/health`  
2. extract `/v1/extract` (텍스트 → Transcript)  
3. engine `/v1/diagnose` (Transcript → 선별/반려)  
4. web이 떠 있으면 `/api/health` + BFF 경유 extract→diagnose  

---

## 4. 배포 인프라

### 4.1 권장 배치 (대회 MVP)

| 계층 | 플랫폼 | 이유 |
| --- | --- | --- |
| **web** | **Vercel** | Next.js 최적, 공개 데모 URL 빠름 |
| **extract** | **Railway / Render / Fly.io** | 장시간·파일 업로드·추후 STT에 유리 |
| **engine** | **Railway / Render / Fly.io** | LLM 호출·타임아웃 제어 |

Vercel만으로 API까지 몰아넣는 것도 가능하지만, **역할 분리·STT/LLM 부하**를 위해 서비스 분리를 기본으로 둔다.

### 4.2 Vercel (web)

1. Root Directory: 모노레포 루트 또는 `apps/web`  
2. Install: `npm install`  
3. Build: `npm run build -w @q-agent/contracts && npm run build -w @q-agent/web`  
4. Env:
   - `EXTRACT_SERVICE_URL=https://<extract-host>`
   - `ENGINE_SERVICE_URL=https://<engine-host>`

`apps/web/vercel.json` 참고.

### 4.3 Railway / Render (extract, engine)

각 서비스별:

- Root / Watch: 해당 `services/*`  
- Dockerfile 사용 시: 빌드 context = **모노레포 루트**, dockerfile = `services/extract/Dockerfile` (또는 engine)  
- Env:
  - `PORT` (플랫폼 주입 가능)
  - `CORS_ORIGIN=https://<your-vercel-domain>`
  - (engine 추후) `OPENAI_API_KEY` 등 — **대시보드에만**

### 4.4 네트워크·보안

- 서비스는 가능하면 **공개하되**, 브라우저 CORS는 web origin만 허용 (`CORS_ORIGIN`).  
- API 키는 서비스/ Vercel 서버 환경변수에만.  
- 퍼블릭 리포: `.env` 커밋 금지, fixture는 합성 데이터만 (`KICKOFF` 4.3).

### 4.5 배포 체크리스트

- [ ] extract `/health` 200  
- [ ] engine `/health` 200  
- [ ] web `/api/health` 에서 upstream 둘 다 ok  
- [ ] 텍스트 진단 E2E (랜딩에서 버튼)  
- [ ] 심사 기간(9.21~10.17) 동안 URL 유지  

---

## 5. 모듈 간 통신 계약 (요약)

### extract ← web

`POST /v1/extract`

```json
{ "text": "...", "language": "ko" }
```

→ `{ ok: true, transcript: Transcript }`

### engine ← web

`POST /v1/diagnose`

```json
{
  "transcript": { "...Transcript..." },
  "preset": "decision",
  "tone": 2,
  "options": { "max_questions": 3 }
}
```

→ `{ ok: true, status: "done"|"rejected", questions: [...], ... }`

타입 정의: `packages/contracts/src/index.ts`

---

## 6. 통신 검증 결과

**실측일:** 2026-09-14  
**환경:** Windows / Node 24 / npm workspaces 로컬 (`dev:extract`, `dev:engine`, `dev:web`)  
**명령:** `npm run smoke`

```
=== Q-Agent smoke test PASSED ===
 - OK extract /health
 - OK engine /health
 - OK extract /v1/extract (segments=5)
 - OK engine /v1/diagnose (status=done, n=2)
 - OK web /api/health (BFF → both upstreams)
 - OK web BFF extract→diagnose orchestration path
```

| # | 경로 | 결과 |
| --- | --- | --- |
| 1 | `GET :4001/health` | PASS |
| 2 | `GET :4002/health` | PASS |
| 3 | `POST :4001/v1/extract` | PASS (segments=5) |
| 4 | `POST :4002/v1/diagnose` | PASS (status=done, n=2) |
| 5 | `GET :3000/api/health` | PASS (양쪽 upstream ok) |
| 6 | web BFF extract→diagnose | PASS |

결론: **프론트 BFF ↔ 추출 ↔ 엔진 모듈 간 계약 통신이 확인되었다.**  
(현재 engine은 mock, extract 오디오는 STT stub — 실 LLM/STT 교체 시에도 동일 엔드포인트 유지)

---

## 7. 담당자 작업 연결

| 담당 | 작업 디렉터리 | 로컬 명령 | 배포 |
| --- | --- | --- | --- |
| 프론트 | `apps/web` | `npm run dev:web` | Vercel |
| 추출 AI | `services/extract` | `npm run dev:extract` | Railway/Render |
| 생성+선발 | `services/engine` | `npm run dev:engine` | Railway/Render |
| 공통 | `packages/contracts`, `fixtures` | 변경 시 전원 동기화 | — |

계약 변경 시: **코드보다 `packages/contracts` + fixtures를 먼저** 바꾸고 PR을 분리한다 (`docs/KICKOFF.md` 4.2).

---

## 8. 다음 구현 우선순위 (골격 이후)

1. **engine**: mock → 실제 LLM (generate / filter / EVPI score / tone)  
2. **extract**: 오디오 STT (Whisper 등) — 텍스트 폴백 유지  
3. **web**: 오디오 업로드 UI, 반려/배지 폴리시, 샘플 원클릭  
4. 프로덕션 Dockerfile로 web까지 이미지화 (선택)

---

## 9. 트러블슈팅

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| web `/api/health` 503 | extract/engine 미기동 또는 URL 오타 | 서비스 기동, env 확인 |
| `Cannot find module @q-agent/contracts` | contracts 미빌드 | `npm run build:contracts` |
| CORS 에러 (직접 호출 시) | 브라우저가 서비스 직접 호출 | 반드시 `/api/*` BFF 사용 |
| Docker healthcheck 실패 | 포트/ENV 불일치 | `PORT`와 EXPOSE 일치 확인 |
| Vercel만 배포하고 서비스 없음 | upstream 없음 | extract/engine 먼저 배포 후 URL 주입 |
