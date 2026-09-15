import { OPERATORS, type CandidateQuestion } from "./types";

const ABUSE =
  /(바보|멍청|무능|한심|꺼져|씨발|병신|장애인|차별|쓰레기)/i;
const BLAME =
  /(누구\s*잘못|네\s*탓|당신\s*잘못|책임자\s*누구|무능한)/i;
const LEADING =
  /(또\s+.+(했|한)\s*지|때문에\s+.+(죠|지)\s*\?|당연히\s+.+\?)/i;
const CLOSED_INTERROGATION =
  /^(정말|그냥|혹시)?\s*.{0,20}(인가요|합니까|맞나요|아니에요)\s*\?$/;
const OFFTOPIC =
  /(날씨|점심\s*뭐|축구\s*경기|연예인)/i;

const ALLOWED = new Set(OPERATORS);

/** Rule-only guardrails. Returns survivors. */
export function applyGuardrails(
  candidates: CandidateQuestion[]
): CandidateQuestion[] {
  return candidates.filter((c) => {
    const t = c.text.trim();
    if (!t) return false;
    if (ABUSE.test(t) || BLAME.test(t)) return false;
    if (LEADING.test(t)) return false;
    if (CLOSED_INTERROGATION.test(t)) return false;
    if (OFFTOPIC.test(t)) return false;
    if (!ALLOWED.has(c.operator)) return false;
    return true;
  });
}
