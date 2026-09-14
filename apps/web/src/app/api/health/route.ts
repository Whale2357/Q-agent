import { NextResponse } from "next/server";

const EXTRACT_SERVICE_URL =
  process.env.EXTRACT_SERVICE_URL || "http://localhost:4001";
const ENGINE_SERVICE_URL =
  process.env.ENGINE_SERVICE_URL || "http://localhost:4002";

export async function GET() {
  const checks = await Promise.allSettled([
    fetch(`${EXTRACT_SERVICE_URL}/health`, { cache: "no-store" }).then((r) =>
      r.json()
    ),
    fetch(`${ENGINE_SERVICE_URL}/health`, { cache: "no-store" }).then((r) =>
      r.json()
    ),
  ]);

  const extract =
    checks[0].status === "fulfilled"
      ? checks[0].value
      : { ok: false, error: String(checks[0].reason) };
  const engine =
    checks[1].status === "fulfilled"
      ? checks[1].value
      : { ok: false, error: String(checks[1].reason) };

  const ok = Boolean(extract?.ok) && Boolean(engine?.ok);
  return NextResponse.json(
    {
      ok,
      service: "web-bff",
      upstream: { extract, engine },
      ts: new Date().toISOString(),
    },
    { status: ok ? 200 : 503 }
  );
}
