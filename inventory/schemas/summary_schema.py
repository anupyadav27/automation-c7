"""
Scan Summary Schema

Summary statistics for inventory scan runs.
"""

from typing import Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime


class ScanSummary(BaseModel):
    """Inventory scan summary"""
    scan_run_id: str = Field(..., description="Scan run identifier")
    tenant_id: str = Field(..., description="Tenant identifier")
    started_at: datetime = Field(..., description="Scan start timestamp")
    completed_at: datetime = Field(..., description="Scan completion timestamp")
    status: str = Field(..., description="Scan status")
    total_assets: int = Field(..., description="Total assets discovered")
    total_relationships: int = Field(..., description="Total relationships discovered")
    assets_by_provider: Dict[str, int] = Field(default_factory=dict, description="Asset count by provider")
    assets_by_resource_type: Dict[str, int] = Field(default_factory=dict, description="Asset count by resource type")
    assets_by_region: Dict[str, int] = Field(default_factory=dict, description="Asset count by region")
    providers_scanned: List[str] = Field(default_factory=list, description="Providers scanned")
    accounts_scanned: List[str] = Field(default_factory=list, description="Accounts scanned")
    regions_scanned: List[str] = Field(default_factory=list, description="Regions scanned")
    errors_count: int = Field(default=0, description="Number of errors encountered")
    raw_refs: List[str] = Field(default_factory=list, description="Raw collector output references")

