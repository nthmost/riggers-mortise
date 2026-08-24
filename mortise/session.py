"""One-shot and interactive chat sessions."""

import httpx
from rich.console import Console
from rich.prompt import Prompt

from . import ui
from .backends import ollama, openai
from .config import Config
from .rig import Rig
from .select import find, rank

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


async def one_shot(config: Config, rig: Rig, prompt: str) -> None:
    """Send a single prompt to one rig and stream the reply."""
    ui.notice(f"[dim]→ {rig.label}[/]")
    messages = [{"role": "user", "content": prompt}]
    async with httpx.AsyncClient() as client:
        await _run_turn(client, rig, messages, config.chat_timeout)


def _read_prompt() -> str | None:
    """Read one line of user input, or None on EOF."""
    try:
        return Prompt.ask("[cyan]you[/]")
    except (EOFError, KeyboardInterrupt):
        return None


async def chat_loop(config: Config, rig: Rig) -> None:
    """Interactive REPL against one rig, keeping conversation history."""
    console.print(f"[green]jacked into[/] [bold]{rig.label}[/]  (Ctrl-D to disconnect)")
    messages: list[dict] = []
    async with httpx.AsyncClient() as client:
        while True:
            prompt = _read_prompt()
            if prompt is None:
                break
            messages.append({"role": "user", "content": prompt})
            reply = await _run_turn(client, rig, messages, config.chat_timeout)
            messages.append({"role": "assistant", "content": reply})


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


def choose_rig(rigs: list[Rig], model: str | None) -> Rig | None:
    """Resolve the rig to use: explicit model, or suggest-and-confirm."""
    if model:
        return find(rigs, model)
    return _confirm_suggested(rigs)
