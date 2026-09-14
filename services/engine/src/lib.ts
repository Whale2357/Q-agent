import type {
  DiagnoseRequest,
  DiagnoseSuccessResponse,
  ErrorResponse,
  ScoredQuestion,
  ToneLevel,
} from "@q-agent/contracts";

function applyTone(text: string, tone: ToneLevel): string {
  switch (tone) {
    case 1:
      return text;
    case 2:
      return text.replace(/\?$/, "일까요?");
    case 3:
      return `혹시 ${text.replace(/\?$/, "")}에 대해 어떻게 보시나요?`;
    case 4:
      return `한 가지 관점으로, ${text.replace(/\?$/, "")}도 살펴볼 여지가 있을까요?`;
    default:
      return text;
  }
}

/** Deterministic mock pipeline for skeleton / smoke tests. Replace with LLM stages. */
export function diagnoseMock(req: DiagnoseRequest): DiagnoseSuccessResponse {
  const max = req.options?.max_questions ?? 3;
  const text = req.transcript.text || "";
  const lower = text.toLowerCase();

  // Force reject path for explicit fixture keyword
  if (text.includes("[REJECT]") || text.trim().length < 8) {
    return {
      ok: true,
      status: "rejected",
      preset: req.preset,
      tone: req.tone,
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

  const candidates: Omit<ScoredQuestion, "text">[] = [];

  if (req.preset === "decision") {
    candidates.push({
      id: "cand_1",
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
      rationale: "A/B 주장만 반복되어 판단 기준이 비어 있음",
      hypothetical_answer_summary: "기준이 비용이면 A, 속도면 B로 결정이 갈림",
    });
    if (lower.includes("동의") || text.includes("동의")) {
      candidates.push({
        id: "cand_2",
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
        rationale: "성급한 합의 신호 — 실패 조건을 먼저 묻는다",
        hypothetical_answer_summary: "실패 조건이 드러나면 합의를 보류할 수 있음",
      });
    }
  } else {
    candidates.push({
      id: "cand_1",
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
      rationale: "증상(카피)에 고착 — 문제 정의를 재질문",
      hypothetical_answer_summary: "문제가 유입/제품이라면 다음 액션이 달라짐",
    });
  }

  const baseTexts: Record<string, string> = {
    cand_1:
      req.preset === "decision"
        ? "지금 A와 B를 가르는 기준이 비용인가요, 속도인가요?"
        : "우리가 풀려는 문제가 정말 '카피' 문제라고 보는 근거는 무엇인가요?",
    cand_2: "만약 지금 결론이 틀렸다면, 가장 먼저 깨질 가정은 무엇인가요?",
  };

  const questions: ScoredQuestion[] = candidates.slice(0, max).map((c) => ({
    ...c,
    text: applyTone(baseTexts[c.id] || "무엇을 확인해야 할까요?", req.tone),
  }));

  return {
    ok: true,
    status: "done",
    preset: req.preset,
    tone: req.tone,
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
