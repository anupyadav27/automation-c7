"""GCP resource provider (stub - requires google-cloud SDKs)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GCPProvider:
    """Fetch GCP resources for policy evaluation."""

    def fetch_resources(self, region: str | None = None) -> list[dict[str, Any]]:
        """Fetch resources from GCP."""
        try:
            from google.cloud import asset_v1
        except ImportError:
            logger.warning("google-cloud-asset not installed - returning empty resource list")
            return []

        try:
            import os
            project_id = os.environ.get("GCP_PROJECT_ID", "")
            if not project_id:
                logger.error("GCP_PROJECT_ID not set")
                return []

            client = asset_v1.AssetServiceClient()
            request = asset_v1.ListAssetsRequest(
                parent=f"projects/{project_id}",
                content_type=asset_v1.ContentType.RESOURCE,
            )
            resources = []
            for asset in client.list_assets(request=request):
                resources.append({
                    "resource_id": asset.name,
                    "resource_type": self._normalize_type(asset.asset_type),
                    "provider": "gcp",
                    "region": region or "global",
                    "name": asset.name.split("/")[-1],
                    "tags": {},
                })
            return resources
        except Exception as e:
            logger.error(f"Failed to fetch GCP resources: {e}")
            return []

    def _normalize_type(self, gcp_type: str) -> str:
        """Normalize GCP asset type to simple form."""
        type_map = {
            "compute.googleapis.com/Instance": "compute_instance",
            "storage.googleapis.com/Bucket": "storage_bucket",
            "sqladmin.googleapis.com/Instance": "sql_instance",
            "compute.googleapis.com/Firewall": "firewall_rule",
        }
        return type_map.get(gcp_type, gcp_type.split("/")[-1].lower())
