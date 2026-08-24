"""Command-line interface for Rigger's Mortise."""

import asyncio
import sys
from typing import Optional

import httpx
import typer

from . import __version__, history, ui
from .config import Config, load
from .discovery import discover
from .session import chat_loop, choose_rig, one_shot, pick_oneshot

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


def _fail_no_rig(model: Optional[str], resume: bool) -> None:
    """Print a helpful error and exit when no rig matches."""
    if resume:
        ui.notice("[red]No resumable conversation among nearby rigs.[/] Start one with `mortise chat`.")
    elif model:
        ui.notice(f"[red]No rig matches '{model}'.[/] Run `mortise` to see the fleet.")
    else:
        ui.notice("[red]No rigs found.[/] Widen discovery, e.g. `mortise -d known,routers,scan ask ...`")
    raise typer.Exit(1)


async def _ask(config: Config, prompt: str, model: Optional[str], resume: bool, session: Optional[str]) -> None:
    """Discover, pick a rig non-interactively, and stream one answer."""
    rigs = await discover(config)
    rig = pick_oneshot(rigs, model, resume, session)
    if rig is None:
        _fail_no_rig(model, resume)
    await one_shot(config, rig, prompt, resume, session)


@app.command()
def ask(
    ctx: typer.Context,
    prompt: Optional[str] = typer.Argument(None, help="Prompt text; omit to read stdin"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Force a model (name or host/model)"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Continue the latest default conversation"),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Named conversation to continue/create"),
) -> None:
    """Send one prompt to a nearby rig and stream the reply."""
    asyncio.run(_ask(ctx.obj, _prompt_text(prompt), model, resume, session))


async def _chat(config: Config, model: Optional[str], resume: bool, session: Optional[str]) -> None:
    """Discover, choose a rig (suggest/confirm), and run the REPL."""
    rigs = await discover(config)
    rig = choose_rig(rigs, model, resume, session)
    if rig is None:
        _fail_no_rig(model, resume)
    await chat_loop(config, rig, resume, session)


@app.command()
def chat(
    ctx: typer.Context,
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Force a model (skip the picker)"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Continue the latest default conversation"),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Named conversation to continue/create"),
) -> None:
    """Open an interactive REPL against a nearby rig."""
    asyncio.run(_chat(ctx.obj, model, resume, session))


def _replay_session(session_id: str) -> None:
    """Print a stored conversation, or fail if the id is unknown."""
    session = history.session_by_id(session_id)
    if session is None:
        ui.notice(f"[red]No session '{session_id}'.[/] Run `mortise log` to list them.")
        raise typer.Exit(1)
    ui.show_transcript(session, history.load_messages(session))


@app.command()
def log(
    session_id: Optional[str] = typer.Argument(None, help="Session id (or 'last') to replay; omit to list all"),
) -> None:
    """List stored conversations, or replay one to watch it compound."""
    if session_id is None:
        ui.show_sessions(history.list_sessions())
        return
    _replay_session(session_id)


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
