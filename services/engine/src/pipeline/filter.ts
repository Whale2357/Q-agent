import type { TranscriptSegment } from "@q-agent/contracts";
import type { CandidateQuestion } from "./types";
import { jaccard, tokenize } from "./window";

const PRESET_KEYWORDS: Record<string, string[]> = {
  decision: ["기준", "선택", "결정", "대안", "비용", "속도", "합의", "trade"],
  problem: ["문제", "원인", "가정", "정의", "증상", "해결", "왜"],
};

function isQuestionForm(text: string): boolean {
  const t = text.trim();
  if (t.length < 15 || t.length > 120) return false;
  return /[?？]$/.test(t) || /(까요|가요|습니까|인가|할지|어떨까)\s*$/.test(t);
}

function isStatementOnly(text: string): boolean {
  return /(해야\s*한다|해보자|진행하자|동의한다)\s*[.!]?\s*$/.test(text) && !/[?？]/.test(text);
}

function isClosedProbe(text: string): boolean {
  return /^(네|아니요|예|아니)?.*(인가요|합니까|맞나요)\s*\?$/.test(text.trim());
}

/** Rule-only INQUISITIVE-style filter. No count cap. */
export function applyFilter(
  candidates: CandidateQuestion[],
  recentSegments: TranscriptSegment[],
  preset: string
): CandidateQuestion[] {
  const recentText = recentSegments
    .map((s) => (s.speaker ? `${s.speaker}: ${s.text}` : s.text))
    .join("\n");
  const recentTokens = tokenize(recentText);
  const presetKeys = PRESET_KEYWORDS[preset] || [];

  const passed: CandidateQuestion[] = [];

  for (const c of candidates) {
    const t = c.text.trim();
    if (!isQuestionForm(t)) continue;
    if (isStatementOnly(t)) continue;
    if (isClosedProbe(t)) continue;

    const qTokens = tokenize(t);
    let overlap = 0;
    for (const tok of qTokens) if (recentTokens.has(tok)) overlap += 1;
    const presetHit = presetKeys.some((k) => t.includes(k));
    if (overlap < 1 && !presetHit && recentTokens.size > 0) continue;

    // redundancy vs recent turns
    if (jaccard(qTokens, recentTokens) >= 0.7) continue;

    passed.push(c);
  }

  // drop near-duplicate candidates (keep earlier)
  const deduped: CandidateQuestion[] = [];
  for (const c of passed) {
    const ct = tokenize(c.text);
    const dup = deduped.some((d) => jaccard(ct, tokenize(d.text)) >= 0.75);
    if (!dup) deduped.push(c);
  }
  return deduped;
}
