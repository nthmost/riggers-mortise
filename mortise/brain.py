"""Local orchestrator: a tool-capable local model that delegates to the fleet."""

import json
from typing import Callable

import httpx

from . import tools
from .backends import ollama
from .config import Config
from .identity import canonical_host
from .rig import Rig
from .select import find, rank

Trace = Callable[[str, str], None]

MAX_STEPS = 8

SYSTEM = (
    "You are the orchestrator running on the user's local machine. You coordinate a "
    "fleet of nearby language models to fulfill the user's request. Use list_rigs to "
    "see what is available, delegate to route a single subtask to the right model "
    "(target is a policy: auto, fast, capable, cheap — or an exact model name), and "
    "fanout_judge for hard subtasks that benefit from several opinions. Prefer "
    "delegating substantial work rather than doing it all yourself. When you have "
    "enough to respond, give the user a clear final answer with no further tool call."
)


def _is_local(rig: Rig) -> bool:
    """Whether a rig runs on the machine mortise is running on."""
    return canonical_host(httpx.URL(rig.endpoint).host) == "@local"


def pick_brain(rigs: list[Rig], model: str | None = None) -> Rig | None:
    """Choose the brain: an explicit model, else the best local tool-capable rig."""
    if model:
        return find(rigs, model)
    local = [rig for rig in rigs if _is_local(rig) and rig.backend == "ollama"]
    capable = [rig for rig in local if rig.tools] or local
    return rank(capable)[0] if capable else None


def _args(raw) -> dict:
    """Coerce tool-call arguments (dict or JSON string) to a dict."""
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _native_calls(message: dict) -> list[tuple[str, dict]]:
    """Extract tool calls from a well-formed tool_calls field."""
    calls = message.get("tool_calls") or []
    return [(c["function"]["name"], _args(c["function"].get("arguments"))) for c in calls]


def _content_call(message: dict) -> list[tuple[str, dict]]:
    """Fallback: recover a tool call a weaker model dumped into content as JSON."""
    content = (message.get("content") or "").strip()
    if not content:
        return []
    try:
        data = json.loads(content)
    except ValueError:
        return []
    if isinstance(data, dict) and "name" in data:
        return [(data["name"], data.get("arguments") or data.get("parameters") or {})]
    return []


def _calls(message: dict) -> list[tuple[str, dict]]:
    """Tool calls in a brain message, preferring native over content-parsed."""
    return _native_calls(message) or _content_call(message)


def _assistant_turn(message: dict, calls: list[tuple[str, dict]]) -> dict:
    """Normalize the brain's message for appending back into the transcript."""
    if message.get("tool_calls"):
        return {"role": "assistant", "content": message.get("content") or "", "tool_calls": message["tool_calls"]}
    synthetic = [{"function": {"name": name, "arguments": args}} for name, args in calls]
    return {"role": "assistant", "content": "", "tool_calls": synthetic}


def _brief(args: dict) -> str:
    """Short one-line rendering of tool arguments for the trace."""
    return " ".join(f"{key}={str(value)[:60]}" for key, value in args.items())


async def _run_tool(name: str, args: dict, ctx: tools.Context, trace: Trace | None) -> str:
    """Dispatch one tool call and return its result string."""
    if trace:
        trace(name, _brief(args))
    tool = tools.by_name(name)
    if tool is None:
        return f"error: unknown tool '{name}'"
    result = await tool.handler(args, ctx)
    if trace:
        trace("↳", result[:80].replace("\n", " "))
    return result


async def _step(http: httpx.AsyncClient, rig: Rig, messages: list[dict], ctx: tools.Context, trace: Trace | None) -> str | None:
    """Run one brain turn; return the final answer, or None to keep looping."""
    message = await ollama.chat_tools(http, rig, messages, tools.schemas(), ctx.config.chat_timeout)
    calls = _calls(message)
    if not calls:
        return (message.get("content") or "").strip()
    messages.append(_assistant_turn(message, calls))
    for name, args in calls:
        result = await _run_tool(name, args, ctx, trace)
        messages.append({"role": "tool", "content": result, "tool_name": name})
    return None


async def run(config: Config, rigs: list[Rig], brain_rig: Rig, task: str, *, max_steps: int = MAX_STEPS, trace: Trace | None = None) -> str:
    """Run the orchestrator loop: reason, delegate, synthesize a final answer."""
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]
    async with httpx.AsyncClient() as http:
        ctx = tools.Context(rigs=rigs, config=config, http=http)
        for _ in range(max_steps):
            answer = await _step(http, brain_rig, messages, ctx, trace)
            if answer is not None:
                return answer
    return "(brain reached its step limit without a final answer)"
