import cors from "cors";
import express from "express";
import { CONTRACT_VERSION, type DiagnoseRequest } from "@q-agent/contracts";
import { LlmTimeoutError } from "./llm/client";
import { fail } from "./lib";
import { diagnose, resolveMode } from "./pipeline/diagnose";
import { PROMPT_VERSION } from "./pipeline/types";

const PORT = Number(process.env.ENGINE_PORT || process.env.PORT || 4002);
const CORS_ORIGIN = process.env.CORS_ORIGIN || "http://localhost:3000";

const app = express();
app.use(cors({ origin: CORS_ORIGIN }));
app.use(express.json({ limit: "2mb" }));

app.get("/health", (_req, res) => {
  res.json({
    ok: true,
    service: "engine",
    contract_version: CONTRACT_VERSION,
    prompt_version: PROMPT_VERSION,
    mode: resolveMode(),
    ts: new Date().toISOString(),
  });
});

app.post("/v1/diagnose", async (req, res) => {
  try {
    const body = req.body as DiagnoseRequest;
    if (!body?.transcript?.text || !body.preset || !body.tone) {
      return res.status(400).json(
        fail(
          "INVALID_INPUT",
          "transcript.text, preset, tone 필드가 필요합니다.",
          false
        )
      );
    }
    if (body.preset !== "decision" && body.preset !== "problem") {
      return res
        .status(400)
        .json(fail("INVALID_INPUT", "preset은 decision|problem 이어야 합니다."));
    }
    if (![1, 2, 3, 4].includes(Number(body.tone))) {
      return res
        .status(400)
        .json(fail("INVALID_INPUT", "tone은 1~4 이어야 합니다."));
    }

    const result = await diagnose(body);
    return res.json(result);
  } catch (err) {
    console.error("[engine]", err);
    if (err instanceof LlmTimeoutError) {
      return res
        .status(504)
        .json(fail("LLM_TIMEOUT", err.message, true));
    }
    return res
      .status(500)
      .json(fail("INTERNAL", "진단 중 오류가 발생했습니다.", true));
  }
});

app.listen(PORT, () => {
  console.log(
    `[engine] listening on http://localhost:${PORT} mode=${resolveMode()}`
  );
});
