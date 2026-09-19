import { isRealtimeSessionSuccess } from "@q-agent/contracts";
import { guardRequest, proxyRealtime } from "../../../../lib/realtime-proxy";

export async function POST(request: Request) {
  const denied = guardRequest(request, "session");
  return denied ?? proxyRealtime(request, "/v1/session", isRealtimeSessionSuccess);
}
