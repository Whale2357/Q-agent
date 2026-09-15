import type { ErrorResponse } from "@q-agent/contracts";

export function fail(
  code: ErrorResponse["error"]["code"],
  message: string,
  retryable = false
): ErrorResponse {
  return { ok: false, error: { code, message, retryable } };
}
