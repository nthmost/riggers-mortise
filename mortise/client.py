"""Library API: pick rigs and run completions with no terminal UI."""

import asyncio
import re
import time
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from . import stats
from .backends import ollama, openai
from .identity import canonical_host
from .rig import Rig
from .select import find, rank

POLICIES = ("auto", "fast", "capable", "cheap")


def as_messages(prompt: str | list[dict]) -> list[dict]:
    """Accept a string prompt or an existing message list, return messages."""
    if isinstance(prompt, str):
        return [{"role": "user", "content": prompt}]
    return prompt


def _stream_fn(rig: Rig):
    """Select the streaming function for a rig's backend."""
    return ollama.chat_stream if rig.backend == "ollama" else openai.chat_stream


def _tok_s(metrics: dict, reply: str, elapsed: float) -> float:
    """Tokens/sec from exact eval stats, else a client-side estimate."""
    count, duration = metrics.get("eval_count"), metrics.get("eval_duration")
    if count and duration:
        return count / (duration / 1e9)
    return (len(reply) // 4) / elapsed if elapsed > 0 else 0.0


def _record(rig: Rig, reply: str, elapsed: float, metrics: dict) -> None:
    """Persist observed throughput for a rig's host and model."""
    tok_s = _tok_s(metrics, reply, elapsed)
    if tok_s > 0:
        stats.record(canonical_host(httpx.URL(rig.endpoint).host), rig.model, tok_s)


async def _stream(http: httpx.AsyncClient, rig: Rig, messages: list[dict], timeout: float, record: bool) -> AsyncIterator[str]:
    """Stream tokens over a given HTTP client, recording throughput at the end."""
    parts: list[str] = []
    metrics: dict = {}
    start = time.perf_counter()
    async for chunk in _stream_fn(rig)(http, rig, messages, timeout, metrics):
        parts.append(chunk)
        yield chunk
    if record:
        _record(rig, "".join(parts), time.perf_counter() - start, metrics)


async def stream(rig: Rig, prompt: str | list[dict], *, timeout: float = 120.0, http: httpx.AsyncClient | None = None, record: bool = True) -> AsyncIterator[str]:
    """Stream assistant tokens from a rig (opens its own HTTP client if none given)."""
    messages = as_messages(prompt)
    if http is not None:
        async for chunk in _stream(http, rig, messages, timeout, record):
            yield chunk
        return
    async with httpx.AsyncClient() as owned:
        async for chunk in _stream(owned, rig, messages, timeout, record):
            yield chunk


async def complete(rig: Rig, prompt: str | list[dict], *, timeout: float = 120.0, http: httpx.AsyncClient | None = None, record: bool = True) -> str:
    """Return the full assistant reply from a rig as a string."""
    parts = [chunk async for chunk in stream(rig, prompt, timeout=timeout, http=http, record=record)]
    return "".join(parts)


async def stoke(rig: Rig, *, ttl: float | None = None, timeout: float = 120.0, http: httpx.AsyncClient | None = None) -> bool:
    """Keep a rig hot: preload and pin its model in memory, producing no tokens.

    Tend the firebox so the next generation never cold-starts. `ttl` is how long
    to stay hot in seconds; None pins it indefinitely. Returns True if stoked,
    False if the backend has no notion of warmth to tend (e.g. an openai router).
    """
    if rig.backend != "ollama":
        return False
    keep_alive = -1 if ttl is None else int(ttl)
    if http is not None:
        return await ollama.stoke(http, rig, keep_alive, timeout)
    async with httpx.AsyncClient() as owned:
        return await ollama.stoke(owned, rig, keep_alive, timeout)


async def unstoke(rig: Rig, *, timeout: float = 30.0, http: httpx.AsyncClient | None = None) -> bool:
    """Let a stoked rig go cold, releasing its memory (Ollama keep_alive: 0)."""
    return await stoke(rig, ttl=0, timeout=timeout, http=http)


def _matches(rig: Rig, min_size: float | None, backend: str | None, host: str | None) -> bool:
    """Whether a rig passes the optional selection filters."""
    if min_size and (rig.size_b or 0.0) < min_size:
        return False
    if backend and rig.backend != backend:
        return False
    if host and host not in rig.host:
        return False
    return True


def _filter(rigs: list[Rig], min_size: float | None, backend: str | None, host: str | None) -> list[Rig]:
    """Apply optional selection filters to a rig list."""
    return [rig for rig in rigs if _matches(rig, min_size, backend, host)]


def _capable_key(rig: Rig) -> tuple[int, float]:
    """Order key for 'capable': models that fit first, then largest."""
    return (1 if rig.oversized else 0, -(rig.size_b or 0.0))


def _ordered_by_policy(rigs: list[Rig], policy: str) -> list[Rig]:
    """Rank a pool of rigs according to a routing policy."""
    if policy == "auto":
        return rank(rigs)
    if policy == "fast":
        return sorted(rigs, key=lambda rig: rig.tok_s or 0.0, reverse=True)
    if policy == "capable":
        return sorted(rigs, key=_capable_key)
    return sorted(rigs, key=lambda rig: rig.size_b or 1e9)  # cheap


def order(rigs: list[Rig], spec: str = "auto", *, min_size: float | None = None, backend: str | None = None, host: str | None = None) -> list[Rig]:
    """Candidate rigs for a spec (policy or exact model), best-first, for failover."""
    pool = _filter(rigs, min_size, backend, host)
    if spec in POLICIES:
        return _ordered_by_policy(pool, spec)
    hit = find(pool, spec)
    return [hit] if hit else []


def pick(rigs: list[Rig], spec: str = "auto", *, min_size: float | None = None, backend: str | None = None, host: str | None = None) -> Rig | None:
    """Choose the single best rig for a spec (policy name or exact model)."""
    candidates = order(rigs, spec, min_size=min_size, backend=backend, host=host)
    return candidates[0] if candidates else None


def distinct(rigs: list[Rig]) -> list[Rig]:
    """Drop repeated rigs, preserving order (by backend, endpoint, model)."""
    seen: set[tuple] = set()
    out: list[Rig] = []
    for rig in rigs:
        if rig.key not in seen:
            seen.add(rig.key)
            out.append(rig)
    return out


@dataclass
class Answer:
    """One rig's response to a fanned-out prompt."""

    rig: Rig
    text: str | None  # None if the rig failed
    error: str | None = None


@dataclass
class Verdict:
    """A judge rig's choice among candidate answers."""

    winner: Answer
    index: int
    reason: str
    raw: str


async def fanout(prompt: str | list[dict], rigs: list[Rig], *, timeout: float = 120.0, record: bool = True) -> list[Answer]:
    """Run the same prompt on several rigs concurrently, gathering all replies."""
    async with httpx.AsyncClient() as http:
        return await asyncio.gather(*(_answer(http, rig, prompt, timeout, record) for rig in rigs))


async def _answer(http: httpx.AsyncClient, rig: Rig, prompt: str | list[dict], timeout: float, record: bool) -> Answer:
    """Complete against one rig, capturing failures instead of raising."""
    try:
        text = await complete(rig, prompt, timeout=timeout, http=http, record=record)
        return Answer(rig=rig, text=text)
    except httpx.HTTPError as error:
        return Answer(rig=rig, text=None, error=str(error))


def _label(index: int) -> str:
    """Letter label for a candidate answer (0 -> A, 1 -> B, ...)."""
    return chr(ord("A") + index)


def _judge_prompt(task: str, answers: list[Answer]) -> str:
    """Build the instruction that asks a judge to pick the best candidate."""
    blocks = [f"[{_label(i)}] (from {a.rig.label}):\n{a.text}" for i, a in enumerate(answers)]
    candidates = "\n\n".join(blocks)
    return (
        "You are judging candidate answers to a task.\n\n"
        f"TASK:\n{task}\n\n"
        f"CANDIDATES:\n{candidates}\n\n"
        "Choose the single best candidate. Reply with its label on the first line "
        "as 'BEST: X', then one sentence explaining why."
    )


def _parse_choice(raw: str, count: int) -> int:
    """Extract the chosen candidate index from a judge's reply (default 0)."""
    match = re.search(r"BEST:\s*([A-Za-z])", raw)
    if not match:
        return 0
    index = ord(match.group(1).upper()) - ord("A")
    return index if 0 <= index < count else 0


def _reason(raw: str) -> str:
    """Return the judge's explanation, minus a leading 'BEST: X' line."""
    lines = raw.strip().splitlines()
    if lines and lines[0].upper().startswith("BEST:"):
        return "\n".join(lines[1:]).strip() or lines[0].strip()
    return raw.strip()


async def judge(task: str, answers: list[Answer], judge_rig: Rig, *, timeout: float = 120.0) -> Verdict:
    """Have a judge rig pick the best of several candidate answers."""
    valid = [answer for answer in answers if answer.text]
    if not valid:
        raise ValueError("No successful answers to judge.")
    raw = await complete(judge_rig, _judge_prompt(task, valid), timeout=timeout)
    index = _parse_choice(raw, len(valid))
    return Verdict(winner=valid[index], index=index, reason=_reason(raw), raw=raw)
