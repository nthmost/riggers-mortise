"""Discovery via configured LiteLLM / OpenAI-compatible routers."""

import asyncio

import httpx

from ..backends import openai
from ..config import Config
from ..rig import Rig


async def discover(client: httpx.AsyncClient, config: Config) -> list[Rig]:
    """Query every configured router's model list concurrently."""
    tasks = [
        openai.list_rigs(client, endpoint, config.router_api_key, "routers", config.probe_timeout)
        for endpoint in config.routers
    ]
    groups = await asyncio.gather(*tasks)
    return [rig for group in groups for rig in group]
