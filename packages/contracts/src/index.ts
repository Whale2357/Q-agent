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

export const CONTRACT_VERSION = "0.2.0";
