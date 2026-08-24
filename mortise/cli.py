"""Command-line interface for Rigger's Mortise."""

import asyncio
import sys
from typing import Optional

import httpx
import typer

from . import __version__, ui
from .config import Config, load
from .discovery import discover
from .rig import Rig
from .select import suggest, find
from .session import chat_loop, choose_rig, one_shot

app = typer.Typer(add_completion=False, help="Jack into whatever LLMs are alive nearby.")


def _split(value: Optional[str]) -> Optional[list[str]]:
    """Split a comma-separated CLI value, or None to leave unset."""
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve_config(discovery, hosts, routers, scan_subnets) -> Config:
    """Build a Config from CLI option strings (comma lists)."""
    return load(
        discovery=_split(discovery),
        hosts=_split(hosts),
        routers=_split(routers),
        scan_subnets=_split(scan_subnets),
    )


def _version_callback(value: bool) -> None:
    """Print the version and exit when --version is given."""
    if value:
        typer.echo(f"mortise {__version__}")
        raise typer.Exit()


def _do_scan(config: Config) -> None:
    """Discover the fleet and print it."""
    rigs = asyncio.run(discover(config))
    ui.show_fleet(rigs)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    discovery: Optional[str] = typer.Option(None, "--discovery", "-d", help="Comma list: known,routers,scan"),
    hosts: Optional[str] = typer.Option(None, "--hosts", help="Comma list of Ollama endpoints"),
    routers: Optional[str] = typer.Option(None, "--routers", help="Comma list of router endpoints"),
    scan_subnets: Optional[str] = typer.Option(None, "--scan-subnet", help="Comma list of CIDR subnets"),
    version: bool = typer.Option(False, "--version", callback=_version_callback, is_eager=True),
) -> None:
    """Resolve config from flags/env/file and default to a fleet scan."""
    ctx.obj = _resolve_config(discovery, hosts, routers, scan_subnets)
    if ctx.invoked_subcommand is None:
        _do_scan(ctx.obj)


@app.command()
def scan(ctx: typer.Context) -> None:
    """List every LLM currently alive nearby."""
    _do_scan(ctx.obj)


def _prompt_text(prompt: Optional[str]) -> str:
    """Return the prompt argument, or read it from stdin."""
    if prompt is not None:
        return prompt
    return sys.stdin.read().strip()


def _fail_no_rig(model: Optional[str]) -> None:
    """Print a helpful error and exit when no rig matches."""
    if model:
        ui.notice(f"[red]No rig matches '{model}'.[/] Run `mortise` to see the fleet.")
    else:
        ui.notice("[red]No rigs found.[/] Widen discovery, e.g. `mortise -d known,routers,scan ask ...`")
    raise typer.Exit(1)


async def _ask(config: Config, prompt: str, model: Optional[str]) -> None:
    """Discover, pick a rig non-interactively, and stream one answer."""
    rigs = await discover(config)
    rig = find(rigs, model) if model else suggest(rigs)
    if rig is None:
        _fail_no_rig(model)
    await one_shot(config, rig, prompt)


@app.command()
def ask(
    ctx: typer.Context,
    prompt: Optional[str] = typer.Argument(None, help="Prompt text; omit to read stdin"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Force a model (name or host/model)"),
) -> None:
    """Send one prompt to a nearby rig and stream the reply."""
    asyncio.run(_ask(ctx.obj, _prompt_text(prompt), model))


async def _chat(config: Config, model: Optional[str]) -> None:
    """Discover, choose a rig (suggest/confirm), and run the REPL."""
    rigs = await discover(config)
    rig = choose_rig(rigs, model)
    if rig is None:
        _fail_no_rig(model)
    await chat_loop(config, rig)


@app.command()
def chat(
    ctx: typer.Context,
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Force a model (skip the picker)"),
) -> None:
    """Open an interactive REPL against a nearby rig."""
    asyncio.run(_chat(ctx.obj, model))


def main() -> None:
    """Console-script entry point."""
    try:
        app()
    except ValueError as error:
        ui.notice(f"[red]{error}[/]")
        raise SystemExit(1)
    except httpx.HTTPError as error:
        ui.notice(f"[red]rig error:[/] {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
