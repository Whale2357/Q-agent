/** Rule-based depth score 0~1. No LLM rewrite. */
export function scoreDepth(text: string, depthHint?: string): number {
  let score = 0.55;
  const t = text;

  if (/(왜|기준|가정|만약|조건|trade-?off|근거|전제)/i.test(t)) score += 0.2;
  if (depthHint && /(why|criteria|assumption|counter|reframe)/i.test(depthHint)) {
    score += 0.1;
  }
  if (/^(정말|그냥)?.{0,12}(인가요|맞나요)\s*\?$/.test(t.trim())) score -= 0.25;
  if (/(정의가\s*무엇|무슨\s*뜻)/.test(t)) score -= 0.2;

  return Math.max(0, Math.min(1, score));
}
