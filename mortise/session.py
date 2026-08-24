"""One-shot and interactive chat sessions, with persistent history."""

import httpx
from rich.console import Console
from rich.prompt import Prompt

from . import history, ui
from .backends import ollama, openai
from .config import Config
from .history import DEFAULT_NAME, Session
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


def _reply_count(messages: list[dict]) -> int:
    """Number of assistant turns in a message list."""
    return sum(1 for message in messages if message["role"] == "assistant")


def _show_counter(messages: list[dict]) -> None:
    """Print the growing turn count and context size after a turn."""
    ui.notice(f"[dim][turn {_reply_count(messages)} · ~{_ctx_tokens(messages)} ctx tokens][/]")


def _resume_or_fail(rig: Rig, name: str) -> Session:
    """Return the latest transcript for a rig's model and name, or raise."""
    session = history.latest_session(rig.model, name)
    if session is None:
        raise ValueError(f"No prior conversation with {rig.model} to resume.")
    return session


def _oneshot_session(rig: Rig, resume: bool, name: str | None) -> Session | None:
    """Pick the session a one-shot writes to: named, resumed, or none."""
    if name:
        return history.open_named(rig, name)
    if resume:
        return _resume_or_fail(rig, DEFAULT_NAME)
    return None


def _persist(session: Session | None, prompt: str, reply: str) -> None:
    """Append an exchange to its session, if one is active."""
    if session is None:
        return
    history.append_message(session, "user", prompt)
    history.append_message(session, "assistant", reply)


def _oneshot_banner(rig: Rig, session: Session | None) -> str:
    """Describe the target rig and any resumed context for a one-shot."""
    if session is None:
        return f"[dim]→ {rig.label}[/]"
    return f"[dim]→ {rig.label} · {session.name} (resuming {session.turns} turns)[/]"


async def one_shot(config: Config, rig: Rig, prompt: str, resume: bool, name: str | None) -> None:
    """Send a single prompt to one rig and stream the reply."""
    session = _oneshot_session(rig, resume, name)
    prior = history.load_messages(session) if session else []
    messages = prior + [{"role": "user", "content": prompt}]
    ui.notice(_oneshot_banner(rig, session))
    async with httpx.AsyncClient() as client:
        reply = await _run_turn(client, rig, messages, config.chat_timeout)
    _persist(session, prompt, reply)


def _read_prompt() -> str | None:
    """Read one line of user input, or None on EOF."""
    try:
        return Prompt.ask("[cyan]you[/]")
    except (EOFError, KeyboardInterrupt):
        return None


def _chat_session(rig: Rig, resume: bool, name: str | None) -> Session:
    """Pick the session a REPL writes to: named, resumed, or fresh default."""
    if name:
        return history.open_named(rig, name)
    if resume:
        return _resume_or_fail(rig, DEFAULT_NAME)
    return history.new_session(rig, DEFAULT_NAME)


def _replay(messages: list[dict]) -> None:
    """Print a resumed conversation so its growth is visible."""
    for message in messages:
        who = "[dim]you:[/]" if message["role"] == "user" else "[dim]rig:[/]"
        console.print(f"{who} {message['content']}")


def _greet(rig: Rig, session: Session, messages: list[dict]) -> None:
    """Announce the rig, conversation name, and how much history is loaded."""
    tag = f" · {session.name}" if session.name != DEFAULT_NAME else ""
    turns = _reply_count(messages)
    resumed = f" [dim](resuming {turns} turns)[/]" if turns else ""
    console.print(f"[green]jacked into[/] [bold]{rig.label}[/]{tag}{resumed}  (Ctrl-D to disconnect)")


async def _chat_turn(client: httpx.AsyncClient, config: Config, rig: Rig, session: Session, messages: list[dict], prompt: str) -> None:
    """Run one REPL exchange: record the prompt, stream the reply, persist both."""
    messages.append({"role": "user", "content": prompt})
    history.append_message(session, "user", prompt)
    reply = await _run_turn(client, rig, messages, config.chat_timeout)
    messages.append({"role": "assistant", "content": reply})
    history.append_message(session, "assistant", reply)
    _show_counter(messages)


async def chat_loop(config: Config, rig: Rig, resume: bool, name: str | None) -> None:
    """Interactive REPL against one rig, persisting the conversation."""
    session = _chat_session(rig, resume, name)
    messages = history.load_messages(session)
    _greet(rig, session, messages)
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


def _rigs_with(rigs: list[Rig], name: str) -> list[Rig]:
    """Keep only rigs whose model has a stored conversation of this name."""
    return [rig for rig in rigs if history.latest_session(rig.model, name)]


def _newest_with(rigs: list[Rig], name: str) -> Rig | None:
    """Pick the live rig whose named conversation was touched most recently."""
    pool = _rigs_with(rigs, name)
    if not pool:
        return None
    return max(pool, key=lambda rig: history.latest_session(rig.model, name).started)


def choose_rig(rigs: list[Rig], model: str | None, resume: bool, name: str | None) -> Rig | None:
    """Resolve the rig for the REPL: explicit model, resumable, or suggested."""
    if model:
        return find(rigs, model)
    if resume and not name:
        return _confirm_suggested(_rigs_with(rigs, DEFAULT_NAME))
    return _confirm_suggested(rigs)


def pick_oneshot(rigs: list[Rig], model: str | None, resume: bool, name: str | None) -> Rig | None:
    """Resolve the rig for a one-shot: explicit model, named, resumable, or best."""
    if model:
        return find(rigs, model)
    if name:
        return _newest_with(rigs, name) or suggest(rigs)
    if resume:
        return _newest_with(rigs, DEFAULT_NAME)
    return suggest(rigs)
