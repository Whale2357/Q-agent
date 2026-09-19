"use client";

import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type ReactNode,
} from "react";
import type { DiagnoseResponse, ScoredQuestion } from "@q-agent/contracts";

const HISTORY_STORAGE_KEY = "q-agent-meeting-history-v1";
const AUDIO_DATABASE_NAME = "q-agent-recordings";
const AUDIO_STORE_NAME = "recordings";
const MAX_HISTORY_ITEMS = 30;
const MAX_VISIBLE_THOUGHTS = 6;

type InputMode = "record" | "upload" | "text";
type WorkspaceMode = "upload" | "record";
type ActivityState = "idle" | "connecting" | "recording" | "processing" | "done" | "error";
type HistoryStatus = "completed" | "partial" | "rejected";
type WorkspaceMessageKind = "network" | "permission" | "processing" | "rejected";
type SuccessfulDiagnosis = Extract<DiagnoseResponse, { ok: true }>;

interface HistoryItem {
  id: string;
  createdAt: string;
  source: InputMode;
  title: string;
  transcript: string;
  durationSeconds?: number;
  result: SuccessfulDiagnosis | null;
  status?: HistoryStatus;
  errorMessage?: string;
}

interface ThoughtQuestion {
  id: string;
  text: string;
  createdAt: number;
  slot: number;
}

interface RealtimeEvent {
  type:
    | "status"
    | "ready"
    | "transcript"
    | "context"
    | "questions"
    | "pool_update"
    | "final_question"
    | "stopped"
    | "error";
  status?: "loading" | "extracting" | "generating" | "selecting" | "done" | "rejected" | "error";
  meeting_id?: string;
  transcript?: string;
  diagnosis?: SuccessfulDiagnosis | null;
  message?: string;
  trigger?: "silence" | "ask" | "stop";
  pool_size?: number;
}

type IconName = "spark" | "plus" | "history" | "mic" | "text" | "close" | "upload" | "stop" | "check";

function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    spark: <path d="m12 3 1.1 3.9L17 8l-3.9 1.1L12 13l-1.1-3.9L7 8l3.9-1.1L12 3Zm5.5 9 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3ZM6 13l.9 3.1L10 17l-3.1.9L6 21l-.9-3.1L2 17l3.1-.9L6 13Z" />,
    plus: <path d="M12 5v14M5 12h14" />,
    history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></>,
    mic: <><rect x="8" y="3" width="8" height="12" rx="4" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8.5 21h7" /></>,
    text: <><path d="M5 6h14M9 6v12M6 18h6" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    upload: <><path d="M12 16V4m-4 4 4-4 4 4" /><path d="M5 15v4h14v-4" /></>,
    stop: <rect x="7" y="7" width="10" height="10" rx="2" />,
    check: <path d="m5 12 4 4L19 6" />,
  };

  return <svg viewBox="0 0 24 24" aria-hidden="true" className="icon">{paths[name]}</svg>;
}

function BrainLogoIcon() {
  return (
    <img
      className="brain-logo-icon"
      src="/frankenstein-brain-logo.png"
      alt=""
      aria-hidden="true"
      draggable="false"
    />
  );
}

function BrainIcon() {
  return (
    <svg className="brain-icon" viewBox="0 0 160 120" aria-hidden="true">
      <defs>
        <linearGradient id="brain-neon-line" x1="24" y1="28" x2="136" y2="96" gradientUnits="userSpaceOnUse">
          <stop stopColor="#d4ffe0" />
          <stop offset=".48" stopColor="#68ed94" />
          <stop offset="1" stopColor="#20c96b" />
        </linearGradient>
        <path id="brain-shape" d="M79.8 108.7c-7.7 6.2-19.8 3.5-23.7-5.6-10.4 2.8-20.6-5.1-20.8-15.9-10.4-3.2-14.7-16.1-8.3-24.8-6.1-8.6-1.7-20.8 8.2-24.1-.4-10.8 9.3-19 19.8-16.7C60.2 12 72.9 9.9 80 17.9c7.1-8 19.8-5.9 25 3.7 10.5-2.3 20.2 5.9 19.8 16.7 9.9 3.3 14.3 15.5 8.2 24.1 6.4 8.7 2.1 21.6-8.3 24.8-.2 10.8-10.4 18.7-20.8 15.9-3.9 9.1-16 11.8-23.7 5.6Z" />
        <g id="brain-fold-pattern">
          <path id="brain-fold-center" pathLength="100" d="M80 18c-5.7 6.8-5.9 14.8-1.1 21.8-6.6 6-6.3 15.5.4 21.1-5.5 7-5.1 16.9.7 22.8-4.5 7.1-3.8 17.3-.2 24.4" />
          <path id="brain-fold-left-outer" pathLength="100" d="M54 22c-1.2 8.1 2.7 13.5 10.3 15.4M36 39c8.7-.8 14 3.8 14.6 11.8M27 63c7.1-5.4 15.5-3.1 19.2 4.5M35 87c7.7-2.8 14.5.7 16.5 8.3" />
          <path id="brain-fold-left-inner" pathLength="100" d="M67 39c-8.3 1.3-12.2 7.8-9.6 15.6M45 56c3.5 6.8 9.1 9.2 16.5 6.7M56 70c-6.4 3.1-8.1 10.2-4.1 16M65 84c-5.5 5.1-4.5 13.1 1.8 17.2" />
          <path id="brain-fold-right-outer" pathLength="100" d="M106 22c1.2 8.1-2.7 13.5-10.3 15.4M124 39c-8.7-.8-14 3.8-14.6 11.8M133 63c-7.1-5.4-15.5-3.1-19.2 4.5M125 87c-7.7-2.8-14.5.7-16.5 8.3" />
          <path id="brain-fold-right-inner" pathLength="100" d="M93 39c8.3 1.3 12.2 7.8 9.6 15.6M115 56c-3.5 6.8-9.1 9.2-16.5 6.7M104 70c6.4 3.1 8.1 10.2 4.1 16M95 84c5.5 5.1 4.5 13.1-1.8 17.2" />
          <path id="brain-fold-accents" pathLength="100" d="M70 25c-5.1-1.8-9.4.3-11.6 5.8M90 25c5.1-1.8 9.4.3 11.6 5.8M64 68c5.5 1.2 8.6 5.3 7.7 10.5M96 68c-5.5 1.2-8.6 5.3-7.7 10.5" />
        </g>
      </defs>
      <ellipse className="brain-ground-shadow" cx="80" cy="111" rx="37" ry="5" />
      <g className="brain-bouncy">
        <use className="brain-outline" href="#brain-shape" />
        <g className="brain-folds"><use href="#brain-fold-pattern" /></g>
        <g className="brain-neon-folds" stroke="url(#brain-neon-line)">
          <use href="#brain-fold-center" />
          <use href="#brain-fold-left-outer" />
          <use href="#brain-fold-left-inner" />
          <use href="#brain-fold-right-outer" />
          <use href="#brain-fold-right-inner" />
          <use href="#brain-fold-accents" />
        </g>
      </g>
    </svg>
  );
}

function formatDuration(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function formatHistoryTime(value: string) {
  const date = new Date(value);
  const today = new Date();
  const isToday = date.toDateString() === today.toDateString();
  return new Intl.DateTimeFormat("ko-KR", isToday
    ? { hour: "numeric", minute: "2-digit" }
    : { month: "short", day: "numeric" }).format(date);
}

function formatHistoryMeta(item: HistoryItem) {
  const questionCount = item.result?.questions.length ?? 0;
  const status = item.status ?? (item.result?.rejected ? "rejected" : "completed");
  if (status === "partial") return `부분 저장 · 질문 ${questionCount}개`;
  if (status === "rejected") return "질문 반려";
  return `질문 ${questionCount}개`;
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

function pcmRms(samples: Float32Array) {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let index = 0; index < samples.length; index += 1) {
    const value = samples[index] ?? 0;
    sum += value * value;
  }
  return Math.sqrt(sum / samples.length);
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

function wait(milliseconds: number) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export default function HomePage() {
  const [mode, setMode] = useState<WorkspaceMode>("record");
  const [activity, setActivity] = useState<ActivityState>("idle");
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [thoughts, setThoughts] = useState<ThoughtQuestion[]>([]);
  const [dismissingIds, setDismissingIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<WorkspaceMessageKind | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyReady, setHistoryReady] = useState(false);
  const [activeHistoryId, setActiveHistoryId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const nextThoughtSlot = useRef(0);
  const [retrying, setRetrying] = useState(false);
  const [isEmittingQuestion, setIsEmittingQuestion] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 1000px)");
    const sync = () => {
      if (media.matches) setSidebarOpen(false);
    };
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const mediaStream = useRef<MediaStream | null>(null);
  const realtimeSocket = useRef<WebSocket | null>(null);
  const audioContext = useRef<AudioContext | null>(null);
  const audioSource = useRef<MediaStreamAudioSourceNode | null>(null);
  const audioProcessor = useRef<ScriptProcessorNode | null>(null);
  const silentGain = useRef<GainNode | null>(null);
  const recordingTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const recordingStartedAt = useRef(0);
  const recordingDurationValue = useRef(0);
  const recordingActive = useRef(false);
  const audioChunks = useRef<Blob[]>([]);
  const liveTranscriptValue = useRef("");
  const latestDiagnosis = useRef<SuccessfulDiagnosis | null>(null);
  const pendingAudioBlob = useRef<Blob | null>(null);
  const pendingSource = useRef<InputMode>("record");
  const pendingTitle = useRef("");
  const pendingHistoryId = useRef<string | null>(null);
  const realtimeStopped = useRef(false);
  const sessionEndedNormally = useRef(false);
  const discardSession = useRef(false);
  const pendingErrorMessage = useRef<string | null>(null);
  const reconnectAttempts = useRef(0);
  const reconnectInFlight = useRef(false);
  const failureFinalizing = useRef(false);
  const dismissTimers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const questionBurstTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const knownQuestionIds = useRef<Set<string>>(new Set());

  const isThinking = activity === "connecting" || activity === "recording" || activity === "processing";

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
    if (!historyReady) return;
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(history));
  }, [history, historyReady]);

  useEffect(() => {
    if (thoughts.length <= MAX_VISIBLE_THOUGHTS) return;
    const overflowIds = thoughts
      .slice()
      .sort((left, right) => left.createdAt - right.createdAt)
      .slice(0, thoughts.length - MAX_VISIBLE_THOUGHTS)
      .map((thought) => thought.id);
    setDismissingIds((previous) => new Set([...previous, ...overflowIds]));
    const timer = setTimeout(() => {
      setThoughts((previous) => previous.filter((thought) => !overflowIds.includes(thought.id)));
      setDismissingIds((previous) => {
        const next = new Set(previous);
        overflowIds.forEach((id) => next.delete(id));
        return next;
      });
    }, 850);
    return () => clearTimeout(timer);
  }, [thoughts]);

  useEffect(() => () => {
    clearRecordingTimer();
    dismissTimers.current.forEach(clearTimeout);
    if (questionBurstTimer.current) clearTimeout(questionBurstTimer.current);
    closeRealtimeSocket();
    cleanupAudioGraph();
    stopMediaStream();
  }, []);

  function setWorkspaceMessage(kind: WorkspaceMessageKind, message: string) {
    setErrorKind(kind);
    setError(message);
  }

  function clearWorkspaceMessage() {
    setErrorKind(null);
    setError(null);
  }

  function clearRecordingTimer() {
    if (!recordingTimer.current) return;
    clearInterval(recordingTimer.current);
    recordingTimer.current = null;
  }

  function stopMediaStream() {
    mediaStream.current?.getTracks().forEach((track) => track.stop());
    mediaStream.current = null;
  }

  function closeRealtimeSocket() {
    const socket = realtimeSocket.current;
    realtimeSocket.current = null;
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
  }

  function stopMediaRecorder() {
    const recorder = mediaRecorder.current;
    if (!recorder || recorder.state === "inactive") return Promise.resolve();
    return new Promise<void>((resolve) => {
      recorder.addEventListener("stop", () => resolve(), { once: true });
      try {
        recorder.stop();
      } catch {
        resolve();
      }
    });
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

  function prepareSession(source: InputMode, title: string, blob: Blob | null) {
    setThoughts([]);
    setDismissingIds(new Set());
    setIsEmittingQuestion(false);
    knownQuestionIds.current = new Set();
    nextThoughtSlot.current = 0;
    if (questionBurstTimer.current) clearTimeout(questionBurstTimer.current);
    clearWorkspaceMessage();
    setActiveHistoryId(null);
    liveTranscriptValue.current = "";
    latestDiagnosis.current = null;
    pendingAudioBlob.current = blob;
    pendingSource.current = source;
    pendingTitle.current = title;
    pendingHistoryId.current = crypto.randomUUID();
    realtimeStopped.current = false;
    sessionEndedNormally.current = false;
    discardSession.current = false;
    pendingErrorMessage.current = null;
    reconnectAttempts.current = 0;
    reconnectInFlight.current = false;
    failureFinalizing.current = false;
    recordingDurationValue.current = 0;
  }

  function allocateThoughtSlot(occupied: Set<number>) {
    for (let slot = 0; slot < MAX_VISIBLE_THOUGHTS; slot += 1) {
      if (!occupied.has(slot)) return slot;
    }
    const slot = nextThoughtSlot.current % MAX_VISIBLE_THOUGHTS;
    nextThoughtSlot.current += 1;
    return slot;
  }

  function addQuestions(questions: ScoredQuestion[]) {
    if (questions.length === 0) return;
    const fresh = questions.filter((question) => !knownQuestionIds.current.has(question.id));
    if (fresh.length === 0) return;
    fresh.forEach((question) => knownQuestionIds.current.add(question.id));
    setThoughts((previous) => {
      const occupied = new Set(previous.map((thought) => thought.slot));
      const additions = fresh.map((question, index) => {
        const slot = allocateThoughtSlot(occupied);
        occupied.add(slot);
        return {
          id: question.id,
          text: question.text,
          createdAt: Date.now() + index,
          slot,
        };
      });
      return [...previous, ...additions];
    });
    setIsEmittingQuestion(true);
    if (questionBurstTimer.current) clearTimeout(questionBurstTimer.current);
    questionBurstTimer.current = setTimeout(() => {
      setIsEmittingQuestion(false);
      questionBurstTimer.current = null;
    }, 1100);
  }

  function applyDiagnosis(diagnosis: SuccessfulDiagnosis) {
    latestDiagnosis.current = diagnosis;
    addQuestions(diagnosis.questions);
  }

  function handleRealtimeEvent(event: RealtimeEvent) {
    if (event.type === "status") return;
    if (event.type === "transcript" && event.transcript !== undefined) {
      liveTranscriptValue.current = event.transcript;
      return;
    }
    if (event.type === "pool_update") {
      if (event.transcript !== undefined) liveTranscriptValue.current = event.transcript;
      return;
    }
    if (
      (event.type === "final_question" || event.type === "questions") &&
      event.diagnosis
    ) {
      if (event.transcript !== undefined) liveTranscriptValue.current = event.transcript;
      applyDiagnosis(event.diagnosis);
      if (event.diagnosis.rejected || event.diagnosis.questions.length === 0) {
        setWorkspaceMessage("rejected", "질문이 비어 반려되었습니다. 회의 맥락이 더 쌓이면 다시 시도해 주세요.");
      } else {
        clearWorkspaceMessage();
      }
      return;
    }
    if (event.type === "stopped") {
      sessionEndedNormally.current = true;
      realtimeStopped.current = true;
      if (event.transcript !== undefined) liveTranscriptValue.current = event.transcript;
      if (event.diagnosis) applyDiagnosis(event.diagnosis);
      setActivity("done");
      if (!event.diagnosis || event.diagnosis.rejected || event.diagnosis.questions.length === 0) {
        setWorkspaceMessage("rejected", "질문이 비어 반려되었습니다. 오류가 아니라 평가 기준을 넘은 질문이 없는 상태입니다.");
      } else {
        clearWorkspaceMessage();
      }
      realtimeSocket.current = null;
      void persistCompletedSession();
      return;
    }
    if (event.type === "error") {
      void recoverRealtimeConnection(event.message ?? "realtime 서버가 오류를 반환했습니다.");
    }
  }

  function connectRealtimeSocket({ reconnecting = false }: { reconnecting?: boolean } = {}) {
    return new Promise<WebSocket>((resolve, reject) => {
      void (async () => {
        let sessionToken = "";
        try {
          const sessionResponse = await fetch("/api/realtime/session", {
            method: "POST",
            cache: "no-store",
          });
          const sessionPayload = (await sessionResponse.json()) as {
            ok?: boolean;
            token?: string;
            error?: { message?: string };
          };
          if (!sessionResponse.ok || !sessionPayload.ok || !sessionPayload.token) {
            throw new Error(
              sessionPayload.error?.message ?? "녹음 세션을 발급받지 못했습니다."
            );
          }
          sessionToken = sessionPayload.token;
        } catch (error) {
          reject(
            error instanceof Error
              ? error
              : new Error("네트워크/서버 오류: 녹음 세션 발급에 실패했습니다.")
          );
          return;
        }

        const socket = new WebSocket(realtimeSocketUrl());
        realtimeSocket.current = socket;
        if (!reconnecting) setActivity("connecting");
        let settled = false;
        let disconnectReported = false;
        const timeout = setTimeout(() => {
          if (realtimeSocket.current === socket) realtimeSocket.current = null;
          socket.close();
          if (!settled) {
            settled = true;
            reject(new Error("네트워크/서버 오류: realtime 모델 준비 시간이 초과되었습니다."));
          }
        }, 180_000);

        const reportDisconnect = (message: string) => {
          if (disconnectReported || realtimeSocket.current !== socket) return;
          disconnectReported = true;
          realtimeSocket.current = null;
          clearTimeout(timeout);
          if (!settled) {
            settled = true;
            reject(new Error(`네트워크/서버 오류: ${message}`));
            return;
          }
          void recoverRealtimeConnection(message);
        };

        socket.onopen = () =>
          socket.send(
            JSON.stringify({
              type: "start",
              sample_rate: 16_000,
              session_token: sessionToken,
            })
          );
        socket.onmessage = (message) => {
          try {
            const event = JSON.parse(String(message.data)) as RealtimeEvent;
            if (event.type === "error") {
              const serverMessage = event.message ?? "realtime 서버가 오류를 반환했습니다.";
              if (!settled) {
                settled = true;
                clearTimeout(timeout);
                if (realtimeSocket.current === socket) realtimeSocket.current = null;
                socket.close();
                reject(new Error(`네트워크/서버 오류: ${serverMessage}`));
              } else {
                reportDisconnect(serverMessage);
                socket.close();
              }
              return;
            }
            if (event.type === "ready" && !settled) {
              settled = true;
              clearTimeout(timeout);
              resolve(socket);
            }
            handleRealtimeEvent(event);
          } catch {
            setWorkspaceMessage("processing", "서버 응답을 해석하지 못했습니다.");
          }
        };
        socket.onerror = () => {
          reportDisconnect("realtime 서비스에 연결할 수 없습니다. 서버 상태를 확인해 주세요.");
          if (socket.readyState < WebSocket.CLOSING) socket.close();
        };
        socket.onclose = () => {
          if (!sessionEndedNormally.current && !discardSession.current) {
            reportDisconnect("realtime 연결이 예기치 않게 종료되었습니다.");
          }
        };
      })();
    });
  }

  async function recoverRealtimeConnection(message: string) {
    if (sessionEndedNormally.current || discardSession.current || reconnectInFlight.current) return;
    if (recordingActive.current && reconnectAttempts.current < 1) {
      reconnectAttempts.current += 1;
      reconnectInFlight.current = true;
      setWorkspaceMessage("network", "네트워크 연결이 끊겨 자동으로 한 번 재연결하고 있습니다.");
      try {
        const socket = await connectRealtimeSocket({ reconnecting: true });
        clearWorkspaceMessage();
        if (recordingActive.current) {
          setActivity("recording");
        } else {
          setActivity("processing");
          socket.send(JSON.stringify({ type: "stop" }));
        }
      } catch (caught) {
        const detail = caught instanceof Error ? caught.message.replace(/^네트워크\/서버 오류:\s*/, "") : message;
        await finalizeFailedSession(`네트워크/서버 오류: 자동 재연결에 실패했습니다. ${detail}`);
      } finally {
        reconnectInFlight.current = false;
      }
      return;
    }
    await finalizeFailedSession(`네트워크/서버 오류: ${message}`);
  }

  async function finalizeFailedSession(message: string, kind: WorkspaceMessageKind = "network") {
    if (failureFinalizing.current) return;
    failureFinalizing.current = true;
    pendingErrorMessage.current = message;
    setActivity("error");
    setWorkspaceMessage(kind, message);
    recordingActive.current = false;
    clearRecordingTimer();
    if (recordingStartedAt.current > 0) {
      const elapsed = Math.max(1, Math.floor((Date.now() - recordingStartedAt.current) / 1000));
      recordingDurationValue.current = Math.max(recordingDurationValue.current, elapsed);
      setRecordingSeconds(recordingDurationValue.current);
    }
    cleanupAudioGraph();
    closeRealtimeSocket();
    await stopMediaRecorder();
    stopMediaStream();
    await persistCompletedSession(message);
    failureFinalizing.current = false;
  }

  async function persistCompletedSession(failureMessage = pendingErrorMessage.current) {
    if (discardSession.current) return;
    const blob = pendingAudioBlob.current;
    const diagnosis = latestDiagnosis.current;
    const id = pendingHistoryId.current;
    const transcript = liveTranscriptValue.current.trim();
    if (!id || (!blob && !diagnosis && !transcript && !failureMessage)) return;
    const status: HistoryStatus = failureMessage
      ? "partial"
      : diagnosis?.rejected
        ? "rejected"
        : diagnosis
          ? "completed"
          : realtimeStopped.current
            ? "rejected"
            : "partial";

    const historyItem: HistoryItem = {
      id,
      createdAt: new Date().toISOString(),
      source: pendingSource.current,
      title: pendingTitle.current,
      transcript,
      durationSeconds: recordingDurationValue.current,
      result: diagnosis,
      status,
      errorMessage: failureMessage ?? undefined,
    };
    setHistory((previous) => [historyItem, ...previous.filter((item) => item.id !== id)].slice(0, MAX_HISTORY_ITEMS));
    setActiveHistoryId(id);
    if (blob) await saveRecording(id, blob).catch(() => undefined);
    if (pendingHistoryId.current === id) {
      pendingAudioBlob.current = null;
      pendingErrorMessage.current = null;
    }
  }

  async function startRecording() {
    if (isThinking) return;
    prepareSession("record", `회의 녹음 · ${new Intl.DateTimeFormat("ko-KR", { hour: "numeric", minute: "2-digit" }).format(new Date())}`, null);
    setRecordingSeconds(0);

    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setActivity("error");
      setWorkspaceMessage("processing", "이 브라우저에서는 마이크 녹음을 지원하지 않습니다. 최신 Chrome 또는 Edge를 사용해 주세요.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStream.current = stream;
      await connectRealtimeSocket();
      const preferredTypes = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
      const mimeType = preferredTypes.find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);

      mediaRecorder.current = recorder;
      audioChunks.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunks.current.push(event.data);
      };
      recorder.onstop = () => {
        pendingAudioBlob.current = new Blob(audioChunks.current, { type: recorder.mimeType || "audio/webm" });
        stream.getTracks().forEach((track) => track.stop());
        mediaStream.current = null;
        mediaRecorder.current = null;
        void persistCompletedSession();
      };
      recorder.onerror = () => {
        void finalizeFailedSession("녹음 처리 오류: 브라우저에서 오디오 데이터를 저장하지 못했습니다.", "processing");
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
        if (pcmRms(pcm) < 0.008) return;
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
      setActivity("recording");
    } catch (caught) {
      recordingActive.current = false;
      discardSession.current = true;
      stopMediaStream();
      cleanupAudioGraph();
      closeRealtimeSocket();
      setActivity("error");
      if (caught instanceof DOMException && caught.name === "NotAllowedError") {
        setWorkspaceMessage("permission", "마이크 권한이 필요합니다. 브라우저 주소창에서 마이크 사용을 허용해 주세요.");
      } else {
        const message = caught instanceof Error ? caught.message : "녹음을 시작하지 못했습니다.";
        setWorkspaceMessage(
          /네트워크|서버|realtime|연결/i.test(message) ? "network" : "processing",
          message,
        );
      }
    }
  }

  function stopRecording() {
    if (activity !== "recording") return;
    recordingActive.current = false;
    cleanupAudioGraph();
    clearRecordingTimer();
    const elapsed = Math.max(1, Math.floor((Date.now() - recordingStartedAt.current) / 1000));
    recordingDurationValue.current = elapsed;
    setRecordingSeconds(elapsed);
    setActivity("processing");
    if (realtimeSocket.current?.readyState === WebSocket.OPEN) {
      realtimeSocket.current.send(JSON.stringify({ type: "stop" }));
    }
    if (mediaRecorder.current?.state === "recording") mediaRecorder.current.stop();
  }

  async function retryRecording() {
    if (retrying) return;
    setRetrying(true);
    try {
      while (failureFinalizing.current) await wait(25);
      recordingActive.current = false;
      clearRecordingTimer();
      cleanupAudioGraph();
      closeRealtimeSocket();
      await stopMediaRecorder();
      stopMediaStream();
      setActivity("idle");
      clearWorkspaceMessage();
      await startRecording();
    } finally {
      setRetrying(false);
    }
  }

  function isAudioUpload(file: File) {
    return (
      file.type.startsWith("audio/") ||
      /\.(mp3|wav|m4a|aac|ogg|flac|webm)$/i.test(file.name)
    );
  }

  function isTextUpload(file: File) {
    return (
      file.type.startsWith("text/") ||
      file.type === "application/json" ||
      /\.(txt|md|markdown|csv|log|json)$/i.test(file.name)
    );
  }

  function selectFile(file: File | null) {
    if (!file || isThinking) return;
    const audio = isAudioUpload(file);
    const text = isTextUpload(file);
    if (!audio && !text) {
      setWorkspaceMessage(
        "processing",
        "녹음 파일(MP3, WAV 등) 또는 텍스트 파일(TXT, MD 등)만 업로드할 수 있습니다."
      );
      return;
    }
    const maxBytes = audio ? 200 * 1024 * 1024 : 5 * 1024 * 1024;
    if (file.size > maxBytes) {
      setWorkspaceMessage(
        "processing",
        audio
          ? "오디오 파일은 200MB 이하만 업로드할 수 있습니다."
          : "텍스트 파일은 5MB 이하만 업로드할 수 있습니다."
      );
      return;
    }
    setSelectedFile(file);
    clearWorkspaceMessage();
    setActivity("idle");
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    selectFile(event.target.files?.[0] ?? null);
    event.target.value = "";
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    selectFile(event.dataTransfer.files?.[0] ?? null);
  }

  async function decodeAudioFile(file: File) {
    const context = new AudioContext();
    try {
      const decoded = await context.decodeAudioData(await file.arrayBuffer());
      const mono = new Float32Array(decoded.length);
      for (let channel = 0; channel < decoded.numberOfChannels; channel += 1) {
        const channelData = decoded.getChannelData(channel);
        for (let index = 0; index < decoded.length; index += 1) {
          mono[index] += channelData[index] / decoded.numberOfChannels;
        }
      }
      return {
        pcm: downsampleTo16Khz(mono, decoded.sampleRate),
        durationSeconds: Math.max(1, Math.round(decoded.duration)),
      };
    } finally {
      await context.close();
    }
  }

  async function sendUploadedText(file: File) {
    prepareSession("text", file.name, null);
    setActivity("processing");
    try {
      const content = (await file.text()).trim();
      if (content.length < 8) {
        throw new Error("텍스트가 너무 짧습니다. 8자 이상 입력해 주세요.");
      }
      liveTranscriptValue.current = content;
      const response = await fetch("/api/realtime/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: content, language: "ko" }),
        cache: "no-store",
      });
      const payload = (await response.json()) as {
        ok?: boolean;
        diagnosis?: SuccessfulDiagnosis;
        transcript?: string;
        error?: { message?: string };
      };
      if (!response.ok || !payload.ok || !payload.diagnosis) {
        throw new Error(payload.error?.message ?? "텍스트 분석에 실패했습니다.");
      }
      if (payload.transcript) liveTranscriptValue.current = payload.transcript;
      realtimeStopped.current = true;
      sessionEndedNormally.current = true;
      applyDiagnosis(payload.diagnosis);
      setActivity("done");
      if (payload.diagnosis.rejected || payload.diagnosis.questions.length === 0) {
        setWorkspaceMessage(
          "rejected",
          "질문이 비어 반려되었습니다. 오류가 아니라 평가 기준을 넘은 질문이 없는 상태입니다."
        );
      } else {
        clearWorkspaceMessage();
      }
      await persistCompletedSession();
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : "텍스트 파일 분석에 실패했습니다.";
      const kind: WorkspaceMessageKind = /네트워크|서버|realtime|연결/i.test(message)
        ? "network"
        : "processing";
      pendingErrorMessage.current = message;
      setActivity("error");
      setWorkspaceMessage(kind, message);
      await persistCompletedSession(message);
    }
  }

  async function sendUploadedAudio() {
    if (!selectedFile || isThinking) return;
    if (isTextUpload(selectedFile) && !isAudioUpload(selectedFile)) {
      await sendUploadedText(selectedFile);
      return;
    }

    prepareSession("upload", selectedFile.name, selectedFile);
    setActivity("processing");

    try {
      const { pcm, durationSeconds } = await decodeAudioFile(selectedFile);
      recordingDurationValue.current = durationSeconds;
      setRecordingSeconds(durationSeconds);
      const socket = await connectRealtimeSocket();
      setActivity("processing");

      const chunkSize = 16_384;
      for (let offset = 0; offset < pcm.length; offset += chunkSize) {
        while (socket.bufferedAmount > 2 * 1024 * 1024) await wait(20);
        socket.send(pcm.slice(offset, Math.min(offset + chunkSize, pcm.length)).buffer);
        if ((offset / chunkSize) % 24 === 0) await wait(0);
      }
      socket.send(JSON.stringify({ type: "stop" }));
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "오디오 파일 분석에 실패했습니다.";
      const kind: WorkspaceMessageKind = /네트워크|서버|realtime|연결/i.test(message) ? "network" : "processing";
      pendingErrorMessage.current = message;
      closeRealtimeSocket();
      setActivity("error");
      setWorkspaceMessage(kind, message);
      await persistCompletedSession(message);
    }
  }

  function dismissThought(id: string) {
    setDismissingIds((previous) => new Set(previous).add(id));
    const timer = setTimeout(() => {
      setThoughts((previous) => previous.filter((thought) => thought.id !== id));
      setDismissingIds((previous) => {
        const next = new Set(previous);
        next.delete(id);
        return next;
      });
    }, 320);
    dismissTimers.current.push(timer);
  }

  function switchMode(nextMode: WorkspaceMode) {
    if (isThinking) return;
    setMode(nextMode);
    clearWorkspaceMessage();
    setActivity("idle");
  }

  function askFromBrain() {
    if (activity !== "recording") return;
    const socket = realtimeSocket.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setWorkspaceMessage("network", "녹음 연결이 아직 준비되지 않았습니다. 잠시 후 다시 눌러 주세요.");
      return;
    }
    setIsEmittingQuestion(true);
    if (questionBurstTimer.current) clearTimeout(questionBurstTimer.current);
    questionBurstTimer.current = setTimeout(() => {
      setIsEmittingQuestion(false);
      questionBurstTimer.current = null;
    }, 1400);
    socket.send(JSON.stringify({ type: "ask" }));
  }

  function startNewMeeting() {
    if (activity === "recording") {
      discardSession.current = true;
      stopRecording();
    }
    setThoughts([]);
    setDismissingIds(new Set());
    setIsEmittingQuestion(false);
    knownQuestionIds.current = new Set();
    nextThoughtSlot.current = 0;
    if (questionBurstTimer.current) clearTimeout(questionBurstTimer.current);
    setSelectedFile(null);
    setRecordingSeconds(0);
    clearWorkspaceMessage();
    setActivity("idle");
    setActiveHistoryId(null);
  }

  function openHistory(item: HistoryItem) {
    if (isThinking) return;
    knownQuestionIds.current = new Set((item.result?.questions ?? []).map((question) => question.id));
    setIsEmittingQuestion(false);
    if (questionBurstTimer.current) clearTimeout(questionBurstTimer.current);
    nextThoughtSlot.current = 0;
    setThoughts((item.result?.questions ?? []).slice(0, MAX_VISIBLE_THOUGHTS).map((question, index) => ({
      id: question.id,
      text: question.text,
      createdAt: index,
      slot: index,
    })));
    setMode(item.source === "upload" || item.source === "text" ? "upload" : "record");
    setRecordingSeconds(item.durationSeconds ?? 0);
    setActivity("done");
    if (item.status === "rejected" || item.result?.rejected) {
      setWorkspaceMessage("rejected", "질문이 비어 반려된 기록입니다. 오류가 아니라 평가 기준을 넘은 질문이 없었던 상태입니다.");
    } else if (item.errorMessage) {
      setWorkspaceMessage(
        /네트워크|서버|realtime|연결/i.test(item.errorMessage) ? "network" : "processing",
        item.errorMessage,
      );
    } else {
      clearWorkspaceMessage();
    }
    setActiveHistoryId(item.id);
    setSidebarOpen(false);
  }

  async function removeHistory(item: HistoryItem) {
    setHistory((previous) => previous.filter((entry) => entry.id !== item.id));
    if (item.source === "record" || item.source === "upload") await deleteRecording(item.id).catch(() => undefined);
    if (activeHistoryId === item.id) startNewMeeting();
  }

  return (
    <main className="site-shell">
      <div className="ambient-light ambient-light-one" aria-hidden="true" />
      <div className="ambient-light ambient-light-two" aria-hidden="true" />
      <header className="topbar">
        <button
          className="sidebar-toggle"
          type="button"
          aria-label={sidebarOpen ? "기록 닫기" : "기록 열기"}
          aria-pressed={sidebarOpen}
          onClick={() => setSidebarOpen((open) => !open)}
        >
          <Icon name="history" />
        </button>
        <a className="brand" href="/" aria-label="STEIN 홈">
          <span className="brand-mark"><BrainLogoIcon /></span><span className="brand-name">STEIN</span>
        </a>
        <span className="brand-subtitle">회의를 녹음하면 맥락을 실시간으로 읽고 후보 질문을 생성·평가해, 기준을 넘은 질문만 건넵니다.</span>
      </header>

      <div className={`app-layout${sidebarOpen ? "" : " sidebar-collapsed"}`}>
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
                  <span className="history-source"><Icon name={item.source === "record" ? "mic" : item.source === "upload" ? "upload" : "text"} /></span>
                  <span className="history-summary"><strong>{item.title}</strong><small>{formatHistoryTime(item.createdAt)} · {formatHistoryMeta(item)}</small></span>
                </button>
                <button className="history-remove" type="button" aria-label={`${item.title} 삭제`} onClick={() => removeHistory(item)}><Icon name="close" /></button>
              </div>
            ))}
          </div>
          <p className="history-storage-note">기록과 녹음은 이 브라우저에만 저장됩니다.</p>
        </aside>

        <section className="brain-workspace" aria-label="회의 질문 생성">
          <div className={`mode-switch ${mode}`} role="tablist" aria-label="입력 모드">
            <span className="mode-switch-slider" aria-hidden="true" />
            <button type="button" role="tab" aria-selected={mode === "upload"} disabled={isThinking} onClick={() => switchMode("upload")}><Icon name="upload" />파일 업로드</button>
            <button type="button" role="tab" aria-selected={mode === "record"} disabled={isThinking} onClick={() => switchMode("record")}><Icon name="mic" />녹음 · 실시간</button>
          </div>

          <div className={`thought-stage${activity === "recording" ? " is-listening" : ""}${isEmittingQuestion ? " is-emitting-question" : ""}`} aria-live="polite">
            {thoughts.map((thought) => (
              <button
                key={thought.id}
                className={`thought-bubble slot-${thought.slot}${dismissingIds.has(thought.id) ? " is-dismissing" : ""}`}
                data-side={thought.slot % 2 === 0 ? "left" : "right"}
                type="button"
                title="해결된 질문으로 표시하고 지우기"
                onClick={() => dismissThought(thought.id)}
              >
                <span>{thought.text}</span>
                <small><Icon name="check" /> 해결했다면 클릭</small>
              </button>
            ))}

            <div className="brain-center">
              <button
                type="button"
                className={`brain-core${activity === "recording" ? " is-clickable" : ""}`}
                disabled={activity !== "recording"}
                aria-label={activity === "recording" ? "지금 질문 받기" : "녹음 중일 때 클릭하면 질문이 나옵니다"}
                title={activity === "recording" ? "클릭하면 질문을 요청합니다" : undefined}
                onClick={askFromBrain}
              >
                <BrainIcon />
              </button>
              {activity === "recording" && <time>{formatDuration(recordingSeconds)}</time>}
            </div>
          </div>

          <div className="interaction-panel">
            {mode === "upload" ? (
              <>
                <label className={`upload-zone${selectedFile ? " has-file" : ""}`} onDragOver={(event) => event.preventDefault()} onDrop={handleDrop}>
                  <input
                    type="file"
                    accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac,.webm,text/plain,.txt,.md,.markdown,.csv,.log,.json,application/json"
                    disabled={isThinking}
                    onChange={handleFileChange}
                  />
                  <span className="upload-zone-icon"><Icon name={selectedFile ? "check" : "upload"} /></span>
                  <strong>
                    {selectedFile
                      ? selectedFile.name
                      : "녹음·텍스트 파일을 놓거나 클릭하세요"}
                  </strong>
                  <span>
                    {selectedFile
                      ? isTextUpload(selectedFile) && !isAudioUpload(selectedFile)
                        ? `${(selectedFile.size / 1024).toFixed(1)}KB · 텍스트`
                        : `${(selectedFile.size / 1024 / 1024).toFixed(1)}MB · ${formatDuration(recordingSeconds)}`
                      : "오디오 MP3/WAV 등 · 텍스트 TXT/MD 등 · 오디오 최대 200MB"}
                  </span>
                </label>
                <button className="generate-button" type="button" disabled={!selectedFile || isThinking} onClick={() => void sendUploadedAudio()}><Icon name="spark" />질문 생성 시작</button>
              </>
            ) : (
              <div className="live-controls">
                <button
                  className={`live-record-button${activity === "recording" ? " is-recording" : ""}`}
                  type="button"
                  disabled={activity === "connecting" || activity === "processing" || retrying}
                  onClick={activity === "recording" ? stopRecording : activity === "error" ? () => void retryRecording() : startRecording}
                >
                  <Icon name={activity === "recording" ? "stop" : "mic"} />
                  <span>{activity === "recording" ? "녹음 종료" : activity === "error" ? "다시 녹음" : activity === "done" ? "새 녹음 시작" : "녹음 시작"}</span>
                </button>
                <p>
                  {activity === "recording"
                    ? "침묵이 길어지거나 뇌를 클릭하면 질문이 나옵니다."
                    : "마이크 권한을 허용하면 실시간으로 회의를 분석합니다."}
                </p>
              </div>
            )}
            {error && (
              <div className={`workspace-feedback ${errorKind ?? "processing"}`} role="alert">
                <strong>{errorKind === "network" ? "네트워크/서버 오류" : errorKind === "rejected" ? "질문 반려" : errorKind === "permission" ? "마이크 권한 필요" : "처리 오류"}</strong>
                <p>{error}</p>
                {activity === "error" && mode === "record" && errorKind === "network" && (
                  <button type="button" disabled={retrying} onClick={() => void retryRecording()}>{retrying ? "재연결 중…" : "연결 재시도"}</button>
                )}
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
