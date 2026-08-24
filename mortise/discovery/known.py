"""Discovery via an explicit list of known Ollama hosts."""

import asyncio

import httpx

from ..backends import ollama
from ..config import Config
from ..rig import Rig


async def discover(client: httpx.AsyncClient, config: Config) -> list[Rig]:
    """Probe every configured known host concurrently."""
    tasks = [ollama.list_rigs(client, host, "known", config.probe_timeout) for host in config.hosts]
    groups = await asyncio.gather(*tasks)
    return [rig for group in groups for rig in group]
