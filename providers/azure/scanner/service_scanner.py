"""
Azure Discovery Scanner

DB-driven multi-service discovery for Azure subscriptions.
Service enumeration is driven by rule_discoveries table — no hardcoded handlers.

Authentication: ClientSecretCredential resolved from AWS Secrets Manager
via credential_ref (e.g. 'threat-engine/azure/{subscription_id}').

Implementation stories:
  AZ-01/AZ-01b  — this skeleton
  AZ-02          — AzureClientFactory (client_factory.py)
  AZ-02b         — _call_with_timeout
  AZ-04          — scan_service, extract_resource_identifier, normalize
  AZ-17b         — _resolve_credentials (Secrets Manager → ClientSecretCredential)
"""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional

from providers.common.models.provider_interface import (
    AuthenticationError,
    DiscoveryError,
    DiscoveryScanner,
)
from providers.azure.client_factory import AzureClientFactory
from providers.azure.pagination import azure_list_all

logger = logging.getLogger(__name__)

# Per-call timeout (seconds) — matches AWS scanner OPERATION_TIMEOUT
OPERATION_TIMEOUT = 10

# Thread pool for blocking Azure SDK calls
_AZURE_EXECUTOR = ThreadPoolExecutor(max_workers=10, thread_name_prefix="azure-sdk")

# Normalize Azure resource type strings → short names for downstream engines
_RESOURCE_TYPE_MAP: Dict[str, str] = {
    "Microsoft.Compute/virtualMachines":              "VirtualMachine",
    "Microsoft.Compute/virtualMachineScaleSets":      "VMSS",
    "Microsoft.Compute/disks":                        "ManagedDisk",
    "Microsoft.Compute/snapshots":                    "Snapshot",
    "Microsoft.Network/virtualNetworks":              "VirtualNetwork",
    "Microsoft.Network/networkSecurityGroups":        "NetworkSecurityGroup",
    "Microsoft.Network/loadBalancers":                "LoadBalancer",
    "Microsoft.Network/applicationGateways":          "ApplicationGateway",
    "Microsoft.Network/subnets":                      "Subnet",
    "Microsoft.Network/publicIPAddresses":            "PublicIPAddress",
    "Microsoft.Network/networkInterfaces":            "NetworkInterface",
    "Microsoft.Network/firewallPolicies":             "FirewallPolicy",
    "Microsoft.Storage/storageAccounts":              "StorageAccount",
    "Microsoft.KeyVault/vaults":                      "KeyVault",
    "Microsoft.Sql/servers":                          "SQLServer",
    "Microsoft.Sql/servers/databases":                "SQLDatabase",
    "Microsoft.ContainerService/managedClusters":     "AKSCluster",
    "Microsoft.Web/sites":                            "AppService",
    "Microsoft.DocumentDB/databaseAccounts":          "CosmosDB",
    "Microsoft.DBforPostgreSQL/servers":              "PostgreSQLServer",
    "Microsoft.DBforMySQL/servers":                   "MySQLServer",
    "Microsoft.Authorization/roleAssignments":        "RoleAssignment",
    "Microsoft.Authorization/roleDefinitions":        "RoleDefinition",
    "Microsoft.Insights/activityLogAlerts":           "ActivityLogAlert",
    "Microsoft.Insights/diagnosticSettings":          "DiagnosticSetting",
    "Microsoft.Security/securityContacts":            "SecurityContact",
    "Microsoft.Security/pricings":                    "SecurityPricing",
}


def _call_with_timeout(future: Future, service: str, region: str) -> Optional[Any]:
    """Execute a submitted future with timeout, returning None on timeout/error.

    Prevents hung Azure API calls from blocking executor threads indefinitely.
    Every Azure SDK call submitted to _AZURE_EXECUTOR must use this wrapper.

    Args:
        future: Submitted concurrent.futures.Future
        service: Service name for logging context (e.g. 'compute')
        region: Region name for logging context (e.g. 'eastus')

    Returns:
        Future result, or None if timed out or errored
    """
    try:
        return future.result(timeout=OPERATION_TIMEOUT)
    except FuturesTimeoutError:
        logger.warning(
            "Azure API call timed out after %ds: service=%s region=%s",
            OPERATION_TIMEOUT, service, region,
        )
        return None
    except Exception as exc:
        logger.error(
            "Azure API call failed: service=%s region=%s error=%s",
            service, region, exc,
        )
        return None


def _normalize_location(location: str) -> str:
    """Normalize Azure location string for comparison.

    Azure API returns 'eastus', 'East US', 'eastus2' etc. interchangeably.
    Normalize to lowercase with spaces stripped.

    Args:
        location: Raw Azure location string

    Returns:
        Lowercase no-space location string
    """
    return location.lower().replace(" ", "")


class AzureDiscoveryScanner(DiscoveryScanner):
    """Azure cloud resource discovery scanner.

    Implements DB-driven service discovery for Azure subscriptions.
    All service enumeration is driven by rule_discoveries table, not hardcoded.

    Credential resolution: credential_ref → AWS Secrets Manager →
    ClientSecretCredential(tenant_id, client_id, client_secret).

    Usage::

        scanner = AzureDiscoveryScanner(credentials=creds, provider="azure")
        scanner.authenticate()
        resources = asyncio.run(scanner.scan_service("compute", "eastus", config))
    """

    def __init__(self, credentials: Dict[str, Any], **kwargs) -> None:
        """Initialize Azure scanner.

        Args:
            credentials: Credential dict, expected to contain either:
                - Pre-resolved keys: tenant_id, client_id, client_secret, subscription_id
                - Or: credential_ref, credential_type (resolved via _resolve_credentials)
            **kwargs: provider (str), account_id (str)
        """
        super().__init__(credentials=credentials, **kwargs)
        self.subscription_id: Optional[str] = credentials.get("subscription_id")
        self.credential_ref: Optional[str] = credentials.get("credential_ref")
        self.credential_type: Optional[str] = credentials.get("credential_type")
        self._factory: Optional[AzureClientFactory] = None  # Set by authenticate()

    # ── Authentication ──────────────────────────────────────────────────────

    def authenticate(self) -> AzureClientFactory:
        """Authenticate using Azure Service Principal (ClientSecretCredential).

        If credentials dict already contains all 4 SP keys, uses them directly.
        Otherwise calls _resolve_credentials(credential_ref) to fetch from
        AWS Secrets Manager (AZ-17b).

        Returns:
            AzureClientFactory (also stored as self._factory)

        Raises:
            AuthenticationError: If credentials are missing or auth fails.
        """
        required = {"tenant_id", "client_id", "client_secret", "subscription_id"}
        creds = self.credentials

        if not required.issubset(creds.keys()):
            if not self.credential_ref:
                raise AuthenticationError(
                    "Azure credentials missing required keys and no credential_ref provided. "
                    f"Expected: {required}"
                )
            try:
                resolved = self._resolve_credentials(self.credential_ref)
                creds = {**creds, **resolved}
            except Exception as exc:
                raise AuthenticationError(
                    f"Failed to resolve Azure credentials from {self.credential_ref!r}: {exc}"
                ) from exc

        missing = required - set(creds.keys())
        if missing:
            raise AuthenticationError(
                f"Azure credentials missing required keys after resolution: {missing}"
            )

        try:
            self._factory = AzureClientFactory(credentials=creds)
            self.subscription_id = creds["subscription_id"]
            self.session = self._factory  # base class compat
            logger.info(
                "Azure authentication successful: subscription=%s",
                self.subscription_id,
            )
            return self._factory
        except Exception as exc:
            raise AuthenticationError(f"Azure ClientSecretCredential failed: {exc}") from exc

    def _resolve_credentials(self, credential_ref: str) -> dict:
        """Resolve Azure SP credentials from AWS Secrets Manager.

        Args:
            credential_ref: e.g. 'threat-engine/azure/f6d24b5d-51ed-47b7-9f6a-0ad194156b5e'

        Returns:
            Dict with: tenant_id, client_id, client_secret, subscription_id

        Raises:
            ValueError: If secret is missing required keys.

        Full implementation: AZ-17b.
        """
        import boto3  # lazy — only needed for Azure credential resolution

        client = boto3.client("secretsmanager", region_name="ap-south-1")
        secret = client.get_secret_value(SecretId=credential_ref)
        creds = json.loads(secret["SecretString"])

        required_keys = {"tenant_id", "client_id", "client_secret", "subscription_id"}
        missing = required_keys - set(creds.keys())
        if missing:
            raise ValueError(
                f"Azure credentials at {credential_ref!r} missing keys: {missing}"
            )
        return creds

    # ── Client factory ──────────────────────────────────────────────────────

    def get_client(self, service: str, region: str) -> Any:
        """Return Azure management client for the given service.

        Args:
            service: Service name from rule_discoveries (e.g. 'compute', 'storage')
            region: Azure location — not used for client creation (Azure clients
                    are subscription-scoped, not region-scoped), kept for interface compat.

        Returns:
            Azure management client

        Raises:
            DiscoveryError: If authenticate() has not been called.
        """
        if self._factory is None:
            raise DiscoveryError("authenticate() must be called before get_client()")
        return self._factory.get_client(service)

    def get_service_client_name(self, service: str) -> str:
        """Map rule_discoveries service name to Azure SDK client class name.

        Args:
            service: Service name (e.g. 'compute', 'storage', 'keyvault')

        Returns:
            Azure SDK client class name (e.g. 'ComputeManagementClient')
        """
        if self._factory is None:
            from providers.azure.client_factory import _CLIENT_MAP
            _, class_name = _CLIENT_MAP.get(service, ("", service))
            return class_name
        return self._factory.get_client_name(service)

    # ── Discovery ───────────────────────────────────────────────────────────

    async def scan_service(
        self,
        service: str,
        region: str,
        config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Execute DB-driven discovery for one Azure service in one region.

        Processes each action in config['discovery'] array:
        1. Resolves action string to SDK method (dot-notation: 'virtual_machines.list_all')
        2. Calls azure_list_all() in thread pool (non-blocking)
        3. Filters results by region (Azure SDK returns subscription-wide for most list_all calls)
        4. Normalizes each resource to standard output dict

        Server-side vs client-side filtering note:
        - Azure compute, storage, sql: No server-side region filter on list_all().
          Must use client-side filter on item.location. Documented per-service below.
        - Azure network (list by resource group): RG pre-filtered by region where SDK supports.
        - All filtering is documented inline — no silent O(N) client-side scans.

        Args:
            service: Azure service name (e.g. 'compute', 'storage', 'keyvault')
            region: Azure location (e.g. 'eastus', 'westeurope')
            config: Discovery config from rule_discoveries.discoveries_data:
                    {"discovery": [{"action": "virtual_machines.list_all", "params": {}, ...}]}

        Returns:
            List of normalized resource dicts with standard fields.

        Raises:
            DiscoveryError: If authenticate() has not been called.
        """
        if self._factory is None:
            raise DiscoveryError("authenticate() must be called before scan_service()")

        try:
            client = self._factory.get_client(service)
        except (ValueError, ImportError) as exc:
            logger.warning(
                "No Azure client for service=%s, skipping region=%s: %s",
                service, region, exc,
            )
            return []

        loop = asyncio.get_event_loop()
        results: List[Dict[str, Any]] = []
        region_normalized = _normalize_location(region)

        discovery_actions = config.get("discovery", [])
        if not discovery_actions:
            logger.debug("No discovery actions for service=%s", service)
            return []

        for action_spec in discovery_actions:
            action = action_spec.get("action", "")
            params = action_spec.get("params") or {}
            resource_type_hint: Optional[str] = action_spec.get("resource_type")

            method = self._resolve_sdk_method(client, action)
            if method is None:
                logger.warning(
                    "Cannot resolve azure action=%r for service=%s — skipping",
                    action, service,
                )
                continue

            # Run blocking azure_list_all in thread pool (non-blocking event loop)
            try:
                items: List[Dict[str, Any]] = await loop.run_in_executor(
                    _AZURE_EXECUTOR,
                    lambda m=method, p=params: azure_list_all(m, **p),
                )
            except Exception as exc:
                logger.error(
                    "azure_list_all failed: service=%s region=%s action=%s: %s",
                    service, region, action, exc,
                )
                continue

            if not items:
                continue

            for item in items:
                # Client-side region filter (Azure list_all is subscription-wide)
                # DOCUMENTED: Azure SDK does not support server-side region filter
                # on virtual_machines.list_all(), storage_accounts.list(), etc.
                # We filter client-side on item['location'] to scope to one region.
                item_location = _normalize_location(item.get("location", ""))
                if item_location and item_location != region_normalized:
                    continue

                resource = self._normalize_resource(
                    item, service, region, resource_type_hint
                )
                if resource:
                    results.append(resource)

        logger.info(
            "Azure scan_service: service=%s region=%s found=%d",
            service, region, len(results),
        )
        return results

    def extract_resource_identifier(
        self,
        item: Dict[str, Any],
        service: str,
        region: str,
        account_id: str,
        resource_type: Optional[str] = None,
    ) -> Dict[str, str]:
        """Extract Azure resource identifiers from SDK response item.

        Azure resource_uid = full Azure Resource ID:
        /subscriptions/{sub}/resourceGroups/{rg}/providers/{type}/{name}

        Args:
            item: Azure SDK resource dict (from as_dict())
            service: Service name
            region: Azure location
            account_id: Subscription ID
            resource_type: Optional resource type override

        Returns:
            Dict with resource_uid, resource_id, resource_name
        """
        resource_uid = item.get("id", "")
        resource_name = item.get("name", "")

        # Fallback resource_uid if 'id' is absent
        if not resource_uid and resource_name and self.subscription_id:
            resource_uid = (
                f"/subscriptions/{self.subscription_id}"
                f"/providers/Microsoft.{service.capitalize()}/{resource_name}"
            )

        # Normalize resource type from the 'type' field in the response
        raw_type = item.get("type", "")
        normalized_type = _RESOURCE_TYPE_MAP.get(raw_type, raw_type or service)

        return {
            "resource_uid": resource_uid,
            "resource_id": resource_uid,  # Azure uses full Resource ID as both
            "resource_name": resource_name,
            "resource_type": normalized_type,
        }

    # ── Optional overrides ──────────────────────────────────────────────────

    async def list_available_regions(self) -> List[str]:
        """Return list of Azure locations from SubscriptionClient.

        Returns empty list on error — DiscoveryEngine uses DB-configured regions.
        """
        if self._factory is None:
            return []
        try:
            loop = asyncio.get_event_loop()
            sub_client = self._factory.get_client("resource")

            locations = await loop.run_in_executor(
                _AZURE_EXECUTOR,
                lambda: azure_list_all(
                    sub_client.subscriptions.list_locations,
                    subscription_id=self.subscription_id,
                ),
            )
            return sorted({loc.get("name", "") for loc in locations if loc.get("name")})
        except Exception as exc:
            logger.warning("Could not list Azure regions: %s — using defaults", exc)
            return []

    def get_account_id(self) -> str:
        """Return Azure subscription ID."""
        if not self.subscription_id:
            raise DiscoveryError(
                "subscription_id not set — call authenticate() first"
            )
        return self.subscription_id

    # ── Private helpers ─────────────────────────────────────────────────────

    def _resolve_sdk_method(self, client: Any, action: str) -> Optional[Any]:
        """Resolve a dot-notation action string to an SDK method on client.

        Examples:
            'virtual_machines.list_all' → client.virtual_machines.list_all
            'storage_accounts.list'     → client.storage_accounts.list
            'servers.list'              → client.servers.list

        Args:
            client: Azure management client instance
            action: Dot-notation method path (e.g. 'virtual_machines.list_all')

        Returns:
            Callable method, or None if the path cannot be resolved
        """
        parts = action.split(".")
        obj: Any = client
        for part in parts:
            obj = getattr(obj, part, None)
            if obj is None:
                logger.debug(
                    "Cannot resolve action path %r: attribute %r not found on %s",
                    action, part, type(client).__name__,
                )
                return None
        return obj if callable(obj) else None

    def _normalize_resource(
        self,
        item: Dict[str, Any],
        service: str,
        region: str,
        resource_type_hint: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Normalize an Azure SDK resource dict to the standard discovery output.

        Args:
            item: Azure SDK resource dict (from as_dict())
            service: Service name for fallback resource_type
            region: Azure location
            resource_type_hint: Optional resource type from action spec override

        Returns:
            Standard resource dict, or None if resource_uid is missing/empty
        """
        resource_uid = item.get("id", "")
        if not resource_uid:
            logger.debug(
                "Skipping Azure resource with no 'id' field: service=%s name=%s",
                service, item.get("name", "<unknown>"),
            )
            return None

        raw_type = item.get("type", "")
        resource_type = (
            resource_type_hint
            or _RESOURCE_TYPE_MAP.get(raw_type)
            or raw_type
            or service
        )

        return {
            "resource_uid":  resource_uid,
            "resource_type": resource_type,
            "resource_name": item.get("name", ""),
            "provider":      "azure",
            "region":        item.get("location", region),
            "account_id":    self.subscription_id or "",
            "raw_data":      item,
        }
