import test from "node:test";
import assert from "node:assert/strict";
import { checkDeployment } from "../check-deployment.mjs";

const production = {
  REALTIME_API_KEY: "test-only-" + "a".repeat(32),
  OPENAI_API_KEY: "test-only-provider-key",
  REALTIME_SERVICE_URL: "https://api.stein.test",
  NEXT_PUBLIC_REALTIME_WS_URL: "wss://api.stein.test/v1/realtime",
  CORS_ORIGIN: "https://stein.test,https://preview.stein.test",
  REALTIME_DB_PATH: "/app/data/stein.db",
};

test("valid split-host deployment passes without exposing values", () => {
  assert.deepEqual(checkDeployment(production), []);
  assert.deepEqual(checkDeployment({ ...production, OPENAI_API_KEY: "" }, "web"), []);
});
test("insecure or credential-bearing URLs and weak secrets are rejected", () => {
  const errors = checkDeployment({ ...production, REALTIME_SERVICE_URL: "https://secret@api.stein.test", NEXT_PUBLIC_REALTIME_WS_URL: "ws://localhost:8765", REALTIME_API_KEY: "weak" });
  assert.ok(errors.length >= 3);
  assert.ok(!errors.join(" ").includes("secret@"));
});
test("wildcard CORS and missing provider key cannot pass readiness", () => {
  const errors = checkDeployment({ ...production, CORS_ORIGIN: "*", OPENAI_API_KEY: "" }, "realtime");
  assert.ok(errors.some(x => x.startsWith("CORS_ORIGIN")));
  assert.ok(errors.some(x => x.startsWith("OPENAI_API_KEY")));
});
test("websocket endpoint and CORS path mistakes are detected", () => {
  const errors = checkDeployment({ ...production, NEXT_PUBLIC_REALTIME_WS_URL: "wss://api.stein.test", CORS_ORIGIN: "https://stein.test/path" });
  assert.equal(errors.length, 2);
});
