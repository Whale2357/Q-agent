# Q-Agent

원티드 AI Championship 2026 — 회의 맥락 판독 & 질문 큐레이션 엔진 모노레포.

## 구조

```
apps/web              Next.js 프론트 + BFF (/api/*)
services/extract      음성/텍스트 → Transcript
services/engine       질문 생성 + 선발
packages/contracts    공유 TypeScript 계약
fixtures/             샘플 회의록
scripts/smoke-test.mjs 모듈 통신 검증
```

협업 규칙: [`docs/KICKOFF.md`](docs/KICKOFF.md)  
최종 기획: [`docs/최종_기획안.md`](docs/최종_기획안.md)  
인프라·통신 검증: [`docs/INFRASTRUCTURE.md`](docs/INFRASTRUCTURE.md)  
MVP2 범위·브랜치 운영 (`develop_2`): [`docs/MVP2.md`](docs/MVP2.md)

## 로컬 실행 (권장)

```bash
cp .env.example .env
npm install

# 터미널 3개
npm run dev:extract
npm run dev:engine
npm run dev:web
```

- Web: http://localhost:3000  
- Extract: http://localhost:4001/health  
- Engine: http://localhost:4002/health  

```bash
npm run smoke
```

## Docker Compose

```bash
docker compose up --build
```

## 배포 요약

| 모듈 | 권장 호스트 | 환경변수 |
| --- | --- | --- |
| web | Vercel (`apps/web`) | `EXTRACT_SERVICE_URL`, `ENGINE_SERVICE_URL` |
| extract | Railway / Render / Fly | `PORT`, `CORS_ORIGIN` |
| engine | Railway / Render / Fly | `PORT`, `CORS_ORIGIN`, (추후 LLM 키) |

**비밀키는 커밋하지 마세요.** `.env`는 gitignore 대상입니다.
