import { MAX_TEXT_CHARACTERS, MAX_TEXT_REQUEST_BYTES, type ErrorCode } from "@q-agent/contracts";

export function apiError(code: ErrorCode, message: string, status: number, retryable = false) {
  return Response.json({ ok: false, error: { code, message, retryable } }, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

// Defense in depth for a single BFF process. Multi-instance deployments must also
// configure a shared gateway/WAF limit; forwarded IP headers must be trusted there.
const requests = new Map<string, { count: number; resetAt: number }>();
export function guardRequest(request: Request, operation: "text" | "session"): Response | null {
  const origin = request.headers.get("origin");
  const allowedOrigins = (process.env.WEB_ALLOWED_ORIGINS ?? "").split(",").map((item) => item.trim()).filter(Boolean);
  // Next's standalone Request.url may use its internal localhost hostname.
  // Host represents the requested site; do not trust arbitrary forwarded hosts.
  let sameHost = false;
  if (origin) {
    try {
      const parsed = new URL(origin);
      sameHost = ["https:", "http:"].includes(parsed.protocol)
        && parsed.origin === origin
        && parsed.host === (request.headers.get("host") ?? new URL(request.url).host);
    } catch { /* Invalid Origin is denied below. */ }
  }
  if (request.headers.get("sec-fetch-site") === "cross-site"
    || (origin && !(allowedOrigins.length ? allowedOrigins.includes(origin) : sameHost))) {
    return apiError("UNAUTHORIZED", "허용되지 않은 요청입니다.", 403);
  }
  const now = Date.now();
  for (const [key, entry] of requests) if (entry.resetAt <= now) requests.delete(key);
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
  const key = `${operation}:${ip}`;
  const entry = requests.get(key) ?? { count: 0, resetAt: now + 60_000 };
  if (entry.count >= (operation === "text" ? 6 : 12) || (!requests.has(key) && requests.size >= 10_000)) {
    const response = apiError("RATE_LIMITED", "요청이 많습니다. 잠시 후 다시 시도해 주세요.", 429, true);
    response.headers.set("Retry-After", String(Math.max(1, Math.ceil((entry.resetAt - now) / 1000))));
    return response;
  }
  entry.count += 1;
  requests.set(key, entry);
  return null;
}

export async function readTextRequest(request: Request): Promise<{ text: string; language: string } | Response> {
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    return apiError("INVALID_INPUT", "JSON 형식으로 요청해 주세요.", 415);
  }
  if (Number(request.headers.get("content-length")) > MAX_TEXT_REQUEST_BYTES) {
    return apiError("INVALID_INPUT", "요청 본문이 너무 큽니다.", 413);
  }
  const reader = request.body?.getReader();
  if (!reader) return apiError("INVALID_INPUT", "분석할 텍스트가 필요합니다.", 400);
  const decoder = new TextDecoder();
  let size = 0;
  let content = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_TEXT_REQUEST_BYTES) {
        void reader.cancel().catch(() => undefined);
        return apiError("INVALID_INPUT", "요청 본문이 너무 큽니다.", 413);
      }
      content += decoder.decode(value, { stream: true });
    }
    content += decoder.decode();
    const body: unknown = JSON.parse(content);
    if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("invalid body");
    const { text, language = "ko" } = body as { text?: unknown; language?: unknown };
    if (typeof text !== "string" || text.trim().length < 8 || text.length > MAX_TEXT_CHARACTERS
      || typeof language !== "string" || !/^[a-z]{2,3}(?:-[A-Za-z]{2,4})?$/.test(language)) {
      return apiError("INVALID_INPUT", `텍스트는 8자 이상 ${MAX_TEXT_CHARACTERS.toLocaleString("ko-KR")}자 이하로 입력해 주세요.`, 400);
    }
    return { text: text.trim(), language };
  } catch {
    return apiError("INVALID_INPUT", "요청 형식을 확인해 주세요.", 400);
  } finally {
    reader.releaseLock();
  }
}

export async function proxyRealtime(request: Request, path: string, validate: (value: unknown) => boolean, body?: unknown) {
  const baseUrl = (process.env.REALTIME_SERVICE_URL || "http://127.0.0.1:8765").replace(/\/$/, "");
  const apiKey = process.env.REALTIME_API_KEY;
  const timeoutMs = path === "/v1/text" ? 200_000 : 15_000;
  try {
    const upstream = await fetch(`${baseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(timeoutMs)]),
    });
    if (!upstream.ok) {
      // Do not expose provider errors, internal addresses or authentication details.
      const status = [400, 413, 422, 429, 503, 504].includes(upstream.status) ? upstream.status : 502;
      return apiError(status === 429 ? "RATE_LIMITED" : status === 400 || status === 422 || status === 413 ? "INVALID_INPUT" : "REALTIME_UNAVAILABLE",
        status === 429 || status === 503 ? "서버가 사용 중입니다. 잠시 후 다시 시도해 주세요." : "요청을 처리하지 못했습니다. 입력 또는 서버 상태를 확인해 주세요.", status, status >= 429);
    }
    const data: unknown = await upstream.json();
    if (!validate(data)) throw new Error("Invalid upstream response");
    return Response.json(data, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const timedOut = error instanceof Error && ["TimeoutError", "AbortError"].includes(error.name);
    return apiError(timedOut ? "LLM_TIMEOUT" : "REALTIME_UNAVAILABLE",
      timedOut ? "처리 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요." : "분석 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.", timedOut ? 504 : 502, true);
  }
}
