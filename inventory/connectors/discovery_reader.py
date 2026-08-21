"""
Discovery Reader

Reads discovery records from configscan-engine output format.
Discovery files are NDJSON format: {account_id}_{region}_{service}.ndjson
"""

import os
import json
from pathlib import Path
from typing import Iterator, Dict, Any, Optional, List
import glob


class DiscoveryReader:
    """Reads discovery records from configscan-engine output"""
    
    def __init__(self, discovery_base_path: Optional[str] = None):
        """
        Initialize discovery reader.
        
        Args:
            discovery_base_path: Base path to discovery files.
                               Default: engine_output/engine_configscan_aws/output/discoveries
        """
        if discovery_base_path is None:
            from providers.common.storage_paths import get_project_root
            root = get_project_root()
            self.discovery_base_path = root / "engine_output" / "engine_configscan_aws" / "output" / "discoveries"
        else:
            self.discovery_base_path = Path(discovery_base_path)
    
    def get_discovery_path(self, scan_id: str) -> Path:
        """Get path to discovery directory for a scan"""
        return self.discovery_base_path / scan_id / "discovery"
    
    def read_discovery_records(
        self,
        scan_id: str,
        account_id: Optional[str] = None,
        account_ids: Optional[list] = None,
        region: Optional[str] = None,
        service: Optional[str] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        Read discovery records from NDJSON files.
        
        Args:
            scan_id: Configscan scan ID (e.g., "discovery_20260122_080533") or "latest" for auto-detect
            account_id: Optional filter by account ID
            region: Optional filter by region (use "global" or None for global services)
            service: Optional filter by service name
        
        Yields:
            Discovery record dictionaries
        """
        # Auto-detect latest scan if "latest" is specified
        if scan_id == "latest":
            scan_id = self.get_latest_scan_id()
            if not scan_id:
                return
        
        discovery_path = self.get_discovery_path(scan_id)
        
        if not discovery_path.exists():
            return
        
        # Find matching files - pattern: {account_id}_{region}_{service}.ndjson
        pattern_parts = []
        if account_id:
            pattern_parts.append(account_id)
        else:
            pattern_parts.append("*")
        
        if region:
            pattern_parts.append(region)
        elif account_id:
            pattern_parts.append("*")  # Match any region if account specified
        
        if service:
            pattern_parts.append(service)
        else:
            pattern_parts.append("*")
        
        pattern = "_".join(pattern_parts) + ".ndjson"
        pattern = str(discovery_path / pattern)
        
        for file_path in glob.glob(pattern):
            try:
                with open(file_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                record = json.loads(line)
                                # Apply filters if specified
                                if account_id and record.get("account_id") != account_id:
                                    continue
                                if region is not None and record.get("region") != region:
                                    continue
                                if service and record.get("service") != service:
                                    continue
                                yield record
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                continue
    
    def list_discovery_files(self, scan_id: str) -> List[str]:
        """List all discovery files for a scan"""
        discovery_path = self.get_discovery_path(scan_id)
        if not discovery_path.exists():
            return []
        
        return [f.name for f in discovery_path.glob("*.ndjson")]
    
    def get_latest_scan_id(self) -> Optional[str]:
        """
        Get the latest scan ID by finding the most recently modified discovery directory.
        
        Returns:
            Latest scan ID or None if no scans found
        """
        if not self.discovery_base_path.exists():
            return None
        
        # Find all scan directories
        scan_dirs = []
        for item in self.discovery_base_path.iterdir():
            if item.is_dir() and item.name.startswith("discovery_"):
                discovery_path = item / "discovery"
                if discovery_path.exists():
                    # Get modification time of discovery directory or summary.json
                    summary_file = discovery_path / "summary.json"
                    if summary_file.exists():
                        mtime = summary_file.stat().st_mtime
                    else:
                        mtime = discovery_path.stat().st_mtime
                    scan_dirs.append((mtime, item.name))
        
        if not scan_dirs:
            return None
        
        # Sort by modification time (most recent first)
        scan_dirs.sort(reverse=True)
        return scan_dirs[0][1]
    
    def list_available_scans(self) -> List[Dict[str, Any]]:
        """
        List all available scan IDs with metadata.
        
        Returns:
            List of dicts with scan_id and metadata
        """
        if not self.discovery_base_path.exists():
            return []
        
        scans = []
        for item in self.discovery_base_path.iterdir():
            if item.is_dir() and item.name.startswith("discovery_"):
                discovery_path = item / "discovery"
                if discovery_path.exists():
                    summary_file = discovery_path / "summary.json"
                    metadata = {}
                    if summary_file.exists():
                        try:
                            with open(summary_file, 'r') as f:
                                metadata = json.load(f)
                        except Exception:
                            pass
                    
                    scans.append({
                        "scan_id": item.name,
                        "discovery_path": str(discovery_path),
                        "metadata": metadata
                    })
        
        return scans
