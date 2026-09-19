/**
 * Smoke test: web BFF ↔ realtime
 *
 *   node scripts/smoke-test.mjs
 *   WEB_URL=http://localhost:3000 node scripts/smoke-test.mjs
 *   Add --with-models to exercise real generation (provider charges apply).
 */
const REALTIME_URL = process.env.REALTIME_SERVICE_URL || "http://127.0.0.1:8765";
const WEB_URL = process.env.WEB_URL || "";
const REALTIME_API_KEY = process.env.REALTIME_API_KEY || "";
const WITH_MODELS = process.argv.includes("--with-models");

const SAMPLE_TEXT = [
  "오늘 회의에서는 Q-Agent 배포 범위를 확정하자.",
  "웹은 realtime만 쓰고 레거시 extract/engine은 제거한다.",
  "스모크 테스트는 health와 텍스트 진단만 검증한다.",
].join("\n");

function authHeaders(extra = {}) {
  const headers = { ...extra };
  if (REALTIME_API_KEY) {
    headers.Authorization = `Bearer ${REALTIME_API_KEY}`;
  }
  return headers;
}

async function getJson(url, init) {
  const res = await fetch(url, { ...init, signal: AbortSignal.timeout(210_000) });
  let json = null;
  try {
    json = await res.json();
  } catch {
    json = null;
  }
  return { res, json };
}

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

async function main() {
  const report = [];

  const health = await getJson(`${REALTIME_URL}/health`);
  assert(
    health.res.ok && health.json?.ok,
    `realtime health failed: ${JSON.stringify(health.json)}`
  );
  report.push("OK realtime /health");

  const session = await getJson(`${REALTIME_URL}/v1/session`, {
    method: "POST",
    headers: authHeaders(),
  });
  assert(
    session.res.ok && session.json?.ok && session.json?.token,
    `realtime /v1/session failed: ${JSON.stringify(session.json)}`
  );
  report.push("OK realtime /v1/session");

  if (WITH_MODELS) {
    const text = await getJson(`${REALTIME_URL}/v1/text`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ text: SAMPLE_TEXT, language: "ko" }),
    });
    assert(text.res.ok && text.json?.ok, `realtime /v1/text failed: ${JSON.stringify(text.json)}`);
    assert(text.json.diagnosis, "realtime /v1/text missing diagnosis");
    report.push("OK realtime /v1/text");
  } else {
    report.push("SKIP model generation (add --with-models; consumes provider credits)");
  }

  if (WEB_URL) {
    const webHealth = await getJson(`${WEB_URL}/api/health`);
    assert(
      webHealth.res.ok && webHealth.json?.ok && webHealth.json?.upstream?.realtime?.ok,
      `web /api/health failed: ${JSON.stringify(webHealth.json)}`
    );
    report.push("OK web /api/health → realtime");

    const webSession = await getJson(`${WEB_URL}/api/realtime/session`, {
      method: "POST",
    });
    assert(
      webSession.res.ok && webSession.json?.ok && webSession.json?.token,
      `web /api/realtime/session failed: ${JSON.stringify(webSession.json)}`
    );
    report.push("OK web BFF /api/realtime/session");

    if (WITH_MODELS) {
      const webText = await getJson(`${WEB_URL}/api/realtime/text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: SAMPLE_TEXT, language: "ko" }),
      });
      assert(
        webText.res.ok && webText.json?.ok,
        `web /api/realtime/text failed: ${JSON.stringify(webText.json)}`
      );
      report.push("OK web BFF /api/realtime/text");
    }
  } else {
    report.push("SKIP web BFF (set WEB_URL to include)");
  }

  console.log("\n=== Q-Agent smoke test PASSED ===");
  for (const line of report) console.log(` - ${line}`);
}

main().catch((err) => {
  console.error("\n=== Q-Agent smoke test FAILED ===");
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
