"""Common orchestration components"""

from .discovery_engine import DiscoveryEngine

__all__ = ['DiscoveryEngine', 'get_orchestration_metadata']


def get_orchestration_metadata(scan_run_id: str) -> dict:
    """Look up a discovery scan's metadata (tenant, provider, status).

    Reads discovery_report in the Discoveries DB. Raises ValueError when the
    scan is unknown, which the API layer maps to a 404.
    """
    from providers.common.database.database_manager import DatabaseManager

    db = DatabaseManager()
    try:
        conn = db._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM discovery_report WHERE scan_run_id = %s "
                    "ORDER BY created_at DESC LIMIT 1",
                    (scan_run_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise ValueError(f"No discovery scan found for scan_run_id={scan_run_id}")
                columns = [d[0] for d in cur.description]
                return dict(zip(columns, row))
        finally:
            db._return_connection(conn)
    finally:
        db.close()
