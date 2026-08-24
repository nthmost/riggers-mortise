"""Layered configuration: defaults < file < env < CLI flags."""

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

DEFAULT_HOSTS = [
    "http://loki.local:11434",
    "http://spartacus.local:11434",
    "http://styx.local:11434",
    "http://localhost:11434",
]
DEFAULT_ROUTERS = ["http://spartacus.local:4000"]
DEFAULT_SCAN_PORTS = [11434, 4000]


@dataclass
class Config:
    """Fully resolved runtime configuration."""

    discovery: list[str] = field(default_factory=lambda: ["known"])
    hosts: list[str] = field(default_factory=lambda: list(DEFAULT_HOSTS))
    routers: list[str] = field(default_factory=lambda: list(DEFAULT_ROUTERS))
    router_api_key: str = "dummy"
    scan_subnets: list[str] = field(default_factory=list)
    scan_ports: list[int] = field(default_factory=lambda: list(DEFAULT_SCAN_PORTS))
    scan_concurrency: int = 64
    scan_timeout: float = 0.5
    probe_timeout: float = 2.0
    chat_timeout: float = 120.0
    host_ram: dict[str, float] = field(default_factory=dict)


def config_path() -> Path:
    """Location of the TOML config file (override with $MORTISE_CONFIG)."""
    override = os.environ.get("MORTISE_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "mortise" / "config.toml"


def load_file(path: Path) -> dict:
    """Read the TOML config file, or {} if it is absent."""
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _csv(value: str) -> list[str]:
    """Split a comma-separated string into a clean list."""
    return [item.strip() for item in value.split(",") if item.strip()]


def apply_file(config: Config, data: dict) -> Config:
    """Overlay values from a parsed TOML config file."""
    known = data.get("known", {})
    routers = data.get("routers", {})
    scan = data.get("scan", {})
    return replace(
        config,
        discovery=data.get("discovery", config.discovery),
        hosts=known.get("hosts", config.hosts),
        routers=routers.get("endpoints", config.routers),
        router_api_key=routers.get("api_key", config.router_api_key),
        scan_subnets=scan.get("subnets", config.scan_subnets),
        scan_ports=scan.get("ports", config.scan_ports),
        scan_concurrency=scan.get("concurrency", config.scan_concurrency),
        scan_timeout=scan.get("timeout", config.scan_timeout),
        probe_timeout=data.get("probe_timeout", config.probe_timeout),
        chat_timeout=data.get("chat_timeout", config.chat_timeout),
        host_ram=data.get("resources", config.host_ram),
    )


def _env_list(name: str, current: list[str]) -> list[str]:
    """Return a comma-list env override, or the current value."""
    raw = os.environ.get(name)
    return _csv(raw) if raw is not None else current


def apply_env(config: Config) -> Config:
    """Overlay MORTISE_* environment variables."""
    return replace(
        config,
        discovery=_env_list("MORTISE_DISCOVERY", config.discovery),
        hosts=_env_list("MORTISE_HOSTS", config.hosts),
        routers=_env_list("MORTISE_ROUTERS", config.routers),
        scan_subnets=_env_list("MORTISE_SCAN_SUBNETS", config.scan_subnets),
    )


def apply_cli(config: Config, **overrides) -> Config:
    """Overlay non-None CLI option values (highest precedence)."""
    clean = {key: value for key, value in overrides.items() if value is not None}
    return replace(config, **clean)


def load(**cli_overrides) -> Config:
    """Resolve configuration across defaults, file, env, and CLI flags."""
    config = apply_file(Config(), load_file(config_path()))
    config = apply_env(config)
    return apply_cli(config, **cli_overrides)
