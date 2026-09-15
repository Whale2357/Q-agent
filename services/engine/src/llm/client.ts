import OpenAI from "openai";

const DEFAULT_TIMEOUT_MS = Number(process.env.ENGINE_LLM_TIMEOUT_MS || 20000);

export class LlmTimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LlmTimeoutError";
  }
}

let client: OpenAI | null = null;

export function getOpenAI(): OpenAI {
  const key = process.env.OPENAI_API_KEY;
  if (!key) {
    throw new Error("OPENAI_API_KEY is not set");
  }
  if (!client) {
    client = new OpenAI({ apiKey: key, timeout: DEFAULT_TIMEOUT_MS });
  }
  return client;
}

export function getModel(kind: "generate" | "score" = "generate"): string {
  if (kind === "score") {
    return (
      process.env.ENGINE_MODEL_SCORE ||
      process.env.ENGINE_MODEL ||
      "gpt-4o-mini"
    );
  }
  return process.env.ENGINE_MODEL_GENERATE || process.env.ENGINE_MODEL || "gpt-4o-mini";
}

export async function chatJson(params: {
  system: string;
  user: string;
  model?: string;
  timeoutMs?: number;
  temperature?: number;
}): Promise<string> {
  const openai = getOpenAI();
  const timeoutMs = params.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  const work = openai.chat.completions.create({
    model: params.model || getModel("generate"),
    temperature: params.temperature ?? 0.3,
    response_format: { type: "json_object" },
    messages: [
      { role: "system", content: params.system },
      { role: "user", content: params.user },
    ],
  });

  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const result = await Promise.race([
      work,
      new Promise<never>((_, reject) => {
        timer = setTimeout(
          () => reject(new LlmTimeoutError(`LLM timed out after ${timeoutMs}ms`)),
          timeoutMs
        );
      }),
    ]);
    const content = result.choices[0]?.message?.content;
    if (!content) throw new Error("Empty LLM response");
    return content;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export function parseJsonObject(raw: string): unknown {
  const trimmed = raw.trim();
  try {
    return JSON.parse(trimmed);
  } catch {
    const start = trimmed.indexOf("{");
    const end = trimmed.lastIndexOf("}");
    if (start >= 0 && end > start) {
      return JSON.parse(trimmed.slice(start, end + 1));
    }
    throw new Error("Failed to parse LLM JSON");
  }
}
