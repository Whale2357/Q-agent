# Q-Agent realtime service

LangGraph 없이 순수 Python으로 동작하며, 로컬 모델과 OpenAI API를 같은
회의 파이프라인에서 선택할 수 있습니다.

```text
브라우저 마이크 -> VAD/버퍼 -> STT -> SQLite 원문
      -> Context(5초) -> Question Context State
      -> Generator(맥락 버전↑ + 최소 25초) -> 후보 저장
      -> Hybrid Evaluator(규칙 필터 + LLM 소프트 점수) -> 활성 풀 ≤3
      -> 침묵 20초 또는 사용자 ask -> 최종 질문 1문장 표시
```

공개 배포에서는 프런트 계약을 바꾸지 않고 제공자만 교체합니다.

```text
브라우저 마이크 -> Silero VAD -> OpenAI STT -> SQLite
              -> Question Context State -> OpenAI LLM
              -> 하이브리드 평가/선발 -> 침묵·요청 시 브라우저에 1문장
```

현재 웹은 이 서비스의 HTTP/WebSocket만 사용합니다. 후보 필드는
`category`와 `operator` 방향에 맞춰져 있습니다.

## 현재 책임

- CPU/Python: 오디오 수신, VAD, 버퍼, transcript·상태 저장, 이벤트 기반 주기 제어
- GPU/faster-whisper: 확정된 발화의 음성 인식
- Qwen Context Agent: transcript dirty 시(debounce) Question Context State 병합
- Qwen Generator: Context 갱신 신호 + 최소 25초 간격으로 후보 5개 생성·저장
- Hybrid Evaluator: 규칙(길이·의문형·근거·중복·금칙) + LLM(정보이득·가정·stale)
- 최종 노출: 서버 침묵 20초 또는 WebSocket `ask` / 녹음 종료 시 1문장
- Stop 최적화: 활성 풀이 있으면 즉시 노출(불필요한 3단 LLM 생략)
- 세션 게이트: `POST /v1/session` 단회 토큰 + `MAX_AUDIO_SESSIONS` 동시 녹음 상한
- HTTP 보호: `REALTIME_API_KEY` 설정 시 `/v1/text`·`/v1/session`에 Bearer 필요

질문에는 생성 당시 `context_version`이 저장됩니다. LLM 처리 중 맥락 버전이
바뀌면 해당 결과는 저장하지 않아 오래된 질문이 화면에 노출되는 것을 막습니다.

## 설치

Python 3.11 또는 3.12 환경에서 실행합니다.

```powershell
conda activate Q-agent
cd C:\Users\xnejf\q-agent\services\realtime
python -m pip install -e .
```

Ollama가 실행 중이고 역할별 모델 3개가 설치되어 있어야 합니다.

```powershell
ollama pull qwen3:1.7b
ollama pull qwen3:4b
ollama pull qwen3:8b
```

Whisper는
기본적으로 CUDA를 자동 감지하며, NVIDIA GPU가 없으면 CPU `int8`로
실행됩니다. CPU 환경에서는 첫 모델 로드와 전사가 느릴 수 있습니다.

필요하면 `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`, `WHISPER_MODEL` 환경변수로
동작 방식을 고정할 수 있습니다.

## 마이크 확인

```powershell
q-agent-realtime --list-devices
```

## 실행

```powershell
q-agent-realtime --device 1 --meeting-objective "Q-Agent 시스템 설계"
```

- 발화가 끝난 뒤 확정 transcript가 출력되고 SQLite에 저장됩니다.
- Enter를 누르면 현재 최고 활성 질문을 요청합니다.
- `q`를 입력하고 Enter를 누르면 회의를 종료합니다.
- **최종 질문 노출:** 활성 질문이 있고 **침묵 ≥ 20초**(`SILENCE_TRIGGER_SECONDS`, 기본 20)이면
  한 문장을 자동 출력합니다. 사용자 요청(Enter)은 침묵과 무관하게 언제든 가능합니다.

## 웹 프런트 연결

브라우저 마이크를 사용하는 웹 모드에서는 CLI 대신 API 서버를 실행합니다.

```powershell
q-agent-realtime-server --host 127.0.0.1 --port 8765
```

- `WS /v1/realtime`: 16 kHz mono Float32 PCM. 메시지 `start`(필수 `session_token`) → PCM → `ask`(선택) → `stop`
- 서버 이벤트: `ready`, `status`, `transcript`, `context`, `pool_update`, `final_question`, `stopped`, `error`
- **최종 질문**은 `final_question`만 사용합니다. `pool_update`는 후보 풀 크기/내부 상태용입니다.
- `POST /v1/session`: 단회용 녹음 세션 토큰 발급
- `POST /v1/text`: 텍스트 원샷 분석(즉시 생성·평가 후 diagnosis 반환)
- `GET /health`: 현재 LLM/STT 제공자와 모델·세션 슬롯 상태 확인

녹음 시작 전 웹 BFF가 `/api/realtime/session`으로 토큰을 받아 `start.session_token`에
넣습니다. `REALTIME_API_KEY`가 있으면 BFF가 Bearer로 HTTP를 인증합니다.

WebSocket에서 `ask`를 보내면 침묵과 무관하게 활성 풀의 최고점 1문장을 `final_question`으로 보냅니다.
침묵 임계는 `SILENCE_TRIGGER_SECONDS`(기본 **20**), 생성 최소 간격은
`GENERATOR_MIN_INTERVAL_SECONDS`(기본 **25**, Context 버전 증가 시에만 실행)입니다.

기본 DB는 `data/q-agent.db`입니다. 로컬 DB와 녹음 원본은 Git에 포함하지 않습니다.

## 모델 제공자 설정

환경변수를 지정하지 않으면 OpenAI Responses API와 Audio Transcriptions API를
사용합니다. 따라서 realtime 서버에 `OPENAI_API_KEY`가 필요합니다.

| 모드 | `LLM_PROVIDER` | `STT_PROVIDER` | 필요한 설정 |
| --- | --- | --- | --- |
| API 기본값 | `openai` | `openai` | `OPENAI_API_KEY` |
| 완전 로컬 | `ollama` | `local` | Ollama + 로컬 Whisper |
| 혼합 | `ollama` 또는 `openai` | `local` 또는 `openai` | 선택한 제공자 설정 |

API 모드 설정은 다음과 같습니다.

```dotenv
LLM_PROVIDER=openai
STT_PROVIDER=openai
OPENAI_API_KEY=서버에만_저장하는_키
OPENAI_CONTEXT_MODEL=gpt-4o-mini
OPENAI_GENERATOR_MODEL=gpt-4o-mini
OPENAI_EVALUATOR_MODEL=gpt-4o-mini
OPENAI_STT_MODEL=gpt-4o-mini-transcribe
CORS_ORIGIN=https://프런트주소.example
```

API 키는 `NEXT_PUBLIC_*` 변수나 브라우저 코드에 넣지 않습니다. realtime
서버에서만 읽어 OpenAI Responses API의 Structured Outputs와 Audio
Transcriptions API를 호출하며, 응답 저장은 `store: false`로 요청합니다.
전체 변수는 [`.env.example`](.env.example)에 정리되어 있습니다.

OpenAI 모드에서는 실제 녹음을 시작하기 전에 API 키와 각 모델 접근 권한을
확인합니다.

## 선택 사항: 로컬 모델 설정

로컬 모드는 역할별 클라이언트, 실행 주기, 모델을 모두 분리합니다. 맥락 보존은
`qwen3:4b`, 복잡하고 다양한 후보 생성은 `qwen3:8b`, 정해진 스키마에 따른
질문 평가는 `qwen3:1.7b`가 담당합니다. 회의 준비 시 세 모델을 미리 적재하고
서버가 종료될 때까지 유지하므로 각 역할의 첫 호출 지연을 줄입니다.

| 역할 | 기본 모델 | 주기 | thinking | temperature |
| --- | --- | --- | --- | --- |
| Context Updater | `qwen3:4b` | 5초 | off | 0.1 |
| Question Generator (5개 배치) | `qwen3:8b` | 30초 | on | 0.5 |
| Question Evaluator | `qwen3:1.7b` | 후보 즉시 + 활성 질문 60초 | off | 0.0 |

기본 컨텍스트 길이는 Context/Evaluator 4K, Generator 8K입니다. Ollama의 동시
적재 상한을 별도로 낮춘 경우 `OLLAMA_MAX_LOADED_MODELS`를 3 이상으로 설정해야
합니다. GPU 메모리가 부족하면 요청이 대기하거나 모델이 교체될 수 있습니다.
모델과 주기는 `.env.example`의 역할별 변수로 교체할 수 있습니다.

RTX 4070 Ti SUPER 16GB에서 Whisper turbo와 세 Qwen을 모두 적재하고 Generator
8K 요청까지 실행한 실측 최대 사용량은 약 15.2GB였습니다. 기본 설정은 연구용
단일 회의 세션을 전제로 하며, 다른 GPU 작업이나 복수 동시 세션에서는 컨텍스트
길이 또는 모델 크기를 낮춰야 합니다.

## 테스트

```powershell
python -m unittest discover -s tests -v
```

테스트는 마이크, GPU, Ollama 없이 실행됩니다. OpenAI 연동 테스트도 모의 HTTP
서버를 사용하므로 실제 API 키와 비용이 필요하지 않습니다.
