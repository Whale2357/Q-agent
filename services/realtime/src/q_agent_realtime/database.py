from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Iterable

from .domain import (
    QuestionCandidate,
    QuestionContextState,
    QuestionStatus,
    TranscriptSegment,
    utc_now,
)


class Repository:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meetings (
                    id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    ended_at TEXT
                );

                CREATE TABLE IF NOT EXISTS transcript_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
                );

                CREATE INDEX IF NOT EXISTS idx_segments_meeting_id
                ON transcript_segments(meeting_id, id);

                CREATE TABLE IF NOT EXISTS context_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(meeting_id, version),
                    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
                );

                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY,
                    meeting_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    meeting_purpose TEXT NOT NULL,
                    detected_problem TEXT NOT NULL,
                    question_role TEXT NOT NULL,
                    theory TEXT NOT NULL,
                    context_version INTEGER NOT NULL DEFAULT 0,
                    category TEXT NOT NULL DEFAULT 'essence',
                    operator TEXT NOT NULL DEFAULT 'criterion_clarification',
                    evidence_segment_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    information_gain REAL NOT NULL DEFAULT 0,
                    non_redundancy REAL NOT NULL DEFAULT 0,
                    assumption_surfacing REAL NOT NULL DEFAULT 0,
                    final_score REAL NOT NULL DEFAULT 0,
                    evaluation_reason TEXT NOT NULL DEFAULT '',
                    generated_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    displayed_at TEXT,
                    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
                );

                CREATE INDEX IF NOT EXISTS idx_questions_meeting_status
                ON questions(meeting_id, status, final_score DESC);
                """
            )
            self._ensure_column("questions", "context_version", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column("questions", "category", "TEXT NOT NULL DEFAULT 'essence'")
            self._ensure_column(
                "questions",
                "operator",
                "TEXT NOT NULL DEFAULT 'criterion_clarification'",
            )

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            str(row["name"])
            for row in self._connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self._connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def create_meeting(self, objective: str = "") -> str:
        meeting_id = f"mtg_{uuid.uuid4().hex[:12]}"
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO meetings(id, objective, started_at) VALUES (?, ?, ?)",
                (meeting_id, objective, utc_now()),
            )
        return meeting_id

    def end_meeting(self, meeting_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE meetings SET ended_at = ? WHERE id = ?", (utc_now(), meeting_id)
            )

    def add_segment(self, segment: TranscriptSegment) -> TranscriptSegment:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO transcript_segments(meeting_id, start_ms, end_ms, text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    segment.meeting_id,
                    segment.start_ms,
                    segment.end_ms,
                    segment.text,
                    segment.created_at,
                ),
            )
            segment.id = int(cursor.lastrowid)
        return segment

    def segments_after(self, meeting_id: str, segment_id: int) -> list[TranscriptSegment]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM transcript_segments
                WHERE meeting_id = ? AND id > ?
                ORDER BY id ASC
                """,
                (meeting_id, segment_id),
            ).fetchall()
        return [self._row_to_segment(row) for row in rows]

    def recent_segments(self, meeting_id: str, seconds: float) -> list[TranscriptSegment]:
        with self._lock:
            last = self._connection.execute(
                "SELECT MAX(end_ms) AS max_end FROM transcript_segments WHERE meeting_id = ?",
                (meeting_id,),
            ).fetchone()
            max_end = int(last["max_end"] or 0)
            cutoff = max(0, max_end - int(seconds * 1000))
            rows = self._connection.execute(
                """
                SELECT * FROM transcript_segments
                WHERE meeting_id = ? AND end_ms >= ?
                ORDER BY id ASC
                """,
                (meeting_id, cutoff),
            ).fetchall()
        return [self._row_to_segment(row) for row in rows]

    def save_context(self, state: QuestionContextState) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO context_snapshots(meeting_id, version, state_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    state.meeting_id,
                    state.version,
                    json.dumps(state.to_dict(), ensure_ascii=False),
                    state.updated_at,
                ),
            )

    def latest_context(self, meeting_id: str) -> QuestionContextState | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT state_json FROM context_snapshots
                WHERE meeting_id = ? ORDER BY version DESC LIMIT 1
                """,
                (meeting_id,),
            ).fetchone()
        return QuestionContextState.from_dict(json.loads(row["state_json"])) if row else None

    def save_questions(self, questions: Iterable[QuestionCandidate]) -> None:
        with self._lock, self._connection:
            for question in questions:
                self._connection.execute(
                    """
                    INSERT INTO questions(
                        id, meeting_id, text, meeting_purpose, detected_problem,
                        question_role, theory, context_version, category, operator,
                        evidence_segment_ids_json, status,
                        information_gain, non_redundancy, assumption_surfacing,
                        final_score, evaluation_reason, generated_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        status = excluded.status,
                        context_version = excluded.context_version,
                        category = excluded.category,
                        operator = excluded.operator,
                        information_gain = excluded.information_gain,
                        non_redundancy = excluded.non_redundancy,
                        assumption_surfacing = excluded.assumption_surfacing,
                        final_score = excluded.final_score,
                        evaluation_reason = excluded.evaluation_reason,
                        updated_at = excluded.updated_at
                    """,
                    (
                        question.id,
                        question.meeting_id,
                        question.text,
                        question.meeting_purpose,
                        question.detected_problem,
                        question.question_role,
                        question.theory,
                        question.context_version,
                        question.category,
                        question.operator,
                        json.dumps(question.evidence_segment_ids),
                        question.status.value,
                        question.information_gain,
                        question.non_redundancy,
                        question.assumption_surfacing,
                        question.final_score,
                        question.evaluation_reason,
                        question.generated_at,
                        question.updated_at,
                    ),
                )

    def expire_eligible_questions_before(
        self, meeting_id: str, context_version: int
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE questions
                SET status = ?, updated_at = ?
                WHERE meeting_id = ? AND status = ? AND context_version < ?
                """,
                (
                    QuestionStatus.EXPIRED.value,
                    utc_now(),
                    meeting_id,
                    QuestionStatus.ELIGIBLE.value,
                    context_version,
                ),
            )

    def questions_by_status(
        self, meeting_id: str, statuses: Iterable[QuestionStatus]
    ) -> list[QuestionCandidate]:
        values = [status.value for status in statuses]
        if not values:
            return []
        placeholders = ",".join("?" for _ in values)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT * FROM questions
                WHERE meeting_id = ? AND status IN ({placeholders})
                ORDER BY final_score DESC, generated_at ASC
                """,
                [meeting_id, *values],
            ).fetchall()
        return [self._row_to_question(row) for row in rows]

    def best_eligible_question(self, meeting_id: str) -> QuestionCandidate | None:
        questions = self.questions_by_status(meeting_id, [QuestionStatus.ELIGIBLE])
        return questions[0] if questions else None

    def update_question_status(self, question_id: str, status: QuestionStatus) -> None:
        displayed_at = utc_now() if status is QuestionStatus.DISPLAYED else None
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE questions
                SET status = ?, updated_at = ?, displayed_at = COALESCE(?, displayed_at)
                WHERE id = ?
                """,
                (status.value, utc_now(), displayed_at, question_id),
            )

    def question_history(self, meeting_id: str) -> dict[str, list[dict[str, object]]]:
        mapping = {
            "active": [QuestionStatus.ELIGIBLE],
            "displayed": [QuestionStatus.DISPLAYED],
            "resolved": [QuestionStatus.RESOLVED, QuestionStatus.EXPIRED],
            "rejected": [QuestionStatus.REJECTED],
        }
        history: dict[str, list[dict[str, object]]] = {}
        for key, statuses in mapping.items():
            history[key] = [
                {"id": question.id, "text": question.text, "status": question.status.value}
                for question in self.questions_by_status(meeting_id, statuses)[:20]
            ]
        return history

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @staticmethod
    def _row_to_segment(row: sqlite3.Row) -> TranscriptSegment:
        return TranscriptSegment(
            id=int(row["id"]),
            meeting_id=str(row["meeting_id"]),
            start_ms=int(row["start_ms"]),
            end_ms=int(row["end_ms"]),
            text=str(row["text"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _row_to_question(row: sqlite3.Row) -> QuestionCandidate:
        return QuestionCandidate(
            id=str(row["id"]),
            meeting_id=str(row["meeting_id"]),
            text=str(row["text"]),
            meeting_purpose=str(row["meeting_purpose"]),
            detected_problem=str(row["detected_problem"]),
            question_role=str(row["question_role"]),
            theory=str(row["theory"]),
            context_version=int(row["context_version"]),
            category=str(row["category"]),
            operator=str(row["operator"]),
            evidence_segment_ids=json.loads(row["evidence_segment_ids_json"]),
            status=QuestionStatus(str(row["status"])),
            information_gain=float(row["information_gain"]),
            non_redundancy=float(row["non_redundancy"]),
            assumption_surfacing=float(row["assumption_surfacing"]),
            final_score=float(row["final_score"]),
            evaluation_reason=str(row["evaluation_reason"]),
            generated_at=str(row["generated_at"]),
            updated_at=str(row["updated_at"]),
        )
