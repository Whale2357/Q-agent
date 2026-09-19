import { isTextMeetingSuccess } from "@q-agent/contracts";
import { guardRequest, readTextRequest, proxyRealtime } from "../../../../lib/realtime-proxy";

export const runtime = "nodejs";
export const maxDuration = 240;

export async function POST(request: Request) {
  const denied = guardRequest(request, "text");
  if (denied) return denied;
  const body = await readTextRequest(request);
  if (body instanceof Response) return body;
  return proxyRealtime(request, "/v1/text", isTextMeetingSuccess, body);
}
