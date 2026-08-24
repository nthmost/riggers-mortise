"""Ranking and lookup of rigs."""

from .rig import Rig

WARM_WEIGHT = 2.0
SPEED_WEIGHT = 1.5
CAPABILITY_WEIGHT = 1.0
OVERSIZED_PENALTY = 3.0
UNKNOWN_SPEED = 0.5  # neutral score for a rig whose throughput isn't measured yet


def _ratio(value: float | None, best: float) -> float:
    """Normalize a value against the fleet's best, guarding divide-by-zero."""
    return (value / best) if (value and best) else 0.0


def _score(rig: Rig, best_speed: float, best_size: float) -> float:
    """Balanced desirability: warmth + throughput + capability − poor fit."""
    warm = WARM_WEIGHT if rig.warm else 0.0
    speed = SPEED_WEIGHT * (_ratio(rig.tok_s, best_speed) if rig.tok_s else UNKNOWN_SPEED)
    capability = CAPABILITY_WEIGHT * _ratio(rig.size_b, best_size)
    penalty = OVERSIZED_PENALTY if rig.oversized else 0.0
    return warm + speed + capability - penalty


def rank(rigs: list[Rig]) -> list[Rig]:
    """Return rigs ordered best-default-first by a balanced score."""
    best_speed = max((rig.tok_s or 0.0 for rig in rigs), default=0.0)
    best_size = max((rig.size_b or 0.0 for rig in rigs), default=0.0)
    return sorted(rigs, key=lambda rig: _score(rig, best_speed, best_size), reverse=True)


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
