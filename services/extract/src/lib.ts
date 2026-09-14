import { randomUUID } from "crypto";
import type {
  ErrorResponse,
  ExtractSuccessResponse,
  Transcript,
  TranscriptSegment,
} from "@q-agent/contracts";

/** MVP: text passthrough + light normalization. STT hook lives here later. */
export function normalizeTextToTranscript(
  raw: string,
  source: "text" | "audio" = "text",
  language = "ko"
): Transcript {
  const text = raw.replace(/\r\n/g, "\n").trim();
  const segments: TranscriptSegment[] = [];

  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const m = trimmed.match(/^([A-Za-z가-힣0-9]+)\s*[:：]\s*(.+)$/);
    if (m) {
      segments.push({ speaker: m[1], text: m[2].trim() });
    } else {
      segments.push({ text: trimmed });
    }
  }

  return {
    transcript_id: `tr_${randomUUID().slice(0, 8)}`,
    language,
    source,
    text: segments.map((s) => (s.speaker ? `${s.speaker}: ${s.text}` : s.text)).join("\n"),
    segments,
    meta: {
      duration_ms: null,
      warning:
        source === "audio"
          ? "STT stub: audio bytes accepted but transcribed as placeholder. Replace with Whisper/etc."
          : null,
    },
  };
}

export function success(transcript: Transcript): ExtractSuccessResponse {
  return { ok: true, transcript };
}

export function fail(
  code: ErrorResponse["error"]["code"],
  message: string,
  retryable = false
): ErrorResponse {
  return { ok: false, error: { code, message, retryable } };
}
