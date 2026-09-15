export const PROMPT_VERSION = "engine-prompts-2026-09-15";

export function generateSystemPrompt(): string {
  return `당신은 회의 Guided Reflexivity용 질문 생성기입니다.
반드시 JSON만 출력하세요. 후보는 정확히 8개입니다.

규칙:
- operator 5종(assumption_challenge, reframing, criterion_clarification, counterfactual, constraint_relaxation)을 최소 1회씩 포함
- category(blind_spot, essence, expansion)를 각 최소 1개
- 동일 preg_trigger는 최대 2개
- tone 지시를 문장에 즉시 반영 (후단 재작성 없음)
- 얕은 확인/정의형 금지. 기준·가정·반증·리프레이밍 수준의 깊은 질문만
- 인신공격, 유도질문, 예/아니오 추궁 금지
- 사람 이름에 대한 비난 금지. 아이디어/가정만 겨냥

preg_trigger 허용값: knowledge_gap, contradiction, anomaly, inconsistency, unexpected_outcome, goal_obstacle

출력 스키마:
{"candidates":[{"id":"c1","text":"...?","preg_trigger":"contradiction","operator":"criterion_clarification","category":"essence","depth_hint":"why_criteria"}]}`;
}

export function generateUserPrompt(input: {
  preset: string;
  tone: number;
  windowText: string;
}): string {
  const presetHint =
    input.preset === "decision"
      ? "의사결정 교착: 판단 기준, trade-off, 반증 조건을 드러내는 질문 중심."
      : "문제 해결 고착: 문제 정의, 숨은 가정, reframing 질문 중심.";

  const toneHint: Record<number, string> = {
    1: "직설적·간결",
    2: "명확하되 존중하는 어조",
    3: "부드럽게 묻는 어조 (혹시/어떻게 보시나요)",
    4: "우회적·탐색적 어조",
  };

  return `preset: ${input.preset}
tone: ${input.tone} (${toneHint[input.tone] || "존중"})
지시: ${presetHint}

회의 맥락:
${input.windowText}

위 맥락만 근거로 후보 질문 8개를 JSON으로 생성하세요.`;
}

export function scoreSystemPrompt(): string {
  return `당신은 질문 가치 채점기입니다. EVPI 관점만 사용합니다.
norm 하나: "이 질문의 답이 나오면 회의의 다음 행동 또는 결론이 바뀌는가?"
JSON만 출력하세요.

출력 스키마:
{"scores":[{"id":"c1","info_gain":0.0,"hypothetical_answer_summary":"...","action_before":"...","action_after":"...","rationale":"..."}]}

info_gain은 0~1. 행동/결론이 안 바뀌면 낮은 점수.`;
}

export function scoreUserPrompt(input: {
  preset: string;
  windowText: string;
  candidates: { id: string; text: string }[];
}): string {
  const list = input.candidates
    .map((c) => `- ${c.id}: ${c.text}`)
    .join("\n");
  return `preset: ${input.preset}

회의 맥락:
${input.windowText}

채점할 질문 (전원):
${list}

각 질문에 대해 짧은 가상 답과 답 전/후 다음 행동을 비교해 info_gain을 매기세요.`;
}
