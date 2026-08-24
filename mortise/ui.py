"""Terminal rendering: the fleet table and streaming output."""

import sys
import time

from rich.console import Console
from rich.table import Table

from . import history
from .history import Session
from .rig import Rig
from .select import rank

console = Console()
err_console = Console(stderr=True)

_COLUMNS = ("#", "MODEL", "HOST", "SIZE", "QUANT", "WARM", "LAT", "CONV", "SRC", "API")


def _size_text(rig: Rig) -> str:
    """Format a rig's parameter size."""
    return f"{rig.size_b:g}B" if rig.size_b else "—"


def _warm_text(rig: Rig) -> str:
    """Format a rig's warmth as a glyph."""
    return "🔥" if rig.warm else "·"


def _latency_text(rig: Rig) -> str:
    """Format a rig's probe latency."""
    return f"{rig.latency_ms:.0f}ms" if rig.latency_ms is not None else "—"


def _conv_text(rig: Rig, counts: dict[str, int]) -> str:
    """Format how many stored conversations exist for a rig's model."""
    return f"💬{counts[rig.model]}" if counts.get(rig.model) else "·"


def _row(index: int, rig: Rig, counts: dict[str, int]) -> tuple[str, ...]:
    """Build one table row for a ranked rig."""
    return (
        str(index), rig.model, rig.host, _size_text(rig), rig.quant or "—",
        _warm_text(rig), _latency_text(rig), _conv_text(rig, counts), rig.source, rig.backend,
    )


def fleet_table(rigs: list[Rig], counts: dict[str, int]) -> Table:
    """Build a table of the discovered fleet, best first."""
    table = Table(title="nearby rigs", header_style="bold cyan")
    for column in _COLUMNS:
        table.add_column(column)
    for index, rig in enumerate(rank(rigs)):
        table.add_row(*_row(index, rig, counts))
    return table


def show_fleet(rigs: list[Rig]) -> None:
    """Print the fleet table, or a friendly empty-state message."""
    if not rigs:
        console.print("[yellow]No rigs answered — nothing awake nearby, or discovery is too narrow.[/]")
        return
    console.print(fleet_table(rigs, history.counts_by_model()))


def _when(epoch: float) -> str:
    """Format an epoch timestamp as a short local date-time."""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch))


def show_sessions(sessions: list[Session]) -> None:
    """Print the list of stored conversations, newest first."""
    if not sessions:
        console.print("[yellow]No stored conversations yet. Start one with `mortise chat`.[/]")
        return
    table = Table(title="conversations", header_style="bold cyan")
    for column in ("ID", "MODEL", "HOST", "TURNS", "WHEN"):
        table.add_column(column)
    for session in sessions:
        table.add_row(session.id, session.model, session.host, str(session.turns), _when(session.started))
    console.print(table)


def show_transcript(session: Session, messages: list[dict]) -> None:
    """Print a stored conversation in full."""
    console.print(f"[bold cyan]{session.model}[/] on {session.host} — {_when(session.started)}")
    for message in messages:
        who = "[cyan]you[/]" if message["role"] == "user" else "[green]rig[/]"
        console.print(f"{who}: {message['content']}")


def notice(message: str) -> None:
    """Print an informational notice to stderr (keeps stdout clean)."""
    err_console.print(message)


def stream_out(text: str) -> None:
    """Write a streamed token chunk to stdout without buffering."""
    sys.stdout.write(text)
    sys.stdout.flush()
