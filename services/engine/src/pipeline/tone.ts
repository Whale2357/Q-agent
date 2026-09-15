import type { ToneLevel } from "@q-agent/contracts";

/**
 * Light rule wrapping when model ignored tone.
 * Prefer generate-time tone; this is a safety net only.
 * Never double-wrap an already well-formed question.
 */
export function ensureTone(text: string, tone: ToneLevel): string {
  const t = text.trim();
  if (!t) return t;

  if (tone === 1) {
    return t
      .replace(/^혹시\s*/, "")
      .replace(/^한\s*가지\s*관점으로,\s*/, "");
  }

  // Already a question → leave wording (generate should have applied tone)
  if (/[?？]$/.test(t)) {
    if (tone === 3 && !/^혹시/.test(t) && !/어떻게 보시나요/.test(t)) {
      return `혹시 ${t}`;
    }
    if (tone === 4 && !/살펴볼 여지/.test(t) && !/한\s*가지\s*관점/.test(t)) {
      const core = t.replace(/[?？]\s*$/, "");
      return `한 가지 관점으로, ${core}도 살펴볼 여지가 있을까요?`;
    }
    return t;
  }

  const core = t.replace(/[.!]\s*$/, "");
  switch (tone) {
    case 2:
      return `${core}?`;
    case 3:
      return `혹시 ${core}에 대해 어떻게 보시나요?`;
    case 4:
      return `한 가지 관점으로, ${core}도 살펴볼 여지가 있을까요?`;
    default:
      return `${core}?`;
  }
}
