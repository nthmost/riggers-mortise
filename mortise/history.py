"""Persistent per-model conversation history (JSONL session transcripts)."""

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .rig import Rig


def history_dir() -> Path:
    """Directory holding session transcripts (XDG state, created on demand)."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    path = Path(base) / "mortise" / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slug(model: str) -> str:
    """Filesystem-safe form of a model name."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", model)


@dataclass
class Session:
    """One conversation transcript on disk."""

    path: Path
    model: str
    host: str
    started: float
    turns: int

    @property
    def id(self) -> str:
        """Stable identifier (the file stem)."""
        return self.path.stem


def _write_line(path: Path, obj: dict) -> None:
    """Append one JSON object as a line to a transcript file."""
    with path.open("a") as handle:
        handle.write(json.dumps(obj) + "\n")


def new_session(rig: Rig) -> Session:
    """Create a fresh transcript file for a rig and write its header."""
    started = time.time()
    path = history_dir() / f"{int(started * 1000)}-{_slug(rig.model)}.jsonl"
    _write_line(path, {"meta": {"model": rig.model, "host": rig.host, "started": started}})
    return Session(path=path, model=rig.model, host=rig.host, started=started, turns=0)


def append_message(session: Session, role: str, content: str) -> None:
    """Append one chat message to a session transcript."""
    _write_line(session.path, {"role": role, "content": content})
    if role == "assistant":
        session.turns += 1


def load_messages(session: Session) -> list[dict]:
    """Read the chat messages from a transcript (excludes the meta line)."""
    lines = session.path.read_text().splitlines()
    parsed = [json.loads(line) for line in lines]
    return [{"role": obj["role"], "content": obj["content"]} for obj in parsed if "role" in obj]


def _count_replies(lines: list[str]) -> int:
    """Count assistant messages among transcript lines."""
    return sum(1 for line in lines if json.loads(line).get("role") == "assistant")


def _read_session(path: Path) -> Session | None:
    """Build a Session from a transcript file, or None if unreadable."""
    lines = path.read_text().splitlines()
    if not lines:
        return None
    meta = json.loads(lines[0]).get("meta", {})
    return Session(
        path=path,
        model=meta.get("model", "?"),
        host=meta.get("host", "?"),
        started=meta.get("started", 0.0),
        turns=_count_replies(lines[1:]),
    )


def list_sessions() -> list[Session]:
    """All stored transcripts, newest first."""
    found = [_read_session(path) for path in history_dir().glob("*.jsonl")]
    live = [session for session in found if session is not None]
    return sorted(live, key=lambda session: session.started, reverse=True)


def latest_session(model: str) -> Session | None:
    """Most recent transcript for a given model, if any."""
    return next((session for session in list_sessions() if session.model == model), None)


def session_by_id(session_id: str) -> Session | None:
    """Look up a transcript by its id (file stem) or the alias 'last'."""
    sessions = list_sessions()
    if session_id == "last":
        return sessions[0] if sessions else None
    return next((session for session in sessions if session.id == session_id), None)


def counts_by_model() -> dict[str, int]:
    """Map each model name to how many stored conversations it has."""
    counts: dict[str, int] = {}
    for session in list_sessions():
        counts[session.model] = counts.get(session.model, 0) + 1
    return counts
