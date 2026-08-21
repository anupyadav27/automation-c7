"""store.catalog — build-generated reference data (catalog_* tables).

Postgres serves the synced tables; the files backend reads the source CSVs
directly, so consumers get identical rows either way.
"""
import csv
import os

from cspm import paths

from . import get_backend, is_postgres

AWS_CATALOG_DIR = os.path.join(paths.ROOT, "providers", "aws", "catalog")

# CSV stem → standard table name (platform-standards.md §2)
#
# `rule_diagram_*` marks the tables the ARCHITECTURE DIAGRAM is built from —
# what a service is, how it is discovered, what relates to what. The name says
# which product surface owns the row, which `catalog_*` never did: it said only
# "generated", and generated-for-what is the question a reader has.
TABLE_MAP = {
    "enrich_specs": "rule_diagram_discovery_enrich",
    "detail_fields": "rule_diagram_discovery",
    "resource_catalog": "rule_diagram_services",
    "asset_types": "catalog_asset_classes",
    "arn_recipes_full": "catalog_arn_recipes",
    "arn_recipes": "catalog_arn_recipes_c7n",
    "relations_full": "rule_diagram_relationship",
    "relations_mined": "catalog_relations_mined",
    "relations": "catalog_relations_curated",
    "relationship_master": "catalog_relations_master",
    "layers": "catalog_services_layer",
    "layer_assignment": "catalog_layer_assignments",
    "icon_map": "catalog_icons",
    "cfn_types": "catalog_cfn_types",
    "resource_types": "catalog_c7n_types",
    "location_paths": "catalog_location_paths",
    "policy_sources": "rule_diagram_policy_sources",
    "value_joins": "catalog_value_joins",
    "collection_args": "catalog_collection_args",
    "collection_filters": "catalog_collection_filters",
    "non_asset_types": "catalog_non_asset_types",
    "accounts": "catalog_collected_accounts",
}


def table_for(stem: str) -> str:
    return TABLE_MAP.get(stem, f"catalog_{stem}")


def rows(table: str, limit=1000, offset=0, **filters):
    """Rows from a catalog table (or its source CSV in files mode)."""
    backend = get_backend()
    if is_postgres():
        where, params = ["1=1"], []
        for key, value in filters.items():
            if value is not None:
                where.append(f'"{key}" = %s')
                params.append(value)
        total = backend.query_one(
            f'SELECT count(*) AS n FROM {table} WHERE {" AND ".join(where)}',
            params)["n"]
        data = backend.query(
            f'SELECT * FROM {table} WHERE {" AND ".join(where)} LIMIT %s OFFSET %s',
            params + [limit, offset])
        return data, total

    stem = next((s for s, t in TABLE_MAP.items() if t == table),
                table.replace("catalog_", ""))
    path = os.path.join(AWS_CATALOG_DIR, f"{stem}.csv")
    if not os.path.exists(path):
        return [], 0
    with open(path) as fh:
        data = [r for r in csv.DictReader(fh) if backend.match(r, **filters)]
    return backend.paginate(data, limit, offset)


def resource_type(key: str):
    data, _ = rows("catalog_resource_types", limit=1, resource_key=key)
    return data[0] if data else None
