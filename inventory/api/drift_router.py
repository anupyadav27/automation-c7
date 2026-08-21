"""
Drift Router — drift detection and scan comparison endpoints.

Endpoints:
  GET /api/v1/inventory/drift                     — drift records (or compare two scans)
  GET /api/v1/inventory/runs/{scan_run_id}/drift  — drift for a specific scan run

Database:
  READS:  inventory_drift, inventory_findings (for two-scan comparison mode)
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List

from fastapi import APIRouter, HTTPException, Query
from providers.common.logger import LogContext, log_duration
from .router_utils import _get_loader

logger = logging.getLogger(__name__)

router = APIRouter()


def _group_drift(drift_records: List[Dict], type_key: str) -> Dict[str, List]:
    by_change_type: Dict[str, List] = {}
    for drift in drift_records:
        change = drift.get(type_key, drift.get("change_type", "unknown"))
        by_change_type.setdefault(change, []).append(drift)
    return by_change_type


@router.get("/api/v1/inventory/drift")
async def get_drift(
    tenant_id: str = Query(...),
    baseline_scan: Optional[str] = Query(None),
    compare_scan: Optional[str] = Query(None),
    scan_run_id: Optional[str] = Query(None),
    change_type: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
):
    """
    Get drift records.

    Two modes:
    - **Comparison mode**: provide both baseline_scan and compare_scan — diffs asset sets
    - **Pre-computed mode**: provide scan_run_id (or omit for latest) — reads inventory_drift table
    """
    start_time = time.time()
    with LogContext(tenant_id=tenant_id):
        try:
            loader = _get_loader()
            drift_records: List[Dict] = []
            type_key = "change_type"

            if baseline_scan and compare_scan:
                # Comparison mode — diff two asset sets
                _base_assets, _ = loader.load_assets(tenant_id=tenant_id, scan_run_id=baseline_scan, limit=50000)
                _cmp_assets, _ = loader.load_assets(tenant_id=tenant_id, scan_run_id=compare_scan, limit=50000)
                baseline_assets = {a.get("resource_uid"): a for a in _base_assets}
                compare_assets = {a.get("resource_uid"): a for a in _cmp_assets}

                now_iso = datetime.now(timezone.utc).isoformat() + "Z"

                for uid, asset in compare_assets.items():
                    if uid not in baseline_assets:
                        drift_records.append({
                            "change_type": "asset_added",
                            "resource_uid": uid,
                            "resource_type": asset.get("resource_type"),
                            "provider": asset.get("provider"),
                            "account_id": asset.get("account_id"),
                            "region": asset.get("region"),
                            "detected_at": now_iso,
                        })

                for uid, asset in baseline_assets.items():
                    if uid not in compare_assets:
                        drift_records.append({
                            "change_type": "asset_removed",
                            "resource_uid": uid,
                            "resource_type": asset.get("resource_type"),
                            "provider": asset.get("provider"),
                            "account_id": asset.get("account_id"),
                            "region": asset.get("region"),
                            "detected_at": now_iso,
                        })

                for uid in set(baseline_assets) & set(compare_assets):
                    base, cmp = baseline_assets[uid], compare_assets[uid]
                    if base.get("hash_sha256") != cmp.get("hash_sha256"):
                        diff = [
                            {"path": k, "before": base.get(k), "after": cmp.get(k)}
                            for k in ("tags", "metadata")
                            if base.get(k) != cmp.get(k)
                        ]
                        if diff:
                            drift_records.append({
                                "change_type": "asset_changed",
                                "resource_uid": uid,
                                "resource_type": cmp.get("resource_type"),
                                "provider": cmp.get("provider"),
                                "account_id": cmp.get("account_id"),
                                "region": cmp.get("region"),
                                "diff": diff,
                                "detected_at": now_iso,
                            })

                # Apply filters for comparison mode
                if provider:
                    drift_records = [d for d in drift_records if d.get("provider") == provider]
                if resource_type:
                    drift_records = [d for d in drift_records if d.get("resource_type") == resource_type]
                if account_id:
                    drift_records = [d for d in drift_records if d.get("account_id") == account_id]

            else:
                # Pre-computed mode — read inventory_drift table
                type_key = "drift_type"
                effective_scan = scan_run_id
                if not effective_scan or effective_scan == "latest":
                    effective_scan = loader.get_latest_scan_id(tenant_id)

                drift_records = loader.load_drift_records(
                    tenant_id=tenant_id,
                    scan_run_id=effective_scan,
                    provider=provider,
                    change_type=change_type,
                    limit=500,
                )

            loader.close()

            by_change_type = _group_drift(drift_records, type_key)
            by_provider: Dict[str, Dict] = {}
            for drift in drift_records:
                prov = drift.get("provider", "unknown")
                by_provider.setdefault(prov, {"added": 0, "removed": 0, "changed": 0})
                change = drift.get(type_key, drift.get("change_type", ""))
                if "added" in change:
                    by_provider[prov]["added"] += 1
                elif "removed" in change:
                    by_provider[prov]["removed"] += 1
                else:
                    by_provider[prov]["changed"] += 1

            by_severity: Dict[str, int] = {}
            for drift in drift_records:
                sev = drift.get("severity", "medium")
                by_severity[sev] = by_severity.get(sev, 0) + 1

            affected_resources = len({d.get("resource_uid") for d in drift_records if d.get("resource_uid")})

            log_duration(logger, "Drift records retrieved", (time.time() - start_time) * 1000)
            return {
                "tenant_id": tenant_id,
                "baseline_scan": baseline_scan,
                "compare_scan": compare_scan,
                "summary": {
                    "total_drift": len(drift_records),
                    "affected_resources": affected_resources,
                    "assets_added": sum(1 for d in drift_records if "added" in (d.get(type_key) or d.get("change_type") or "")),
                    "assets_removed": sum(1 for d in drift_records if "removed" in (d.get(type_key) or d.get("change_type") or "")),
                    "assets_changed": sum(1 for d in drift_records if any(
                        w in (d.get(type_key) or d.get("change_type") or "") for w in ("changed", "modified")
                    )),
                    "by_severity": by_severity,
                },
                "drift_records": drift_records,
                "total": len(drift_records),
                "by_change_type": {k: len(v) for k, v in by_change_type.items()},
                "by_provider": by_provider,
                "details": by_change_type,
            }

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load drift: {e}")


@router.get("/api/v1/inventory/runs/{scan_run_id}/drift")
async def get_scan_drift(
    scan_run_id: str,
    tenant_id: str = Query(...),
    change_type: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
):
    """Get pre-computed drift records for a specific scan run."""
    start_time = time.time()
    with LogContext(tenant_id=tenant_id, scan_run_id=scan_run_id):
        try:
            loader = _get_loader()
            effective_scan = scan_run_id if scan_run_id != "latest" else loader.get_latest_scan_id(tenant_id)

            drift_records = loader.load_drift_records(
                tenant_id=tenant_id, scan_run_id=effective_scan,
                provider=provider, change_type=change_type, limit=500,
            )
            loader.close()

            if resource_type:
                drift_records = [d for d in drift_records if d.get("resource_type") == resource_type]
            if account_id:
                drift_records = [d for d in drift_records if d.get("account_id") == account_id]

            by_change_type = _group_drift(drift_records, "change_type")
            log_duration(logger, "Scan drift retrieved", (time.time() - start_time) * 1000)

            return {
                "scan_run_id": scan_run_id,
                "tenant_id": tenant_id,
                "drift_records": drift_records,
                "total": len(drift_records),
                "by_change_type": {k: len(v) for k, v in by_change_type.items()},
                "details": by_change_type,
            }

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load scan drift: {e}")
