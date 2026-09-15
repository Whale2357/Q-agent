import type { DiagnoseRequest } from "@q-agent/contracts";
import {
  generateSystemPrompt,
  generateUserPrompt,
} from "../prompts";
import { chatJson, getModel, parseJsonObject } from "../llm/client";
import { generateResponseSchema } from "../llm/schemas";
import type { CandidateQuestion } from "./types";
import { ensureTone } from "./tone";

/** Deterministic 8-ish candidates for mock mode / fallback. */
export function generateMock(
  req: DiagnoseRequest,
  _windowText: string
): CandidateQuestion[] {
  const tone = req.tone;
  if (req.preset === "decision") {
    const raw: CandidateQuestion[] = [
      {
        id: "c1",
        text: "지금 A와 B를 가르는 핵심 기준이 비용인가요, 속도인가요?",
        preg_trigger: "contradiction",
        operator: "criterion_clarification",
        category: "essence",
        depth_hint: "why_criteria",
      },
      {
        id: "c2",
        text: "만약 지금 합의가 틀렸다면 가장 먼저 깨질 가정은 무엇인가요?",
        preg_trigger: "inconsistency",
        operator: "counterfactual",
        category: "blind_spot",
        depth_hint: "counter",
      },
      {
        id: "c3",
        text: "예산 제약이 없다면 어떤 선택을 하시겠습니까?",
        preg_trigger: "goal_obstacle",
        operator: "constraint_relaxation",
        category: "expansion",
        depth_hint: "constraint",
      },
      {
        id: "c4",
        text: "우리가 '빨라야 한다'고 보는 근거 데이터는 무엇인가요?",
        preg_trigger: "knowledge_gap",
        operator: "assumption_challenge",
        category: "blind_spot",
        depth_hint: "assumption",
      },
      {
        id: "c5",
        text: "결정을 한 달 미루면 어떤 비용이 발생합니까?",
        preg_trigger: "unexpected_outcome",
        operator: "counterfactual",
        category: "essence",
        depth_hint: "why_criteria",
      },
      {
        id: "c6",
        text: "이 문제를 고객 이탈 문제로 다시 정의하면 선택이 달라집니까?",
        preg_trigger: "anomaly",
        operator: "reframing",
        category: "expansion",
        depth_hint: "reframe",
      },
      {
        id: "c7",
        text: "A안과 B안이 둘 다 해결하지 못하는 요구는 무엇입니까?",
        preg_trigger: "knowledge_gap",
        operator: "reframing",
        category: "essence",
        depth_hint: "reframe",
      },
      {
        id: "c8",
        text: "반대 의견을 가진 사람이 가장 강하게 주장할 근거는 무엇일까요?",
        preg_trigger: "contradiction",
        operator: "assumption_challenge",
        category: "blind_spot",
        depth_hint: "assumption",
      },
    ];
    return raw.map((c) => ({ ...c, text: ensureTone(c.text, tone) }));
  }

  const raw: CandidateQuestion[] = [
    {
      id: "c1",
      text: "풀려는 문제가 정말 '카피' 문제라고 보는 근거는 무엇인가요?",
      preg_trigger: "inconsistency",
      operator: "reframing",
      category: "blind_spot",
      depth_hint: "reframe",
    },
    {
      id: "c2",
      text: "전환율 하락의 다른 원인 가설 상위 3가지는 무엇입니까?",
      preg_trigger: "knowledge_gap",
      operator: "assumption_challenge",
      category: "essence",
      depth_hint: "assumption",
    },
    {
      id: "c3",
      text: "카피가 완벽해도 전환율이 안 오르는 조건은 무엇인가요?",
      preg_trigger: "contradiction",
      operator: "counterfactual",
      category: "blind_spot",
      depth_hint: "counter",
    },
    {
      id: "c4",
      text: "유입 품질 제약을 잠시 무시하면 어디를 먼저 고치겠습니까?",
      preg_trigger: "goal_obstacle",
      operator: "constraint_relaxation",
      category: "expansion",
      depth_hint: "constraint",
    },
    {
      id: "c5",
      text: "지난번 카피 변경 전후 지표에서 무엇이 변하지 않았나요?",
      preg_trigger: "unexpected_outcome",
      operator: "criterion_clarification",
      category: "essence",
      depth_hint: "why_criteria",
    },
    {
      id: "c6",
      text: "이 증상을 제품 가치 문제로 보면 다음 실험은 무엇인가요?",
      preg_trigger: "anomaly",
      operator: "reframing",
      category: "expansion",
      depth_hint: "reframe",
    },
    {
      id: "c7",
      text: "성공 여부를 무엇으로 판단할지 기준이 합의되어 있나요?",
      preg_trigger: "knowledge_gap",
      operator: "criterion_clarification",
      category: "essence",
      depth_hint: "why_criteria",
    },
    {
      id: "c8",
      text: "우리가 당연하게 두는 '랜딩이 원인' 가정은 검증되었나요?",
      preg_trigger: "inconsistency",
      operator: "assumption_challenge",
      category: "blind_spot",
      depth_hint: "assumption",
    },
  ];
  return raw.map((c) => ({ ...c, text: ensureTone(c.text, tone) }));
}

export async function generateLive(
  req: DiagnoseRequest,
  windowText: string,
  timeoutMs: number
): Promise<CandidateQuestion[]> {
  const raw = await chatJson({
    system: generateSystemPrompt(),
    user: generateUserPrompt({
      preset: req.preset,
      tone: req.tone,
      windowText,
    }),
    model: getModel("generate"),
    timeoutMs,
    temperature: 0.35,
  });

  const parsed = generateResponseSchema.parse(parseJsonObject(raw));
  return parsed.candidates.slice(0, 8).map((c, i) => ({
    ...c,
    id: c.id || `c${i + 1}`,
    text: ensureTone(c.text, req.tone),
  }));
}
