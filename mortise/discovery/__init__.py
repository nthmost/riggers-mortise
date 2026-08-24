"""Discovery orchestration across configured modes."""

import asyncio

import httpx

from ..config import Config
from ..rig import Rig
from . import known, routers, scan

MODES = {
    "known": known.discover,
    "routers": routers.discover,
    "scan": scan.discover,
}


def selected_modes(config: Config) -> list:
    """Resolve configured discovery mode names to their functions."""
    unknown = [name for name in config.discovery if name not in MODES]
    if unknown:
        raise ValueError(f"Unknown discovery mode(s): {', '.join(unknown)}")
    return [MODES[name] for name in config.discovery]


def dedupe(rigs: list[Rig]) -> list[Rig]:
    """Drop duplicate rigs found by more than one discovery mode."""
    seen: dict[tuple, Rig] = {}
    for rig in rigs:
        seen.setdefault(rig.key, rig)
    return list(seen.values())


async def discover(config: Config) -> list[Rig]:
    """Run all selected discovery modes concurrently and merge results."""
    modes = selected_modes(config)
    async with httpx.AsyncClient() as client:
        groups = await asyncio.gather(*(mode(client, config) for mode in modes))
    return dedupe([rig for group in groups for rig in group])
