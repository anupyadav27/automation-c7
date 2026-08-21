"""
Data Loader Utility

Loads assets, relationships, and drift records from NDJSON files.

=== DATABASE & TABLE MAP ===
Database: None — file-based loader (legacy; see InventoryDBLoader for DB equivalent).

Reads from local filesystem:
  Path: INVENTORY_OUTPUT_DIR or engine_output/engine_inventory/output/{tenant_id}/{scan_run_id}/normalized/
  Files: assets.ndjson, relationships.ndjson, drift.ndjson, summary.json

Tables READ:  None (reads NDJSON files only)
Tables WRITTEN: None (read-only loader for API queries)
===
"""

import os
import json
from typing import List, Dict, Any, Optional, Iterator
from pathlib import Path

from ..schemas.asset_schema import Asset
from ..schemas.relationship_schema import Relationship
from ..schemas.drift_schema import DriftRecord


class DataLoader:
    """Loads inventory data from NDJSON files"""
    
    def __init__(self, output_base_path: Optional[str] = None):
        """
        Initialize data loader.
        
        Args:
            output_base_path: Base path to inventory output.
                            Default: engine_output/engine_inventory/output
        """
        if output_base_path is None:
            from providers.common.storage_paths import get_project_root
            default = str(get_project_root() / "engine_output" / "engine_inventory" / "output")
            output_base_path = os.getenv("INVENTORY_OUTPUT_DIR", default)
        self.output_base_path = Path(output_base_path)
    
    def get_scan_path(self, tenant_id: str, scan_run_id: str) -> Path:
        """Get path to scan output directory"""
        return self.output_base_path / tenant_id / scan_run_id / "normalized"
    
    def load_assets(
        self,
        tenant_id: str,
        scan_run_id: str,
        provider: Optional[str] = None,
        region: Optional[str] = None,
        resource_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Load assets from NDJSON file with optional filtering.
        
        Args:
            tenant_id: Tenant identifier
            scan_run_id: Scan run identifier
            provider: Optional filter by provider
            region: Optional filter by region
            resource_type: Optional filter by resource type
            limit: Optional limit number of results
            offset: Skip first N results
        
        Returns:
            List of asset dictionaries
        """
        scan_path = self.get_scan_path(tenant_id, scan_run_id)
        assets_file = scan_path / "assets.ndjson"
        
        if not assets_file.exists():
            return []
        
        assets = []
        skipped = 0
        
        with open(assets_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    asset = json.loads(line)
                    
                    # Apply filters
                    if provider and asset.get("provider") != provider:
                        continue
                    if region and asset.get("region") != region:
                        continue
                    if resource_type and asset.get("resource_type") != resource_type:
                        continue
                    
                    # Apply offset
                    if skipped < offset:
                        skipped += 1
                        continue
                    
                    assets.append(asset)
                    
                    # Apply limit
                    if limit and len(assets) >= limit:
                        break
                        
                except json.JSONDecodeError:
                    continue
        
        return assets
    
    def load_asset_by_uid(
        self,
        tenant_id: str,
        scan_run_id: str,
        resource_uid: str
    ) -> Optional[Dict[str, Any]]:
        """
        Load a specific asset by resource_uid.
        
        Args:
            tenant_id: Tenant identifier
            scan_run_id: Scan run identifier
            resource_uid: Resource UID to find
        
        Returns:
            Asset dictionary or None if not found
        """
        scan_path = self.get_scan_path(tenant_id, scan_run_id)
        assets_file = scan_path / "assets.ndjson"
        
        if not assets_file.exists():
            return None
        
        with open(assets_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    asset = json.loads(line)
                    if asset.get("resource_uid") == resource_uid:
                        return asset
                except json.JSONDecodeError:
                    continue
        
        return None
    
    def load_relationships(
        self,
        tenant_id: str,
        scan_run_id: str,
        resource_uid: Optional[str] = None,
        relation_type: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Load relationships from NDJSON file with optional filtering.
        
        Args:
            tenant_id: Tenant identifier
            scan_run_id: Scan run identifier
            resource_uid: Optional filter by resource_uid (from_uid or to_uid)
            relation_type: Optional filter by relation type
            limit: Optional limit number of results
        
        Returns:
            List of relationship dictionaries
        """
        scan_path = self.get_scan_path(tenant_id, scan_run_id)
        rels_file = scan_path / "relationships.ndjson"
        
        if not rels_file.exists():
            return []
        
        relationships = []
        
        with open(rels_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    rel = json.loads(line)
                    
                    # Apply filters
                    if resource_uid and (rel.get("from_uid") != resource_uid and rel.get("to_uid") != resource_uid):
                        continue
                    if relation_type and rel.get("relation_type") != relation_type:
                        continue
                    
                    relationships.append(rel)
                    
                    # Apply limit
                    if limit and len(relationships) >= limit:
                        break
                        
                except json.JSONDecodeError:
                    continue
        
        return relationships
    
    def load_drift_records(
        self,
        tenant_id: str,
        scan_run_id: str,
        change_type: Optional[str] = None,
        resource_uid: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Load drift records from NDJSON file with optional filtering.
        
        Args:
            tenant_id: Tenant identifier
            scan_run_id: Scan run identifier
            change_type: Optional filter by change type
            resource_uid: Optional filter by resource_uid
        
        Returns:
            List of drift record dictionaries
        """
        scan_path = self.get_scan_path(tenant_id, scan_run_id)
        drift_file = scan_path / "drift.ndjson"
        
        if not drift_file.exists():
            return []
        
        drift_records = []
        
        with open(drift_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    drift = json.loads(line)
                    
                    # Apply filters
                    if change_type and drift.get("change_type") != change_type:
                        continue
                    if resource_uid and drift.get("resource_uid") != resource_uid:
                        continue
                    
                    drift_records.append(drift)
                        
                except json.JSONDecodeError:
                    continue
        
        return drift_records
    
    def count_assets(
        self,
        tenant_id: str,
        scan_run_id: str,
        provider: Optional[str] = None,
        region: Optional[str] = None,
        resource_type: Optional[str] = None
    ) -> int:
        """Count total assets matching filters"""
        count = 0
        scan_path = self.get_scan_path(tenant_id, scan_run_id)
        assets_file = scan_path / "assets.ndjson"
        
        if not assets_file.exists():
            return 0
        
        with open(assets_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    asset = json.loads(line)
                    
                    # Apply filters
                    if provider and asset.get("provider") != provider:
                        continue
                    if region and asset.get("region") != region:
                        continue
                    if resource_type and asset.get("resource_type") != resource_type:
                        continue
                    
                    count += 1
                        
                except json.JSONDecodeError:
                    continue
        
        return count
