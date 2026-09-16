import { NextResponse } from "next/server";

const REALTIME_SERVICE_URL =
  process.env.REALTIME_SERVICE_URL || "http://127.0.0.1:8765";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const upstream = await fetch(`${REALTIME_SERVICE_URL}/v1/text`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = await upstream.json();
    return NextResponse.json(data, { status: upstream.status });
  } catch (error) {
    return NextResponse.json(
      {
        ok: false,
        error: {
          code: "REALTIME_UNAVAILABLE",
          message:
            error instanceof Error
              ? error.message
              : "realtime service unavailable",
          retryable: true,
        },
      },
      { status: 502 },
    );
  }
}
