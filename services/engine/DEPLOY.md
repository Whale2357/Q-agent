# Deploy: Railway / Render
#
# Root directory / Dockerfile:
#   Build context = monorepo root
#   Dockerfile = services/engine/Dockerfile
#
# Required env:
#   OPENAI_API_KEY
#   ENGINE_MODE=live
#   PORT (platform-injected)
#   CORS_ORIGIN=https://<your-vercel-domain>
#
# Optional:
#   ENGINE_MODEL=gpt-4o-mini
#   ENGINE_SCORE_THRESHOLD=0.65
#   ENGINE_TOTAL_TIMEOUT_MS=35000
#
# After deploy, set apps/web:
#   ENGINE_SERVICE_URL=https://<engine-host>
#
# Health: GET /health  → { ok, mode, prompt_version }
