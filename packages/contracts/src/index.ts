export type MeetingPreset = "decision" | "problem";
export type ToneLevel = 1 | 2 | 3 | 4;
export type PipelineStatus =
  | "extracting"
  | "generating"
  | "selecting"
  | "done"
  | "rejected"
  | "error";
export type QuestionCategory = "blind_spot" | "essence" | "expansion";
export type BadgeCode =
  | "info_gain"
  | "non_redundant"
  | "relevant"
  | "depth"
  | "assumption";
export type OperatorCode =
  | "assumption_challenge"
  | "reframing"
  | "criterion_clarification"
  | "counterfactual"
  | "constraint_relaxation";
export type TranscriptSource = "text" | "audio";
export type ErrorCode =
  | "INVALID_INPUT"
  | "UNAUTHORIZED"
  | "SESSION_LIMIT"
  | "RATE_LIMITED"
  | "LLM_UNAVAILABLE"
  | "MODEL_REQUEST_FAILED"
  | "REALTIME_UNAVAILABLE"
  | "LLM_TIMEOUT"
  | "INTERNAL";

export interface TranscriptSegment {
  speaker?: string;
  text: string;
  start_ms?: number;
  end_ms?: number;
}

export interface Transcript {
  transcript_id: string;
  language: string;
  source: TranscriptSource;
  text: string;
  segments: TranscriptSegment[];
  meta: {
    duration_ms?: number | null;
    warning?: string | null;
  };
}

export interface ErrorBody {
  code: ErrorCode;
  message: string;
  retryable: boolean;
}

export interface ErrorResponse {
  ok: false;
  error: ErrorBody;
}

export interface ScoreBreakdown {
  info_gain: number;
  non_redundant: number;
  relevant: number;
  depth: number;
  final: number;
}

export interface ScoredQuestion {
  id: string;
  text: string;
  category: QuestionCategory;
  operator: OperatorCode;
  scores: ScoreBreakdown;
  badges: BadgeCode[];
  rationale: string;
  hypothetical_answer_summary: string;
}

export interface PipelineStats {
  candidates_generated: number;
  candidates_after_filter: number;
  selected: number;
}

/** realtime `/v1/text` diagnosis and WS `final_question` payload */
export interface DiagnosisSuccess {
  ok: true;
  status: "done" | "rejected";
  preset: MeetingPreset;
  tone: ToneLevel;
  questions: ScoredQuestion[];
  rejected: boolean;
  reject_reason?: string;
  pipeline: PipelineStats;
}

export type DiagnosisResponse = DiagnosisSuccess | ErrorResponse;

/** @deprecated Use DiagnosisSuccess */
export type DiagnoseSuccessResponse = DiagnosisSuccess;
/** @deprecated Use DiagnosisResponse */
export type DiagnoseResponse = DiagnosisResponse;

export interface RealtimeSessionSuccess {
  ok: true;
  token: string;
  expires_in: number;
  max_audio_sessions: number;
  active_audio_sessions: number;
}

export type RealtimeSessionResponse = RealtimeSessionSuccess | ErrorResponse;

export interface TextMeetingSuccess {
  ok: true;
  meeting_id: string;
  transcript: string;
  diagnosis: DiagnosisSuccess;
}

export type TextMeetingResponse = TextMeetingSuccess | ErrorResponse;

export const MAX_TEXT_CHARACTERS = 100_000;
export const MAX_TEXT_REQUEST_BYTES = 512 * 1024;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Validate data received over the network or loaded from browser storage. */
export function isDiagnosisSuccess(value: unknown): value is DiagnosisSuccess {
  if (!isRecord(value) || value.ok !== true || !["done", "rejected"].includes(String(value.status))
    || !["decision", "problem"].includes(String(value.preset)) || typeof value.tone !== "number" || ![1, 2, 3, 4].includes(value.tone)
    || typeof value.rejected !== "boolean" || !Array.isArray(value.questions) || !isRecord(value.pipeline)) return false;
  const pipeline = value.pipeline;
  if (!["candidates_generated", "candidates_after_filter", "selected"].every((key) =>
    Number.isInteger(pipeline[key]) && Number(pipeline[key]) >= 0)) return false;
  return value.questions.every((question: unknown) => {
    if (!isRecord(question) || typeof question.id !== "string" || !question.id
      || typeof question.text !== "string" || !question.text.trim() || !isRecord(question.scores)
      || !["blind_spot", "essence", "expansion"].includes(String(question.category))
      || !["assumption_challenge", "reframing", "criterion_clarification", "counterfactual", "constraint_relaxation"].includes(String(question.operator))
      || !Array.isArray(question.badges) || !question.badges.every((badge: unknown) =>
        ["info_gain", "non_redundant", "relevant", "depth", "assumption"].includes(String(badge)))
      || typeof question.rationale !== "string" || typeof question.hypothetical_answer_summary !== "string") return false;
    const scores = question.scores;
    return ["info_gain", "non_redundant", "relevant", "depth", "final"].every((key) => {
      const score = scores[key];
      return typeof score === "number" && Number.isFinite(score) && score >= 0 && score <= 1;
    });
  });
}

export function isTextMeetingSuccess(value: unknown): value is TextMeetingSuccess {
  return isRecord(value) && value.ok === true && typeof value.meeting_id === "string"
    && typeof value.transcript === "string" && isDiagnosisSuccess(value.diagnosis);
}

export function isRealtimeSessionSuccess(value: unknown): value is RealtimeSessionSuccess {
  return isRecord(value) && value.ok === true && typeof value.token === "string" && value.token.length > 0
    && typeof value.expires_in === "number" && value.expires_in > 0
    && typeof value.max_audio_sessions === "number" && typeof value.active_audio_sessions === "number";
}

export const CONTRACT_VERSION = "0.2.0";
