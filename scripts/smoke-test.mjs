#!/usr/bin/env node
/**
 * Legacy smoke test: extract ↔ engine ↔ (optional) old web routes
 * Usage:
 *   node scripts/smoke-test.mjs
 *   WEB_URL=http://localhost:3000 node scripts/smoke-test.mjs
 */

const EXTRACT_URL = process.env.EXTRACT_SERVICE_URL || "http://localhost:4001";
const ENGINE_URL = process.env.ENGINE_SERVICE_URL || "http://localhost:4002";
const WEB_URL = process.env.WEB_URL || "http://localhost:3000";

const sampleText = `A: 나는 A안이 맞다고 봐. 비용이 중요해.
B: 아니 B안이 더 빨라. 시장이 기다려 주지 않아.
A: 그래도 예산이 없는데.
B: 일단 B로 가자. 다들 동의하지?
C: …음, 잘 모르겠어.`;

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

async function getJson(url, init) {
  const res = await fetch(url, init);
  const json = await res.json().catch(() => ({}));
  return { res, json };
}

async function main() {
  const report = [];

  // 1) health
  {
    const a = await getJson(`${EXTRACT_URL}/health`);
    assert(a.res.ok && a.json.ok, `extract health failed: ${JSON.stringify(a.json)}`);
    report.push("OK extract /health");

    const b = await getJson(`${ENGINE_URL}/health`);
    assert(b.res.ok && b.json.ok, `engine health failed: ${JSON.stringify(b.json)}`);
    report.push("OK engine /health");
  }

  // 2) extract text
  let transcript;
  {
    const { res, json } = await getJson(`${EXTRACT_URL}/v1/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: sampleText, language: "ko" }),
    });
    assert(res.ok && json.ok, `extract failed: ${JSON.stringify(json)}`);
    assert(json.transcript?.text, "transcript.text missing");
    assert(Array.isArray(json.transcript.segments), "segments missing");
    transcript = json.transcript;
    report.push(`OK extract /v1/extract (segments=${transcript.segments.length})`);
  }

  // 3) diagnose
  {
    const { res, json } = await getJson(`${ENGINE_URL}/v1/diagnose`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transcript,
        options: { max_questions: 3 },
      }),
    });
    assert(res.ok && json.ok, `diagnose failed: ${JSON.stringify(json)}`);
    assert(json.status === "done" || json.status === "rejected", "bad status");
    assert(Array.isArray(json.questions), "questions missing");
    assert(
      json.questions.every((question) => !question.text.includes("인가요일까요")),
      "question contains a duplicated Korean ending"
    );
    assert(
      json.questions.some((question) => question.text.includes("잘 모르겠어")),
      "questions are not grounded in the latest transcript"
    );
    report.push(
      `OK engine /v1/diagnose (status=${json.status}, n=${json.questions.length})`
    );
  }

  // 4) optional web BFF
  try {
    const h = await getJson(`${WEB_URL}/api/health`);
    if (h.res.ok && h.json.ok) {
      report.push("OK web /api/health");

      const ex = await getJson(`${WEB_URL}/api/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: sampleText }),
      });
      assert(ex.json.ok, `web extract proxy failed: ${JSON.stringify(ex.json)}`);

      const dg = await getJson(`${WEB_URL}/api/diagnose`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transcript: ex.json.transcript,
        }),
      });
      assert(dg.json.ok, `web diagnose proxy failed: ${JSON.stringify(dg.json)}`);
      report.push("OK web BFF extract→diagnose orchestration path");
    } else {
      report.push("SKIP web (not reachable or upstream down) — services-only OK");
    }
  } catch {
    report.push("SKIP web (not running) — services-only OK");
  }

  console.log("\n=== Q-Agent smoke test PASSED ===");
  for (const line of report) console.log(" -", line);
}

main().catch((err) => {
  console.error("\n=== Q-Agent smoke test FAILED ===");
  console.error(err.message || err);
  process.exit(1);
});
