"""Small shared helpers."""

import httpx


def host_of(endpoint: str) -> str:
    """Extract a display host from an endpoint URL."""
    return httpx.URL(endpoint).host or endpoint
