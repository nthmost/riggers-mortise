"""OpenAI-compatible HTTP gateway with live, policy-based routing."""

import json
import time
from typing import AsyncIterator

import httpx

from . import client as core
from .config import Config
from .discovery import discover
from .rig import Rig

CACHE_TTL = 30.0  # seconds a discovered fleet is reused before re-probing
_cache: dict = {"rigs": [], "at": 0.0}

MISSING_DEPS = (
    "serve needs extra deps. Install them with:\n"
    "  pipx inject riggers-mortise fastapi uvicorn\n"
    "or:  pip install 'riggers-mortise[serve]'"
)


async def _fleet(config: Config) -> list[Rig]:
    """Return the discovered fleet, re-probing only when the cache is stale."""
    now = time.time()
    if now - _cache["at"] > CACHE_TTL:
        _cache["rigs"] = await discover(config)
        _cache["at"] = now
    return _cache["rigs"]


def _sse_chunk(text: str) -> str:
    """Format one streamed token as an OpenAI SSE data line."""
    payload = {"choices": [{"index": 0, "delta": {"content": text}}]}
    return f"data: {json.dumps(payload)}\n\n"


def _completion(rig: Rig, text: str) -> dict:
    """Build a non-streaming OpenAI chat.completion response object."""
    message = {"role": "assistant", "content": text}
    return {
        "object": "chat.completion",
        "model": rig.label,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
    }


async def _stream_first(candidates: list[Rig], messages: list[dict], config: Config) -> AsyncIterator[str]:
    """Stream from the first candidate that produces output; fail over before any token."""
    for rig in candidates:
        produced = False
        try:
            async for chunk in core.stream(rig, messages, timeout=config.chat_timeout):
                produced = True
                yield chunk
            return
        except httpx.HTTPError:
            if produced:
                raise
            continue


async def _sse(candidates: list[Rig], messages: list[dict], config: Config) -> AsyncIterator[str]:
    """Full SSE body: streamed content chunks then the terminator."""
    async for chunk in _stream_first(candidates, messages, config):
        yield _sse_chunk(chunk)
    yield "data: [DONE]\n\n"


async def _first_reply(candidates: list[Rig], messages: list[dict], config: Config) -> tuple[Rig, str] | None:
    """Complete against the first reachable candidate, or None if all fail."""
    for rig in candidates:
        try:
            return rig, await core.complete(rig, messages, timeout=config.chat_timeout)
        except httpx.HTTPError:
            continue
    return None


def _models_payload(rigs: list[Rig]) -> dict:
    """List routing policies and live model names as OpenAI model objects."""
    ids = list(core.POLICIES) + [rig.model for rig in rigs]
    return {"object": "list", "data": [{"id": name, "object": "model"} for name in ids]}


def build_app(config: Config):
    """Construct the FastAPI app (imported lazily so the dep is optional)."""
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse, StreamingResponse
    except ModuleNotFoundError as error:
        raise ValueError(MISSING_DEPS) from error

    app = FastAPI(title="rigger's mortise")

    @app.get("/v1/models")
    async def models():
        return _models_payload(await _fleet(config))

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        body = await request.json()
        spec = body.get("model", "auto")
        messages = body.get("messages", [])
        candidates = core.order(await _fleet(config), spec)
        if not candidates:
            return JSONResponse({"error": f"no live rig for '{spec}'"}, status_code=404)
        if body.get("stream"):
            return StreamingResponse(_sse(candidates, messages, config), media_type="text/event-stream")
        result = await _first_reply(candidates, messages, config)
        if result is None:
            return JSONResponse({"error": "all candidate rigs failed"}, status_code=502)
        return JSONResponse(_completion(*result))

    return app


def run(config: Config, host: str, port: int) -> None:
    """Serve the routing gateway (requires the 'serve' extra)."""
    try:
        import uvicorn
    except ModuleNotFoundError as error:
        raise ValueError(MISSING_DEPS) from error
    uvicorn.run(build_app(config), host=host, port=port)
