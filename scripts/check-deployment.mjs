import { pathToFileURL } from "node:url";

// Does not print values: environment variables can contain credentials.
export function checkDeployment(env, target = "all") {
  const errors = [];
  if (!["all", "web", "realtime"].includes(target)) return ["target must be all, web, or realtime"];
  const value = (key) => (env[key] || "").trim();
  const publicUrl = (key, protocol, raw = value(key)) => {
    try {
      const url = new URL(raw);
      if (url.protocol !== protocol || url.username || url.password || url.hash || url.search) throw new Error();
      if (/^(localhost|127\.|0\.0\.0\.0$|\[::1\]$)/i.test(url.hostname) || /(^|\.)example(\.(com|org|net))?$/.test(url.hostname)) throw new Error();
      return url;
    } catch {
      errors.push(`${key} must be a production ${protocol}// URL without credentials, query, or fragment`);
      return null;
    }
  };
  if (value("REALTIME_API_KEY").length < 32 || /^(long-random-secret|change[-_]?me|your[-_])/i.test(value("REALTIME_API_KEY"))) {
    errors.push("REALTIME_API_KEY must be a random shared secret of at least 32 characters (same value on web and realtime)");
  }
  if (target !== "realtime") {
    publicUrl("REALTIME_SERVICE_URL", "https:");
    const ws = publicUrl("NEXT_PUBLIC_REALTIME_WS_URL", "wss:");
    if (ws && ws.pathname !== "/v1/realtime") errors.push("NEXT_PUBLIC_REALTIME_WS_URL path must be /v1/realtime");
  }
  if (target !== "web") {
    for (const [key, allowed] of [["LLM_PROVIDER", ["openai", "ollama"]], ["STT_PROVIDER", ["openai", "local"]]]) {
      if (!allowed.includes(value(key) || "openai")) errors.push(`${key} is not a supported provider`);
    }
    if ([value("LLM_PROVIDER") || "openai", value("STT_PROVIDER") || "openai"].includes("openai") && !value("OPENAI_API_KEY")) {
      errors.push("OPENAI_API_KEY is required on realtime for the selected provider");
    }
    const origins = value("CORS_ORIGIN").split(",").map(s => s.trim());
    for (const origin of origins) {
      const url = publicUrl("CORS_ORIGIN", "https:", origin);
      if (url && url.origin !== origin) errors.push("CORS_ORIGIN must contain origins only, without paths or trailing slash");
    }
    if (!value("REALTIME_DB_PATH")) errors.push("REALTIME_DB_PATH must point to persistent storage");
    for (const key of ["MAX_AUDIO_SESSIONS", "MAX_TEXT_SESSIONS", "SESSION_TTL_SECONDS"]) {
      if (value(key) && (!Number.isFinite(Number(value(key))) || Number(value(key)) <= 0)) errors.push(`${key} must be positive`);
    }
  }
  return errors;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const target = process.argv[2] || "all";
  const errors = checkDeployment(process.env, target);
  for (const error of errors) console.error(`FAIL ${error}`);
  if (errors.length) process.exitCode = 1;
  else console.log(`Deployment environment OK (${target}). Verify mounted DB storage and public HTTP/WSS connectivity after deployment.`);
}
