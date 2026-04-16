"""Azure resource provider (stub - requires azure-mgmt-* SDKs)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AzureProvider:
    """Fetch Azure resources for policy evaluation."""

    def fetch_resources(self, region: str | None = None) -> list[dict[str, Any]]:
        """Fetch resources from Azure."""
        try:
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.resource import ResourceManagementClient
        except ImportError:
            logger.warning("azure SDK not installed - returning empty resource list")
            return []

        try:
            credential = DefaultAzureCredential()
            # Subscription ID should come from config
            import os
            sub_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
            if not sub_id:
                logger.error("AZURE_SUBSCRIPTION_ID not set")
                return []

            client = ResourceManagementClient(credential, sub_id)
            resources = []
            for res in client.resources.list():
                resources.append({
                    "resource_id": res.id,
                    "resource_type": self._normalize_type(res.type),
                    "provider": "azure",
                    "region": res.location,
                    "name": res.name,
                    "tags": res.tags or {},
                })
            return resources
        except Exception as e:
            logger.error(f"Failed to fetch Azure resources: {e}")
            return []

    def _normalize_type(self, azure_type: str) -> str:
        """Normalize Azure resource type to simple form."""
        # e.g. Microsoft.Compute/virtualMachines -> vm_instance
        type_map = {
            "Microsoft.Compute/virtualMachines": "vm_instance",
            "Microsoft.Storage/storageAccounts": "storage_account",
            "Microsoft.Sql/servers": "sql_server",
            "Microsoft.Network/networkSecurityGroups": "network_security_group",
            "Microsoft.Network/virtualNetworks": "virtual_network",
        }
        return type_map.get(azure_type, azure_type.split("/")[-1].lower())
