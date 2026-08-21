import json
import os
from typing import List, Dict, Any, Optional

class MockInventoryDBLoader:
    """Mock DB loader that reads from a JSON file instead of PostgreSQL"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self._assets = []
        self._load_data()

    def _load_data(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as f:
                data = json.load(f)
                self._assets = data.get("assets", data) if isinstance(data, dict) else data
        else:
            print(f"Warning: Mock data file {self.file_path} not found")

    def load_assets(self, tenant_id, scan_run_id=None, provider=None, **kwargs) -> tuple[List[Dict[str, Any]], int]:
        assets = self._assets
        if provider:
            assets = [a for a in assets if a.get("provider", "").lower() == provider.lower()]
        
        # Add tenant_id if missing in mock data to satisfy API
        for a in assets:
            if "tenant_id" not in a:
                a["tenant_id"] = tenant_id
        
        limit = kwargs.get("limit", 100)
        offset = kwargs.get("offset", 0)
        return assets[offset:offset+limit], len(assets)

    def get_latest_scan_id(self, tenant_id: str) -> str:
        return "mock-scan-run-latest"

    def get_scan_summary(self, tenant_id: str, scan_run_id: str) -> Dict[str, Any]:
        return {
            "scan_run_id": scan_run_id,
            "status": "completed",
            "total_assets": len(self._assets),
            "started_at": "2026-04-20T10:00:00Z",
            "completed_at": "2026-04-20T10:05:00Z"
        }

    def close(self): pass
