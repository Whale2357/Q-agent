import cors from "cors";
import express from "express";
import multer from "multer";
import { CONTRACT_VERSION } from "@q-agent/contracts";
import { fail, normalizeTextToTranscript, success } from "./lib";

const PORT = Number(process.env.EXTRACT_PORT || process.env.PORT || 4001);
const CORS_ORIGIN = process.env.CORS_ORIGIN || "http://localhost:3000";

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 25 * 1024 * 1024 },
});

const app = express();
app.use(cors({ origin: CORS_ORIGIN }));
app.use(express.json({ limit: "2mb" }));

app.get("/health", (_req, res) => {
  res.json({
    ok: true,
    service: "extract",
    contract_version: CONTRACT_VERSION,
    ts: new Date().toISOString(),
  });
});

/**
 * POST /v1/extract
 * - JSON { text, language? }
 * - multipart: file + optional text/language
 */
app.post("/v1/extract", upload.single("file"), (req, res) => {
  try {
    const language =
      (typeof req.body?.language === "string" && req.body.language) || "ko";
    const text =
      typeof req.body?.text === "string" ? req.body.text.trim() : "";

    if (text) {
      return res.json(success(normalizeTextToTranscript(text, "text", language)));
    }

    if (req.file) {
      // Stub STT: treat utf-8 buffer as text if possible; otherwise placeholder.
      let decoded = "";
      try {
        decoded = req.file.buffer.toString("utf8").trim();
      } catch {
        decoded = "";
      }
      const stubText =
        decoded && !decoded.includes("\u0000")
          ? decoded
          : `[audio:${req.file.originalname || "upload"}] STT 미연동 스텁입니다. 텍스트 입력을 사용하세요.`;
      return res.json(
        success(normalizeTextToTranscript(stubText, "audio", language))
      );
    }

    return res.status(400).json(
      fail("INVALID_INPUT", "text 또는 file 중 하나가 필요합니다.", false)
    );
  } catch (err) {
    console.error("[extract]", err);
    return res
      .status(500)
      .json(fail("EXTRACT_FAILED", "추출 중 오류가 발생했습니다.", true));
  }
});

app.listen(PORT, () => {
  console.log(`[extract] listening on http://localhost:${PORT}`);
});
