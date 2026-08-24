"""Discovery via a bounded TCP sweep of nearby subnets."""

import asyncio
import ipaddress

import httpx

from ..backends import ollama, openai
from ..config import Config
from ..rig import Rig

MAX_SWEEP_HOSTS = 4096


def expand_hosts(subnets: list[str]) -> list[str]:
    """Expand CIDR subnets into a flat list of host addresses."""
    hosts: list[str] = []
    for subnet in subnets:
        network = ipaddress.ip_network(subnet, strict=False)
        hosts.extend(str(ip) for ip in network.hosts())
    return hosts


def guard_sweep_size(hosts: list[str]) -> None:
    """Refuse sweeps large enough to look hostile to network gear."""
    if len(hosts) > MAX_SWEEP_HOSTS:
        raise ValueError(
            f"Refusing to sweep {len(hosts)} hosts (limit {MAX_SWEEP_HOSTS}); narrow the subnet."
        )


async def _safe_close(writer: asyncio.StreamWriter) -> None:
    """Close a stream writer, ignoring teardown errors."""
    try:
        await writer.wait_closed()
    except OSError:
        pass


async def port_open(ip: str, port: int, timeout: float) -> bool:
    """Return True if a TCP connection to ip:port succeeds quickly."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    await _safe_close(writer)
    return True


async def identify(client: httpx.AsyncClient, ip: str, port: int, config: Config) -> list[Rig]:
    """Fingerprint an open port as Ollama or OpenAI-compatible."""
    endpoint = f"http://{ip}:{port}"
    rigs = await ollama.list_rigs(client, endpoint, "scan", config.probe_timeout)
    if rigs:
        return rigs
    return await openai.list_rigs(client, endpoint, config.router_api_key, "scan", config.probe_timeout)


async def _probe(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, ip: str, port: int, config: Config
) -> list[Rig]:
    """Check one address:port and identify any model backend there."""
    async with sem:
        if not await port_open(ip, port, config.scan_timeout):
            return []
        return await identify(client, ip, port, config)


async def discover(client: httpx.AsyncClient, config: Config) -> list[Rig]:
    """Sweep configured subnets for live model backends."""
    hosts = expand_hosts(config.scan_subnets)
    guard_sweep_size(hosts)
    sem = asyncio.Semaphore(config.scan_concurrency)
    tasks = [_probe(client, sem, ip, port, config) for ip in hosts for port in config.scan_ports]
    groups = await asyncio.gather(*tasks)
    return [rig for group in groups for rig in group]
