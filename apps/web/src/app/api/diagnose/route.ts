import { NextResponse } from "next/server";

const ENGINE_SERVICE_URL =
  process.env.ENGINE_SERVICE_URL || "http://localhost:4002";

export async function GET() {
  try {
    const res = await fetch(`${ENGINE_SERVICE_URL}/health`, {
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json({ ok: true, upstream: data });
  } catch (e) {
    return NextResponse.json(
      {
        ok: false,
        error: {
          code: "INTERNAL",
          message: e instanceof Error ? e.message : "engine unreachable",
          retryable: true,
        },
      },
      { status: 502 }
    );
  }
}

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const upstream = await fetch(`${ENGINE_SERVICE_URL}/v1/diagnose`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await upstream.json();
    return NextResponse.json(data, { status: upstream.status });
  } catch (e) {
    return NextResponse.json(
      {
        ok: false,
        error: {
          code: "INTERNAL",
          message: e instanceof Error ? e.message : "diagnose proxy failed",
          retryable: true,
        },
      },
      { status: 502 }
    );
  }
}
