"""Named favorites — short ``@aliases`` for model specs.

A favorite is an opt-in pointer, never a default: you invoke it explicitly as
``@name`` wherever a model or spec is accepted (``mortise ask -m @b70``). Its
value is an ordinary spec — a model name, a ``host/model`` label, or a policy —
so a favorite only ever saves you typing the long thing. The ``@`` sigil keeps
a favorite from ever silently shadowing a real model or policy of the same name.
"""

from .config import Config

SIGIL = "@"


def expand(config: Config, spec: str | None) -> str | None:
    """Resolve a ``@favorite`` to its target spec; pass anything else through."""
    if not spec or not spec.startswith(SIGIL):
        return spec
    name = spec[len(SIGIL):]
    if name not in config.favorites:
        known = ", ".join(SIGIL + key for key in sorted(config.favorites)) or "none defined"
        raise ValueError(f"unknown favorite '{spec}' (have: {known})")
    return config.favorites[name]


def expand_all(config: Config, specs: list[str] | None) -> list[str] | None:
    """Expand every ``@favorite`` in a list of specs (or None if unset)."""
    if specs is None:
        return None
    return [expand(config, spec) for spec in specs]
