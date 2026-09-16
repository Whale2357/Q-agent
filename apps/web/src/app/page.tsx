"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import type {
  BadgeCode,
  DiagnoseResponse,
  PipelineStatus,
  QuestionCategory,
} from "@q-agent/contracts";

const HISTORY_STORAGE_KEY = "q-agent-meeting-history-v1";
const AUDIO_DATABASE_NAME = "q-agent-recordings";
const AUDIO_STORE_NAME = "recordings";
const MAX_HISTORY_ITEMS = 30;

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

type InputMode = "record" | "text";
type RecordingState = "idle" | "recording" | "ready";
type UiStatus = "idle" | PipelineStatus;
type SuccessfulDiagnosis = Extract<DiagnoseResponse, { ok: true }>;

interface HistoryItem {
  id: string;
  createdAt: string;
  source: InputMode;
  title: string;
  transcript: string;
  durationSeconds?: number;
  result: SuccessfulDiagnosis;
}

interface RealtimeTextResponse {
  ok: boolean;
  meeting_id?: string;
  transcript?: string;
  diagnosis?: SuccessfulDiagnosis;
  error?: { message: string };
}

interface RealtimeEvent {
  type: "status" | "ready" | "transcript" | "questions" | "stopped" | "error";
  status?: "loading" | PipelineStatus;
  meeting_id?: string;
  transcript?: string;
  diagnosis?: SuccessfulDiagnosis | null;
  message?: string;
}

type IconName =
  | "spark"
  | "copy"
  | "arrow"
  | "check"
  | "mic"
  | "stop"
  | "plus"
  | "history"
  | "text"
  | "close";

function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, React.ReactNode> = {
    spark: <path d="m12 3 1.1 3.9L17 8l-3.9 1.1L12 13l-1.1-3.9L7 8l3.9-1.1L12 3Zm5.5 9 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3ZM6 13l.9 3.1L10 17l-3.1.9L6 21l-.9-3.1L2 17l3.1-.9L6 13Z" />,
    copy: <><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    check: <path d="m5 12 4 4L19 6" />,
    mic: <><rect x="8" y="3" width="8" height="12" rx="4" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8.5 21h7" /></>,
    stop: <rect x="7" y="7" width="10" height="10" rx="2" />,
    plus: <path d="M12 5v14M5 12h14" />,
    history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></>,
    text: <><path d="M5 6h14M9 6v12M6 18h6" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
  };

  return <svg viewBox="0 0 24 24" aria-hidden="true" className="icon">{paths[name]}</svg>;
}

function formatDuration(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function realtimeSocketUrl() {
  const configured = process.env.NEXT_PUBLIC_REALTIME_WS_URL;
  if (configured) return configured;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.hostname}:8765/v1/realtime`;
}

function downsampleTo16Khz(input: Float32Array, inputRate: number) {
  if (inputRate === 16_000) return new Float32Array(input);
  const ratio = inputRate / 16_000;
  const outputLength = Math.max(1, Math.floor(input.length / ratio));
  const output = new Float32Array(outputLength);
  for (let outputIndex = 0; outputIndex < outputLength; outputIndex += 1) {
    const start = Math.floor(outputIndex * ratio);
    const end = Math.min(input.length, Math.floor((outputIndex + 1) * ratio));
    let sum = 0;
    for (let inputIndex = start; inputIndex < end; inputIndex += 1) sum += input[inputIndex];
    output[outputIndex] = sum / Math.max(1, end - start);
  }
  return output;
}

function formatHistoryTime(value: string) {
  const date = new Date(value);
  const today = new Date();
  const isToday = date.toDateString() === today.toDateString();
  return new Intl.DateTimeFormat("ko-KR", isToday
    ? { hour: "numeric", minute: "2-digit" }
    : { month: "short", day: "numeric" }).format(date);
}

function makeHistoryTitle(transcript: string, source: InputMode) {
  if (source === "record") {
    return `회의 녹음 · ${new Intl.DateTimeFormat("ko-KR", { hour: "numeric", minute: "2-digit" }).format(new Date())}`;
  }
  const firstLine = transcript.split("\n").find((line) => line.trim())?.trim() ?? "텍스트 테스트";
  return firstLine.length > 30 ? `${firstLine.slice(0, 30)}…` : firstLine;
}

function openAudioDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(AUDIO_DATABASE_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(AUDIO_STORE_NAME)) {
        request.result.createObjectStore(AUDIO_STORE_NAME);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function saveRecording(id: string, blob: Blob) {
  const database = await openAudioDatabase();
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(AUDIO_STORE_NAME, "readwrite");
    transaction.objectStore(AUDIO_STORE_NAME).put(blob, id);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
  database.close();
}

async function loadRecording(id: string): Promise<Blob | null> {
  const database = await openAudioDatabase();
  const result = await new Promise<Blob | undefined>((resolve, reject) => {
    const request = database.transaction(AUDIO_STORE_NAME).objectStore(AUDIO_STORE_NAME).get(id);
    request.onsuccess = () => resolve(request.result as Blob | undefined);
    request.onerror = () => reject(request.error);
  });
  database.close();
  return result ?? null;
}

async function deleteRecording(id: string) {
  const database = await openAudioDatabase();
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(AUDIO_STORE_NAME, "readwrite");
    transaction.objectStore(AUDIO_STORE_NAME).delete(id);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
  database.close();
}

export default function HomePage() {
  const [inputMode, setInputMode] = useState<InputMode>("record");
  const [text, setText] = useState("");
  const [recordingState, setRecordingState] = useState<RecordingState>("idle");
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [liveTranscript, setLiveTranscript] = useState("");
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<UiStatus>("idle");
  const [result, setResult] = useState<SuccessfulDiagnosis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyReady, setHistoryReady] = useState(false);
  const [activeHistoryId, setActiveHistoryId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [realtimeReady, setRealtimeReady] = useState<boolean | null>(null);
  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const mediaStream = useRef<MediaStream | null>(null);
  const realtimeSocket = useRef<WebSocket | null>(null);
  const audioContext = useRef<AudioContext | null>(null);
  const audioSource = useRef<MediaStreamAudioSourceNode | null>(null);
  const audioProcessor = useRef<ScriptProcessorNode | null>(null);
  const silentGain = useRef<GainNode | null>(null);
  const recordingActive = useRef(false);
  const liveTranscriptValue = useRef("");
  const latestDiagnosis = useRef<SuccessfulDiagnosis | null>(null);
  const pendingRecordingBlob = useRef<Blob | null>(null);
  const realtimeStopped = useRef(false);
  const audioChunks = useRef<Blob[]>([]);
  const recordingTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const recordingStartedAt = useRef(0);
  const recordingDurationValue = useRef(0);
  const recordingHistoryId = useRef<string | null>(null);
  const selectingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const discardStoppedRecording = useRef(false);

  const canRun = text.trim().length > 0;
  const isRunning = ["extracting", "generating", "selecting"].includes(status);
  const transcriptPreview = useMemo(
    () => text.split("\n").map((line) => line.trim()).filter(Boolean).slice(0, 5),
    [text],
  );

  useEffect(() => {
    try {
      const stored = localStorage.getItem(HISTORY_STORAGE_KEY);
      if (stored) setHistory(JSON.parse(stored) as HistoryItem[]);
    } catch {
      localStorage.removeItem(HISTORY_STORAGE_KEY);
    } finally {
      setHistoryReady(true);
    }
  }, []);

  useEffect(() => {
    fetch("/api/health", { cache: "no-store" })
      .then((response) => response.json())
      .then((payload) => setRealtimeReady(Boolean(payload?.ok)))
      .catch(() => setRealtimeReady(false));
  }, []);

  useEffect(() => {
    if (!historyReady) return;
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(history));
  }, [history, historyReady]);

  useEffect(() => {
    if (!audioBlob) {
      setAudioUrl(null);
      return;
    }
    const nextUrl = URL.createObjectURL(audioBlob);
    setAudioUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [audioBlob]);

  useEffect(() => () => {
    if (recordingTimer.current) clearInterval(recordingTimer.current);
    if (selectingTimer.current) clearTimeout(selectingTimer.current);
    realtimeSocket.current?.close();
    audioProcessor.current?.disconnect();
    audioSource.current?.disconnect();
    silentGain.current?.disconnect();
    void audioContext.current?.close();
    mediaStream.current?.getTracks().forEach((track) => track.stop());
  }, []);

  function resetAnalysis() {
    setResult(null);
    setError(null);
    setStatus("idle");
  }

  function switchMode(nextMode: InputMode) {
    if (recordingState === "recording") return;
    setInputMode(nextMode);
    resetAnalysis();
    setActiveHistoryId(null);
  }

  function startNewMeeting() {
    if (recordingState === "recording") {
      discardStoppedRecording.current = true;
      stopRecording();
    }
    setInputMode("record");
    setText("");
    setAudioBlob(null);
    setRecordingSeconds(0);
    setLiveTranscript("");
    liveTranscriptValue.current = "";
    latestDiagnosis.current = null;
    pendingRecordingBlob.current = null;
    realtimeStopped.current = false;
    recordingHistoryId.current = null;
    setRecordingState("idle");
    setActiveHistoryId(null);
    setSidebarOpen(false);
    resetAnalysis();
  }

  async function startRecording() {
    discardStoppedRecording.current = false;
    resetAnalysis();
    setActiveHistoryId(null);
    setAudioBlob(null);
    setRecordingSeconds(0);
    setLiveTranscript("");
    liveTranscriptValue.current = "";
    latestDiagnosis.current = null;
    pendingRecordingBlob.current = null;
    realtimeStopped.current = false;
    recordingDurationValue.current = 0;
    recordingHistoryId.current = crypto.randomUUID();

    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("이 브라우저에서는 마이크 녹음을 지원하지 않습니다. 최신 Chrome 또는 Edge를 사용해 주세요.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      await connectRealtimeSocket();
      const preferredTypes = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
      const mimeType = preferredTypes.find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);

      mediaStream.current = stream;
      mediaRecorder.current = recorder;
      audioChunks.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunks.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(audioChunks.current, { type: recorder.mimeType || "audio/webm" });
        if (!discardStoppedRecording.current) {
          setAudioBlob(blob);
          setRecordingState("ready");
          pendingRecordingBlob.current = blob;
          void persistCompletedRecording();
        }
        stream.getTracks().forEach((track) => track.stop());
        mediaStream.current = null;
      };
      recorder.start(1000);

      const context = new AudioContext();
      await context.resume();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const gain = context.createGain();
      gain.gain.value = 0;
      processor.onaudioprocess = (event) => {
        const socket = realtimeSocket.current;
        if (!recordingActive.current || socket?.readyState !== WebSocket.OPEN) return;
        const pcm = downsampleTo16Khz(event.inputBuffer.getChannelData(0), context.sampleRate);
        socket.send(pcm.buffer);
      };
      source.connect(processor);
      processor.connect(gain);
      gain.connect(context.destination);
      audioContext.current = context;
      audioSource.current = source;
      audioProcessor.current = processor;
      silentGain.current = gain;

      recordingActive.current = true;
      recordingStartedAt.current = Date.now();
      recordingTimer.current = setInterval(() => {
        const elapsed = Math.floor((Date.now() - recordingStartedAt.current) / 1000);
        recordingDurationValue.current = elapsed;
        setRecordingSeconds(elapsed);
      }, 250);
      setRecordingState("recording");
    } catch (caught) {
      recordingActive.current = false;
      discardStoppedRecording.current = true;
      if (mediaRecorder.current?.state === "recording") mediaRecorder.current.stop();
      cleanupAudioGraph();
      realtimeSocket.current?.close();
      realtimeSocket.current = null;
      mediaStream.current?.getTracks().forEach((track) => track.stop());
      mediaStream.current = null;
      setRecordingState("idle");
      setStatus("idle");
      setError(caught instanceof DOMException && caught.name === "NotAllowedError"
        ? "마이크 권한이 필요합니다. 브라우저 주소창에서 마이크 사용을 허용해 주세요."
        : caught instanceof Error
          ? caught.message
          : "realtime 서비스에 연결하지 못했습니다.");
    }
  }

  function stopRecording() {
    recordingActive.current = false;
    cleanupAudioGraph();
    if (recordingTimer.current) {
      clearInterval(recordingTimer.current);
      recordingTimer.current = null;
    }
    const elapsed = Math.max(1, Math.floor((Date.now() - recordingStartedAt.current) / 1000));
    recordingDurationValue.current = elapsed;
    setRecordingSeconds(elapsed);
    const socket = realtimeSocket.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "stop" }));
    }
    if (mediaRecorder.current?.state === "recording") mediaRecorder.current.stop();
  }

  function cleanupAudioGraph() {
    if (audioProcessor.current) audioProcessor.current.onaudioprocess = null;
    audioProcessor.current?.disconnect();
    audioSource.current?.disconnect();
    silentGain.current?.disconnect();
    void audioContext.current?.close();
    audioProcessor.current = null;
    audioSource.current = null;
    silentGain.current = null;
    audioContext.current = null;
  }

  function connectRealtimeSocket() {
    return new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(realtimeSocketUrl());
      realtimeSocket.current = socket;
      setStatus("extracting");
      const timeout = setTimeout(() => {
        socket.close();
        reject(new Error("realtime 모델 준비 시간이 초과되었습니다."));
      }, 180_000);

      socket.onopen = () => socket.send(JSON.stringify({ type: "start", sample_rate: 16_000 }));
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(String(message.data)) as RealtimeEvent;
          handleRealtimeEvent(event);
          if (event.type === "ready") {
            clearTimeout(timeout);
            resolve();
          } else if (event.type === "error") {
            clearTimeout(timeout);
            reject(new Error(event.message ?? "realtime 서비스 오류"));
          }
        } catch {
          setError("realtime 응답을 해석하지 못했습니다.");
        }
      };
      socket.onerror = () => {
        clearTimeout(timeout);
        reject(new Error("realtime 서비스에 연결할 수 없습니다. Python 서버를 확인해 주세요."));
      };
      socket.onclose = () => {
        if (recordingActive.current) {
          recordingActive.current = false;
          cleanupAudioGraph();
          setRecordingState("ready");
          setStatus("error");
          setError("realtime 연결이 예기치 않게 종료되었습니다.");
        }
      };
    });
  }

  function handleRealtimeEvent(event: RealtimeEvent) {
    if (event.type === "status" && event.status) {
      setStatus(event.status === "loading" ? "extracting" : event.status);
      return;
    }
    if (event.type === "ready") {
      setStatus("idle");
      return;
    }
    if (event.type === "transcript" && event.transcript !== undefined) {
      liveTranscriptValue.current = event.transcript;
      setLiveTranscript(event.transcript);
      return;
    }
    if (event.type === "questions" && event.diagnosis) {
      latestDiagnosis.current = event.diagnosis;
      if (event.transcript !== undefined) {
        liveTranscriptValue.current = event.transcript;
        setLiveTranscript(event.transcript);
      }
      setResult(event.diagnosis);
      setStatus(event.diagnosis.status);
      return;
    }
    if (event.type === "stopped") {
      realtimeStopped.current = true;
      if (event.transcript !== undefined) {
        liveTranscriptValue.current = event.transcript;
        setLiveTranscript(event.transcript);
      }
      if (event.diagnosis) {
        latestDiagnosis.current = event.diagnosis;
        setResult(event.diagnosis);
        setStatus(event.diagnosis.status);
      }
      realtimeSocket.current = null;
      void persistCompletedRecording();
      return;
    }
    if (event.type === "error") {
      setStatus("error");
      setError(event.message ?? "realtime 처리 중 오류가 발생했습니다.");
    }
  }

  async function persistCompletedRecording() {
    if (discardStoppedRecording.current) return;
    const blob = pendingRecordingBlob.current;
    const diagnosis = latestDiagnosis.current;
    if (!blob || !diagnosis || !realtimeStopped.current) return;
    const transcript = liveTranscriptValue.current.trim();
    const id = recordingHistoryId.current ?? crypto.randomUUID();
    const historyItem: HistoryItem = {
      id,
      createdAt: new Date().toISOString(),
      source: "record",
      title: makeHistoryTitle(transcript, "record"),
      transcript,
      durationSeconds: recordingDurationValue.current,
      result: diagnosis,
    };
    setHistory((previous) => [historyItem, ...previous.filter((item) => item.id !== id)].slice(0, MAX_HISTORY_ITEMS));
    setActiveHistoryId(id);
    await saveRecording(id, blob).catch(() => undefined);
    pendingRecordingBlob.current = null;
  }

  async function runDiagnose() {
    if (!canRun || isRunning) return;
    const normalizedText = text.trim();
    if (normalizedText.length < 8) return;
    setError(null);
    setStatus("extracting");
    setResult(null);
    selectingTimer.current = setTimeout(() => setStatus("generating"), 500);

    try {
      const response = await fetch("/api/realtime/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: normalizedText, language: "ko" }),
      });
      const payload = (await response.json()) as RealtimeTextResponse;
      if (!payload.ok || !payload.diagnosis || payload.transcript === undefined) {
        throw new Error(payload.error?.message ?? "realtime 텍스트 분석에 실패했습니다.");
      }
      if (selectingTimer.current) clearTimeout(selectingTimer.current);
      setResult(payload.diagnosis);
      setStatus(payload.diagnosis.status);
      const id = activeHistoryId ?? payload.meeting_id ?? crypto.randomUUID();
      const historyItem: HistoryItem = {
        id,
        createdAt: new Date().toISOString(),
        source: "text",
        title: makeHistoryTitle(payload.transcript, "text"),
        transcript: payload.transcript,
        result: payload.diagnosis,
      };
      setHistory((previous) => [historyItem, ...previous.filter((item) => item.id !== id)].slice(0, MAX_HISTORY_ITEMS));
      setActiveHistoryId(id);
    } catch (caught) {
      if (selectingTimer.current) clearTimeout(selectingTimer.current);
      setStatus("error");
      setError(caught instanceof Error ? caught.message : "진단 중 알 수 없는 오류가 발생했습니다.");
    }
  }

  async function openHistory(item: HistoryItem) {
    if (isRunning || recordingState === "recording") return;
    setActiveHistoryId(item.id);
    setInputMode(item.source);
    setText(item.transcript);
    setLiveTranscript(item.source === "record" ? item.transcript : "");
    liveTranscriptValue.current = item.source === "record" ? item.transcript : "";
    setResult(item.result);
    setStatus(item.result.status);
    setError(null);
    setRecordingSeconds(item.durationSeconds ?? 0);
    setSidebarOpen(false);

    if (item.source === "record") {
      const storedAudio = await loadRecording(item.id).catch(() => null);
      setAudioBlob(storedAudio);
      setRecordingState(storedAudio ? "ready" : "idle");
    } else {
      setAudioBlob(null);
      setRecordingState("idle");
    }
  }

  async function removeHistory(item: HistoryItem) {
    setHistory((previous) => previous.filter((entry) => entry.id !== item.id));
    if (item.source === "record") await deleteRecording(item.id).catch(() => undefined);
    if (activeHistoryId === item.id) startNewMeeting();
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
        <button className="mobile-history-button" type="button" aria-label="기록 열기" onClick={() => setSidebarOpen(true)}><Icon name="history" /></button>
        <a className="brand" href="#top" aria-label="Q-Agent 홈">
          <span className="brand-mark"><Icon name="spark" /></span><span>Q-Agent</span>
        </a>
        <span className="brand-subtitle">Meeting reasoning copilot</span>
        <div className={`service-state${realtimeReady === false ? " offline" : ""}`}><span aria-hidden="true" />{realtimeReady === null ? "realtime 확인 중" : realtimeReady ? "realtime 연결됨" : "realtime 연결 필요"}</div>
      </header>

      <div className="app-layout">
        <button className={`sidebar-scrim${sidebarOpen ? " open" : ""}`} type="button" aria-label="기록 닫기" onClick={() => setSidebarOpen(false)} />
        <aside className={`history-sidebar${sidebarOpen ? " open" : ""}`} aria-label="이전 회의 기록">
          <div className="history-heading">
            <div><Icon name="history" /><h2>회의 기록</h2></div>
            <button className="sidebar-close" type="button" aria-label="기록 닫기" onClick={() => setSidebarOpen(false)}><Icon name="close" /></button>
          </div>
          <button className="new-meeting-button" type="button" onClick={startNewMeeting}><Icon name="plus" /><span>새 회의 시작</span></button>
          <div className="history-list">
            <p className="history-label">최근 기록</p>
            {historyReady && history.length === 0 && (
              <div className="history-empty"><span><Icon name="spark" /></span><p>첫 회의를 시작하면<br />질문 기록이 여기에 남아요.</p></div>
            )}
            {history.map((item) => (
              <div key={item.id} className={`history-item${activeHistoryId === item.id ? " active" : ""}`}>
                <button className="history-open" type="button" onClick={() => openHistory(item)}>
                  <span className="history-source"><Icon name={item.source === "record" ? "mic" : "text"} /></span>
                  <span className="history-summary"><strong>{item.title}</strong><small>{formatHistoryTime(item.createdAt)} · 질문 {item.result.questions.length}개</small></span>
                </button>
                <button className="history-remove" type="button" aria-label={`${item.title} 삭제`} onClick={() => removeHistory(item)}><Icon name="close" /></button>
              </div>
            ))}
          </div>
          <p className="history-storage-note">기록과 녹음은 이 브라우저에만 저장됩니다.</p>
        </aside>

        <div id="top" className="page-content">
          <section className="hero" aria-labelledby="hero-title">
            <div>
              <p className="eyebrow">Evaluation-first AI</p>
              <h1 id="hero-title">회의가 막힌 순간,<br /><em>가장 가치 있는 질문만.</em></h1>
              <p className="hero-copy">회의를 녹음하면 맥락을 실시간으로 읽고 후보 질문을 생성·평가해, 기준을 넘은 질문만 건넵니다.</p>
            </div>
            <div className="hero-proof" aria-label="Q-Agent 처리 방식">
              <span>Listen</span><Icon name="arrow" /><span>Evaluate</span><Icon name="arrow" /><strong>Question</strong>
            </div>
          </section>

          <section className="workspace" aria-label="실시간 회의 질문 워크스페이스" onPointerMove={trackGlassLight}>
            <div className="input-panel">
              <div className="panel-heading">
                <div><span className="step-number">01</span><div><h2>회의 시작</h2><p>녹음을 시작하거나 테스트용 텍스트를 입력하세요.</p></div></div>
                <div className="mode-tabs" role="tablist" aria-label="입력 방식">
                  <button type="button" role="tab" aria-selected={inputMode === "record"} onClick={() => switchMode("record")}><Icon name="mic" />녹음</button>
                  <button type="button" role="tab" aria-selected={inputMode === "text"} onClick={() => switchMode("text")}><Icon name="text" />텍스트 테스트</button>
                </div>
              </div>

              {inputMode === "text" ? (
                <>
                  <div className="text-input-wrap">
                    <label htmlFor="meeting-log" className="sr-only">회의 로그</label>
                    <textarea id="meeting-log" value={text} onChange={(event) => { setText(event.target.value); setActiveHistoryId(null); resetAnalysis(); }} placeholder={"A: 이번 분기 우선순위는…\nB: 저는 고객 이탈 문제부터 봐야 한다고 생각해요."} />
                    <span className="character-count">{text.length.toLocaleString("ko-KR")}자</span>
                  </div>
                  {transcriptPreview.length > 0 && (
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
                </>
              ) : (
                <div className={`recorder${recordingState === "recording" ? " is-recording" : ""}`}>
                  {recordingState === "idle" && (
                    <>
                      <button className="record-trigger" type="button" onClick={startRecording}><Icon name="mic" /><span className="record-pulse" /></button>
                      <strong>회의 녹음 시작</strong>
                      <p>버튼을 누르면 마이크로 회의를 듣기 시작합니다.</p>
                    </>
                  )}
                  {recordingState === "recording" && (
                    <>
                      <div className="recording-status"><span /><strong>회의를 듣고 질문을 만들고 있어요</strong></div>
                      <time>{formatDuration(recordingSeconds)}</time>
                      <div className="audio-wave" aria-hidden="true">{Array.from({ length: 18 }, (_, index) => <i key={index} />)}</div>
                      <div className="live-transcript" aria-live="polite">
                        <small>Whisper 실시간 전사</small>
                        <p>{liveTranscript || "말씀을 시작하면 Whisper가 확정한 발화가 여기에 표시됩니다."}</p>
                      </div>
                      <button className="stop-recording" type="button" onClick={stopRecording}><Icon name="stop" />녹음 종료</button>
                    </>
                  )}
                  {recordingState === "ready" && (
                    <>
                      <div className="recording-ready"><span><Icon name="check" /></span><div><strong>회의 녹음이 종료되었습니다</strong><small>{formatDuration(recordingSeconds)} · 마지막 발화까지 자동 분석합니다</small></div></div>
                      {audioUrl && <audio className="recording-player" controls src={audioUrl}>오디오 재생을 지원하지 않는 브라우저입니다.</audio>}
                      <button className="record-again" type="button" onClick={startRecording}><Icon name="mic" />다시 녹음</button>
                    </>
                  )}
                </div>
              )}

              {error && status === "idle" && <p className="input-error" role="alert">{error}</p>}
              {inputMode === "text" && (
                <button className="diagnose-button" type="button" disabled={!canRun || isRunning} onClick={runDiagnose}>
                  <span>{isRunning ? "회의 맥락을 분석하고 있어요" : "텍스트로 질문 테스트하기"}</span><Icon name="arrow" />
                </button>
              )}
            </div>

            <div className="result-panel" aria-live="polite">
              <div className="panel-heading result-heading">
                <div><span className="step-number">02</span><div><h2>실시간 질문</h2><p>맥락을 바꿀 가치가 있는 질문만 보여드려요.</p></div></div>
                {result?.ok && <span className="result-count">후보 {result.pipeline.candidates_generated} → 선별 {result.pipeline.selected}</span>}
              </div>
              <Pipeline status={status} />

              {status === "idle" && (
                <div className="empty-result"><span className="empty-orbit"><Icon name="spark" /></span><strong>회의가 시작되면<br />필요한 순간에 질문이 나타납니다.</strong><p>왼쪽에서 녹음을 시작하거나 텍스트로 질문 생성을 테스트해 보세요.</p></div>
              )}
              {isRunning && !result && (
                <div className="analyzing-result"><div className="scan-line" /><p>{status === "extracting" ? "발화와 맥락을 정리하는 중" : status === "generating" ? "인지적 맹점에서 후보를 만드는 중" : "중복과 정보 가치를 평가하는 중"}</p><div className="skeleton-question" /><div className="skeleton-question short" /></div>
              )}
              {error && status === "error" && (
                <div className="error-result" role="alert"><strong>진단을 완료하지 못했습니다.</strong><p>{error}</p>{inputMode === "text" && <button type="button" onClick={runDiagnose}>다시 시도</button>}</div>
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
            <div><span>01 관련성</span><span>02 비중복</span><span>03 행동 변화</span><span>04 맥락 적합성</span></div>
          </section>
        </div>
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
