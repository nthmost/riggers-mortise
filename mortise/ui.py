"""Terminal rendering: the fleet table and streaming output."""

import sys

from rich.console import Console
from rich.table import Table

from .rig import Rig
from .select import rank

console = Console()
err_console = Console(stderr=True)

_COLUMNS = ("#", "MODEL", "HOST", "SIZE", "QUANT", "WARM", "LAT", "SRC", "API")


def _size_text(rig: Rig) -> str:
    """Format a rig's parameter size."""
    return f"{rig.size_b:g}B" if rig.size_b else "—"


def _warm_text(rig: Rig) -> str:
    """Format a rig's warmth as a glyph."""
    return "🔥" if rig.warm else "·"


def _latency_text(rig: Rig) -> str:
    """Format a rig's probe latency."""
    return f"{rig.latency_ms:.0f}ms" if rig.latency_ms is not None else "—"


def _row(index: int, rig: Rig) -> tuple[str, ...]:
    """Build one table row for a ranked rig."""
    return (
        str(index), rig.model, rig.host, _size_text(rig), rig.quant or "—",
        _warm_text(rig), _latency_text(rig), rig.source, rig.backend,
    )


def fleet_table(rigs: list[Rig]) -> Table:
    """Build a table of the discovered fleet, best first."""
    table = Table(title="nearby rigs", header_style="bold cyan")
    for column in _COLUMNS:
        table.add_column(column)
    for index, rig in enumerate(rank(rigs)):
        table.add_row(*_row(index, rig))
    return table


def show_fleet(rigs: list[Rig]) -> None:
    """Print the fleet table, or a friendly empty-state message."""
    if not rigs:
        console.print("[yellow]No rigs answered — nothing awake nearby, or discovery is too narrow.[/]")
        return
    console.print(fleet_table(rigs))


def notice(message: str) -> None:
    """Print an informational notice to stderr (keeps stdout clean)."""
    err_console.print(message)


def stream_out(text: str) -> None:
    """Write a streamed token chunk to stdout without buffering."""
    sys.stdout.write(text)
    sys.stdout.flush()
