"""Discovery orchestration across configured modes."""

import asyncio

import httpx

from .. import resources, stats
from ..config import Config
from ..identity import canonical_host, identity
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


def _identity_key(rig: Rig) -> tuple:
    """De-dup key that treats hostname aliases for one daemon as equal."""
    host, port = identity(rig.endpoint)
    return (rig.backend, host, port, rig.model)


def dedupe(rigs: list[Rig]) -> list[Rig]:
    """Collapse rigs that resolve to the same backend instance."""
    seen: dict[tuple, Rig] = {}
    for rig in rigs:
        seen.setdefault(_identity_key(rig), rig)
    return list(seen.values())


def _annotate(rig: Rig, config: Config) -> Rig:
    """Attach observed throughput and fit assessment to a rig."""
    host = canonical_host(httpx.URL(rig.endpoint).host)
    rig.tok_s = stats.get(host, rig.model)
    rig.oversized = resources.oversized(rig, config)
    return rig


async def discover(config: Config) -> list[Rig]:
    """Run all selected discovery modes concurrently and merge results."""
    modes = selected_modes(config)
    async with httpx.AsyncClient() as client:
        groups = await asyncio.gather(*(mode(client, config) for mode in modes))
    rigs = dedupe([rig for group in groups for rig in group])
    return [_annotate(rig, config) for rig in rigs]
