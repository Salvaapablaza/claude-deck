"""Session state store and slot assignment."""

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MAX_SLOTS = 15

TERMINAL_HOSTS = {"code.exe", "windowsterminal.exe", "wt.exe"}

EVENT_STATE_MAP = {
    "SessionStart": "idle",
    "UserPromptSubmit": "running",
    "Stop": "idle",
    "SessionEnd": "offline",
}


@dataclass
class Session:
    session_id: str
    cwd: str
    slot: int
    state: str = "idle"
    last_event: float = field(default_factory=time.time)
    ancestry: list[int] = field(default_factory=list)

    @property
    def label(self) -> str:
        return Path(self.cwd).name if self.cwd else self.session_id[:7]


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}
        self._dirty_slots: set[int] = set()

    def _free_slot(self) -> Optional[int]:
        used = {s.slot for s in self._sessions.values()}
        for slot in range(1, MAX_SLOTS + 1):
            if slot not in used:
                return slot
        return None

    def handle_event(
        self,
        session_id: str,
        cwd: str,
        event: str,
        message: str = "",
        ancestry: Optional[list[int]] = None,
        ancestry_names: Optional[list[str]] = None,
    ) -> None:
        with self._lock:
            session = self._sessions.get(session_id)

            if event == "SessionEnd":
                if session:
                    self._dirty_slots.add(session.slot)
                    del self._sessions[session_id]
                return

            if session is None:
                if ancestry_names and not TERMINAL_HOSTS.intersection(ancestry_names):
                    return
                slot = self._free_slot()
                if slot is None:
                    return
                session = Session(session_id=session_id, cwd=cwd, slot=slot)
                self._sessions[session_id] = session

            if cwd:
                session.cwd = cwd
            if ancestry:
                session.ancestry = ancestry
            session.last_event = time.time()

            if event == "Notification":
                lowered = message.lower()
                if "permission" in lowered:
                    session.state = "permission"
                elif session.state == "running":
                    session.state = "question"
            else:
                session.state = EVENT_STATE_MAP.get(event, session.state)

            self._dirty_slots.add(session.slot)

    def session_for_slot(self, slot: int) -> Optional[Session]:
        with self._lock:
            for session in self._sessions.values():
                if session.slot == slot:
                    return session
            return None

    def attention_session(self) -> Optional[Session]:
        """Most recently active session waiting on the user."""
        with self._lock:
            waiting = [
                s
                for s in self._sessions.values()
                if s.state in ("permission", "question")
            ]
            if not waiting:
                return None
            return max(waiting, key=lambda s: s.last_event)

    def snapshot(self) -> list[Session]:
        with self._lock:
            return list(self._sessions.values())

    def pop_dirty(self) -> set[int]:
        with self._lock:
            dirty = self._dirty_slots
            self._dirty_slots = set()
            return dirty

    def mark_all_dirty(self) -> None:
        with self._lock:
            self._dirty_slots.update(range(1, MAX_SLOTS + 1))

    def sweep_stale(self, max_age_s: float = 12 * 3600) -> None:
        """Drop sessions that stopped sending events (killed terminals etc.)."""
        now = time.time()
        with self._lock:
            for sid, session in list(self._sessions.items()):
                if now - session.last_event > max_age_s:
                    self._dirty_slots.add(session.slot)
                    del self._sessions[sid]
