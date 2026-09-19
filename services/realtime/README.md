# Q-Agent realtime service

LangGraph 없이 순수 Python으로 동작하는 로컬 회의 파이프라인입니다.

```text
마이크 -> Silero VAD -> faster-whisper -> SQLite
      -> Question Context State -> Qwen3 8B
      -> 질문 후보 8개 -> 3대 지표 배치 평가 -> 활성 질문 최대 3개
      -> 사용자 요청 또는 20초 정적 -> 질문 한 문장 출력
```

기존 `services/extract`, `services/engine`의 TypeScript 데모 계약은 변경하지 않습니다.
이 서비스의 후보 필드는 MVP2의 `category`와 `operator` 방향에 맞췄으며,
공유 계약이 확정되면 HTTP 어댑터를 추가해 `engine`의 Score/Select 단계로 넘길 수 있습니다.

## 현재 책임

- Python: 마이크, VAD, Whisper, transcript 저장, Question Context State, 주기 제어
- Qwen Generator: 근거 segment가 연결된 후보 8개 생성
- 로컬 Evaluator: PDF 3대 지표 평가 및 최대 3개 활성화
- 향후 MVP2 연결: 로컬 Evaluator를 `services/engine` 호출 어댑터로 교체

질문에는 생성 당시 `context_version`이 저장됩니다. LLM 처리 중 맥락 버전이
바뀌면 해당 결과는 저장하지 않아 오래된 질문이 화면에 노출되는 것을 막습니다.

## 설치

이미 만든 Conda 환경에서 실행합니다.

```powershell
conda activate Q-agent
cd C:\Users\xnejf\q-agent\services\realtime
python -m pip install -e .
```

Ollama가 실행 중이고 `qwen3:8b`가 설치되어 있어야 합니다.

## 마이크 확인

```powershell
q-agent-realtime --list-devices
```

## 실행

```powershell
q-agent-realtime --device 1 --meeting-objective "Q-Agent 시스템 설계"
```

Context/Generator/Evaluator 프롬프트는 기본적으로 다음 폴더의 Markdown 파일을
읽습니다.

```text
C:\Users\xnejf\Documents\ChatGPT\회의 진행 Agent\prompts
```

다른 폴더를 사용하려면 `--prompt-dir` 또는 `Q_AGENT_PROMPT_DIR` 환경 변수를
지정합니다. 실행 시 `_shared_v1.md`, `context_v1.md`, `evaluator_v1.md`,
`generator_v1.md`, `purpose_guide_v1.md`가 모두 있는지 확인합니다.

```powershell
q-agent-realtime --prompt-dir "C:\path\to\prompts"
```

- 발화가 끝난 뒤 확정 transcript가 출력되고 SQLite에 저장됩니다.
- Enter를 누르면 현재 최고 활성 질문을 요청합니다.
- `q`를 입력하고 Enter를 누르면 회의를 종료합니다.
- 활성 질문이 존재하고 20초 이상 정적이면 질문 한 문장이 자동 출력됩니다.

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
