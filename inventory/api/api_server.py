"""
Inventory Engine API Server

FastAPI application wiring — app setup, middleware, startup hooks, and router includes.

=== DATABASE & TABLE MAP ===
All database access is handled inside the individual routers.  This file
only configures the app-level plumbing (CORS, logging, telemetry, startup).

READS via routers:
  threat_engine_inventory  — inventory_report, inventory_findings, inventory_relationships,
                             inventory_drift, inventory_scan_data, architecture_resource_placement,
                             resource_inventory_identifier, resource_security_relationship_rules
  threat_engine_discoveries — discovery_report, discovery_findings (for scan listing)

WRITES via orchestrator → PostgresIndexWriter:
  threat_engine_inventory  — inventory_report, inventory_findings, inventory_relationships

=== ROUTER MAP ===
  scan_router.py          — POST /api/v1/scan, GET /api/v1/inventory/scan/*, /runs/*/summary
  assets_router.py        — GET /api/v1/inventory/assets/*, /accounts/*, /services/*
  graph_router.py         — GET /api/v1/inventory/graph, /relationships, /attack-paths, blast-radius
  drift_router.py         — GET /api/v1/inventory/drift, /runs/*/drift
  architecture_router.py  — GET /api/v1/inventory/taxonomy, /architecture
  rules_router.py         — GET/POST /api/v1/admin/rules (rule management)
  ui_data_router.py       — GET /api/v1/inventory/ui-data (BFF aggregation)
===
"""

import os
import sys
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Make the repo root importable when run as a script (uvicorn api_server:app)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from providers.common.logger import setup_logger
from providers.common.telemetry import configure_telemetry
from providers.common.middleware import RequestLoggingMiddleware, CorrelationIDMiddleware

from ..database.connection.database_config import get_database_config

# ── Routers ───────────────────────────────────────────────────────────────────
from ..api.scan_router import router as scan_router
from ..api.assets_router import router as assets_router
from ..api.graph_router import router as graph_router
from ..api.drift_router import router as drift_router
from ..api.architecture_router import router as architecture_router
from ..api.rules_router import router as rules_router

logger = setup_logger(__name__, engine_name="engine-inventory")

app = FastAPI(
    title="Inventory Engine API",
    description="Cloud Resource Inventory — Discovery, Graph, Attack Paths",
    version="2.0.0",
)
configure_telemetry("engine-inventory", app)

# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(RequestLoggingMiddleware, engine_name="engine-inventory")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def _preload_arn_patterns():
    """Warm the in-memory ARN identifier cache from resource_inventory_identifier table."""
    try:
        import psycopg2
        from providers.common.arn import preload_identifier_patterns

        db_cfg = get_database_config("inventory")
        conn = psycopg2.connect(
            host=db_cfg.host, port=db_cfg.port, dbname=db_cfg.database,
            user=db_cfg.username, password=db_cfg.password, connect_timeout=5,
        )
        try:
            total = sum(
                preload_identifier_patterns(conn, csp)
                for csp in ("aws", "azure", "gcp", "oci", "ibm", "alicloud")
            )
            logger.info("ARN identifier patterns preloaded", extra={"extra_fields": {"total_patterns": total}})
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Failed to preload ARN patterns (non-fatal)", extra={"extra_fields": {"error": str(exc)}})

# ── Include routers ───────────────────────────────────────────────────────────
app.include_router(rules_router)
app.include_router(scan_router)
# graph_router MUST come before assets_router — both use {resource_uid:path} catch-all,
# and FastAPI evaluates routes in registration order. graph_router has more-specific
# suffixes (/blast-radius, /relationships) that would be swallowed by assets_router's
# catch-all if it were registered first.
app.include_router(graph_router)
app.include_router(assets_router)
app.include_router(drift_router)
app.include_router(architecture_router)

try:
    from .ui_data_router import router as ui_data_router
    app.include_router(ui_data_router)
except ImportError as e:
    logger.warning("UI data router not available", extra={"extra_fields": {"error": str(e)}})

# ── Health endpoints ──────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"service": "engine-inventory", "version": "2.0.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/v1/health/live")
async def liveness():
    return {"status": "alive"}


@app.get("/api/v1/health/ready")
async def readiness():
    try:
        import psycopg2
        db_cfg = get_database_config("inventory")
        conn = psycopg2.connect(
            host=db_cfg.host, port=db_cfg.port, dbname=db_cfg.database,
            user=db_cfg.username, password=db_cfg.password, connect_timeout=3,
        )
        conn.close()
        return {"status": "ready"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "not ready", "error": str(e)})


@app.get("/api/v1/health")
async def api_health():
    try:
        import psycopg2
        db_cfg = get_database_config("inventory")
        conn = psycopg2.connect(
            host=db_cfg.host, port=db_cfg.port, dbname=db_cfg.database,
            user=db_cfg.username, password=db_cfg.password, connect_timeout=3,
        )
        conn.close()
        return {"status": "healthy", "database": "connected", "service": "engine-inventory", "version": "2.0.0"}
    except Exception as e:
        return {"status": "degraded", "database": "disconnected", "error": str(e), "service": "engine-inventory", "version": "2.0.0"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
