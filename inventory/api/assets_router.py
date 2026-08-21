"""
Assets Router — asset CRUD and per-account/service summaries.

Endpoints:
  GET /api/v1/inventory/assets                       — list assets (paginated, filtered)
  GET /api/v1/inventory/assets/{resource_uid}        — asset detail + drift_info
  GET /api/v1/inventory/assets/{resource_uid}/drift  — full drift history for an asset
  GET /api/v1/inventory/accounts/{account_id}        — account summary (service/region breakdown)
  GET /api/v1/inventory/services/{service}           — service summary (account/region breakdown)

Database:
  READS:  inventory_findings, inventory_drift
"""

import logging
import time
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from providers.common.logger import LogContext, log_duration
from .router_utils import _get_loader

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/v1/inventory/assets")
async def list_assets(
    tenant_id: str = Query(...),
    scan_run_id: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    account_ids: Optional[str] = Query(None, description="Comma-separated account IDs"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List assets with filters and pagination (multi-account support)."""
    try:
        parsed_account_ids: Optional[List[str]] = (
            [a.strip() for a in account_ids.split(",") if a.strip()] if account_ids else None
        )
        loader = _get_loader()

        if not scan_run_id or scan_run_id == "latest":
            scan_run_id = loader.get_latest_scan_id(tenant_id)
            if not scan_run_id:
                loader.close()
                return {"assets": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

        assets, total = loader.load_assets(
            tenant_id=tenant_id,
            scan_run_id=scan_run_id,
            provider=provider,
            region=region,
            resource_type=resource_type,
            account_id=account_id,
            account_ids=parsed_account_ids,
            limit=limit,
            offset=offset,
        )
        loader.close()

        return {
            "assets": assets,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(assets)) < total,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load assets: {e}")


@router.get("/api/v1/inventory/assets/{resource_uid:path}/drift")
async def get_asset_drift_history(
    resource_uid: str,
    tenant_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
):
    """Get drift history for a specific asset."""
    start_time = time.time()
    with LogContext(tenant_id=tenant_id):
        try:
            loader = _get_loader()
            drift_info = loader.load_asset_drift(tenant_id, resource_uid, limit=limit)
            loader.close()
            log_duration(logger, "Asset drift history retrieved", (time.time() - start_time) * 1000)
            return {"resource_uid": resource_uid, "drift_info": drift_info, "total": drift_info.get("total", 0)}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load asset drift history: {e}")


@router.get("/api/v1/inventory/assets/{resource_uid:path}")
async def get_asset(
    resource_uid: str,
    tenant_id: str = Query(...),
    scan_run_id: Optional[str] = Query(None),
):
    """Get asset detail (inventory data + drift_info).

    Cross-engine enrichment (check, threat, compliance) is handled at the BFF layer.
    Note: sub-routes like /relationships, /drift, /blast-radius are handled by their
    own routers — FastAPI evaluates more-specific routes first.
    """
    try:
        loader = _get_loader()
        if not scan_run_id or scan_run_id == "latest":
            scan_run_id = loader.get_latest_scan_id(tenant_id)

        asset = loader.load_asset_by_uid(
            tenant_id=tenant_id, resource_uid=resource_uid, scan_run_id=scan_run_id
        )
        if not asset:
            loader.close()
            raise HTTPException(status_code=404, detail=f"Asset not found: {resource_uid}")

        try:
            asset["drift_info"] = loader.load_asset_drift(tenant_id, resource_uid)
        except Exception as e:
            logger.warning(f"Drift enrichment failed for {resource_uid}: {e}")
            asset["drift_info"] = {"last_check": None, "has_drift": False, "changes": [], "total": 0}

        loader.close()
        return asset

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load asset: {e}")


@router.get("/api/v1/inventory/accounts/{account_id}")
async def get_account_summary(
    account_id: str,
    tenant_id: str = Query(...),
    scan_run_id: Optional[str] = Query(None),
):
    """Account summary — asset count by service and region."""
    try:
        loader = _get_loader()
        if not scan_run_id or scan_run_id == "latest":
            scan_run_id = loader.get_latest_scan_id(tenant_id)
            if not scan_run_id:
                loader.close()
                return {"account_id": account_id, "total_assets": 0, "by_service": {}, "by_region": {}, "provider": "unknown"}

        account_assets, _ = loader.load_assets(
            tenant_id=tenant_id, scan_run_id=scan_run_id, account_id=account_id, limit=10000
        )
        loader.close()

        by_service: dict = {}
        by_region: dict = {}
        for asset in account_assets:
            svc = asset.get("resource_type", "unknown").split(".")[0]
            by_service[svc] = by_service.get(svc, 0) + 1
            reg = asset.get("region", "unknown")
            by_region[reg] = by_region.get(reg, 0) + 1

        return {
            "account_id": account_id,
            "total_assets": len(account_assets),
            "by_service": by_service,
            "by_region": by_region,
            "provider": account_assets[0].get("provider") if account_assets else "unknown",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load account summary: {e}")


@router.get("/api/v1/inventory/services/{service}")
async def get_service_summary(
    service: str,
    tenant_id: str = Query(...),
    scan_run_id: Optional[str] = Query(None),
):
    """Service summary — asset count by account, region, and resource type."""
    try:
        loader = _get_loader()
        if not scan_run_id or scan_run_id == "latest":
            scan_run_id = loader.get_latest_scan_id(tenant_id)
            if not scan_run_id:
                loader.close()
                return {"service": service, "total_assets": 0, "by_account": {}, "by_region": {}, "by_resource_type": {}}

        service_assets, _ = loader.load_assets(
            tenant_id=tenant_id, scan_run_id=scan_run_id, resource_type_prefix=service, limit=10000
        )
        loader.close()

        by_account: dict = {}
        by_region: dict = {}
        by_resource_type: dict = {}
        for asset in service_assets:
            acct = asset.get("account_id", "unknown")
            by_account[acct] = by_account.get(acct, 0) + 1
            reg = asset.get("region", "unknown")
            by_region[reg] = by_region.get(reg, 0) + 1
            rtype = asset.get("resource_type", "unknown")
            by_resource_type[rtype] = by_resource_type.get(rtype, 0) + 1

        return {
            "service": service,
            "total_assets": len(service_assets),
            "by_account": by_account,
            "by_region": by_region,
            "by_resource_type": by_resource_type,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load service summary: {e}")
