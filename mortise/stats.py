"""Observed throughput per (host, model), persisted as JSON."""

import json
from pathlib import Path

from .history import history_dir


def _stats_path() -> Path:
    """Location of the throughput store (sibling of the sessions dir)."""
    return history_dir().parent / "throughput.json"


def _load() -> dict:
    """Read the throughput store, or {} if it does not exist."""
    path = _stats_path()
    return json.loads(path.read_text()) if path.is_file() else {}


def _save(data: dict) -> None:
    """Write the throughput store."""
    _stats_path().write_text(json.dumps(data))


def _key(host: str, model: str) -> str:
    """Composite store key for a host and model."""
    return f"{host}\x00{model}"


def record(host: str, model: str, tok_s: float) -> None:
    """Fold a new tokens/sec sample into the running mean for host+model."""
    data = _load()
    entry = data.get(_key(host, model), {"tok_s": 0.0, "n": 0})
    count = entry["n"]
    entry["tok_s"] = (entry["tok_s"] * count + tok_s) / (count + 1)
    entry["n"] = count + 1
    data[_key(host, model)] = entry
    _save(data)


def get(host: str, model: str) -> float | None:
    """Return the mean observed tokens/sec for host+model, if measured."""
    entry = _load().get(_key(host, model))
    return entry["tok_s"] if entry else None
