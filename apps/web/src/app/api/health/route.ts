export async function GET() {
  const baseUrl = (process.env.REALTIME_SERVICE_URL || "http://127.0.0.1:8765").replace(/\/$/, "");
  let ok = false;
  try {
    const response = await fetch(`${baseUrl}/health`, { cache: "no-store", redirect: "error", signal: AbortSignal.timeout(7000) });
    const data = await response.json();
    ok = response.ok && data?.ok === true;
  } catch { /* Keep provider and network details out of public health responses. */ }
  return Response.json({ ok, service: "web-bff", upstream: { realtime: { ok } }, ts: new Date().toISOString() }, {
    status: ok ? 200 : 503, headers: { "Cache-Control": "no-store" },
  });
}
