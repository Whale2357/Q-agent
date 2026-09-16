import type {
  DiagnoseRequest,
  DiagnoseSuccessResponse,
  ErrorResponse,
  MeetingPreset,
  ScoredQuestion,
  ToneLevel,
} from "@q-agent/contracts";

function applyTone(text: string, tone: ToneLevel): string {
  switch (tone) {
    case 1:
    case 2:
      return text;
    case 3:
      return `혹시 ${text.replace(/\?$/, "")}에 대해 어떻게 보시나요?`;
    case 4:
      return `한 가지 관점으로, ${text.replace(/\?$/, "")}도 살펴볼 여지가 있을까요?`;
    default:
      return text;
  }
}

function latestMeetingFocus(text: string): string {
  const latestLine = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .at(-1) ?? text.trim();
  const withoutSpeaker = latestLine.replace(/^[A-Za-z가-힣0-9]+\s*[:：]\s*/, "");
  const normalized = withoutSpeaker.replace(/[?.!。！？]+$/g, "").trim();
  return normalized.length > 42 ? `${normalized.slice(0, 42)}…` : normalized;
}

/** Deterministic mock pipeline for skeleton / smoke tests. Replace with LLM stages. */
export function diagnoseMock(req: DiagnoseRequest): DiagnoseSuccessResponse {
  const max = req.options?.max_questions ?? 3;
  const text = req.transcript.text || "";
  const lower = text.toLowerCase();
  const inferredPreset: MeetingPreset = /문제|원인|하락|감소|오류|장애|이탈|전환율/.test(lower)
    ? "problem"
    : "decision";
  const preset = req.preset ?? inferredPreset;
  const tone = req.tone ?? 2;

  // Force reject path for explicit fixture keyword
  if (text.includes("[REJECT]") || text.trim().length < 8) {
    return {
      ok: true,
      status: "rejected",
      preset,
      tone,
      questions: [],
      rejected: true,
      reject_reason: "현재 맥락에서 임계값을 넘는 유효 질문이 없습니다",
      pipeline: {
        candidates_generated: 2,
        candidates_after_filter: 0,
        selected: 0,
      },
    };
  }

  const focus = latestMeetingFocus(text);
  const candidates: ScoredQuestion[] = [];

  if (preset === "decision") {
    candidates.push({
      id: "cand_1",
      text: `방금 나온 “${focus}” 의견을 판단할 핵심 기준은 무엇인가요?`,
      category: "essence",
      operator: "criterion_clarification",
      scores: {
        info_gain: 0.86,
        non_redundant: 0.91,
        relevant: 0.9,
        depth: 0.72,
        final: 0.86,
      },
      badges: ["info_gain", "non_redundant", "relevant"],
      rationale: `최근 발화인 “${focus}”에 판단 기준이 명시되지 않았습니다.`,
      hypothetical_answer_summary: "판단 기준이 정해지면 대안의 우선순위를 비교할 수 있음",
    });
    candidates.push({
      id: "cand_2",
      text: "현재 논의에서 아직 사실로 확인하지 않은 가장 큰 가정은 무엇인가요?",
      category: "blind_spot",
      operator: "counterfactual",
      scores: {
        info_gain: 0.78,
        non_redundant: 0.88,
        relevant: 0.8,
        depth: 0.75,
        final: 0.8,
      },
      badges: ["info_gain", "depth"],
      rationale: "결론을 내리기 전에 근거가 약한 전제를 확인합니다.",
      hypothetical_answer_summary: "숨은 가정이 드러나면 결정을 보류하거나 검증할 수 있음",
    });
  } else {
    candidates.push({
      id: "cand_1",
      text: `“${focus}”을 문제의 원인으로 보는 구체적인 근거는 무엇인가요?`,
      category: "blind_spot",
      operator: "reframing",
      scores: {
        info_gain: 0.84,
        non_redundant: 0.87,
        relevant: 0.89,
        depth: 0.8,
        final: 0.85,
      },
      badges: ["info_gain", "assumption", "depth"],
      rationale: `최근 언급된 “${focus}”이 원인인지 증상인지 구분할 필요가 있습니다.`,
      hypothetical_answer_summary: "원인에 대한 근거가 확인되면 다음 행동이 달라짐",
    });
    candidates.push({
      id: "cand_2",
      text: "지금 가정한 원인이 아니라면, 다음으로 확인해야 할 가능성은 무엇인가요?",
      category: "expansion",
      operator: "reframing",
      scores: {
        info_gain: 0.79,
        non_redundant: 0.84,
        relevant: 0.81,
        depth: 0.76,
        final: 0.8,
      },
      badges: ["info_gain", "assumption"],
      rationale: "단일 원인에 고착되지 않도록 대안 가설을 확인합니다.",
      hypothetical_answer_summary: "대안 원인을 비교하면 검증 순서를 정할 수 있음",
    });
  }

  const questions = candidates.slice(0, max).map((candidate) => ({
    ...candidate,
    text: applyTone(candidate.text, tone),
  }));

  return {
    ok: true,
    status: "done",
    preset,
    tone,
    questions,
    rejected: false,
    pipeline: {
      candidates_generated: candidates.length + 3,
      candidates_after_filter: candidates.length,
      selected: questions.length,
    },
  };
}

export function fail(
  code: ErrorResponse["error"]["code"],
  message: string,
  retryable = false
): ErrorResponse {
  return { ok: false, error: { code, message, retryable } };
}
