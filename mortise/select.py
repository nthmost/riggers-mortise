"""Ranking and lookup of rigs."""

from .rig import Rig


def rank_key(rig: Rig) -> tuple[int, float, float]:
    """Sort key: warm first, then larger, then lower latency."""
    return (0 if rig.warm else 1, -(rig.size_b or 0.0), rig.latency_ms or 1e9)


def rank(rigs: list[Rig]) -> list[Rig]:
    """Return rigs ordered best-default-first."""
    return sorted(rigs, key=rank_key)


def suggest(rigs: list[Rig]) -> Rig | None:
    """Pick the single best default rig, or None if the fleet is empty."""
    ordered = rank(rigs)
    return ordered[0] if ordered else None


def find(rigs: list[Rig], model: str) -> Rig | None:
    """Find a rig by exact model name or host/model label."""
    for rig in rigs:
        if model in (rig.model, rig.label):
            return rig
    return None
