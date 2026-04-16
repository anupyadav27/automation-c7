"""Cloud provider abstraction layer."""

from __future__ import annotations

from typing import Any, Protocol


class CloudProvider(Protocol):
    """Interface for cloud resource providers."""

    def fetch_resources(self, region: str | None = None) -> list[dict[str, Any]]: ...


def get_provider(name: str) -> CloudProvider:
    """Get a cloud provider by name."""
    if name == "aws":
        from .aws import AWSProvider
        return AWSProvider()
    elif name == "azure":
        from .azure import AzureProvider
        return AzureProvider()
    elif name == "gcp":
        from .gcp import GCPProvider
        return GCPProvider()
    else:
        raise ValueError(f"Unknown provider: {name}")
