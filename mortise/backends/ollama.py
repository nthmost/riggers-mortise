"""Native Ollama backend: model discovery and streaming chat."""

import json
import time
from typing import AsyncIterator

import httpx

from ..rig import Rig
from ..util import host_of


def parse_size_b(param_size: str | None) -> float | None:
    """Convert an Ollama parameter_size like '8.0B' to a float count."""
    if not param_size:
        return None
    cleaned = param_size.strip().rstrip("Bb")
    try:
        return float(cleaned)
    except ValueError:
        return None


async def _fetch_tags(client: httpx.AsyncClient, endpoint: str, timeout: float) -> list[dict] | None:
    """Fetch /api/tags model entries, or None if unreachable."""
    try:
        response = await client.get(f"{endpoint}/api/tags", timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    return response.json().get("models", [])


async def loaded_models(client: httpx.AsyncClient, endpoint: str, timeout: float) -> set[str]:
    """Return the set of model names currently loaded in memory."""
    try:
        response = await client.get(f"{endpoint}/api/ps", timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError:
        return set()
    return {model["name"] for model in response.json().get("models", [])}


def _rig_from_tag(
    entry: dict, endpoint: str, host: str, warm: set[str], source: str, latency_ms: float
) -> Rig:
    """Build a Rig from one /api/tags model entry."""
    details = entry.get("details", {})
    name = entry.get("name", entry.get("model", "?"))
    return Rig(
        host=host,
        endpoint=endpoint,
        backend="ollama",
        model=name,
        size_b=parse_size_b(details.get("parameter_size")),
        size_bytes=entry.get("size"),
        quant=details.get("quantization_level"),
        warm=name in warm,
        latency_ms=latency_ms,
        source=source,
    )


async def list_rigs(
    client: httpx.AsyncClient, endpoint: str, source: str, probe_timeout: float
) -> list[Rig]:
    """Discover all models served by one Ollama endpoint."""
    start = time.perf_counter()
    tags = await _fetch_tags(client, endpoint, probe_timeout)
    if tags is None:
        return []
    latency_ms = (time.perf_counter() - start) * 1000
    warm = await loaded_models(client, endpoint, probe_timeout)
    host = host_of(endpoint)
    return [_rig_from_tag(entry, endpoint, host, warm, source, latency_ms) for entry in tags]


def _record_metrics(data: dict, metrics: dict | None) -> None:
    """Capture Ollama's eval stats from a final stream message."""
    if metrics is None or not data.get("done"):
        return
    metrics["eval_count"] = data.get("eval_count")
    metrics["eval_duration"] = data.get("eval_duration")


async def chat_stream(
    client: httpx.AsyncClient, rig: Rig, messages: list[dict], timeout: float, metrics: dict | None = None
) -> AsyncIterator[str]:
    """Stream assistant text from an Ollama /api/chat request."""
    payload = {"model": rig.model, "messages": messages, "stream": True}
    url = f"{rig.endpoint}/api/chat"
    async with client.stream("POST", url, json=payload, timeout=timeout) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            data = json.loads(line)
            content = data.get("message", {}).get("content", "")
            if content:
                yield content
            _record_metrics(data, metrics)
