"""Tool registry for the local orchestrator brain.

Each Tool couples a JSON-schema declaration (what the brain sees) with an async
handler (what runs when the brain calls it). New capabilities — web fetch,
shell, files — are added by appending Tool entries; nothing else changes.
"""

from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from . import client
from .config import Config
from .rig import Rig


@dataclass
class Context:
    """Shared state handlers use to reach the fleet."""

    rigs: list[Rig]
    config: Config
    http: httpx.AsyncClient


@dataclass
class Tool:
    """One capability the brain can call."""

    name: str
    description: str
    parameters: dict  # JSON schema
    handler: Callable[[dict, Context], Awaitable[str]]


def schema(tool: Tool) -> dict:
    """Render a Tool as an Ollama/OpenAI function-tool declaration."""
    function = {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
    return {"type": "function", "function": function}


def _rig_line(rig: Rig) -> str:
    """One-line description of a rig for the brain to reason over."""
    speed = f"{rig.tok_s:.0f} tok/s" if rig.tok_s else "unmeasured"
    fit = ", oversized" if rig.oversized else ""
    return f"- {rig.model} on {rig.host} ({rig.size_b or '?'}B, {speed}{fit})"


async def _list_rigs(args: dict, ctx: Context) -> str:
    """Handler: summarize the delegatable fleet."""
    lines = [_rig_line(rig) for rig in client.order(ctx.rigs, "auto")]
    return "Available rigs:\n" + "\n".join(lines)


async def _delegate(args: dict, ctx: Context) -> str:
    """Handler: route one subtask to a chosen rig."""
    target = args.get("target", "auto")
    rig = client.pick(ctx.rigs, target)
    if rig is None:
        return f"error: no rig for target '{target}'"
    try:
        return await client.complete(rig, args.get("prompt", ""), timeout=ctx.config.chat_timeout, http=ctx.http)
    except httpx.HTTPError as error:
        return f"error: {error}"


async def _fanout_judge(args: dict, ctx: Context) -> str:
    """Handler: run a subtask on several rigs and return the judged-best answer."""
    prompt = args.get("prompt", "")
    count = int(args.get("n") or 3)
    targets = client.order(ctx.rigs, "auto")[:count]
    answers = await client.fanout(prompt, targets, timeout=ctx.config.chat_timeout)
    judge_rig = client.pick(ctx.rigs, "capable")
    verdict = await client.judge(prompt, answers, judge_rig, timeout=ctx.config.chat_timeout)
    return verdict.winner.text or "error: no answer produced"


REGISTRY: list[Tool] = [
    Tool(
        "list_rigs",
        "List the models available to delegate to, with host, size, speed, and fit.",
        {"type": "object", "properties": {}},
        _list_rigs,
    ),
    Tool(
        "delegate",
        "Send one subtask to another model. 'target' is a policy (auto, fast, capable, cheap) or an exact model name.",
        {
            "type": "object",
            "properties": {"target": {"type": "string"}, "prompt": {"type": "string"}},
            "required": ["target", "prompt"],
        },
        _delegate,
    ),
    Tool(
        "fanout_judge",
        "For a hard subtask: run it on several models and return the best answer.",
        {
            "type": "object",
            "properties": {"prompt": {"type": "string"}, "n": {"type": "integer"}},
            "required": ["prompt"],
        },
        _fanout_judge,
    ),
]


def schemas() -> list[dict]:
    """Tool declarations to pass to the brain."""
    return [schema(tool) for tool in REGISTRY]


def by_name(name: str) -> Tool | None:
    """Look up a registered tool by name."""
    return next((tool for tool in REGISTRY if tool.name == name), None)
