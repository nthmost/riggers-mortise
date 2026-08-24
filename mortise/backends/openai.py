"""OpenAI-compatible backend: model discovery and streaming chat."""

import json
from typing import AsyncIterator

import httpx

from ..rig import Rig
from ..util import host_of


def _auth_headers(api_key: str) -> dict[str, str]:
    """Build bearer-auth headers for an OpenAI-compatible endpoint."""
    return {"Authorization": f"Bearer {api_key}"}


async def _fetch_models(
    client: httpx.AsyncClient, endpoint: str, api_key: str, timeout: float
) -> list[dict] | None:
    """Fetch /v1/models entries, or None if unreachable."""
    url = f"{endpoint}/v1/models"
    try:
        response = await client.get(url, headers=_auth_headers(api_key), timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    return response.json().get("data", [])


def _rig_from_model(entry: dict, endpoint: str, host: str, api_key: str, source: str) -> Rig:
    """Build a Rig from one /v1/models entry."""
    return Rig(
        host=host,
        endpoint=endpoint,
        backend="openai",
        model=entry.get("id", "?"),
        source=source,
        api_key=api_key,
    )


async def list_rigs(
    client: httpx.AsyncClient, endpoint: str, api_key: str, source: str, probe_timeout: float
) -> list[Rig]:
    """Discover all models advertised by one OpenAI-compatible endpoint."""
    models = await _fetch_models(client, endpoint, api_key, probe_timeout)
    if models is None:
        return []
    host = host_of(endpoint)
    return [_rig_from_model(entry, endpoint, host, api_key, source) for entry in models]


def _delta_text(line: str) -> str:
    """Extract delta content from one SSE data line."""
    if not line.startswith("data:"):
        return ""
    body = line[len("data:"):].strip()
    if not body or body == "[DONE]":
        return ""
    return json.loads(body)["choices"][0]["delta"].get("content", "") or ""


async def chat_stream(
    client: httpx.AsyncClient, rig: Rig, messages: list[dict], timeout: float, metrics: dict | None = None
) -> AsyncIterator[str]:
    """Stream assistant text from an OpenAI-compatible chat completion.

    Accepts a metrics dict for signature parity with the Ollama backend; this
    protocol has no reliable per-request eval stats, so callers fall back to a
    client-side throughput estimate.
    """
    payload = {"model": rig.model, "messages": messages, "stream": True}
    headers = _auth_headers(rig.api_key or "dummy")
    url = f"{rig.endpoint}/v1/chat/completions"
    async with client.stream("POST", url, json=payload, headers=headers, timeout=timeout) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            chunk = _delta_text(line)
            if chunk:
                yield chunk
