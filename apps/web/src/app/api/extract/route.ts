import { NextResponse } from "next/server";

const EXTRACT_SERVICE_URL =
  process.env.EXTRACT_SERVICE_URL || "http://localhost:4001";

export async function GET() {
  try {
    const res = await fetch(`${EXTRACT_SERVICE_URL}/health`, {
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
          message: e instanceof Error ? e.message : "extract unreachable",
          retryable: true,
        },
      },
      { status: 502 }
    );
  }
}

export async function POST(req: Request) {
  try {
    const contentType = req.headers.get("content-type") || "";
    let upstream: Response;

    if (contentType.includes("multipart/form-data")) {
      const form = await req.formData();
      upstream = await fetch(`${EXTRACT_SERVICE_URL}/v1/extract`, {
        method: "POST",
        body: form,
      });
    } else {
      const body = await req.json();
      upstream = await fetch(`${EXTRACT_SERVICE_URL}/v1/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    }

    const data = await upstream.json();
    return NextResponse.json(data, { status: upstream.status });
  } catch (e) {
    return NextResponse.json(
      {
        ok: false,
        error: {
          code: "EXTRACT_FAILED",
          message: e instanceof Error ? e.message : "extract proxy failed",
          retryable: true,
        },
      },
      { status: 502 }
    );
  }
}
