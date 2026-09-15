import type {
  DiagnoseRequest,
  DiagnoseSuccessResponse,
} from "@q-agent/contracts";
import { applyFilter } from "./filter";
import { generateLive, generateMock } from "./generate";
import { applyGuardrails } from "./guardrails";
import { scoreLive, scoreMock } from "./score";
import { selectQuestions } from "./select";
import type { PipelineDebug } from "./types";
import { PROMPT_VERSION } from "./types";
import { buildTranscriptWindow } from "./window";
import { LlmTimeoutError } from "../llm/client";

export type EngineMode = "mock" | "live";

export function resolveMode(): EngineMode {
  const explicit = (process.env.ENGINE_MODE || "").toLowerCase();
  if (explicit === "mock") return "mock";
  if (explicit === "live") return "live";
  return process.env.OPENAI_API_KEY ? "live" : "mock";
}

function earlyReject(
  req: DiagnoseRequest,
  reason: string
): DiagnoseSuccessResponse {
  return {
    ok: true,
    status: "rejected",
    preset: req.preset,
    tone: req.tone,
    questions: [],
    rejected: true,
    reject_reason: reason,
    pipeline: {
      candidates_generated: 0,
      candidates_after_filter: 0,
      selected: 0,
    },
  };
}

export async function diagnose(
  req: DiagnoseRequest
): Promise<DiagnoseSuccessResponse & { debug?: PipelineDebug }> {
  const text = req.transcript?.text?.trim() || "";
  if (text.includes("[REJECT]") || text.length < 8) {
    return earlyReject(
      req,
      "현재 맥락에서 임계값을 넘는 유효 질문이 없습니다"
    );
  }

  const mode = resolveMode();
  const maxQuestions = req.options?.max_questions ?? 3;
  const recentWindow = req.options?.recent_turn_window ?? 12;
  const { windowText, recentSegments } = buildTranscriptWindow(
    req.transcript,
    recentWindow
  );

  const timings: Record<string, number> = {};
  const totalBudget = Number(process.env.ENGINE_TOTAL_TIMEOUT_MS || 35000);
  const genBudget = Number(process.env.ENGINE_GENERATE_TIMEOUT_MS || 15000);
  const scoreBudget = Number(process.env.ENGINE_SCORE_TIMEOUT_MS || 15000);

  const t0 = Date.now();
  let generated =
    mode === "live"
      ? await generateLive(req, windowText, Math.min(genBudget, totalBudget))
      : generateMock(req, windowText);
  timings.generate = Date.now() - t0;

  // Ensure diversity count target; mock already returns 8
  if (generated.length > 8) generated = generated.slice(0, 8);

  let afterGuard = applyGuardrails(generated);
  let afterFilter = applyFilter(afterGuard, recentSegments, req.preset);

  // one regenerate retry if empty after filter (live only)
  if (afterFilter.length === 0 && mode === "live" && Date.now() - t0 < totalBudget - 5000) {
    const tRetry = Date.now();
    generated = await generateLive(
      req,
      windowText,
      Math.min(genBudget, totalBudget - (Date.now() - t0))
    );
    timings.generate_retry = Date.now() - tRetry;
    afterGuard = applyGuardrails(generated);
    afterFilter = applyFilter(afterGuard, recentSegments, req.preset);
  }

  if (afterFilter.length === 0) {
    return earlyReject(
      req,
      "현재 맥락에서 임계값을 넘는 유효 질문이 없습니다"
    );
  }

  const tScore = Date.now();
  const remaining = totalBudget - (Date.now() - t0);
  let scored;
  try {
    scored =
      mode === "live"
        ? await scoreLive(
            afterFilter,
            req,
            windowText,
            Math.min(scoreBudget, Math.max(3000, remaining))
          )
        : scoreMock(afterFilter, req);
  } catch (err) {
    if (err instanceof LlmTimeoutError) throw err;
    // fallback to mock scoring to keep demo alive
    scored = scoreMock(afterFilter, req);
  }
  timings.score = Date.now() - tScore;

  const result = selectQuestions(scored, req.preset, req.tone, maxQuestions, undefined, {
    candidates_generated: generated.length,
    candidates_after_filter: afterFilter.length,
  });

  if (req.options?.debug) {
    return {
      ...result,
      debug: {
        prompt_version: PROMPT_VERSION,
        mode,
        window_text: windowText,
        generated,
        after_guardrails: afterGuard,
        after_filter: afterFilter,
        scored,
        timings_ms: timings,
      },
    };
  }

  return result;
}
