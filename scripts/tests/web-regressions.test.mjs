import test from "node:test";
import assert from "node:assert/strict";
import { PcmResampler } from "../../apps/web/src/lib/audio-resampler.ts";
import { guardRequest, readTextRequest, proxyRealtime } from "../../apps/web/src/lib/realtime-proxy.ts";
import { isDiagnosisSuccess } from "@q-agent/contracts";

test("streaming resampling preserves timing across block boundaries", () => {
  const resampler = new PcmResampler(44100);
  let count = 0;
  for (let i = 0; i < 100; i++) {
    const output = resampler.process(new Float32Array(4096).fill(.25));
    count += output.length;
    assert.ok(output.every(value => Math.abs(value - .25) < 1e-6));
  }
  assert.ok(Math.abs(count - 409600 * 16000 / 44100) < 1);
});
test("8 kHz files are upsampled to the promised 16 kHz PCM", () => {
  assert.equal(new PcmResampler(8000).process(new Float32Array(8000)).length, 16000);
});
test("silence is retained and nonfinite audio is sanitized", () => {
  const output = new PcmResampler(16000).process(new Float32Array([0, 0, NaN, Infinity, 2]));
  assert.deepEqual([...output], [0, 0, 0, 0, 1]);
});
test("cross-site API requests cannot mint session tickets", () => {
  const response = guardRequest(new Request("https://stein.test/api/realtime/session", { method: "POST", headers: { Origin: "https://attacker.test" } }), "session");
  assert.equal(response.status, 403);
});
test("standalone internal URL does not reject the public same-origin Host", () => {
  const request = new Request("http://localhost:3000/api/realtime/session", {
    method: "POST", headers: { Host: "stein.test", Origin: "https://stein.test", "sec-fetch-site": "same-origin" },
  });
  assert.equal(guardRequest(request, "session"), null);
});
test("spoofed forwarded host does not allow a foreign Origin", () => {
  const request = new Request("http://localhost:3000/api/realtime/session", {
    method: "POST", headers: { Host: "stein.test", Origin: "https://attacker.test", "x-forwarded-host": "attacker.test" },
  });
  assert.equal(guardRequest(request, "session").status, 403);
});
test("malformed and oversized JSON are rejected before contacting backend", async () => {
  for (const body of ["[]", "{", JSON.stringify({ text: "x".repeat(100001) })]) {
    const result = await readTextRequest(new Request("http://localhost/api", { method: "POST", headers: { "Content-Type": "application/json" }, body }));
    assert.ok(result instanceof Response);
    assert.equal(result.status, 400);
  }
});
test("valid text is normalized", async () => {
  const result = await readTextRequest(new Request("http://localhost/api", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: "  QA 완료 기준을 정합시다.  " }) }));
  assert.deepEqual(result, { text: "QA 완료 기준을 정합시다.", language: "ko" });
});
test("upstream secrets are not forwarded in error responses", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ error: "secret-provider-key" }, { status: 401 });
  try {
    const response = await proxyRealtime(new Request("http://localhost"), "/v1/text", () => true, {});
    assert.equal(response.status, 502);
    assert.ok(!(await response.text()).includes("secret-provider-key"));
  } finally { globalThis.fetch = original; }
});
test("invalid stored diagnoses cannot crash question rendering", () => {
  assert.equal(isDiagnosisSuccess(null), false);
  assert.equal(isDiagnosisSuccess({ ok: true, questions: [null] }), false);
});
