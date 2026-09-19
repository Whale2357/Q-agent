from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class SessionTicket:
    token: str
    expires_at: float
    kind: str = "audio"


class SessionGate:
    """Issues short-lived WS tickets and caps concurrent audio sessions."""

    def __init__(
        self,
        *,
        api_key: str = "",
        max_audio_sessions: int = 2,
        session_ttl_seconds: float = 120.0,
        max_pending_tickets: int = 128,
        max_text_sessions: int = 2,
    ) -> None:
        self.api_key = api_key.strip()
        self.max_audio_sessions = max(1, max_audio_sessions)
        self.session_ttl_seconds = max(1.0, session_ttl_seconds)
        self.max_pending_tickets = max(1, max_pending_tickets)
        self.max_text_sessions = max(1, max_text_sessions)
        self._lock = threading.Lock()
        self._tickets: dict[str, SessionTicket] = {}
        self._active_audio = 0
        self._active_text = 0

    @property
    def auth_required(self) -> bool:
        return bool(self.api_key)

    def check_api_key(self, authorization: str | None) -> bool:
        if not self.auth_required:
            return True
        if not authorization:
            return False
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() != "bearer":
            return False
        return secrets.compare_digest(value.strip().encode(), self.api_key.encode())

    def issue_ticket(self, *, kind: str = "audio") -> SessionTicket:
        self._purge_expired()
        token = secrets.token_urlsafe(24)
        ticket = SessionTicket(
            token=token,
            expires_at=time.time() + self.session_ttl_seconds,
            kind=kind,
        )
        with self._lock:
            if len(self._tickets) >= self.max_pending_tickets:
                raise ValueError("Too many pending session tickets")
            self._tickets[token] = ticket
        return ticket

    def consume_ticket(self, token: str | None) -> SessionTicket | None:
        if not isinstance(token, str) or not token or len(token) > 256:
            return None
        self._purge_expired()
        with self._lock:
            ticket = self._tickets.pop(token, None)
        if ticket is None:
            return None
        if ticket.expires_at < time.time():
            return None
        return ticket

    def try_acquire_audio_slot(self) -> bool:
        with self._lock:
            if self._active_audio >= self.max_audio_sessions:
                return False
            self._active_audio += 1
            return True

    def release_audio_slot(self) -> None:
        with self._lock:
            self._active_audio = max(0, self._active_audio - 1)

    def try_acquire_text_slot(self) -> bool:
        with self._lock:
            if self._active_text >= self.max_text_sessions:
                return False
            self._active_text += 1
            return True

    def release_text_slot(self) -> None:
        with self._lock:
            self._active_text = max(0, self._active_text - 1)

    @property
    def active_audio_sessions(self) -> int:
        with self._lock:
            return self._active_audio

    def _purge_expired(self) -> None:
        now = time.time()
        with self._lock:
            expired = [key for key, ticket in self._tickets.items() if ticket.expires_at < now]
            for key in expired:
                del self._tickets[key]
