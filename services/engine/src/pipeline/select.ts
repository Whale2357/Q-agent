import type {
  BadgeCode,
  DiagnoseSuccessResponse,
  MeetingPreset,
  ToneLevel,
} from "@q-agent/contracts";
import type { ScoredCandidate } from "./types";
import { toScoredQuestion } from "./types";

const DEFAULT_THRESHOLD = Number(process.env.ENGINE_SCORE_THRESHOLD || 0.65);

function badgesFromScores(scores: ScoredCandidate["scores"]): BadgeCode[] {
  const badges: BadgeCode[] = [];
  if (scores.info_gain >= 0.7) badges.push("info_gain");
  if (scores.non_redundant >= 0.7) badges.push("non_redundant");
  if (scores.relevant >= 0.7) badges.push("relevant");
  if (scores.depth >= 0.7) badges.push("depth");
  return badges.length ? badges : ["info_gain"];
}

export function selectQuestions(
  scored: ScoredCandidate[],
  preset: MeetingPreset,
  tone: ToneLevel,
  maxQuestions: number,
  threshold = DEFAULT_THRESHOLD,
  pipelineCounts: {
    candidates_generated: number;
    candidates_after_filter: number;
  }
): DiagnoseSuccessResponse {
  const eligible = scored
    .map((c) => ({
      ...c,
      badges: c.badges.length ? c.badges : badgesFromScores(c.scores),
    }))
    .filter((c) => c.scores.final >= threshold)
    .sort((a, b) => b.scores.final - a.scores.final);

  // prefer category diversity
  const picked: ScoredCandidate[] = [];
  const seenCat = new Set<string>();
  for (const c of eligible) {
    if (picked.length >= maxQuestions) break;
    if (!seenCat.has(c.category)) {
      picked.push(c);
      seenCat.add(c.category);
    }
  }
  for (const c of eligible) {
    if (picked.length >= maxQuestions) break;
    if (!picked.find((p) => p.id === c.id)) picked.push(c);
  }

  if (picked.length === 0) {
    return {
      ok: true,
      status: "rejected",
      preset,
      tone,
      questions: [],
      rejected: true,
      reject_reason: "현재 맥락에서 임계값을 넘는 유효 질문이 없습니다",
      pipeline: {
        candidates_generated: pipelineCounts.candidates_generated,
        candidates_after_filter: pipelineCounts.candidates_after_filter,
        selected: 0,
      },
    };
  }

  return {
    ok: true,
    status: "done",
    preset,
    tone,
    questions: picked.map(toScoredQuestion),
    rejected: false,
    pipeline: {
      candidates_generated: pipelineCounts.candidates_generated,
      candidates_after_filter: pipelineCounts.candidates_after_filter,
      selected: picked.length,
    },
  };
}
