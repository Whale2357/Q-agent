import type {
  BadgeCode,
  OperatorCode,
  QuestionCategory,
  ScoreBreakdown,
  ScoredQuestion,
} from "@q-agent/contracts";

export const PROMPT_VERSION = "engine-prompts-2026-09-15";

export const OPERATORS: OperatorCode[] = [
  "assumption_challenge",
  "reframing",
  "criterion_clarification",
  "counterfactual",
  "constraint_relaxation",
];

export type PregTrigger =
  | "knowledge_gap"
  | "contradiction"
  | "anomaly"
  | "inconsistency"
  | "unexpected_outcome"
  | "goal_obstacle";

export interface CandidateQuestion {
  id: string;
  text: string;
  preg_trigger: PregTrigger;
  operator: OperatorCode;
  category: QuestionCategory;
  depth_hint?: string;
}

export interface ScoredCandidate extends CandidateQuestion {
  scores: ScoreBreakdown;
  badges: BadgeCode[];
  rationale: string;
  hypothetical_answer_summary: string;
}

export interface PipelineDebug {
  prompt_version: string;
  mode: "mock" | "live";
  window_text: string;
  generated: CandidateQuestion[];
  after_guardrails: CandidateQuestion[];
  after_filter: CandidateQuestion[];
  scored: ScoredCandidate[];
  timings_ms: Record<string, number>;
}

export function toScoredQuestion(c: ScoredCandidate): ScoredQuestion {
  return {
    id: c.id,
    text: c.text,
    category: c.category,
    operator: c.operator,
    scores: c.scores,
    badges: c.badges,
    rationale: c.rationale,
    hypothetical_answer_summary: c.hypothetical_answer_summary,
  };
}
