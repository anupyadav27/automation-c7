"""store.pipeline — run bookkeeping: the Runs table's single source.

Postgres: pipeline_runs / pipeline_run_artifacts.
Files: the same run dicts in out/runs.json, newest first.
"""
from datetime import datetime, timezone

from . import get_backend, is_postgres


def _now():
    return datetime.now(timezone.utc)


def start_run(scan_run_id, tenant_id="local", trigger="manual",
              triggered_by=None, providers=None, accounts=None, regions=None):
    run = {
        "scan_run_id": scan_run_id,
        "tenant_id": tenant_id,
        "trigger": trigger,
        "triggered_by": triggered_by,
        "providers": providers or [],
        "accounts": accounts or [],
        "regions": regions or [],
        "stages": {},
        "totals": {},
        "status": "running",
        "started_at": _now(),
        "completed_at": None,
    }
    backend = get_backend()
    if is_postgres():
        backend.upsert("pipeline_runs", [run], ["scan_run_id"])
    else:
        runs = backend.read("runs", default=[]) or []
        runs = [r for r in runs if r.get("scan_run_id") != scan_run_id]
        runs.insert(0, run)
        backend.write("runs", runs[:200])
    return run


def record_stage(scan_run_id, stage, status, records=None, error=None,
                 duration_seconds=None):
    entry = {"status": status, "at": _now().isoformat()}
    if records is not None:
        entry["records"] = records
    if error:
        entry["error"] = str(error)[:500]
    if duration_seconds is not None:
        entry["duration_seconds"] = round(duration_seconds, 1)

    backend = get_backend()
    if is_postgres():
        backend.execute(
            """UPDATE pipeline_runs
               SET stages = stages || jsonb_build_object(%s, %s::jsonb)
               WHERE scan_run_id = %s""",
            [stage, __import__("json").dumps(entry), scan_run_id])
    else:
        runs = backend.read("runs", default=[]) or []
        for run in runs:
            if run.get("scan_run_id") == scan_run_id:
                run.setdefault("stages", {})[stage] = entry
        backend.write("runs", runs)
    return entry


def complete_run(scan_run_id, status, totals=None):
    backend = get_backend()
    if is_postgres():
        backend.execute(
            """UPDATE pipeline_runs SET status=%s, totals=%s, completed_at=%s
               WHERE scan_run_id=%s""",
            [status, __import__("psycopg2").extras.Json(totals or {}),
             _now(), scan_run_id])
    else:
        runs = backend.read("runs", default=[]) or []
        for run in runs:
            if run.get("scan_run_id") == scan_run_id:
                run["status"] = status
                run["totals"] = totals or {}
                run["completed_at"] = _now().isoformat()
        backend.write("runs", runs)


def list_runs(limit=50, offset=0, tenant_id=None):
    backend = get_backend()
    if is_postgres():
        where = "WHERE tenant_id = %s" if tenant_id else ""
        params = [tenant_id] if tenant_id else []
        total = backend.query_one(
            f"SELECT count(*) AS n FROM pipeline_runs {where}", params)["n"]
        rows = backend.query(
            f"SELECT * FROM pipeline_runs {where} ORDER BY started_at DESC "
            f"LIMIT %s OFFSET %s", params + [limit, offset])
        return rows, total
    runs = backend.read("runs", default=[]) or []
    if tenant_id:
        runs = [r for r in runs if r.get("tenant_id") == tenant_id]
    return backend.paginate(runs, limit, offset)
