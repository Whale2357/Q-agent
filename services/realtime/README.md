# Q-Agent realtime service

LangGraph 없이 순수 Python으로 동작하는 로컬 회의 파이프라인입니다.

```text
마이크 -> Silero VAD -> faster-whisper -> SQLite
      -> Question Context State -> Qwen3 8B
      -> 질문 후보 8개 -> 3대 지표 배치 평가 -> 활성 질문 최대 3개
      -> 사용자 요청 또는 20초 정적 -> 질문 한 문장 출력
```

기존 `services/extract`, `services/engine`의 TypeScript 데모 계약은 변경하지 않습니다.
현재 웹은 이 서비스의 HTTP/WebSocket 어댑터를 직접 사용하며 후보 필드는
MVP2의 `category`와 `operator` 방향에 맞춰져 있습니다.

## 현재 책임

- Python: 마이크, VAD, Whisper, transcript 저장, Question Context State, 주기 제어
- Qwen Generator: 근거 segment가 연결된 후보 8개 생성
- Qwen Evaluator: PDF 3대 지표 평가 및 최대 3개 활성화
- Web API: 텍스트 요청과 브라우저 PCM WebSocket 수신, 전사·질문 이벤트 송신

질문에는 생성 당시 `context_version`이 저장됩니다. LLM 처리 중 맥락 버전이
바뀌면 해당 결과는 저장하지 않아 오래된 질문이 화면에 노출되는 것을 막습니다.

## 설치

Python 3.11 또는 3.12 환경에서 실행합니다.

```powershell
conda activate Q-agent
cd C:\Users\xnejf\q-agent\services\realtime
python -m pip install -e .
```

Ollama가 실행 중이고 `qwen3:8b`가 설치되어 있어야 합니다. Whisper는
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
- 활성 질문이 존재하고 20초 이상 정적이면 질문 한 문장이 자동 출력됩니다.

## 웹 프런트 연결

브라우저 마이크를 사용하는 웹 모드에서는 CLI 대신 API 서버를 실행합니다.

```powershell
q-agent-realtime-server --host 127.0.0.1 --port 8765
```

- `WS /v1/realtime`: 16 kHz mono Float32 PCM 스트림을 받아 전사·질문 이벤트 반환
- `POST /v1/text`: 텍스트 테스트도 동일한 Context → Generator → Evaluator 파이프라인 사용
- `GET /health`: Ollama 모델 준비 여부와 Whisper 로드 상태 확인

WebSocket 메시지 순서는 `start` → PCM binary frames → `stop`입니다. 서버는
`ready`, `status`, `transcript`, `questions`, `stopped`, `error` 이벤트를 반환합니다.
프런트 BFF의 기본 HTTP 주소는 `http://127.0.0.1:8765`, 브라우저 WebSocket
주소는 `ws://127.0.0.1:8765/v1/realtime`입니다.

기본 DB는 `data/q-agent.db`입니다. 로컬 DB와 녹음 원본은 Git에 포함하지 않습니다.

## 모델 설정

모든 LLM 역할은 동일한 `qwen3:8b`를 공유하며 Ollama 요청만 역할별로 분리합니다.

| 역할 | thinking | temperature |
| --- | --- | --- |
| Context Updater | off | 0.1 |
| Question Generator (8개 배치) | on | 0.5 |
| Question Evaluator | off | 0.0 |

64K 별칭 대신 8K 컨텍스트를 기본값으로 사용합니다.

## 테스트

```powershell
python -m unittest discover -s tests -v
```

테스트는 마이크, GPU, Ollama 없이 실행됩니다.
