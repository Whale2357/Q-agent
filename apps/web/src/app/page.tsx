"use client";

import { useMemo, useState } from "react";
import type {
  DiagnoseResponse,
  ExtractResponse,
  MeetingPreset,
  ToneLevel,
} from "@q-agent/contracts";

const SAMPLE = `A: 나는 A안이 맞다고 봐. 비용이 중요해.
B: 아니 B안이 더 빨라. 시장이 기다려 주지 않아.
A: 그래도 예산이 없는데.
B: 일단 B로 가자. 다들 동의하지?
C: …음, 잘 모르겠어.`;

export default function HomePage() {
  const [text, setText] = useState(SAMPLE);
  const [preset, setPreset] = useState<MeetingPreset>("decision");
  const [tone, setTone] = useState<ToneLevel>(2);
  const [status, setStatus] = useState("idle");
  const [result, setResult] = useState<DiagnoseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canRun = useMemo(() => text.trim().length > 0, [text]);

  async function runDiagnose() {
    setError(null);
    setResult(null);
    setStatus("extracting");
    try {
      const extractRes = await fetch("/api/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, language: "ko" }),
      });
      const extractJson = (await extractRes.json()) as ExtractResponse;
      if (!extractJson.ok) {
        throw new Error(extractJson.error.message);
      }

      setStatus("generating+selecting");
      const diagnoseRes = await fetch("/api/diagnose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transcript: extractJson.transcript,
          preset,
          tone,
          options: { max_questions: 3 },
        }),
      });
      const diagnoseJson = (await diagnoseRes.json()) as DiagnoseResponse;
      if (!diagnoseJson.ok) {
        throw new Error(diagnoseJson.error.message);
      }
      setResult(diagnoseJson);
      setStatus(diagnoseJson.status);
    } catch (e) {
      setStatus("error");
      setError(e instanceof Error ? e.message : "unknown error");
    }
  }

  return (
    <main>
      <h1>Q-Agent</h1>
      <p className="lead">
        질문을 많이 만드는 AI가 아니라, 평가·선별·반려하는 인지 증강 엔진.
        (골격: 프론트 BFF → extract → engine)
      </p>

      <section className="panel">
        <label htmlFor="log">회의 로그 (텍스트)</label>
        <textarea
          id="log"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />

        <div className="row">
          <div>
            <label htmlFor="preset">프리셋</label>
            <select
              id="preset"
              value={preset}
              onChange={(e) => setPreset(e.target.value as MeetingPreset)}
            >
              <option value="decision">decision (의사결정)</option>
              <option value="problem">problem (문제해결)</option>
            </select>
          </div>
          <div>
            <label htmlFor="tone">톤 (1직설~4우회)</label>
            <select
              id="tone"
              value={tone}
              onChange={(e) => setTone(Number(e.target.value) as ToneLevel)}
            >
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
              <option value={4}>4</option>
            </select>
          </div>
          <div style={{ display: "flex", alignItems: "end" }}>
            <button disabled={!canRun || status.includes("ing")} onClick={runDiagnose}>
              현재 대화 진단하기
            </button>
          </div>
        </div>
        <div className="status">status: {status}</div>
        {error && <p className="reject">{error}</p>}
      </section>

      {result && result.ok && result.rejected && (
        <section className="panel reject">
          <strong>의도적 반려</strong>
          <p>{result.reject_reason}</p>
        </section>
      )}

      {result && result.ok && !result.rejected && (
        <section className="panel">
          <strong>선별된 질문</strong>
          {result.questions.map((q) => (
            <article key={q.id} className="card">
              <div>{q.text}</div>
              <div className="badges">
                {q.badges.map((b) => (
                  <span key={b} className="badge">
                    {b}
                  </span>
                ))}
              </div>
              <p className="status">{q.rationale}</p>
            </article>
          ))}
          <pre>{JSON.stringify(result.pipeline, null, 2)}</pre>
        </section>
      )}
    </main>
  );
}
