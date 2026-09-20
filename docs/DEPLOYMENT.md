# STEIN 배포 안내

## 배포 구조와 필수 조건

- 웹: Next.js BFF + UI. Vercel 또는 Docker에서 실행.
- realtime: WebSocket을 지원하는 상시 실행 Docker/VM. 기본 OpenAI 모드는 GPU 불필요.
- realtime은 **1 worker / 1 replica**로 운영. 티켓·동시 슬롯·실시간 맥락은 프로세스 메모리에 있어 수평 확장은 아직 지원하지 않음.
- SQLite `REALTIME_DB_PATH`를 영구 볼륨에 마운트. 재배포 전 백업, 접근 권한, 보존 기간을 정할 것.
- 브라우저는 HTTPS 웹과 WSS realtime에 직접 연결하므로 두 주소 모두 외부에서 접근 가능해야 함.

## 1. realtime 배포

빌드 컨텍스트 `services/realtime`, Dockerfile `services/realtime/Dockerfile`.
PyTorch/TorchAudio 없이 경량 Silero VAD 런타임을 설치하며 로컬 Whisper·마이크
패키지는 제외합니다.
Python 3.12 이미지로 실행하고 호스팅 서비스의 `PORT`를 우선 사용합니다.

호스팅 환경변수:

```dotenv
LLM_PROVIDER=openai
STT_PROVIDER=openai
OPENAI_API_KEY=<비밀키>
REALTIME_API_KEY=<암호학적으로 무작위인 32자 이상의 공유 비밀값>
CORS_ORIGIN=https://<실제 웹 도메인>
REALTIME_DB_PATH=/app/data/q-agent.db
MAX_AUDIO_SESSIONS=2
MAX_TEXT_SESSIONS=2
MAX_PENDING_TICKETS=128
SESSION_TTL_SECONDS=120
REALTIME_MAX_SESSION_SECONDS=7200
REALTIME_REQUEST_TIMEOUT_SECONDS=180
```

`CORS_ORIGIN`은 정확한 origin을 쉼표로 구분합니다. 경로·끝 슬래시·와일드카드는 넣지 않습니다.
`/health`의 HTTP 상태뿐 아니라 JSON `ok: true`를 확인합니다. 이 검사는 모델 접근 권한을
확인하지만 실제 추론 품질이나 WSS 연결 성공을 보증하지 않습니다.

## 2. 웹 배포 (Vercel)

1. 프로젝트 Root Directory를 **`apps/web`**으로 설정.
2. 루트 외부 소스 포함 옵션(Include source files outside of the Root Directory)을 활성화.
3. Node.js 22 사용. `apps/web/vercel.json`의 설치·빌드 명령 사용 (`npm ci`, contracts → web 빌드).
4. 출력 디렉터리는 Root Directory 기준 **`.next`**.
5. 다음 변수를 설정한 뒤 빌드:

```dotenv
REALTIME_SERVICE_URL=https://<realtime 도메인>
REALTIME_API_KEY=<realtime과 동일한 공유 비밀값>
NEXT_PUBLIC_REALTIME_WS_URL=wss://<realtime 도메인>/v1/realtime
# 프록시가 Host를 변경하는 구성에서만 실제 웹 origin을 명시
WEB_ALLOWED_ORIGINS=https://<실제 웹 도메인>
```

`OPENAI_API_KEY`는 realtime에만 저장. `REALTIME_API_KEY`도 서버 전용이며
`NEXT_PUBLIC_*`에 비밀값을 넣지 않습니다. 공개 WS URL은 빌드 시 번들에 들어가므로
주소 변경 시 재빌드합니다. 텍스트 함수는 `maxDuration=240`을 요청하므로 호스팅 요금제의
실행 시간 제한도 확인합니다. 웹 호스트에서 WebSocket 서버 자체를 실행하지 않습니다.

모노레포 설정 참고: [Vercel 공식 문서](https://vercel.com/docs/monorepos).
Docker 웹은 [Next.js standalone 출력](https://nextjs.org/docs/app/api-reference/config/next-config-js/output)을
사용하고 non-root 사용자로 실행합니다.

## 3. Docker Compose를 사용하는 경우

`services/realtime/.env`에는 제공자/API 설정, 저장소 루트 `.env`에는 Compose 공유 설정을 둡니다.
**Compose `environment`가 서비스 `.env`보다 우선**하므로 `REALTIME_API_KEY`, `CORS_ORIGIN`,
세션 제한과 공개 WS URL은 루트 `.env`에 설정해야 두 컨테이너에 동일하게 전달됩니다.
이미 있는 환경 파일을 예제 파일로 덮어쓰지 마세요.

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

웹 BFF → realtime은 내부 Docker 주소 `http://realtime:8765`를 사용해도 됩니다.
외부 HTTPS/WSS는 별도 리버스 프록시/TLS 설정이 필요합니다. 프록시는 WebSocket Upgrade,
180초 이상의 종료 분석 대기, 2시간 녹음과 무음 PCM 전송을 허용해야 합니다.
`./data`가 DB 영구 볼륨이며 백업은 SQLite 온라인 백업 또는 서버 정지 후 전체 DB 파일로 수행합니다.

## 4. 배포 전후 검증

Node.js 22.18 이상, Python 3.11/3.12에서 저장소 루트 기준:

```bash
npm ci
npm test
npm run typecheck
npm run build
npm audit --omit=dev --audit-level=high
python -m pip check
python -m unittest discover -s services/realtime/tests -v
```

환경변수를 호스팅 설정과 동일하게 주입한 셸에서 `npm run check:deploy -- web` 또는
`npm run check:deploy -- realtime`을 실행합니다. 모두 주입했다면 `npm run check:deploy`.
이 명령은 환경 파일을 자동 로드하지 않으며 비밀값은 출력하지 않습니다. public split-host 구성의
HTTPS를 검사하므로 Compose 내부 HTTP 주소는 웹 검사 대신 TLS 프록시/실제 연결로 검증합니다.
영구 볼륨 존재나 DNS 연결까지 검사하는 도구는 아닙니다.

```bash
# REALTIME_SERVICE_URL, REALTIME_API_KEY, WEB_URL을 환경변수로 주입
npm run smoke
# 실제 모델 호출까지: 공급자 과금 발생. 승인된 키/계정에서 실행
npm run smoke -- --with-models
```

기본 smoke는 health와 티켓만 검사합니다. 토큰을 출력하지 않으며 티켓은 TTL 후 만료됩니다.
마지막으로 실제 HTTPS 브라우저에서 텍스트 → 질문 → 기록, 마이크 권한 → 녹음 → 질문 → 종료,
네트워크 단절 → 부분 기록, 새로고침 → 기록 복구를 확인하세요.

## 운영 한계와 보호 설정

- 로그인 없는 공개 앱입니다. 공유 API 키는 BFF↔realtime 인증이지 사용자 인증이 아닙니다.
  공개 전 WAF/게이트웨이의 IP별 속도 제한, 공급자 예산·알림, 필요 시 호스팅 접근 제한을 설정합니다.
- BFF의 텍스트 6회/분·티켓 12회/분 제한은 프로세스 메모리의 보조 방어이며, 여러 인스턴스에 걸친
  전역 제한이 아닙니다. 프록시가 전달 IP 헤더를 검증/덮어써야 합니다.
- 재연결 시 서버 세션을 복구하는 기능은 없습니다. 현재 기록을 저장하고 새 분석을 시작합니다.
- UI 제한: 텍스트 100,000자/512KiB, 오디오 50MiB/30분, 실시간 녹음 기본 2시간.
  길이가 허용 범위 안이어도 모델 지연·브라우저 메모리 상황에 따라 실패할 수 있습니다.
- 브라우저에 최근 30개 기록과 녹음을 보관합니다. 서버에는 분석용 전사·맥락·질문이 SQLite에 남으며,
  브라우저 기록 삭제는 서버 DB 삭제가 아닙니다. 운영자의 별도 데이터 보존·삭제 정책이 필요합니다.
- Python 의존성은 현재 호환 버전 범위를 사용합니다. 동일 소스의 미래 빌드는 달라질 수 있으므로
  CI 통과 이미지를 고정 태그/이미지 digest로 배포하고 재빌드 때 테스트합니다.
- CI는 두 Docker 이미지 빌드까지 검사하도록 추가했습니다. 현재 로컬 PC에는 Docker가 없어
  컨테이너 빌드·실행 검증은 CI 또는 Docker가 있는 환경에서 통과시켜야 합니다.
