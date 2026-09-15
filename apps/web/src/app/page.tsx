"use client";

import {
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import type {
  BadgeCode,
  DiagnoseResponse,
  ExtractResponse,
  MeetingPreset,
  PipelineStatus,
  QuestionCategory,
  ToneLevel,
} from "@q-agent/contracts";

const SAMPLES: Record<MeetingPreset, string> = {
  decision: `A: 나는 A안이 맞다고 봐. 지금은 비용이 가장 중요해.
B: 아니, B안이 더 빨라. 시장이 기다려 주지 않아.
A: 그래도 지금 예산으로는 위험해.
B: 일단 B로 가자. 다들 동의하지?
C: …음, 잘 모르겠어.`,
  problem: `A: 전환율이 떨어졌어. 랜딩 카피를 바꿔야 해.
B: 맞아, 버튼 색도 바꿔보자.
A: 지난번에도 카피를 바꿨는데 결과가 같았잖아.
B: 그래도 카피가 문제야. 다들 그렇게 말하잖아.`,
};

const TONE_LABELS: Record<ToneLevel, string> = {
  1: "직설",
  2: "명확·존중",
  3: "부드럽게",
  4: "우회",
};

const CATEGORY_LABELS: Record<QuestionCategory, string> = {
  blind_spot: "맹점",
  essence: "본질",
  expansion: "확장",
};

const BADGE_LABELS: Record<BadgeCode, string> = {
  info_gain: "정보 이득",
  non_redundant: "비중복",
  relevant: "높은 관련성",
  depth: "깊이",
  assumption: "가정 발견",
};

type InputMode = "text" | "audio";
type UiStatus = "idle" | PipelineStatus;

function Icon({ name }: { name: "spark" | "upload" | "copy" | "arrow" | "check" }) {
  const paths = {
    spark: <path d="m12 3 1.1 3.9L17 8l-3.9 1.1L12 13l-1.1-3.9L7 8l3.9-1.1L12 3Zm5.5 9 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3ZM6 13l.9 3.1L10 17l-3.1.9L6 21l-.9-3.1L2 17l3.1-.9L6 13Z" />,
    upload: <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v5h14v-5" />,
    copy: <><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    check: <path d="m5 12 4 4L19 6" />,
  };

  return <svg viewBox="0 0 24 24" aria-hidden="true" className="icon">{paths[name]}</svg>;
}

export default function HomePage() {
  const [inputMode, setInputMode] = useState<InputMode>("text");
  const [text, setText] = useState(SAMPLES.decision);
  const [file, setFile] = useState<File | null>(null);
  const [preset, setPreset] = useState<MeetingPreset>("decision");
  const [tone, setTone] = useState<ToneLevel>(2);
  const [status, setStatus] = useState<UiStatus>("idle");
  const [result, setResult] = useState<DiagnoseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const selectingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const canRun = inputMode === "text" ? text.trim().length > 0 : Boolean(file);
  const isRunning = ["extracting", "generating", "selecting"].includes(status);
  const transcriptPreview = useMemo(
    () => text.split("\n").map((line) => line.trim()).filter(Boolean).slice(0, 5),
    [text],
  );

  function loadSample(nextPreset: MeetingPreset) {
    setPreset(nextPreset);
    setText(SAMPLES[nextPreset]);
    setInputMode("text");
    setFile(null);
    setResult(null);
    setError(null);
    setStatus("idle");
  }

  async function runDiagnose() {
    if (!canRun || isRunning) return;
    setError(null);
    setResult(null);
    setStatus("extracting");

    try {
      let extractRes: Response;
      if (inputMode === "audio" && file) {
        const form = new FormData();
        form.append("file", file);
        form.append("language", "ko");
        extractRes = await fetch("/api/extract", { method: "POST", body: form });
      } else {
        extractRes = await fetch("/api/extract", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, language: "ko" }),
        });
      }

      const extractJson = (await extractRes.json()) as ExtractResponse;
      if (!extractJson.ok) throw new Error(extractJson.error.message);

      setStatus("generating");
      selectingTimer.current = setTimeout(() => setStatus("selecting"), 700);
      const diagnoseRes = await fetch("/api/diagnose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transcript: extractJson.transcript,
          preset,
          tone,
          options: { max_questions: 3, recent_turn_window: 12 },
        }),
      });
      const diagnoseJson = (await diagnoseRes.json()) as DiagnoseResponse;
      if (!diagnoseJson.ok) throw new Error(diagnoseJson.error.message);

      if (selectingTimer.current) clearTimeout(selectingTimer.current);
      setResult(diagnoseJson);
      setStatus(diagnoseJson.status);
    } catch (caught) {
      if (selectingTimer.current) clearTimeout(selectingTimer.current);
      setStatus("error");
      setError(caught instanceof Error ? caught.message : "진단 중 알 수 없는 오류가 발생했습니다.");
    }
  }

  async function copyQuestion(id: string, question: string) {
    await navigator.clipboard.writeText(question);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1400);
  }

  function trackGlassLight(event: ReactPointerEvent<HTMLElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.setProperty("--glass-x", `${event.clientX - bounds.left}px`);
    event.currentTarget.style.setProperty("--glass-y", `${event.clientY - bounds.top}px`);
  }

  return (
    <main className="site-shell">
      <div className="ambient-light ambient-light-one" aria-hidden="true" />
      <div className="ambient-light ambient-light-two" aria-hidden="true" />
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Q-Agent 홈">
          <span className="brand-mark"><Icon name="spark" /></span><span>Q-Agent</span>
        </a>
        <span className="brand-subtitle">Meeting reasoning copilot</span>
        <div className="service-state"><span aria-hidden="true" />서비스 준비됨</div>
      </header>

      <div id="top" className="page-content">
        <section className="hero" aria-labelledby="hero-title">
          <div>
            <p className="eyebrow">Evaluation-first AI</p>
            <h1 id="hero-title">회의가 막힌 순간,<br /><em>가장 가치 있는 질문만.</em></h1>
            <p className="hero-copy">회의 맥락을 읽고 후보 질문을 생성·평가한 뒤, 기준을 넘은 질문만 안전한 톤으로 건넵니다.</p>
          </div>
          <div className="hero-proof" aria-label="Q-Agent 처리 방식">
            <span>Generate</span><Icon name="arrow" /><span>Evaluate</span><Icon name="arrow" /><strong>Curate</strong>
          </div>
        </section>

        <section className="workspace" aria-label="회의 질문 진단 워크스페이스" onPointerMove={trackGlassLight}>
          <div className="input-panel">
            <div className="panel-heading">
              <div><span className="step-number">01</span><div><h2>회의 맥락</h2><p>텍스트를 붙여넣거나 음성을 업로드하세요.</p></div></div>
              <div className="mode-tabs" role="tablist" aria-label="입력 방식">
                <button type="button" role="tab" aria-selected={inputMode === "text"} onClick={() => setInputMode("text")}>텍스트</button>
                <button type="button" role="tab" aria-selected={inputMode === "audio"} onClick={() => setInputMode("audio")}>음성</button>
              </div>
            </div>

            <div className="sample-row">
              <span>샘플 불러오기</span>
              <button type="button" onClick={() => loadSample("decision")}>의사결정 교착</button>
              <button type="button" onClick={() => loadSample("problem")}>문제 원인 고착</button>
            </div>

            {inputMode === "text" ? (
              <div className="text-input-wrap">
                <label htmlFor="meeting-log" className="sr-only">회의 로그</label>
                <textarea id="meeting-log" value={text} onChange={(event) => setText(event.target.value)} placeholder="A: 이번 분기 우선순위는…" />
                <span className="character-count">{text.length.toLocaleString("ko-KR")}자</span>
              </div>
            ) : (
              <label className={`audio-dropzone${file ? " has-file" : ""}`} htmlFor="audio-file">
                <input id="audio-file" type="file" accept="audio/*" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
                <span className="upload-icon"><Icon name={file ? "check" : "upload"} /></span>
                <strong>{file ? file.name : "음성 파일을 선택하세요"}</strong>
                <span>{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB · 분석 준비 완료` : "MP3, WAV, M4A · 텍스트 경로로 언제든 전환 가능"}</span>
              </label>
            )}

            {inputMode === "text" && transcriptPreview.length > 0 && (
              <div className="transcript-preview" aria-label="발화 미리보기">
                {transcriptPreview.slice(0, 3).map((line, index) => {
                  const [maybeSpeaker, ...rest] = line.split(":");
                  const hasSpeaker = rest.length > 0 && maybeSpeaker.length < 12;
                  return (
                    <div className="preview-line" key={`${line}-${index}`}>
                      <span>{hasSpeaker ? maybeSpeaker : index + 1}</span>
                      <p>{hasSpeaker ? rest.join(":").trim() : line}</p>
                    </div>
                  );
                })}
                {transcriptPreview.length > 3 && <small>+ {transcriptPreview.length - 3}개 발화</small>}
              </div>
            )}

            <div className="configuration">
              <fieldset>
                <legend>회의 목적</legend>
                <div className="segmented-control">
                  <button type="button" aria-pressed={preset === "decision"} onClick={() => setPreset("decision")}><span>의사결정</span><small>기준·trade-off</small></button>
                  <button type="button" aria-pressed={preset === "problem"} onClick={() => setPreset("problem")}><span>문제해결</span><small>가정·reframing</small></button>
                </div>
              </fieldset>
              <fieldset>
                <legend>질문 톤 <strong>{tone} · {TONE_LABELS[tone]}</strong></legend>
                <div className="tone-control">
                  {([1, 2, 3, 4] as ToneLevel[]).map((level) => (
                    <button key={level} type="button" aria-label={`${level}단계 ${TONE_LABELS[level]}`} aria-pressed={tone === level} onClick={() => setTone(level)}>{level}</button>
                  ))}
                </div>
                <div className="tone-scale"><span>직설적</span><span>우회적</span></div>
              </fieldset>
            </div>

            <button className="diagnose-button" type="button" disabled={!canRun || isRunning} onClick={runDiagnose}>
              <span>{isRunning ? "회의 맥락을 분석하고 있어요" : "현재 대화 진단하기"}</span><Icon name="arrow" />
            </button>
          </div>

          <div className="result-panel" aria-live="polite">
            <div className="panel-heading result-heading">
              <div><span className="step-number">02</span><div><h2>큐레이션 결과</h2><p>가치 기준을 통과한 질문만 보여드려요.</p></div></div>
              {result?.ok && <span className="result-count">후보 {result.pipeline.candidates_generated} → 선별 {result.pipeline.selected}</span>}
            </div>
            <Pipeline status={status} />

            {status === "idle" && (
              <div className="empty-result"><span className="empty-orbit"><Icon name="spark" /></span><strong>좋은 질문은 많이 묻는 것에서<br />시작하지 않습니다.</strong><p>왼쪽의 회의 맥락을 진단하면 생성, 필터, 가치 평가를 거친 질문이 여기에 표시됩니다.</p></div>
            )}
            {isRunning && (
              <div className="analyzing-result"><div className="scan-line" /><p>{status === "extracting" ? "발화와 맥락을 정리하는 중" : status === "generating" ? "인지적 맹점에서 후보를 만드는 중" : "중복과 정보 가치를 평가하는 중"}</p><div className="skeleton-question" /><div className="skeleton-question short" /></div>
            )}
            {error && (
              <div className="error-result" role="alert"><strong>진단을 완료하지 못했습니다.</strong><p>{error}</p><button type="button" onClick={runDiagnose}>다시 시도</button></div>
            )}
            {result?.ok && result.rejected && (
              <div className="rejected-result"><span>의도적 반려</span><h3>지금은 질문을 더하지 않는 편이 낫습니다.</h3><p>{result.reject_reason ?? "현재 맥락에서 기준을 넘는 유효한 질문이 발견되지 않았습니다."}</p><small>빈 결과가 아니라, 평가를 통과한 질문이 없다는 판단입니다.</small></div>
            )}
            {result?.ok && !result.rejected && (
              <div className="question-list">
                {result.questions.map((question, index) => (
                  <article className="question-card" key={question.id}>
                    <div className="question-meta"><span>{CATEGORY_LABELS[question.category]}</span><span>{String(index + 1).padStart(2, "0")}</span></div>
                    <h3>{question.text}</h3>
                    <div className="badges">{question.badges.map((badge) => <span key={badge}>{BADGE_LABELS[badge]}</span>)}</div>
                    <p className="rationale">{question.rationale}</p>
                    <div className="question-footer"><span>가치 점수 {(question.scores.final * 100).toFixed(0)}</span><button type="button" onClick={() => copyQuestion(question.id, question.text)}><Icon name={copiedId === question.id ? "check" : "copy"} />{copiedId === question.id ? "복사됨" : "질문 복사"}</button></div>
                  </article>
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="principles" aria-label="Q-Agent 평가 원칙">
          <p><strong>Judge, not wrapper.</strong> 질문을 만드는 능력보다 멈출 줄 아는 기준을 설계합니다.</p>
          <div><span>01 관련성</span><span>02 비중복</span><span>03 행동 변화</span><span>04 안전한 톤</span></div>
        </section>
      </div>
    </main>
  );
}

function Pipeline({ status }: { status: UiStatus }) {
  const steps: { key: PipelineStatus; label: string }[] = [
    { key: "extracting", label: "맥락 추출" },
    { key: "generating", label: "후보 생성" },
    { key: "selecting", label: "평가·선별" },
    { key: "done", label: "결과" },
  ];
  const activeIndex = status === "rejected" ? 3 : steps.findIndex((step) => step.key === status);

  return (
    <ol className="pipeline" aria-label="질문 분석 단계">
      {steps.map((step, index) => {
        const isActive = index === activeIndex;
        const isComplete = activeIndex > index || status === "done" || status === "rejected";
        return <li key={step.key} className={`${isActive ? "active" : ""}${isComplete ? " complete" : ""}`}><span>{isComplete ? <Icon name="check" /> : index + 1}</span><small>{step.label}</small></li>;
      })}
    </ol>
  );
}
