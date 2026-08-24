"""Host resource hints and model-fit checks."""

import os

import httpx

from .config import Config
from .identity import canonical_host
from .rig import Rig

FIT_HEADROOM = 0.9  # a model may use up to this fraction of host RAM before it's "oversized"


def local_ram_gb() -> float | None:
    """Total physical RAM of the machine mortise runs on, in GB."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError):
        return None


def host_ram_gb(rig: Rig, config: Config) -> float | None:
    """Best-known RAM for a rig's host: auto-detected for local, config for remote."""
    if canonical_host(httpx.URL(rig.endpoint).host) == "@local":
        return local_ram_gb()
    return config.host_ram.get(rig.host)


def oversized(rig: Rig, config: Config) -> bool:
    """True if a model's footprint clearly exceeds its host's RAM."""
    ram = host_ram_gb(rig, config)
    if ram is None or rig.size_bytes is None:
        return False
    return rig.size_bytes / 1e9 > ram * FIT_HEADROOM
