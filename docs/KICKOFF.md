# Q-Agent Kickoff — 3인 협업 / 1차 MVP

> **기준 문서:** `docs/최종_기획안.md`  
> **인프라:** `docs/INFRASTRUCTURE.md`  
> **대회:** 원티드 AI Championship 2026  
> **하드 데드라인:** 접수 09.18(금) / 제출 09.20(일) 23:59 (배포 URL 필수)  
> **팀 구성:** 프론트 · 추출 AI · 생성+선발 (질문 엔진)

이 문서는 **구현 시작 전 합의서**다.  
각자 **자기 모듈 + 아래 공통 계약**만 지키면, 병렬로 개발해도 마지막에 붙는다.

---

## 0. 한 줄 합의

```
[입력: 텍스트 | 오디오]
        ↓
[추출 AI]  →  Transcript (정규화 텍스트)
        ↓
[생성 AI]  →  CandidateQuestions[]
        ↓
[선발 엔진] →  CuratedQuestions[] | Reject
        ↓
[프론트]   →  배지·톤·반려 UI로 시연
```

**제품 메시지:** 질문을 많이 만드는 AI가 아니라, **걸러서 건네는 AI**.

---

## 1. 1차 MVP 목표 (Definition of Done)

### 1.1 성공 기준 (이 5개가 되면 제출 가능)

1. **배포된 웹 URL**로 심사위원이 회원가입 없이 데모할 수 있다.  
2. **텍스트 붙여넣기**만으로도 end-to-end가 동작한다. (STT 장애 시에도 데모 가능)  
3. **오디오 파일 업로드 → STT → 동일 파이프라인**이 동작한다. (폴백: 텍스트)  
4. 질문 엔진이 **후보 생성 → 필터/채점 → 선별 또는 의도적 반려**를 수행한다.  
5. 결과에 **채점 근거 배지**와 **톤(정중함) 변환**이 보인다.

### 1.2 데모 시나리오 (필수 2개)

| ID | 프리셋 | 보여줄 것 |
| --- | --- | --- |
| `decision` | 의사결정 | A/B 교착 → 기준/trade-off/반증 질문 선별 |
| `problem` | 문제해결 | 증상=원인 고착 → 가정/리프레이밍 질문 선별 |

각 시나리오용 **샘플 텍스트 회의록** + (가능하면) **샘플 오디오**를 `fixtures/`에 둔다.

### 1.3 1차 MVP에 넣지 않는 것 (명시적 Out of Scope)

- 실시간 마이크 스트리밍 개입, Zoom/Slack 플러그인  
- 정교한 화자 분리(diarization), Vision/화이트보드  
- 계정/결제, DB 기반 히스토리(선택), 온디바이스 모델  
- 회의 목적 7종 전부, 자동 타이밍 개입

> Out of Scope는 실패가 아니라 **품질을 위한 의도적 절단**이다. 랜딩/제출 문구에도 그대로 쓴다.

### 1.4 일정 마일스톤 (3인)

| Day | 날짜 | 팀 공통 목표 |
| --- | --- | --- |
| D0 | 09.14 | Kickoff 확정, 계약 파일 merge, 레포/브랜치 세팅 |
| D1 | 09.15 | 모듈별 Mock으로 계약 검증 (프론트↔가짜 JSON) |
| D2 | 09.16 | 텍스트 E2E 실제 LLM 연동 |
| D3 | 09.17 | 오디오 STT 경로 + UX 폴리시 |
| D4 | 09.18 | **참가 접수** + 배포 1차 URL |
| D5 | 09.19 | 시나리오 A/B 안정화, 반려/중복 데모 |
| D6 | 09.20 | 제출 문구 + 최종 제출 |

---

## 2. 역할별 지시서

공통 규칙: **자기 모듈 폴더 밖을 함부로 수정하지 않는다.**  
계약(`contracts/`) 변경은 PR + 전원 확인 후에만.

권장 디렉터리 (모노레포):

```
/
├── apps/web/                 # 프론트
├── services/extract/         # 추출 AI
├── services/engine/          # 생성 + 선발
├── packages/contracts/       # API/JSON 타입 계약
├── fixtures/                 # 샘플 회의록·오디오
├── docs/
│   ├── KICKOFF.md
│   ├── 최종_기획안.md
│   └── INFRASTRUCTURE.md
└── README.md
```

---

### 2.1 프론트 (Frontend)

**미션:** 사용자가 60초 안에 “추출 → 생성 → 선발 → 결과”를 이해하게 만든다.

#### 필수 구현 (Must) — `최종_기획안` §5.1 + UX §7

- [ ] 랜딩 1화면: 문제 / 차별점(Evaluation·의도적 반려) / CTA  
- [ ] 메신저·회의록 스크립트형 워크스페이스 UI (단순 폼이 아닌 대화 맥락 연출)  
  - 텍스트 붙여넣기  
  - 오디오 업로드 (진행 상태 표시) + STT 실패 시 텍스트 폴백 안내  
  - 프리셋 선택: `decision` | `problem`  
  - 톤 다이얼: `1|2|3|4` (직설→우회), 기본값 2~3  
  - **진단하기** 버튼 (수동 트리거)  
- [ ] 파이프라인 상태 표시: `extracting → generating → selecting → done|rejected`  
- [ ] 결과 카드 (최대 3개 / 카테고리 맹점·본질·확장): 질문 + 근거 배지 + rationale  
- [ ] **의도적 반려** 화면 (빈 결과가 버그가 아님을 카피로 명시)  
- [ ] 샘플 시나리오 원클릭 로드 (`fixtures` A/B) + 반려 데모용 샘플  
- [ ] 배포 (Vercel 등) + 환경변수는 서버/빌드에만  
- [ ] 제출/랜딩용 카피: 문제·AI 활용·스택 / Out of Scope·로드맵 한 줄

#### 부가 구현 (Nice — 제출 전 시간 되면, `최종_기획안` §5.2)

- [ ] 분석 애니메이션 (“파싱→후보→채점→선별”)  
- [ ] 질문 복사 / “이 톤으로 다시 쓰기”  
- [ ] 도움됨/안됨 피드백 버튼 (투표 기간 스토리)  
- [ ] 모바일 레이아웃 폴리시  
- [ ] 카테고리 탭/섹션 UI (맹점·본질·확장 구분 표시)  
- [ ] Before/After 데모 토글 (뻔한 질문 vs 선별 질문)  
- [ ] QDM 전제 방향 UI (부정/중립/긍정) — 엔진 Nice와 계약 맞춤 후  
- [ ] 파이프라인 통계 노출 (`candidates_generated` 등)

#### 확장 부가 (Post-MVP / 본선·로드맵 P1 — `최종_기획안` §9)

- [ ] 자동 개입 타이밍 UI (중단점: 화자 전환·침묵 후 카드 큐)  
- [ ] 히든 프로파일 알림 UI (“오래 말 안 한 화자/미언급 영역”)  
- [ ] 회의 목적 프리셋 확장 카드 (진행점검·아이디어·전략·회고·합의 — 비활성+로드맵 표기 OK)  
- [ ] Slack/Zoom 연동 안내 페이지(실연동 전 목업)  
- [ ] 심리 안전 가이드 카피 (위협 질문 최소화 안내)

#### 하지 말 것

- LLM 프롬프트·채점 로직을 프론트에 두지 말 것  
- API 키를 클라이언트에 노출하지 말 것  
- 계약 외 필드에 의존하는 UI 작성 금지 (없으면 mock으로)  
- Vision/화이트보드 UI, 계정·결제 (Out of Scope)

#### Done 기준

텍스트만으로 A/B 시나리오 데모 가능 + 반려 상태 시연 가능 + 공개 URL 접속 가능.

---

### 2.2 추출 AI (Extract)

**미션:** 어떤 입력이든 엔진이 먹을 수 있는 **정규화 Transcript**로 만든다.  
STT는 가산점, **텍스트 패스스루는 생존 라인**.

#### 필수 구현 (Must)

- [ ] `POST /v1/extract`  
  - `text`만 오면: 정규화만 수행 (공백/화자 라벨 粗 파싱)  
  - `audio`면: **실제 STT** 후 동일 스키마로 반환 (stub 제거 목표)  
- [ ] 출력은 반드시 `Transcript` 계약 준수  
- [ ] 실패 시 표준 에러 (`ErrorResponse`) — 프론트가 텍스트 폴백 안내 가능  
- [ ] `fixtures/` 샘플 오디오 1개 이상 전사 성공  
- [ ] 언어: 한국어 우선 (`ko`)  
- [ ] 텍스트 경로와 오디오 경로가 **동일 Transcript 스키마**로 합류

#### 부가 구현 (Nice — 제출 전 시간 되면)

- [ ] 粗 화자 라벨 (`Speaker 1` / `A:` 파싱 고도화) — 정확 diarization 아님  
- [ ] segment 단위 timestamp  
- [ ] 잡음/짧은 무음 정리  
- [ ] 전사 confidence / `meta.warning` 상세화  
- [ ] 장문 로그 청크 분할 후 병합  
- [ ] 샘플 오디오 fixture 추가 (`decision`/`problem`)

#### 확장 부가 (Post-MVP / 본선·로드맵 P1~P2)

- [ ] 화자 분리(diarization) — 히든 프로파일 입력용  
- [ ] 발언 지분·미발언 화자 요약 메타 (`speaker_stats`)  
- [ ] 중단점 휴리스틱 신호 (화자 전환, 침묵 구간) — 타이밍 UI용  
- [ ] 실시간/스트리밍 STT (사이드패널용)  
- [ ] Vision 입력(화이트보드/PPT OCR) 별도 엔드포인트 초안

#### 하지 말 것

- 질문 생성/채점 로직 넣지 말 것  
- 실시간 WebSocket STT를 Must로 올리지 말 것 (확장 부가)  
- 원본 오디오를 git에 대용량 커밋하지 말 것 (`fixtures`는 짧은 샘플만)

#### Done 기준

텍스트·오디오 모두 `Transcript` JSON으로 안정 반환. 엔진/프론트는 extract 내부를 몰라도 된다.

---

### 2.3 생성 + 선발 (Question Engine)

**미션:** Q-Agent의 심장. **생성은 풍부하게, 출력은 엄격하게.**

내부는 두 스테이지로 나누되, **대외 API는 하나**여도 된다.

```
Transcript + options
   → generate candidates (PREG + operators)
   → filter (INQUISITIVE)
   → score (EVPI: 가상답변 → 행동변화)
   → depth adjust (Graesser)
   → tone rewrite (Politeness 4)
   → CuratedResult | Reject
```

#### 필수 구현 (Must) — `최종_기획안` §3~4 파이프라인

- [ ] `POST /v1/diagnose` (생성+선발 통합 OK)  
- [ ] 후보 생성: **PREG 6트리거** + operator 5종  
  (`assumption_challenge` | `reframing` | `criterion_clarification` | `counterfactual` | `constraint_relaxation`)  
- [ ] 가정 노출은 **생성기(PREG 모순·불일치)** 에서 처리 (독립 스코어 축 아님)  
- [ ] 필터: INQUISITIVE 3게이트 (완결성 / 관련성 / 최근 N턴 비중복)  
- [ ] 채점: **가상 답변 생성 후** “다음 행동·결론 변화” (EVPI; norm 단일 고정)  
- [ ] 깊이 보정: 얕은 확인·정의형 감점 또는 재작성 (Graesser)  
- [ ] 톤 단계 `1~4` (Brown & Levinson) 최종 문장 변환, 기본 안전 톤 우선  
- [ ] 카테고리(맹점/본질/확장)별 임계값 통과분 선별, 총 ≤3  
- [ ] 임계값 미달 시 `status: "rejected"` + reason  
- [ ] 각 질문에 `badges` + `rationale` (+ hypothetical summary)  
- [ ] 프리셋 `decision` | `problem` 분기 (이론: Inquiry/Controversy vs Double-loop/Reframing)  
- [ ] 가드레일: 인신공격·유도질문(Loftus)·닫힌 추궁형·사람 공격 금지

#### 부가 구현 (Nice — 제출 전 시간 되면, 질문이론·기획 반영)

- [ ] 생성/선발 API 물리 분리 (`/v1/generate`, `/v1/select`) — 데모 시각화  
- [ ] QDM 전제 방향 변주 (부정/중립/긍정) — 톤 다이얼 2축  
- [ ] Toulmin warrant 갭 탐지 (주장만 있고 논거 비어 있는 구간 → 가정 질문)  
- [ ] 중간 단계 디버그 페이로드 (`debug: true`일 때만)  
- [ ] 프롬프트 버전 필드 (`prompt_version`)  
- [ ] 반려/중복 회귀용 골든 fixture 세트  
- [ ] 카테고리별 “최우수 1개” 엄격 모드

#### 확장 부가 (Post-MVP / 본선·로드맵 P1~P2)

- [ ] 히든 프로파일 질문 (“미발언 화자·미공유 정보 영역”) — extract `speaker_stats` 연동  
- [ ] 자동 타이밍용 질문 큐 API (지금 띄울지 / 대기)  
- [ ] 회의 목적 프리셋 5종 추가 (진행점검·아이디어·전략·회고·합의정렬)  
- [ ] GROW / Why-WhatIf-How / Pre-mortem 강화 템플릿 (프리셋 옵션)  
- [ ] QUD 스택 기반 비중복 (v2)  
- [ ] Slack/Zoom 컨텍스트 어댑터

#### 하지 말 것

- 임계값 없이 항상 3개 출력 (반려를 죽여서는 안 됨)  
- 프론트에서 재채점하게 만들기  
- norm을 여러 개로 늘리기 (고정: **결정/다음 액션이 바뀌는가**)  
- 계정/결제/온디바이스 sLLM을 Must에 넣지 말 것

#### Done 기준

같은 입력에 대해 (1) 뻔한 중복은 걸러지고 (2) 가치 있는 질문만 남거나 (3) 없으면 반려가 나온다.

---

## 3. 공통 계약 (Contract-First)

### 3.1 원칙

1. **`contracts/`가 진실의 원천**이다. 코드보다 문서가 우선한다.  
2. 필드 추가 = minor. 필드 삭제/의미 변경 = **전원 합의 후** major.  
3. D1까지는 **Mock JSON**으로 프론트가 먼저 완성한다.  
4. 모듈은 상대 구현을 기다리지 말고, 계약 예제로 개발한다.

### 3.2 엔드포인트 (1차)

| Method | Path | Owner | 설명 |
| --- | --- | --- | --- |
| `POST` | `/v1/extract` | 추출 | 텍스트/오디오 → Transcript |
| `POST` | `/v1/diagnose` | 엔진 | Transcript + options → 선별 결과 |
| `GET` | `/health` | 각자 | 배포 생존 확인 |

> 모노레포에서 BFF(Next Route Handler)가 두 서비스를 감싸도 된다.  
> 그 경우에도 **요청/응답 JSON 모양은 아래와 동일**해야 한다.

### 3.3 Enums

```ts
type MeetingPreset = "decision" | "problem";
type ToneLevel = 1 | 2 | 3 | 4; // 1=직설 … 4=우회
type PipelineStatus = "extracting" | "generating" | "selecting" | "done" | "rejected" | "error";
type QuestionCategory = "blind_spot" | "essence" | "expansion";
type BadgeCode = "info_gain" | "non_redundant" | "relevant" | "depth" | "assumption";
type OperatorCode =
  | "assumption_challenge"
  | "reframing"
  | "criterion_clarification"
  | "counterfactual"
  | "constraint_relaxation";
```

### 3.4 Shared types

```json
{
  "Transcript": {
    "transcript_id": "tr_xxx",
    "language": "ko",
    "source": "text | audio",
    "text": "전체 평문 (엔진 최소 입력)",
    "segments": [
      {
        "speaker": "A",
        "text": "나는 A안이 맞다고 봐.",
        "start_ms": 0,
        "end_ms": 3200
      }
    ],
    "meta": {
      "duration_ms": 120000,
      "warning": null
    }
  }
}
```

```json
{
  "DiagnoseRequest": {
    "transcript": { "$ref": "Transcript" },
    "preset": "decision",
    "tone": 2,
    "options": {
      "max_questions": 3,
      "recent_turn_window": 12,
      "debug": false
    }
  }
}
```

```json
{
  "CandidateQuestion": {
    "id": "cand_1",
    "text": "후보 질문 원문",
    "operator": "criterion_clarification",
    "preg_trigger": "contradiction",
    "category": "essence"
  }
}
```

```json
{
  "ScoredQuestion": {
    "id": "cand_1",
    "text": "톤 반영된 최종 질문",
    "category": "essence",
    "operator": "criterion_clarification",
    "scores": {
      "info_gain": 0.82,
      "non_redundant": 0.9,
      "relevant": 0.88,
      "depth": 0.7,
      "final": 0.84
    },
    "badges": ["info_gain", "non_redundant", "relevant"],
    "rationale": "가상 답변에 따라 선택 기준이 A비용 vs B속도에서 달라짐",
    "hypothetical_answer_summary": "기준이 명확해지면 B로 기울 수 있음"
  }
}
```

### 3.5 API Request / Response

#### `POST /v1/extract`

**Request (multipart 또는 JSON 중 하나)**

```json
{
  "text": "선택. 텍스트가 있으면 STT 생략",
  "language": "ko"
}
```

- 오디오: `multipart/form-data` 필드 `file` + 선택 `language`  
- 텍스트와 파일 둘 다 없으면 `400`

**Response 200**

```json
{
  "ok": true,
  "transcript": {
    "transcript_id": "tr_demo_001",
    "language": "ko",
    "source": "audio",
    "text": "...",
    "segments": [],
    "meta": { "duration_ms": 90000, "warning": null }
  }
}
```

#### `POST /v1/diagnose`

**Request:** `DiagnoseRequest`  
**Response 200 — 선별 성공**

```json
{
  "ok": true,
  "status": "done",
  "preset": "decision",
  "tone": 2,
  "questions": [
    {
      "id": "cand_1",
      "text": "지금 A와 B를 가르는 기준이 비용인가요, 속도인가요?",
      "category": "essence",
      "operator": "criterion_clarification",
      "scores": {
        "info_gain": 0.82,
        "non_redundant": 0.9,
        "relevant": 0.88,
        "depth": 0.7,
        "final": 0.84
      },
      "badges": ["info_gain", "non_redundant", "relevant"],
      "rationale": "기준이 정해지면 다음 결정이 달라진다",
      "hypothetical_answer_summary": "비용이면 A, 속도면 B"
    }
  ],
  "rejected": false,
  "pipeline": {
    "candidates_generated": 8,
    "candidates_after_filter": 3,
    "selected": 1
  }
}
```

**Response 200 — 의도적 반려**

```json
{
  "ok": true,
  "status": "rejected",
  "preset": "problem",
  "tone": 3,
  "questions": [],
  "rejected": true,
  "reject_reason": "현재 맥락에서 임계값을 넘는 유효 질문이 없습니다",
  "pipeline": {
    "candidates_generated": 5,
    "candidates_after_filter": 1,
    "selected": 0
  }
}
```

#### 에러 공통

```json
{
  "ok": false,
  "error": {
    "code": "EXTRACT_FAILED | INVALID_INPUT | LLM_TIMEOUT | INTERNAL",
    "message": "사람이 읽을 수 있는 메시지",
    "retryable": true
  }
}
```

### 3.6 프론트 오케스트레이션 (권장)

```
1) (audio?) POST /v1/extract → transcript
2) POST /v1/diagnose { transcript, preset, tone }
3) status===rejected → 반려 UI
   else → 질문 카드 렌더
```

텍스트만 있을 때도 **반드시 extract를 거치거나**, 프론트가 Transcript 객체로 래핑해 diagnose에 넣는다.  
(팀 합의: **항상 extract 경유**를 기본으로 하면 경로가 하나라 디버깅이 쉽다.)

### 3.7 Fixture 계약

`fixtures/` 최소 세트:

| 파일 | 설명 |
| --- | --- |
| `decision.transcript.json` | 의사결정 교착 샘플 |
| `problem.transcript.json` | 문제정의 고착 샘플 |
| `decision.diagnose.response.json` | 성공 응답 예제 |
| `reject.diagnose.response.json` | 반려 응답 예제 |
| `decision.sample.txt` | 원문 텍스트 |
| `decision.sample.mp3` | (선택) 30~90초 짧은 오디오 |

Mock 개발은 이 JSON만으로 진행한다.

---

## 4. 공통 개발 원칙

### 4.1 브랜치 운영

| 브랜치 | 용도 |
| --- | --- |
| `main` | 배포 가능 상태만. 직접 push 금지(가능하면) |
| `develop` | 통합 브랜치 |
| `feat/front-*` | 프론트 |
| `feat/extract-*` | 추출 |
| `feat/engine-*` | 생성+선발 |
| `chore/contracts-*` | 계약 변경 전용 |

규칙:

1. **작은 PR, 하루 1회 이상 develop에 병합**을 목표로 한다.  
2. `main` ← `develop` 은 배포 직전(D4, D6)에만.  
3. 계약 변경 PR은 **구현 PR과 분리**한다.  
4. 머지 전: 자기 모듈 `/health` + fixture 기반 스모크.

### 4.2 계약 우선 (Contract-First)

1. 코드 작성 전 `contracts/` + `fixtures/`를 먼저 읽는다.  
2. 응답에 필드를 몰래 추가해 프론트를 깨지 말 것. 필요하면 contracts PR.  
3. 통합 전 **스키마 예제 diff**로 리뷰한다.  
4. Breaking change가 필요하면 슬랙/채팅에 `#contract`로 알리고 동기화 포인트를 잡는다.

### 4.3 퍼블릭 리포 주의사항

대회/협업 중 리포가 public이 될 수 있다고 가정한다.

**절대 커밋 금지**

- `.env`, `.env.*`, API 키, 토큰, 개인 액세스 키  
- 실제 회사 회의록, 실명·연락처·내부 기밀이 섞인 로그  
- 고객/면접 등 민감 오디오 원본

**필수 조치**

- `.gitignore`에 `.env*`, `*.pem`, `node_modules`, `.next`, 대용량 미디어 패턴  
- 키는 Vercel/호스트 **Environment Variables**만 사용  
- fixture는 **합성(synthetic) 데이터**만  
- README에 “샘플 데이터는 가명/가상” 명시  
- 실수로 키를 푸시했으면 **즉시 키 로테이션** (커밋 삭제만으로 부족)

### 4.4 생성물·산출물 커밋 금지

Git에 넣지 말 것:

| 유형 | 예시 |
| --- | --- |
| 빌드 산출물 | `dist/`, `build/`, `.next/`, `coverage/` |
| 의존성 | `node_modules/`, `.venv/`, `__pycache__/` |
| 모델/캐시 | 로컬 모델 가중치, STT 임시 wav, LLM 캐시 |
| IDE/OS | `.DS_Store`, `.idea/`, `.vscode/`(팀 합의된 공유 설정만 예외) |
| 로그/덤프 | `*.log`, 장문 LLM raw dump (필요 시 `fixtures`에 **익명화된 짧은 예제만**) |

프롬프트 템플릿 소스코드는 커밋 OK.  
**실행 중 만들어진 응답 덤프 전체**는 커밋 금지.

### 4.5 코딩/협업 위생

- 커밋 메시지: `feat(front): ...` / `fix(engine): ...` / `chore(contracts): ...`  
- 한 PR = 한 목적  
- `main` 깨면 최우선으로 핫픽스  
- 외부 API 호출은 서버사이드만  
- README에 로컬 실행 3줄 이상 적을 것 (`pnpm i`, `pnpm dev`, env 예시)

### 4.6 의사결정 에스컬레이션

| 상황 | 처리 |
| --- | --- |
| UI 카피/레이아웃 | 프론트 재량 |
| STT 품질 vs 속도 | 추출 재량 (단, 텍스트 폴백 유지) |
| 채점 임계값/프롬프트 | 엔진 재량 (단, 반려 경로 유지) |
| 계약 변경 | **전원 합의** |
| 범위 추가 유혹 | Kickoff Out of Scope 우선. D5 이후에만 Nice 논의 |

---

## 5. Day-0 체크리스트 (오늘 끝내기)

### 전원

- [ ] 이 Kickoff 읽고 역할 확인  
- [ ] 레포 초대 / `develop` 생성  
- [ ] `.gitignore` / `.env.example` 작성  
- [ ] `contracts/` 초안 merge (이 문서 3절 기준)  
- [ ] `fixtures/` 샘플 텍스트 2종 확정

### 프론트

- [ ] 앱 스케폴딩 + 배포 파이프 초안  
- [ ] Mock diagnose 응답으로 UI 골격

### 추출

- [ ] `/v1/extract` 스켈레톤 + 텍스트 패스스루  
- [ ] STT 프로바이더 1개 선정·키 발급(로컬만)

### 엔진

- [ ] `/v1/diagnose` 스켈레톤 + fixture 기반 mock 선별/반려  
- [ ] 프롬프트 초안 (generate / score / tone) 분리

### 팀장/공통

- [ ] 09.18 접수 담당자 지정  
- [ ] 09.20 제출 문구 초안 담당 지정  
- [ ] 공유 노션/채팅에 **계약 변경 공지 채널** 만들기

---

## 6. 제출용 한 줄 (초안)

> Q-Agent는 회의 음성·텍스트를 정규화한 뒤, 질문을 생성만 하지 않고 EVPI·비중복 기준으로 선별·반려하는 인지 증강 엔진입니다.

---

## 7. 서명 (킥오프 확인)

| 역할 | 이름 | 확인 |
| --- | --- | --- |
| 프론트 |  | [ ] |
| 추출 AI |  | [ ] |
| 생성+선발 |  | [ ] |

**확정일:** 2026-09-14  
**변경 규칙:** 이 문서의 Must/Out of Scope/계약을 바꾸려면 전원 합의 후 버전을 올린다 (`docs/KICKOFF.md` v1.1).
