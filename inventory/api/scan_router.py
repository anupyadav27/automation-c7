"""
Scan Router — inventory scan lifecycle endpoints.

Endpoints:
  POST /api/v1/scan                               — trigger K8s Job scan (pipeline mode)
  POST /api/v1/inventory/scan/discovery           — same (backward-compat alias)
  GET  /api/v1/inventory/scan/{scan_run_id}/status — poll job status
  GET  /api/v1/inventory/runs/{scan_run_id}/summary — scan summary
  GET  /api/v1/inventory/runs/latest/summary       — latest scan summary
  GET  /api/v1/inventory/scans                     — list available discovery scans

Database:
  READS:  inventory_report (status, summaries)
  WRITES: inventory_report (pre-creates 'running' row before Job starts)
"""

import os
import json
import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from providers.common.orchestration import get_orchestration_metadata
from providers.common.job_creator import create_engine_job
from ..connectors.discovery_reader_factory import get_discovery_reader
from .router_utils import _get_raw_conn, _get_loader

logger = logging.getLogger(__name__)

router = APIRouter()

# Scanner Job config (env-driven, same for both scan endpoints)
SCANNER_IMAGE = os.getenv("INVENTORY_SCANNER_IMAGE", "yadavanup84/inventory-engine:v-job")
SCANNER_CPU_REQUEST = os.getenv("SCANNER_CPU_REQUEST", "250m")
SCANNER_MEM_REQUEST = os.getenv("SCANNER_MEM_REQUEST", "1Gi")
SCANNER_CPU_LIMIT = os.getenv("SCANNER_CPU_LIMIT", "1")
SCANNER_MEM_LIMIT = os.getenv("SCANNER_MEM_LIMIT", "2Gi")


class ScanRequest(BaseModel):
    tenant_id: Optional[str] = None
    providers: List[str] = ["aws"]
    accounts: Optional[List[str]] = None
    regions: Optional[List[str]] = None
    services: Optional[str] = None
    previous_scan_id: Optional[str] = None
    discovery_scan_id: Optional[str] = Field(default="latest")
    scan_run_id: Optional[str] = Field(default=None)
    check_scan_id: Optional[str] = Field(default=None)


class DiscoveryScanRequest(BaseModel):
    tenant_id: str
    discovery_scan_id: Optional[str] = Field(default=None, alias="configscan_scan_id")
    scan_run_id: Optional[str] = Field(default=None)
    providers: Optional[List[str]] = None
    accounts: Optional[List[str]] = None
    previous_scan_id: Optional[str] = None
    check_scan_id: Optional[str] = None
    model_config = {"populate_by_name": True}


class ScanResponse(BaseModel):
    scan_run_id: str
    status: str
    message: str
    scan_run_id_ref: Optional[str] = None
    provider: Optional[str] = None


def _pre_create_report(scan_run_id: str, tenant_id: Optional[str], orch_id: str):
    """Insert a 'running' row into inventory_report so status endpoint works immediately."""
    try:
        conn = _get_raw_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO inventory_report
                   (scan_run_id, tenant_id, status, started_at, scan_metadata)
                   VALUES (%s, %s, 'running', NOW(), %s)
                   ON CONFLICT (scan_run_id) DO UPDATE SET status = 'running'""",
                (scan_run_id, tenant_id,
                 json.dumps({"scan_run_id": orch_id, "mode": "job"})),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to pre-create inventory_report: {e}")


def _create_scanner_job(scan_run_id: str) -> str:
    """Create K8s Job on spot node and return job name."""
    return create_engine_job(
        engine_name="inventory",
        scan_id=scan_run_id,
        scan_run_id=scan_run_id,
        image=SCANNER_IMAGE,
        cpu_request=SCANNER_CPU_REQUEST,
        mem_request=SCANNER_MEM_REQUEST,
        cpu_limit=SCANNER_CPU_LIMIT,
        mem_limit=SCANNER_MEM_LIMIT,
        active_deadline_seconds=3600,
    )


@router.post("/api/v1/scan", response_model=ScanResponse)
async def run_inventory_scan(request: ScanRequest):
    """Trigger inventory scan by creating a K8s Job (pipeline mode via scan_run_id)."""
    scan_run_id = request.scan_run_id
    if not scan_run_id:
        raise HTTPException(status_code=400, detail="scan_run_id is required")

    try:
        meta = get_orchestration_metadata(scan_run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not meta.get("scan_run_id"):
        raise HTTPException(
            status_code=400,
            detail=f"Discovery scan not completed yet for scan_run_id={scan_run_id}",
        )

    provider = (meta.get("provider") or meta.get("provider_type", "aws")).lower()
    tenant_id = meta.get("tenant_id") or request.tenant_id

    _pre_create_report(scan_run_id, tenant_id, scan_run_id)

    try:
        job_name = _create_scanner_job(scan_run_id)
    except Exception as e:
        logger.error(f"Failed to create inventory scanner Job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create scanner Job: {e}")

    return ScanResponse(
        scan_run_id=scan_run_id,
        status="running",
        message=f"Scanner Job '{job_name}' created on spot node (image={SCANNER_IMAGE})",
        provider=provider,
    )


@router.post("/api/v1/inventory/scan/discovery", response_model=ScanResponse)
async def run_discovery_scan(request: DiscoveryScanRequest):
    """Trigger inventory scan from discoveries (backward-compat alias for /api/v1/scan)."""
    scan_run_id = request.scan_run_id
    if not scan_run_id:
        raise HTTPException(status_code=400, detail="scan_run_id is required for Job-based execution")

    try:
        meta = get_orchestration_metadata(scan_run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not meta.get("scan_run_id"):
        raise HTTPException(
            status_code=400,
            detail=f"Discovery scan not completed yet for scan_run_id={scan_run_id}",
        )

    tenant_id = meta.get("tenant_id") or request.tenant_id
    provider = (meta.get("provider") or meta.get("provider_type", "aws")).lower()

    _pre_create_report(scan_run_id, tenant_id, scan_run_id)

    try:
        job_name = _create_scanner_job(scan_run_id)
    except Exception as e:
        logger.error(f"Failed to create inventory scanner Job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create scanner Job: {e}")

    return ScanResponse(
        scan_run_id=scan_run_id,
        status="running",
        message=f"Scanner Job '{job_name}' created on spot node (image={SCANNER_IMAGE})",
        provider=provider,
    )


@router.get("/api/v1/inventory/scan/{scan_run_id}/status")
async def get_inventory_scan_status(scan_run_id: str):
    """Poll inventory scan status from inventory_report."""
    import psycopg2.extras
    try:
        conn = _get_raw_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT scan_run_id, status, tenant_id, started_at, completed_at, scan_metadata "
                "FROM inventory_report WHERE scan_run_id = %s",
                (scan_run_id,),
            )
            row = cur.fetchone()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")

    if not row:
        raise HTTPException(status_code=404, detail=f"Scan {scan_run_id} not found")

    result = dict(row)
    for key in ("started_at", "completed_at"):
        val = result.get(key)
        if val and hasattr(val, "isoformat"):
            result[key] = val.isoformat()
    return result


@router.get("/api/v1/inventory/runs/{scan_run_id}/summary")
async def get_scan_summary(scan_run_id: str, tenant_id: str = Query(...)):
    """Get scan summary by scan_run_id (use 'latest' for the most recent completed scan)."""
    try:
        loader = _get_loader()
        if scan_run_id == "latest":
            scan_run_id = loader.get_latest_scan_id(tenant_id)
            if not scan_run_id:
                loader.close()
                raise HTTPException(status_code=404, detail=f"No completed scans for tenant: {tenant_id}")

        summary = loader.get_scan_summary(tenant_id=tenant_id, scan_run_id=scan_run_id)
        loader.close()

        if not summary:
            raise HTTPException(status_code=404, detail=f"Scan summary not found: {scan_run_id}")

        for key in ("started_at", "completed_at"):
            val = summary.get(key)
            if val and hasattr(val, "isoformat"):
                summary[key] = val.isoformat()
        return summary

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load scan summary: {e}")


@router.get("/api/v1/inventory/runs/latest/summary")
async def get_latest_scan_summary(tenant_id: str = Query(...)):
    """Get the most recent completed scan summary."""
    try:
        loader = _get_loader()
        scan_run_id = loader.get_latest_scan_id(tenant_id)
        if not scan_run_id:
            loader.close()
            raise HTTPException(status_code=404, detail=f"No completed scans for tenant: {tenant_id}")

        summary = loader.get_scan_summary(tenant_id=tenant_id, scan_run_id=scan_run_id)
        loader.close()

        if not summary:
            raise HTTPException(status_code=404, detail=f"Summary not found for scan: {scan_run_id}")

        for key in ("started_at", "completed_at"):
            val = summary.get(key)
            if val and hasattr(val, "isoformat"):
                summary[key] = val.isoformat()
        return summary

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load latest scan summary: {e}")


@router.get("/api/v1/inventory/scans")
async def list_scans(tenant_id: Optional[str] = Query(None)):
    """List available discovery scans."""
    try:
        reader = get_discovery_reader(tenant_id=tenant_id)
        scans = reader.list_available_scans()
        latest = reader.get_latest_scan_id()
        return {"scans": scans, "total": len(scans), "latest": latest}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list scans: {e}")
