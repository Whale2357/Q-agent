/**
 * Local pipeline smoke (mock mode, no API key required).
 * Run: npm run test:pipeline -w @q-agent/engine
 */
import type { DiagnoseRequest } from "@q-agent/contracts";
import { diagnose } from "../pipeline/diagnose";

process.env.ENGINE_MODE = "mock";

async function run(label: string, req: DiagnoseRequest) {
  const res = await diagnose(req);
  console.log(`\n=== ${label} ===`);
  console.log(
    JSON.stringify(
      {
        status: res.status,
        rejected: res.rejected,
        n: res.questions.length,
        pipeline: res.pipeline,
        questions: res.questions.map((q) => ({
          text: q.text,
          final: q.scores.final,
          badges: q.badges,
        })),
      },
      null,
      2
    )
  );
  if (res.status === "done" && res.questions.length === 0) {
    throw new Error(`${label}: expected questions`);
  }
  if (label === "reject" && !res.rejected) {
    throw new Error("reject fixture failed");
  }
}

async function main() {
  await run("decision", {
    transcript: {
      transcript_id: "tr_decision",
      language: "ko",
      source: "text",
      text: `A: 나는 A안이 맞다고 봐. 비용이 중요해.
B: 아니 B안이 더 빨라. 시장이 기다려 주지 않아.
A: 그래도 예산이 없는데.
B: 일단 B로 가자. 다들 동의하지?
C: …음, 잘 모르겠어.`,
      segments: [
        { speaker: "A", text: "나는 A안이 맞다고 봐. 비용이 중요해." },
        { speaker: "B", text: "아니 B안이 더 빨라. 시장이 기다려 주지 않아." },
        { speaker: "A", text: "그래도 예산이 없는데." },
        { speaker: "B", text: "일단 B로 가자. 다들 동의하지?" },
        { speaker: "C", text: "…음, 잘 모르겠어." },
      ],
      meta: { duration_ms: null, warning: null },
    },
    preset: "decision",
    tone: 2,
    options: { max_questions: 3, debug: true },
  });

  await run("problem", {
    transcript: {
      transcript_id: "tr_problem",
      language: "ko",
      source: "text",
      text: `A: 전환율이 떨어져. 랜딩 카피를 바꿔야 해.
B: 맞아, 버튼 색도 바꿔보자.
A: 지난번에도 카피 바꿨는데 똑같았잖아.
B: 그래도 카피가 문제야.`,
      segments: [
        { speaker: "A", text: "전환율이 떨어져. 랜딩 카피를 바꿔야 해." },
        { speaker: "B", text: "맞아, 버튼 색도 바꿔보자." },
        { speaker: "A", text: "지난번에도 카피 바꿨는데 똑같았잖아." },
        { speaker: "B", text: "그래도 카피가 문제야." },
      ],
      meta: { duration_ms: null, warning: null },
    },
    preset: "problem",
    tone: 3,
    options: { max_questions: 3 },
  });

  await run("reject", {
    transcript: {
      transcript_id: "tr_reject",
      language: "ko",
      source: "text",
      text: "[REJECT]",
      segments: [{ text: "[REJECT]" }],
      meta: { duration_ms: null, warning: null },
    },
    preset: "decision",
    tone: 2,
  });

  console.log("\nOK engine pipeline smoke (mock)");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
