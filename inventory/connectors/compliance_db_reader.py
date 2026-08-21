"""
Compliance DB Reader (Inventory)

Reads compliance results from the Compliance DB (threat_engine_compliance.compliance_findings)
so Inventory can enrich asset detail with per-resource compliance posture.

=== DATABASE & TABLE MAP ===
Database: threat_engine_compliance (COMPLIANCE DB)
Env: COMPLIANCE_DB_HOST / COMPLIANCE_DB_PORT / COMPLIANCE_DB_NAME / COMPLIANCE_DB_USER / COMPLIANCE_DB_PASSWORD

Tables READ:
  - compliance_findings : get_compliance_for_resource(resource_uid, tenant_id)
                          — SELECT compliance_framework, control_id, control_name,
                                   severity, status, rule_id
                            FROM compliance_findings
                            WHERE resource_uid = %s AND tenant_id = %s

Tables WRITTEN: None (read-only connector)
===
"""

from __future__ import annotations

import os
import logging
from typing import Dict, Any, Optional, List

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


def _db_url_with_search_path(url: str) -> str:
    """Append options=search_path to URL when DB_SCHEMA is set."""
    schema = (os.getenv("DB_SCHEMA") or "").strip()
    if not schema:
        return url
    sep = "&" if "?" in url else "?"
    opts = f"options=-c%20search_path%3D{schema.replace(',', '%2C')}"
    return f"{url}{sep}{opts}"


class ComplianceDBReader:
    """Reads compliance findings from PostgreSQL compliance_findings table."""

    def __init__(self, db_url: Optional[str] = None):
        if db_url is None:
            host = os.getenv("COMPLIANCE_DB_HOST", "localhost")
            port = os.getenv("COMPLIANCE_DB_PORT", "5432")
            db = os.getenv("COMPLIANCE_DB_NAME", "threat_engine_compliance")
            user = os.getenv("COMPLIANCE_DB_USER", "compliance_user")
            pwd = os.getenv("COMPLIANCE_DB_PASSWORD", "compliance_password")
            db_url = f"postgresql://{user}:{pwd}@{host}:{port}/{db}"
        self.db_url = db_url
        self.conn = psycopg2.connect(_db_url_with_search_path(db_url))

    def get_compliance_for_resource(
        self,
        resource_uid: str,
        tenant_id: str,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Return compliance findings for a specific resource (for asset detail Compliance tab).

        Returns list of dicts with framework, control_id, control_name, severity, status.
        """
        query = """
            SELECT
                compliance_framework,
                control_id,
                control_name,
                severity,
                status,
                rule_id,
                category,
                last_seen_at
            FROM compliance_findings
            WHERE (resource_uid = %s OR resource_arn = %s)
              AND tenant_id = %s
            ORDER BY
                CASE LOWER(severity)
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                    ELSE 5
                END,
                compliance_framework, control_id
            LIMIT %s
        """
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (resource_uid, resource_uid, tenant_id, limit))
                rows = cur.fetchall()
        except Exception as e:
            logger.warning(f"Compliance query failed: {e}")
            return []

        results = []
        for r in rows:
            last_seen = r.get("last_seen_at")
            results.append({
                "framework": r.get("compliance_framework") or "",
                "control_id": r.get("control_id") or "",
                "control_name": r.get("control_name") or "",
                "severity": (r.get("severity") or "medium").lower(),
                "status": r.get("status") or "open",
                "rule_id": r.get("rule_id") or "",
                "category": r.get("category") or "",
                "last_seen": last_seen.isoformat() if last_seen else None,
            })
        return results

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
