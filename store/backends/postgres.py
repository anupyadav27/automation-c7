"""
Postgres backend — the one place that owns a connection pool and SQL
execution. Domain modules build statements; this module runs them and
returns plain dicts.
"""
import json
import logging

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)

NAME = "postgres"

_pool = None


def connect(url: str):
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 8, dsn=url, connect_timeout=4)
        # fail fast if unreachable
        conn = _pool.getconn()
        _pool.putconn(conn)


def _run(fn):
    conn = _pool.getconn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                return fn(cur)
    finally:
        _pool.putconn(conn)


def query(sql, params=None):
    def go(cur):
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    return _run(go)


def query_one(sql, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=None) -> int:
    def go(cur):
        cur.execute(sql, params)
        return cur.rowcount
    return _run(go)


def execute_script(sql_text: str):
    def go(cur):
        cur.execute(sql_text)
    return _run(go)


def _strip_nul(value):
    """
    Postgres text cannot hold a NUL byte, and one asset carried one.

    `ivschat.room` came back from AWS with `\x00` in its name. Postgres rejects
    it at the protocol level — not a row error, a statement error — so a single
    byte in a single field aborted an upsert of 1,185 assets and the pipeline
    logged a warning and carried on looking successful. The database sat eleven
    days behind the estate.

    Stripped rather than escaped: a NUL in a resource name is a fact about the
    provider's data, not information anyone can use, and losing it costs a
    reader nothing. Applied at the adapter because that is the one place every
    value passes through on its way to Postgres.
    """
    if isinstance(value, str):
        return value.replace('\x00', '') if '\x00' in value else value
    if isinstance(value, dict):
        return {k: _strip_nul(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_nul(v) for v in value]
    return value


def _adapt(value):
    value = _strip_nul(value)
    if isinstance(value, (dict, list)):
        return psycopg2.extras.Json(value, dumps=lambda o: json.dumps(o, default=str))
    return value


def upsert(table: str, rows: list, key_cols: list, update_cols: list = None) -> int:
    """Batch upsert; update_cols defaults to every non-key column."""
    if not rows:
        return 0
    cols = list(rows[0].keys())
    update_cols = update_cols if update_cols is not None else [c for c in cols if c not in key_cols]
    col_sql = ", ".join(f'"{c}"' for c in cols)
    conflict = ", ".join(f'"{c}"' for c in key_cols)
    if update_cols:
        action = "DO UPDATE SET " + ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
    else:
        action = "DO NOTHING"
    sql = (f'INSERT INTO {table} ({col_sql}) VALUES %s '
           f'ON CONFLICT ({conflict}) {action}')
    values = [tuple(_adapt(row[c]) for c in cols) for row in rows]

    def go(cur):
        psycopg2.extras.execute_values(cur, sql, values, page_size=500)
        return len(values)  # rowcount only reflects the final page
    return _run(go)
