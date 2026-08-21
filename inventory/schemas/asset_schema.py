"""
Asset Schema (cspm_asset.v1)

Canonical asset model for multi-cloud inventory.
"""

from typing import Dict, List, Any, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class Provider(str, Enum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"
    K8S = "k8s"
    OCI = "oci"
    IBM = "ibm"
    ALICLOUD = "alicloud"
    VMWARE = "vmware"


class Scope(str, Enum):
    GLOBAL = "global"
    REGIONAL = "regional"


class Asset(BaseModel):
    """Canonical asset record"""
    schema_version: Literal["cspm_asset.v1"] = "cspm_asset.v1"
    tenant_id: str = Field(..., description="Tenant identifier")
    scan_run_id: str = Field(..., description="Scan run identifier")
    provider: Provider = Field(..., description="Cloud provider")
    account_id: str = Field(..., description="Account/subscription/project ID")
    region: str = Field(..., description="Region code")
    scope: Scope = Field(..., description="Global or regional")
    resource_type: str = Field(..., description="Normalized resource type (e.g., s3.bucket)")
    resource_id: str = Field(..., description="Resource-specific ID")
    resource_uid: str = Field(..., description="Canonical resource ARN — the single unique identifier")
    name: Optional[str] = Field(None, description="Resource name")
    tags: Dict[str, str] = Field(default_factory=dict, description="Resource tags")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    hash_sha256: str = Field(..., description="SHA256 hash for drift detection")
    
    class Config:
        json_schema_extra = {
            "example": {
                "schema_version": "cspm_asset.v1",
                "tenant_id": "tnt_123",
                "scan_run_id": "scan_01HYYY",
                "provider": "aws",
                "account_id": "588989875114",
                "region": "us-east-1",
                "scope": "regional",
                "resource_type": "s3.bucket",
                "resource_id": "my-prod-bucket",
                "resource_uid": "arn:aws:s3:::my-prod-bucket",
                "name": "my-prod-bucket",
                "tags": {"env": "prod", "owner": "payments"},
                "metadata": {
                    "created_at": "2025-10-01T10:12:00Z",
                    "labels": {},
                    "raw_refs": [
                        "s3://inventory/tnt_123/scan_01HYYY/raw/aws/588989875114/us-east-1/s3.json"
                    ]
                },
                "hash_sha256": "abc123..."
            }
        }


def compute_asset_hash(asset: Asset) -> str:
    """Compute SHA256 hash for drift detection"""
    import hashlib
    import json
    
    # Hash key fields that determine identity
    key_fields = {
        "provider": asset.provider.value,
        "account_id": asset.account_id,
        "region": asset.region,
        "resource_type": asset.resource_type,
        "resource_id": asset.resource_id,
        "resource_uid": asset.resource_uid,
        "name": asset.name or "",
        "tags": json.dumps(asset.tags, sort_keys=True)
    }
    
    key_string = json.dumps(key_fields, sort_keys=True)
    return hashlib.sha256(key_string.encode()).hexdigest()


def generate_finding_id(asset: Asset) -> str:
    """Generate deterministic finding_id as UUID for database keys"""
    import uuid

    key = f"{asset.provider.value}|{asset.account_id}|{asset.region}|{asset.resource_uid}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, key))

