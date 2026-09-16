import { NextResponse } from "next/server";

const REALTIME_SERVICE_URL =
  process.env.REALTIME_SERVICE_URL || "http://127.0.0.1:8765";

export async function GET() {
  const check = await Promise.allSettled([
    fetch(`${REALTIME_SERVICE_URL}/health`, { cache: "no-store" }).then((response) =>
      response.json()
    ),
  ]);
  const realtime =
    check[0].status === "fulfilled"
      ? check[0].value
      : { ok: false, error: String(check[0].reason) };
  const ok = Boolean(realtime?.ok);
  return NextResponse.json(
    {
      ok,
      service: "web-bff",
      upstream: { realtime },
      ts: new Date().toISOString(),
    },
    { status: ok ? 200 : 503 }
  );
}
