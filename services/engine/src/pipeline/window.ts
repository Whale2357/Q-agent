import type { Transcript, TranscriptSegment } from "@q-agent/contracts";

/** Build a compact window: optional head snippet + recent N segments. */
export function buildTranscriptWindow(
  transcript: Transcript,
  recentTurnWindow = 12,
  headChars = 200
): { windowText: string; recentSegments: TranscriptSegment[] } {
  const segments: TranscriptSegment[] =
    transcript.segments?.length > 0
      ? transcript.segments
      : transcript.text
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean)
          .map((text) => ({ text } satisfies TranscriptSegment));

  const recentSegments = segments.slice(-Math.max(1, recentTurnWindow));
  const recentText = recentSegments
    .map((s) => (s.speaker ? `${s.speaker}: ${s.text}` : s.text))
    .join("\n");

  const full = transcript.text || recentText;
  if (full.length <= headChars + recentText.length + 20) {
    return { windowText: full, recentSegments };
  }

  const head = full.slice(0, headChars).trim();
  const windowText = `[앞부분 요약]\n${head}…\n\n[최근 발화]\n${recentText}`;
  return { windowText, recentSegments };
}

export function tokenize(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .replace(/[^\p{L}\p{N}\s]/gu, " ")
      .split(/\s+/)
      .filter((t) => t.length >= 2)
  );
}

export function jaccard(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0;
  let inter = 0;
  for (const t of a) if (b.has(t)) inter += 1;
  const union = a.size + b.size - inter;
  return union === 0 ? 0 : inter / union;
}
