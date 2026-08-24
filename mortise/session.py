"""One-shot and interactive chat sessions, with persistent history."""

import httpx
from rich.console import Console
from rich.prompt import Prompt

from . import history, ui
from .backends import ollama, openai
from .config import Config
from .history import Session
from .rig import Rig
from .select import find, rank, suggest

console = Console()


def _stream_fn(rig: Rig):
    """Select the streaming function for a rig's backend."""
    return ollama.chat_stream if rig.backend == "ollama" else openai.chat_stream


async def _run_turn(client: httpx.AsyncClient, rig: Rig, messages: list[dict], timeout: float) -> str:
    """Stream one assistant turn, echoing tokens, and return the full text."""
    parts: list[str] = []
    async for chunk in _stream_fn(rig)(client, rig, messages, timeout):
        ui.stream_out(chunk)
        parts.append(chunk)
    ui.stream_out("\n")
    return "".join(parts)


def _ctx_tokens(messages: list[dict]) -> int:
    """Rough token estimate for the conversation so far (~4 chars/token)."""
    return sum(len(message["content"]) for message in messages) // 4


def _show_counter(messages: list[dict]) -> None:
    """Print the growing turn count and context size after a turn."""
    turns = sum(1 for message in messages if message["role"] == "assistant")
    ui.notice(f"[dim][turn {turns} · ~{_ctx_tokens(messages)} ctx tokens][/]")


def _resume_or_fail(rig: Rig) -> Session:
    """Return the latest transcript for a rig's model, or raise if none."""
    session = history.latest_session(rig.model)
    if session is None:
        raise ValueError(f"No prior conversation with {rig.model} to resume.")
    return session


async def one_shot(config: Config, rig: Rig, prompt: str, resume: bool) -> None:
    """Send a single prompt to one rig and stream the reply."""
    session = _resume_or_fail(rig) if resume else None
    prior = history.load_messages(session) if session else []
    messages = prior + [{"role": "user", "content": prompt}]
    ui.notice(f"[dim]→ {rig.label}[/]" + (f" [dim](resuming {session.turns} turns)[/]" if session else ""))
    async with httpx.AsyncClient() as client:
        reply = await _run_turn(client, rig, messages, config.chat_timeout)
    _persist(session, prompt, reply)


def _persist(session: Session | None, prompt: str, reply: str) -> None:
    """Append a one-shot exchange to its session, if one is active."""
    if session is None:
        return
    history.append_message(session, "user", prompt)
    history.append_message(session, "assistant", reply)


def _read_prompt() -> str | None:
    """Read one line of user input, or None on EOF."""
    try:
        return Prompt.ask("[cyan]you[/]")
    except (EOFError, KeyboardInterrupt):
        return None


def _open_session(rig: Rig, resume: bool) -> Session:
    """Resume the latest transcript for a rig, or start a new one."""
    return _resume_or_fail(rig) if resume else history.new_session(rig)


def _replay(messages: list[dict]) -> None:
    """Print a resumed conversation so its growth is visible."""
    for message in messages:
        who = "[dim]you:[/]" if message["role"] == "user" else "[dim]rig:[/]"
        console.print(f"{who} {message['content']}")


def _greet(rig: Rig, session: Session, resume: bool) -> None:
    """Announce the rig and how much history is loaded."""
    tail = f" [dim](resuming {session.turns} turns)[/]" if resume else ""
    console.print(f"[green]jacked into[/] [bold]{rig.label}[/]{tail}  (Ctrl-D to disconnect)")


async def _chat_turn(client: httpx.AsyncClient, config: Config, rig: Rig, session: Session, messages: list[dict], prompt: str) -> None:
    """Run one REPL exchange: record the prompt, stream the reply, persist both."""
    messages.append({"role": "user", "content": prompt})
    history.append_message(session, "user", prompt)
    reply = await _run_turn(client, rig, messages, config.chat_timeout)
    messages.append({"role": "assistant", "content": reply})
    history.append_message(session, "assistant", reply)
    _show_counter(messages)


async def chat_loop(config: Config, rig: Rig, resume: bool) -> None:
    """Interactive REPL against one rig, persisting the conversation."""
    session = _open_session(rig, resume)
    messages = history.load_messages(session) if resume else []
    _greet(rig, session, resume)
    _replay(messages)
    async with httpx.AsyncClient() as client:
        while True:
            prompt = _read_prompt()
            if prompt is None:
                break
            await _chat_turn(client, config, rig, session, messages, prompt)


def _rig_at(ordered: list[Rig], choice: str) -> Rig | None:
    """Return the rig at a chosen index, or None if out of range."""
    if not choice.isdigit():
        return None
    index = int(choice)
    return ordered[index] if 0 <= index < len(ordered) else None


def _confirm_suggested(rigs: list[Rig]) -> Rig | None:
    """Show ranked rigs, default to the top, let the user pick another."""
    ordered = rank(rigs)
    if not ordered:
        return None
    ui.show_fleet(rigs)
    choice = Prompt.ask("pick a rig #", default="0")
    return _rig_at(ordered, choice)


def _resumable(rigs: list[Rig]) -> list[Rig]:
    """Keep only rigs whose model has a stored conversation."""
    counts = history.counts_by_model()
    return [rig for rig in rigs if counts.get(rig.model)]


def choose_rig(rigs: list[Rig], model: str | None, resume: bool) -> Rig | None:
    """Resolve the rig for the REPL: explicit model, resumable, or suggested."""
    if model:
        return find(rigs, model)
    if resume:
        return _confirm_suggested(_resumable(rigs))
    return _confirm_suggested(rigs)


def _newest_resumable(rigs: list[Rig]) -> Rig | None:
    """Pick the live rig whose model was talked to most recently."""
    resumable = _resumable(rigs)
    if not resumable:
        return None
    return max(resumable, key=lambda rig: history.latest_session(rig.model).started)


def pick_oneshot(rigs: list[Rig], model: str | None, resume: bool) -> Rig | None:
    """Resolve the rig for a one-shot: explicit model, newest resumable, or best."""
    if model:
        return find(rigs, model)
    if resume:
        return _newest_resumable(rigs)
    return suggest(rigs)
