"""
Common FastAPI server for Multi-CSP Discoveries Engine (Lightweight API)

This server is a thin API layer that:
1. Receives scan requests (scan_run_id)
2. Creates a K8s Job on a spot node to run the actual scan
3. Exposes scan status by reading discovery_report DB table

The heavy scan work runs in a separate K8s Job pod (run_scan.py).
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import sys
import psycopg2
import psycopg2.extras
import os
import logging

# Make the repo root importable when run as a script (uvicorn api_server:app)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from providers.common.logger import setup_logger, LogContext, log_duration
from providers.common.telemetry import configure_telemetry
from providers.common.orchestration import get_orchestration_metadata

from providers.common.database.database_manager import DatabaseManager
from providers.common.job_creator import create_engine_job

logger = setup_logger(__name__, engine_name="engine-discoveries-common")

app = FastAPI(
    title="Multi-CSP Discoveries Engine API",
    description="Lightweight API layer — scans run as on-demand K8s Jobs on spot nodes",
    version="3.0.0"
)
configure_telemetry("engine-discoveries", app)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Scanner image (same Docker image, different CMD)
SCANNER_IMAGE = os.getenv(
    "DISCOVERY_SCANNER_IMAGE",
    "yadavanup84/engine-discoveries:v-scan-upload",
)
SCANNER_NAMESPACE = os.getenv("SCANNER_NAMESPACE", "threat-engine-engines")
SCANNER_SERVICE_ACCOUNT = os.getenv("SCANNER_SERVICE_ACCOUNT", "engine-sa")
SCANNER_CPU_REQUEST = os.getenv("SCANNER_CPU_REQUEST", "2")
SCANNER_MEM_REQUEST = os.getenv("SCANNER_MEM_REQUEST", "8Gi")
SCANNER_CPU_LIMIT = os.getenv("SCANNER_CPU_LIMIT", "2")
SCANNER_MEM_LIMIT = os.getenv("SCANNER_MEM_LIMIT", "12Gi")

# Shared DatabaseManager for health checks and status queries
_db_manager = None

def _get_db_manager():
    global _db_manager
    if _db_manager is None:
        try:
            _db_manager = DatabaseManager()
        except Exception:
            pass
    return _db_manager

metrics = {
    "total_scans": 0,
    "successful_scans": 0,
    "failed_scans": 0,
}


def _coerce_list(v):
    """Accept str (comma-separated), list, or None → List[str] or None."""
    if v is None or v == "" or v == []:
        return None
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    return v


class DiscoveryRequest(BaseModel):
    """Discovery scan request model (CSP-agnostic)"""
    # Pipeline scan_run_id
    scan_run_id: Optional[str] = None

    # Legacy parameters (optional when scan_run_id is provided)
    customer_id: Optional[str] = None
    tenant_id: Optional[str] = None
    provider: str = "aws"  # aws, azure, gcp, oci, alicloud
    account_id: Optional[str] = None
    hierarchy_type: str = "account"  # account, subscription, project, tenancy
    include_services: Optional[List[str]] = None
    include_regions: Optional[List[str]] = None
    exclude_regions: Optional[List[str]] = None
    credentials: Optional[Dict[str, Any]] = None
    use_database: Optional[bool] = None  # If None, auto-detect

    from pydantic import model_validator

    @model_validator(mode="before")
    @classmethod
    def _coerce_filters(cls, values):
        for field in ("include_services", "include_regions", "exclude_regions"):
            if field in values:
                values[field] = _coerce_list(values[field])
        return values


class DiscoveryResponse(BaseModel):
    """Discovery scan response model"""
    scan_run_id: str
    status: str
    message: str
    scan_run_id_ref: Optional[str] = None
    provider: Optional[str] = None


# ── K8s Job creation ─────────────────────────────────────────────────────────

def _create_scanner_job(scan_run_id: str, scan_run_id_ref: str, provider: str) -> str:
    """Create a K8s Job to run the discovery scan on a spot node."""
    from kubernetes import client as k8s_client

    extra_env = [
        k8s_client.V1EnvVar(name="MAX_CONCURRENT_TASKS", value=os.getenv("MAX_CONCURRENT_TASKS", "1000")),
        k8s_client.V1EnvVar(name="OPERATION_TIMEOUT", value=os.getenv("OPERATION_TIMEOUT", "10")),
        k8s_client.V1EnvVar(name="SERVICE_SCAN_TIMEOUT", value=os.getenv("SERVICE_SCAN_TIMEOUT", "900")),
        k8s_client.V1EnvVar(name="DISCOVERY_MODE", value="database"),
        k8s_client.V1EnvVar(name="DISCOVERY_CONFIG_SOURCE", value="database"),
    ]
    return create_engine_job(
        engine_name="discovery",
        scan_id=scan_run_id,
        scan_run_id=scan_run_id_ref,
        image=SCANNER_IMAGE,
        cpu_request=SCANNER_CPU_REQUEST,
        mem_request=SCANNER_MEM_REQUEST,
        cpu_limit=SCANNER_CPU_LIMIT,
        mem_limit=SCANNER_MEM_LIMIT,
        active_deadline_seconds=7200,
        extra_env=extra_env,
    )


# ── Orchestration helper ─────────────────────────────────────────────────────

async def _get_scan_context_from_orchestration(scan_run_id: str) -> Dict[str, Any]:
    """Query onboarding DB for scan context using scan_run_id."""
    try:
        metadata = get_orchestration_metadata(scan_run_id)
        if not metadata:
            raise ValueError(f"No orchestration metadata for {scan_run_id}")
        return metadata
    except Exception as e:
        logger.error(f"Failed to retrieve orchestration metadata: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── POST /api/v1/discovery — create a K8s Job ───────────────────────────────

@app.post("/api/v1/discovery", response_model=DiscoveryResponse)
async def create_discovery(request: DiscoveryRequest):
    """
    Trigger a discovery scan by creating a K8s Job on a spot node.

    Flow:
    1. Resolve orchestration metadata (account, provider)
    2. Pre-create discovery_report row in DB (status=running)
    3. Create K8s Job (spot node, high CPU/RAM)
    4. Return scan_run_id immediately
    """
    scan_run_id_param = request.scan_run_id

    if not scan_run_id_param:
        raise HTTPException(status_code=400, detail="scan_run_id is required")

    scan_run_id = scan_run_id_param

    try:
        # 1. Resolve orchestration metadata
        metadata = await _get_scan_context_from_orchestration(scan_run_id)
        provider = metadata.get("provider", "aws")
        account_id = metadata.get("account_id")
        tenant_id = metadata.get("tenant_id", "default-tenant")
        customer_id = metadata.get("customer_id", "default")
        account_id = metadata.get("account_id") or account_id

        # 2. Pre-create scan record in DB so GET endpoint works immediately
        db = _get_db_manager()
        if db:
            db.create_scan(
                scan_id=scan_run_id,
                customer_id=customer_id,
                tenant_id=tenant_id,
                provider=provider,
                account_id=account_id,
                metadata={"scan_run_id": scan_run_id, "mode": "job"},
            )

        # 3. Create K8s Job on spot node
        job_name = _create_scanner_job(scan_run_id, scan_run_id, provider)

        metrics["total_scans"] += 1

        return DiscoveryResponse(
            scan_run_id=scan_run_id,
            status="running",
            message=f"Scanner Job '{job_name}' created on spot node (image={SCANNER_IMAGE})",
            scan_run_id_ref=scan_run_id,
            provider=provider,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create discovery scan: {e}", exc_info=True)
        # Mark as failed if DB row was created
        try:
            db = _get_db_manager()
            if db:
                db.update_scan_status(scan_run_id, "failed")
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /api/v1/discovery/{scan_id} — read status from DB ───────────────────

@app.get("/api/v1/discovery/{scan_id}")
async def get_scan_status(scan_id: str):
    """Get discovery scan status from discovery_report DB table."""
    db = _get_db_manager()
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    conn = db._get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT status, provider, metadata, first_seen_at "
                "FROM discovery_report WHERE scan_run_id = %s",
                (scan_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Scan not found")

            meta = row["metadata"] if isinstance(row["metadata"], dict) else {}
            return {
                "status": row["status"],
                "provider": row.get("provider"),
                "started_at": str(row.get("first_seen_at") or ""),
                "metadata": meta,
            }
    finally:
        db._return_connection(conn)


@app.get("/health")
async def health_check():
    """Health check endpoint (CSP-agnostic)"""
    db = _get_db_manager()
    if db is None:
        return {"status": "degraded", "database": "unavailable"}

    try:
        db.test_connection()
        return {"status": "healthy", "database": "connected"}
    except Exception:
        return {"status": "degraded", "database": "error"}


@app.get("/api/v1/health/live")
async def liveness_check():
    """Kubernetes liveness probe endpoint"""
    return {"status": "alive"}


@app.get("/api/v1/health/ready")
async def readiness_check():
    """Kubernetes readiness probe endpoint - lightweight check without database"""
    # For now, just return ready if the app started successfully
    # Database connection will be checked on first scan request
    return {"status": "ready", "message": "Application started successfully"}


@app.get("/metrics")
async def get_metrics():
    """Get scan metrics (CSP-agnostic)"""
    return metrics


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
