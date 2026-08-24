"""Canonical backend identity, for collapsing hostname aliases."""

import socket
from functools import lru_cache

import httpx


@lru_cache(maxsize=None)
def resolve(host: str) -> str:
    """Resolve a hostname to an IP, or return it unchanged on failure."""
    try:
        return socket.gethostbyname(host)
    except OSError:
        return host


@lru_cache(maxsize=1)
def local_ips() -> frozenset[str]:
    """IP addresses that refer to the machine mortise runs on."""
    ips = {"127.0.0.1", "::1"}
    try:
        name = socket.gethostname()
        ips.add(resolve(name))
        ips.update(socket.gethostbyname_ex(name)[2])
    except OSError:
        pass
    return frozenset(ips)


def canonical_host(host: str) -> str:
    """Map a hostname to a stable identity, folding local aliases to '@local'."""
    ip = resolve(host)
    if ip.startswith("127.") or ip in local_ips():
        return "@local"
    return ip


def identity(endpoint: str) -> tuple[str, int | None]:
    """A (canonical-host, port) pair that is equal for aliased endpoints."""
    url = httpx.URL(endpoint)
    return (canonical_host(url.host), url.port)
