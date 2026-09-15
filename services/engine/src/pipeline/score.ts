import type { DiagnoseRequest } from "@q-agent/contracts";
import { scoreDepth } from "./depth";
import type { CandidateQuestion, ScoredCandidate } from "./types";
import { chatJson, getModel, parseJsonObject } from "../llm/client";
import { scoreResponseSchema } from "../llm/schemas";
import { scoreSystemPrompt, scoreUserPrompt } from "../prompts";

const W_INFO = Number(process.env.ENGINE_W_INFO_GAIN || 0.7);
const W_DEPTH = Number(process.env.ENGINE_W_DEPTH || 0.15);
const W_REL = Number(process.env.ENGINE_W_RELEVANT || 0.15);

function finalize(
  c: CandidateQuestion,
  infoGain: number,
  rationale: string,
  hypo: string
): ScoredCandidate {
  const depth = scoreDepth(c.text, c.depth_hint);
  const relevant = 0.85;
  const non_redundant = 0.85;
  const info_gain = Math.max(0, Math.min(1, infoGain));
  const final = Math.max(
    0,
    Math.min(1, W_INFO * info_gain + W_DEPTH * depth + W_REL * relevant)
  );

  const badges: ScoredCandidate["badges"] = [];
  if (info_gain >= 0.7) badges.push("info_gain");
  if (non_redundant >= 0.7) badges.push("non_redundant");
  if (relevant >= 0.7) badges.push("relevant");
  if (depth >= 0.7) badges.push("depth");
  if (c.operator === "assumption_challenge") badges.push("assumption");

  return {
    ...c,
    scores: { info_gain, non_redundant, relevant, depth, final },
    badges: badges.length ? badges : ["info_gain"],
    rationale,
    hypothetical_answer_summary: hypo,
  };
}

/** Mock batch scoring for all filter survivors. */
export function scoreMock(
  candidates: CandidateQuestion[],
  req: DiagnoseRequest
): ScoredCandidate[] {
  return candidates.map((c, idx) => {
    const base = req.preset === "decision" ? 0.78 : 0.76;
    const info = Math.min(0.95, base + (8 - idx) * 0.01);
    return finalize(
      c,
      info,
      "가상 답변에 따라 다음 결정/문제정의가 달라질 수 있음",
      "답에 따라 선택지 또는 원인 가설이 재정렬됨"
    );
  });
}

/** Live batch EVPI: one LLM call for all candidates. */
export async function scoreLive(
  candidates: CandidateQuestion[],
  req: DiagnoseRequest,
  windowText: string,
  timeoutMs: number
): Promise<ScoredCandidate[]> {
  if (candidates.length === 0) return [];

  const raw = await chatJson({
    system: scoreSystemPrompt(),
    user: scoreUserPrompt({
      preset: req.preset,
      windowText,
      candidates: candidates.map((c) => ({ id: c.id, text: c.text })),
    }),
    model: getModel("score"),
    timeoutMs,
    temperature: 0.2,
  });

  const parsed = scoreResponseSchema.parse(parseJsonObject(raw));
  const byId = new Map(parsed.scores.map((s) => [s.id, s]));

  return candidates.map((c, idx) => {
    const s = byId.get(c.id);
    if (!s) {
      return finalize(
        c,
        Math.max(0.4, 0.7 - idx * 0.05),
        "채점 누락 — 보수적 추정",
        "불명"
      );
    }
    return finalize(c, s.info_gain, s.rationale, s.hypothetical_answer_summary);
  });
}
