"""
Drift Schema (cspm_drift.v1)

Change detection schema for asset and relationship drift.
"""

from typing import Dict, Any, Literal, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class ChangeType(str, Enum):
    """Types of changes detected"""
    ASSET_ADDED = "asset_added"
    ASSET_REMOVED = "asset_removed"
    ASSET_CHANGED = "asset_changed"
    EDGE_ADDED = "edge_added"
    EDGE_REMOVED = "edge_removed"


class DriftRecord(BaseModel):
    """Drift detection record"""
    schema_version: Literal["cspm_drift.v1"] = "cspm_drift.v1"
    tenant_id: str = Field(..., description="Tenant identifier")
    scan_run_id: str = Field(..., description="Current scan run identifier")
    change_type: ChangeType = Field(..., description="Type of change")
    resource_uid: str = Field(..., description="Affected resource UID")
    resource_type: str = Field("", description="Normalised resource type (e.g. ec2.instance)")
    provider: str = Field("", description="Cloud provider (aws, azure, gcp)")
    diff: Optional[Dict[str, Any]] = Field(None, description="Change details")
    detected_at: datetime = Field(default_factory=datetime.utcnow, description="Detection timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "schema_version": "cspm_drift.v1",
                "tenant_id": "tnt_123",
                "scan_run_id": "scan_01HYYY",
                "change_type": "asset_changed",
                "resource_uid": "arn:aws:s3:::my-prod-bucket",
                "diff": {
                    "path": "tags.env",
                    "before": "dev",
                    "after": "prod"
                },
                "detected_at": "2026-01-14T10:00:00Z"
            }
        }

