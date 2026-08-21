"""Azure SDK client factory for CSPM discovery.

Lazy-import factory that maps service names (from rule_discoveries.service)
to Azure management SDK clients. Only imports SDK modules that are actually
needed during a scan — avoids loading all azure-mgmt-* packages at startup.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Maps rule_discoveries.service → (sdk_module_path, class_name)
_CLIENT_MAP: Dict[str, tuple[str, str]] = {
    "compute":          ("azure.mgmt.compute",         "ComputeManagementClient"),
    "network":          ("azure.mgmt.network",          "NetworkManagementClient"),
    "storage":          ("azure.mgmt.storage",          "StorageManagementClient"),
    "keyvault":         ("azure.mgmt.keyvault",         "KeyVaultManagementClient"),
    "sql":              ("azure.mgmt.sql",               "SqlManagementClient"),
    "authorization":    ("azure.mgmt.authorization",    "AuthorizationManagementClient"),
    "containerservice": ("azure.mgmt.containerservice", "ContainerServiceClient"),
    "web":              ("azure.mgmt.web",               "WebSiteManagementClient"),
    "monitor":          ("azure.mgmt.monitor",           "MonitorManagementClient"),
    "security":         ("azure.mgmt.security",         "SecurityCenter"),
    "resource":         ("azure.mgmt.resource",         "ResourceManagementClient"),
    "cosmosdb":         ("azure.mgmt.cosmosdb",         "CosmosDBManagementClient"),
    "dns":              ("azure.mgmt.dns",               "DnsManagementClient"),
}


class AzureClientFactory:
    """Factory for Azure management SDK clients.

    Creates ClientSecretCredential once from the provided credentials dict,
    then vends management clients on demand via get_client(). Clients are
    NOT cached — each call creates a fresh instance to avoid stale sessions
    across long-running scans.

    Usage::

        factory = AzureClientFactory(credentials)
        compute_client = factory.get_client("compute")
        network_client = factory.get_client("network")
    """

    def __init__(self, credentials: Dict[str, str]) -> None:
        """Initialize factory with Azure SP credentials.

        Args:
            credentials: Dict with keys:
                - tenant_id: Entra tenant UUID
                - client_id: Service principal app UUID
                - client_secret: Service principal secret
                - subscription_id: Azure subscription UUID
        """
        from azure.identity import ClientSecretCredential  # lazy import

        self._credential = ClientSecretCredential(
            tenant_id=credentials["tenant_id"],
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
        )
        self._subscription_id = credentials["subscription_id"]
        logger.debug(
            "AzureClientFactory initialized for subscription=%s",
            self._subscription_id,
        )

    def get_client(self, service: str) -> Any:
        """Return an Azure management client for the given service name.

        Uses importlib for lazy loading — only imports the SDK module for
        services that appear in rule_discoveries for this scan.

        Args:
            service: Service name matching rule_discoveries.service column
                     (e.g. 'compute', 'storage', 'keyvault')

        Returns:
            Initialized Azure SDK management client instance

        Raises:
            ValueError: If service name is not in _CLIENT_MAP
        """
        if service not in _CLIENT_MAP:
            raise ValueError(
                f"Unknown Azure service: {service!r}. "
                f"Known services: {sorted(_CLIENT_MAP.keys())}"
            )
        module_path, class_name = _CLIENT_MAP[service]
        module = importlib.import_module(module_path)
        client_class = getattr(module, class_name)
        return client_class(self._credential, self._subscription_id)

    def get_client_name(self, service: str) -> str:
        """Return the SDK class name for a service (for logging/debugging).

        Args:
            service: Service name

        Returns:
            SDK class name, e.g. 'ComputeManagementClient'

        Raises:
            ValueError: If service not in _CLIENT_MAP
        """
        if service not in _CLIENT_MAP:
            raise ValueError(
                f"Unknown Azure service: {service!r}. "
                f"Known services: {sorted(_CLIENT_MAP.keys())}"
            )
        return _CLIENT_MAP[service][1]

    @property
    def subscription_id(self) -> str:
        """Azure subscription ID this factory was initialized for."""
        return self._subscription_id
