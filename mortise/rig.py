"""The Rig record: one addressable model on one nearby backend."""

from dataclasses import dataclass


@dataclass
class Rig:
    """A single model reachable at one endpoint."""

    host: str
    endpoint: str
    backend: str  # "ollama" | "openai"
    model: str
    size_b: float | None = None
    size_bytes: int | None = None  # on-disk footprint, ~memory needed to load
    quant: str | None = None
    warm: bool = False
    latency_ms: float | None = None
    tok_s: float | None = None  # observed throughput on this host (from stats)
    oversized: bool = False  # model footprint clearly exceeds this host's RAM
    tools: bool = False  # model advertises tool-calling capability
    source: str = ""  # discovery mode that found it
    api_key: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        """Identity used for de-duplication across discovery modes."""
        return (self.backend, self.endpoint, self.model)

    @property
    def label(self) -> str:
        """Human-facing name, e.g. loki.local/qwen2.5-coder:14b."""
        return f"{self.host}/{self.model}"
