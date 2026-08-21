import threading
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from api.common import ListParams, envelope
from store import pipeline as pipeline_store
from store.backends import files as files_backend

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])

_lock = threading.Lock()


class ScanRequest(BaseModel):
    policies: list[str] | None = None      # None/[] = the whole pack
    resources: list[str] | None = None     # None/[] = every matched resource
    region: str | None = None
    stages: list[str] | None = None        # default: the full pipeline
    skip_run: bool = False                 # reuse cached c7n output


def _run_scan(scan_run_id: str, req: ScanRequest):
    """Execute the requested stages, recording status as it goes."""
    # The stages this repo actually has. `compliance` and `finops` moved to the
    # threat-engine platform with their engines; this dispatched to imports that
    # no longer resolve, so every scan raised before running anything.
    from orchestration.stages import build_architecture, build_assets, discover

    stages = req.stages or ["discover", "assets", "architecture"]
    status = "success"
    totals = {}
    try:
        for stage in stages:
            try:
                if stage == "discover":
                    result = discover.run(region=req.region, scope="all")
                    totals["assets"] = result.get("assets")
                elif stage == "assets":
                    result = build_assets.run(scan_run_id=scan_run_id)
                    totals["edges"] = result.get("edges")
                elif stage == "architecture":
                    result = build_architecture.run(region=req.region)
                else:
                    continue
                pipeline_store.record_stage(
                    scan_run_id, stage, "success",
                    records=result.get("assets") or result.get("edges"))
            except Exception as exc:
                pipeline_store.record_stage(scan_run_id, stage, "failed", error=exc)
                status = "failed"
                break
    finally:
        pipeline_store.complete_run(scan_run_id, status, totals)
        _lock.release()


@router.post("/runs", status_code=202)
def start_run(req: ScanRequest, background: BackgroundTasks):
    """Launch a scan. One at a time — c7n runs are heavy."""
    if not _lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="a scan is already running")
    scan_run_id = f"scan_{uuid.uuid4().hex[:8]}"
    try:
        pipeline_store.start_run(scan_run_id, trigger="api",
                                 regions=[req.region] if req.region else [])
    except Exception:
        _lock.release()
        raise
    background.add_task(_run_scan, scan_run_id, req)
    return {"data": {"scan_run_id": scan_run_id, "status": "running",
                     "stages": req.stages or ["compliance"]}}


@router.get("/runs")
def list_runs(params: ListParams = Depends()):
    rows, total = pipeline_store.list_runs(limit=params.limit,
                                           offset=params.offset)
    return envelope(rows, total, params.limit, params.offset)


@router.get("/runs/{scan_run_id}/scene")
def run_scene(scan_run_id: str):
    # Scene is a stage-3 artifact; latest scene serves every run until
    # pipeline_run_artifacts stores per-run copies.
    scene = files_backend.read("scene")
    if scene is None:
        raise HTTPException(status_code=404,
                            detail="no scene artifact — run the architecture stage")
    return {"data": scene, "meta": {"scan_run_id": scan_run_id}}


@router.get("/runs/{scan_run_id}/resources")
def run_resources(scan_run_id: str):
    """Per-resource detail (attributes, both edge directions, raw payload).
    Split from the scene because the diagram never needs it."""
    data = files_backend.read("resources")
    if data is None:
        raise HTTPException(status_code=404,
                            detail="no resources artifact — run the architecture stage")
    return {"data": data, "meta": {"scan_run_id": scan_run_id}}


@router.get("/runs/{scan_run_id}")
def get_run(scan_run_id: str):
    rows, _ = pipeline_store.list_runs(limit=200)
    run = next((r for r in rows if r.get("scan_run_id") == scan_run_id), None)
    if run is None:
        raise HTTPException(status_code=404,
                            detail=f"unknown run: {scan_run_id}")
    return {"data": run}
