"""
catalog-sync — load the build-generated CSVs into catalog_* tables.

    python -m store.catalog_sync [--force]

Git stays the source of truth; each table is created from its CSV's header
(all-TEXT columns — the CSVs are build artifacts whose columns evolve with
the build tools). A file whose sha256 matches catalog_sync_state is skipped,
so reruns are free. --force reloads everything.

A NOTE ON WHAT THESE TABLES ARE FOR.

Twenty catalog tables are written here and NINETEEN have no reader in this
repo. The engine loads the CSVs directly — `_load_detail_fields`,
`load_relations`, `resource_catalog.csv` — because the catalog is git-authored
and git is the source of truth. Only `catalog_collected_accounts` is queried,
and only by the cluster-side builders under `inventory/`.

So this is a MIRROR, not a store. That is a legitimate thing to be: the cluster
deployment reads these, and a diff against git is how you tell a deployed
catalog from the one in the repo. But it means the long-standing plan to
consolidate 22 tables into 7 would have merged heterogeneous schemas — 15
columns here, 40 there — into wide sparse tables that nothing queries, to save
a count nobody reads. The tables are not the cost; a `DROP TABLE` per file on
every sync is, and that is worth fixing when something finally reads them.
"""
import argparse
import csv
import hashlib
import os
import re
import sys

from cspm import paths

from . import get_backend, is_postgres
from .catalog import AWS_CATALOG_DIR, table_for


def _column(name: str) -> str:
    col = re.sub(r"[^a-z0-9_]", "_", name.strip().lower()) or "col"
    return f'"{col}"'


def _load_csv(backend, path: str, table: str, force: bool) -> dict:
    rel = os.path.relpath(path, paths.ROOT)
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    state = backend.query_one(
        "SELECT content_hash FROM catalog_sync_state WHERE source_file = %s", [rel])
    if state and state["content_hash"] == digest and not force:
        return {"table": table, "skipped": True}

    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header:
            return {"table": table, "skipped": True}
        cols = [_column(h) for h in header]
        rows = [row for row in reader]

    col_defs = ", ".join(f"{c} TEXT" for c in cols)
    backend.execute_script(
        f"DROP TABLE IF EXISTS {table}; CREATE TABLE {table} ({col_defs});")
    if rows:
        placeholders = ", ".join(["%s"] * len(cols))
        conn_rows = [tuple((v if v != "" else None) for v in
                     (row + [None] * (len(cols) - len(row)))[:len(cols)])
                     for row in rows]
        import psycopg2.extras
        from .backends import postgres as pg
        def go(cur):
            psycopg2.extras.execute_batch(
                cur, f"INSERT INTO {table} VALUES ({placeholders})",
                conn_rows, page_size=1000)
        pg._run(go)

    backend.upsert("catalog_sync_state",
                   [{"source_file": rel, "table_name": table,
                     "content_hash": digest, "row_count": len(rows)}],
                   ["source_file"])
    return {"table": table, "rows": len(rows)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if not is_postgres():
        print("catalog-sync: postgres backend unavailable — files mode reads "
              "the CSVs directly, nothing to sync", file=sys.stderr)
        return 0
    backend = get_backend()

    results = []
    for fname in sorted(os.listdir(AWS_CATALOG_DIR)):
        if fname.endswith(".csv"):
            stem = fname[:-4]
            results.append(_load_csv(
                backend, os.path.join(AWS_CATALOG_DIR, fname),
                table_for(stem), args.force))
    loaded = [r for r in results if not r.get("skipped")]
    print(f"catalog-sync: {len(loaded)} tables loaded, "
          f"{len(results) - len(loaded)} unchanged", file=sys.stderr)
    for r in loaded:
        print(f"  {r['table']:40s} {r['rows']:>6} rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
