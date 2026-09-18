import { NextResponse } from "next/server";

const REALTIME_SERVICE_URL =
  process.env.REALTIME_SERVICE_URL || "http://127.0.0.1:8765";
const REALTIME_API_KEY = process.env.REALTIME_API_KEY || "";

function upstreamHeaders(init?: HeadersInit): Headers {
  const headers = new Headers(init);
  if (REALTIME_API_KEY) {
    headers.set("Authorization", `Bearer ${REALTIME_API_KEY}`);
  }
  return headers;
}

export async function POST() {
  try {
    const upstream = await fetch(`${REALTIME_SERVICE_URL}/v1/session`, {
      method: "POST",
      headers: upstreamHeaders(),
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
      { status: 502 }
    );
  }
}
