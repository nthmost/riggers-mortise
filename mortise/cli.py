"""Command-line interface for Rigger's Mortise."""

import asyncio
import sys
from typing import Optional

import httpx
import typer

from . import __version__, brain, client, favorites, history, ui
from .config import Config, load
from .discovery import discover
from .select import find, rank
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
    asyncio.run(_ask(ctx.obj, _prompt_text(prompt), favorites.expand(ctx.obj, model), resume, session))


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
    asyncio.run(_chat(ctx.obj, favorites.expand(ctx.obj, model), resume, session))


async def _stoke(config: Config, spec: str, off: bool, ttl: Optional[float]) -> None:
    """Discover, pick a rig for the spec, and keep it hot (or let it go cold)."""
    rigs = await discover(config)
    rig = client.pick(rigs, spec)
    if rig is None:
        _fail_no_rig(spec, False)
    if off:
        released = await client.unstoke(rig)
        ui.notice(f"[dim]released[/] {rig.label}" if released else f"[yellow]{rig.label} has no warmth to release[/]")
        return
    ui.notice(f"[dim]stoking {rig.label}…[/]")
    dwell = "pinned" if ttl is None else f"{ttl:g}s"
    if await client.stoke(rig, ttl=ttl):
        ui.notice(f"[green]🔥 stoked[/] {rig.label} [dim]({dwell})[/]")
    else:
        ui.notice(f"[yellow]{rig.label} can't be stoked (not an Ollama rig)[/]")


@app.command()
def stoke(
    ctx: typer.Context,
    spec: str = typer.Argument("fast", help="Policy (auto/fast/capable/cheap) or exact model to keep hot"),
    off: bool = typer.Option(False, "--off", "-o", help="Let the rig go cold instead (release memory)"),
    ttl: Optional[float] = typer.Option(None, "--ttl", help="Seconds to stay hot; omit to pin indefinitely"),
) -> None:
    """Keep a rig hot in memory so it never cold-starts."""
    asyncio.run(_stoke(ctx.obj, favorites.expand(ctx.obj, spec), off, ttl))


@app.command("favorites")
def favorites_cmd(ctx: typer.Context) -> None:
    """List the @favorites defined in your config (invoke one with -m @name)."""
    ui.show_favorites(ctx.obj.favorites)


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


def _targets(rigs: list, to: Optional[list[str]], models: Optional[list[str]], count: int) -> list:
    """Resolve which rigs to fan out to: explicit models, policies, or top-N."""
    if models:
        return client.distinct([rig for rig in (find(rigs, name) for name in models) if rig])
    if to:
        return client.distinct([rig for rig in (client.pick(rigs, spec) for spec in to) if rig])
    return rank(rigs)[:count]


async def _fanout(config: Config, prompt: str, to, models, count: int) -> None:
    """Discover, choose targets, and print every rig's answer."""
    rigs = await discover(config)
    targets = _targets(rigs, to, models, count)
    if not targets:
        _fail_no_rig(None, False)
    ui.notice(f"[dim]fanning out to {len(targets)} rigs…[/]")
    answers = await client.fanout(prompt, targets, timeout=config.chat_timeout)
    ui.show_answers(answers)


@app.command()
def fanout(
    ctx: typer.Context,
    prompt: Optional[str] = typer.Argument(None, help="Prompt text; omit to read stdin"),
    to: Optional[str] = typer.Option(None, "--to", help="Comma list of policies (auto,fast,capable,cheap)"),
    models: Optional[str] = typer.Option(None, "--models", help="Comma list of exact models"),
    count: int = typer.Option(3, "-n", help="Top-N rigs when neither --to nor --models is given"),
) -> None:
    """Run one prompt across several rigs and show every answer."""
    cfg = ctx.obj
    asyncio.run(_fanout(cfg, _prompt_text(prompt),
                        favorites.expand_all(cfg, _split(to)),
                        favorites.expand_all(cfg, _split(models)), count))


async def _judge(config: Config, prompt: str, to, models, count: int, judge_spec: str) -> None:
    """Fan out, then have a judge rig pick the best answer."""
    rigs = await discover(config)
    targets = _targets(rigs, to, models, count)
    judge_rig = client.pick(rigs, judge_spec)
    if not targets or judge_rig is None:
        _fail_no_rig(None, False)
    ui.notice(f"[dim]fanning out to {len(targets)} rigs, judged by {judge_rig.label}…[/]")
    answers = await client.fanout(prompt, targets, timeout=config.chat_timeout)
    ui.show_answers(answers)
    ui.show_verdict(await client.judge(prompt, answers, judge_rig, timeout=config.chat_timeout))


@app.command()
def judge(
    ctx: typer.Context,
    prompt: Optional[str] = typer.Argument(None, help="Prompt text; omit to read stdin"),
    to: Optional[str] = typer.Option(None, "--to", help="Comma list of policies (auto,fast,capable,cheap)"),
    models: Optional[str] = typer.Option(None, "--models", help="Comma list of exact models"),
    count: int = typer.Option(3, "-n", help="Top-N rigs when neither --to nor --models is given"),
    judge_spec: str = typer.Option("capable", "--judge", help="Policy or model for the judge"),
) -> None:
    """Fan out one prompt, then let a capable rig pick the best answer."""
    cfg = ctx.obj
    asyncio.run(_judge(cfg, _prompt_text(prompt),
                       favorites.expand_all(cfg, _split(to)),
                       favorites.expand_all(cfg, _split(models)),
                       count, favorites.expand(cfg, judge_spec)))


async def _brain(config: Config, task: str, model: Optional[str], steps: int) -> None:
    """Pick a local brain and let it orchestrate the fleet to answer a task."""
    rigs = await discover(config)
    brain_rig = brain.pick_brain(rigs, model)
    if brain_rig is None:
        ui.notice("[red]No tool-capable local model to use as a brain.[/]")
        raise typer.Exit(1)
    ui.notice(f"[magenta]🧠 brain:[/] {brain_rig.label}")
    answer = await brain.run(config, rigs, brain_rig, task, max_steps=steps, trace=ui.brain_trace)
    ui.console.print(answer)


@app.command("brain")
def brain_cmd(
    ctx: typer.Context,
    task: Optional[str] = typer.Argument(None, help="The request; omit to read stdin"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Force the brain model"),
    steps: int = typer.Option(8, "--steps", help="Max orchestration steps"),
) -> None:
    """Let a local model orchestrate the fleet, delegating subtasks as needed."""
    asyncio.run(_brain(ctx.obj, _prompt_text(task), favorites.expand(ctx.obj, model), steps))


@app.command()
def serve(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host", help="Address to bind"),
    port: int = typer.Option(8080, "--port", help="Port to listen on"),
) -> None:
    """Run an OpenAI-compatible routing endpoint over the live fleet."""
    from . import serve as server
    server.run(ctx.obj, host, port)


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
