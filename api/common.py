"""Shared API plumbing — one envelope, one query grammar, one error shape."""
import json
from datetime import datetime, timezone

from fastapi import Query
from fastapi.responses import JSONResponse


def envelope(rows, total, limit, offset, fmt=None, **meta):
    if fmt == "csv":
        return csv_response(rows)
    return {
        "data": rows,
        "pagination": {"total": total, "limit": limit, "offset": offset},
        "meta": {"generated_at": datetime.now(timezone.utc).isoformat(), **meta},
    }


def csv_response(rows):
    """`format=csv` on any list endpoint — what the table export button calls."""
    import csv as csv_module
    import io

    from fastapi.responses import StreamingResponse

    buffer = io.StringIO()
    if rows:
        columns = list(rows[0].keys())
        writer = csv_module.DictWriter(buffer, fieldnames=columns,
                                       extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                k: (json.dumps(v, default=str)
                    if isinstance(v, (dict, list)) else v)
                for k, v in row.items() if k in columns})
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.read()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=export.csv"})


def error_response(status: int, code: str, message: str, detail=None):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": detail}},
    )


class ListParams:
    """Uniform limit/offset/sort for every list endpoint."""

    def __init__(
        self,
        limit: int = Query(50, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        sort: str = Query(None, description="field:asc|desc"),
    ):
        self.limit = limit
        self.offset = offset
        self.sort = sort


def fill_prompt(template, record):
    """Render an ai_fix_prompt template with this record's identifiers."""
    if not template:
        return None
    evidence = record.get("evidence") or {}
    if not isinstance(evidence, str):
        evidence = json.dumps(evidence, default=str)[:1500]
    return (template
            .replace("{{resource_id}}", str(record.get("resource_id")
                                            or record.get("resource_uid") or "unknown"))
            .replace("{{region}}", str(record.get("region") or "unknown"))
            .replace("{{account_id}}", str(record.get("account_id") or "unknown"))
            .replace("{{evidence}}", evidence))
