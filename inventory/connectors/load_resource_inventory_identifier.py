"""
Resource Inventory Identifier Loader

Reads all step5_resource_catalog_inventory_enrich.json files from data_pythonsdk
and upserts the records into the resource_inventory_identifier table in
threat_engine_inventory database.

Run once to populate the table; re-run to refresh after catalog updates.

=== DATABASE & TABLE MAP ===
Database: threat_engine_inventory (INVENTORY DB)
Table WRITTEN:
  - resource_inventory_identifier : UPSERT per (csp, service, resource_type)
      Columns: csp, service, resource_type, classification, has_arn,
               arn_entity, identifier_type, primary_param, identifier_pattern,
               can_inventory_from_roots, should_inventory,
               root_ops, enrich_ops, raw_catalog, loaded_at

=== CSP FORMAT VARIANTS ===
This loader handles four different step5 JSON layouts:

  Format A — AWS/OCI/AliCloud/IBM (resources key, nested):
    {"csp": "aws", "resources": {"resource_type": {"inventory": {"ops": [...]}}}}
    Ops use:  "operation", "python_method", "required_params": []

  Format B — Azure (flat, single resource per file):
    {"resource": "NAME", "resource_independent_methods": [...], "resource_dependent_methods": [...]}

  Format C — GCP (nested under services.{svc}.resources):
    {"services": {"svc": {"resources": {"rt": {"inventory": {"ops": [...]}}}}}}
    Ops use:  "op" (→ normalized to "operation"),
              "python_call" (→ normalized to "python_method"),
              "required_params": {} dict (→ normalized to list of keys)

All formats are normalized to a single canonical op shape:
  {"operation": str, "independent": bool, "required_params": [str, ...],
   "python_method": str | None, "kind": str | None}

=== PURPOSE ===
The inventory engine reads ALL resource data from discovery_findings (DB).
resource_inventory_identifier is a lookup catalog that the inventory engine
uses to classify each discovery_findings record as either:
  - root op   (independent=true)  → creates Asset in Pass 1
  - enrich op (independent=false) → enriches existing Asset in Pass 2

The python_method/http fields in step5 are for the discovery engine (which
calls cloud APIs). The inventory engine only needs: operation, independent,
required_params, arn_entity, can_inventory_from_roots.

Usage:
  python -m engine_inventory.inventory_engine.connectors.load_resource_inventory_identifier
  # or
  DATA_PYTHONSDK_PATH=/path/to/data_pythonsdk python load_resource_inventory_identifier.py
===
"""

import os
import sys
import json
import logging
import re
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# ── Default catalog path ──────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent  # threat-engine root
_DEFAULT_CATALOG_PATH = _REPO_ROOT / "data_pythonsdk"


# ── Op normalization ──────────────────────────────────────────────────────────

def _normalize_op(op: Dict[str, Any], parent_resource_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Normalize a single operation dict to a canonical shape across all CSP formats.

    Handles:
      - GCP: 'op' field → 'operation'
      - GCP: 'python_call' (full call expression) → 'python_method' (snake_case method)
      - GCP: 'required_params' as dict → list of parameter name keys
      - OCI/AliCloud/IBM: missing 'required_params' → []
      - All: extract 'param_sources' from GCP chain_to_independent.execution_steps
             or infer from required_params for non-GCP CSPs

    Returns a new dict with canonical fields:
      operation        str   — operation name (primary key for matching discovery_findings)
      independent      bool  — True = root/Pass-1, False = enrich/Pass-2
      required_params  list  — parameter names required to call the op (may be empty)
      python_method    str|None — snake_case method name (informational)
      kind             str|None — read_list | read_get | etc.
      param_sources    dict  — how to resolve each required_param from the parent asset:
                               {
                                 "Bucket": {
                                   "from_field":          "resource_id",
                                   "from_asset_field":    "name",
                                   "parent_resource_type": "bucket"
                                 }
                               }
    """
    normalized: Dict[str, Any] = {}

    # operation: prefer 'operation', fall back to 'op' (GCP)
    operation = op.get("operation") or op.get("op", "")
    normalized["operation"] = operation

    # independent flag
    normalized["independent"] = bool(op.get("independent", True))

    # kind (read_list, read_get, etc.)
    normalized["kind"] = op.get("kind")

    # python_method: prefer explicit field; derive from python_call (GCP) or operation
    python_method = op.get("python_method")
    if not python_method:
        python_call = op.get("python_call", "")
        if python_call:
            python_method = _extract_method_from_call(python_call)
        if not python_method and operation:
            op_last = operation.split(".")[-1] if "." in operation else operation
            python_method = _to_snake(op_last)
    normalized["python_method"] = python_method or None

    # required_params: normalize dict → list of keys; None/missing → []
    rp = op.get("required_params")
    if isinstance(rp, dict):
        normalized["required_params"] = list(rp.keys())
    elif isinstance(rp, list):
        normalized["required_params"] = [p for p in rp if isinstance(p, str)]
    else:
        normalized["required_params"] = []

    # param_sources: tells the inventory engine HOW to resolve each required_param
    # from the parent asset's fields.
    #
    # Shape: { "ParamName": { "from_field": "resource_id" | "resource_arn" | "name",
    #                          "from_asset_field": "resource_id" | "name" | ...,
    #                          "parent_resource_type": "bucket" | "vpc" | ... } }
    #
    # Priority:
    #   1. GCP chain_to_independent.execution_steps[n].param_sources (explicit)
    #   2. Inferred from required_params names using naming heuristics
    param_sources: Dict[str, Any] = {}

    # 1. Try to extract from GCP chain_to_independent
    chain = op.get("chain_to_independent", {})
    if isinstance(chain, dict):
        for step in chain.get("execution_steps", []):
            for param_name, sources in step.get("param_sources", {}).items():
                if isinstance(sources, dict):
                    # GCP param_source shape: {paramName: {siteId: {from_step:1, field:"reviewedSite"}}}
                    for _, src in sources.items():
                        if isinstance(src, dict) and "field" in src:
                            param_sources[param_name] = {
                                "from_field": _to_snake(src["field"]),
                                "from_asset_field": _to_snake(src["field"]),
                                "parent_resource_type": parent_resource_type,
                            }

    # 2. Infer from required_params for non-GCP CSPs
    if not param_sources and normalized["required_params"] and not normalized["independent"]:
        for param in normalized["required_params"]:
            param_sources[param] = _infer_param_source(param, parent_resource_type)

    if param_sources:
        normalized["param_sources"] = param_sources

    return normalized


def _infer_param_source(param_name: str, parent_resource_type: Optional[str]) -> Dict[str, Any]:
    """
    Infer how to resolve a required_param from the parent asset's discovery fields.

    Rules (in priority order):
      - params ending in 'Arn' / 'ARN'       → from resource_arn / resource_uid
      - params ending in 'Name' OR whose name matches the parent_resource_type
        (e.g. "Bucket" when parent is "bucket")  → from resource_id / name
      - params ending in 'Id' / '_id' / 'Identifier' → from resource_id
      - default                               → from resource_uid (fallback)
    """
    p = param_name.lower()

    # Does param name match the parent resource type? (e.g. "Bucket" → parent="bucket")
    is_resource_name_param = (
        parent_resource_type and p == parent_resource_type.lower().replace("_", "")
    )

    if p.endswith("arn"):
        field = "resource_arn"
        asset_field = "resource_uid"
    elif p.endswith("name") or is_resource_name_param:
        # AWS name-style IDs: BucketName, FunctionName, TableName, or just "Bucket"
        field = "resource_id"
        asset_field = "name"
    elif p.endswith("id") or p.endswith("_id") or p.endswith("identifier"):
        field = "resource_id"
        asset_field = "resource_id"
    else:
        field = "resource_uid"
        asset_field = "resource_uid"

    return {
        "from_field": field,           # column in discovery_findings
        "from_asset_field": asset_field,   # field on Asset object
        "parent_resource_type": parent_resource_type,
    }


def _extract_method_from_call(python_call: str) -> Optional[str]:
    """
    Extract a reasonable snake_case method name from a GCP call expression.

    Examples:
      "svc.violatingSites().list(**params).execute()"   → "violating_sites_list"
      "svc.sites().get(**params).execute()"             → "sites_get"
      "svc.projects().instances().list(**params).execute()" → "instances_list"
    """
    # Remove .execute() and (**params) suffixes
    cleaned = re.sub(r'\.execute\(\)$', '', python_call.strip())
    cleaned = re.sub(r'\(\*\*\w+\)$', '', cleaned)
    # Extract method chain after 'svc.'
    match = re.match(r'svc\.(.*)', cleaned)
    if not match:
        return None
    chain = match.group(1)
    # Split on () to get method names: "violatingSites().list" → ["violatingSites", "list"]
    # Strip both leading dots and trailing () to handle ".methodName" fragments
    parts = [p.lstrip('.').rstrip('()') for p in chain.split('()') if p.lstrip('.').rstrip('()')]
    if not parts:
        return None
    # Join last 2 parts as snake_case: ["violatingSites", "list"] → "violating_sites_list"
    relevant = parts[-2:] if len(parts) >= 2 else parts
    return "_".join(_to_snake(p) for p in relevant)


def _to_snake(name: str) -> str:
    """CamelCase → snake_case."""
    s1 = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


# ── Main loader ───────────────────────────────────────────────────────────────

def load_catalog_into_db(
    catalog_base_path: Optional[str] = None,
    db_url: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, int]:
    """
    Walk all CSP directories in catalog_base_path and upsert into resource_inventory_identifier.

    Args:
        catalog_base_path: Root of data_pythonsdk tree.
                           Falls back to DATA_PYTHONSDK_PATH env var, then repo default.
        db_url: PostgreSQL connection string for threat_engine_inventory.
                Falls back to env vars: INVENTORY_DB_HOST, INVENTORY_DB_NAME, etc.
        dry_run: If True, parse and log without writing to DB.

    Returns:
        {"inserted": N, "updated": N, "skipped": N, "errors": N}
    """
    catalog_path = Path(
        catalog_base_path
        or os.getenv("DATA_PYTHONSDK_PATH", str(_DEFAULT_CATALOG_PATH))
    )

    if not catalog_path.exists():
        raise FileNotFoundError(f"Catalog base path not found: {catalog_path}")

    if not dry_run:
        conn = _get_db_connection(db_url)
    else:
        conn = None

    stats = {"inserted": 0, "updated": 0, "skipped": 0, "errors": 0}
    rows: List[Dict[str, Any]] = []

    # Walk step5 files.
    # Supports two layouts:
    #   Full:    {catalog_path}/{csp}/{service}/step5_*.json  → parts == 3
    #   CSP-filtered: {catalog_path}/{service}/step5_*.json  → parts == 2
    #                 (catalog_path is already the CSP directory)
    step5_glob = catalog_path.rglob("step5_resource_catalog_inventory_enrich.json")
    for step5_file in sorted(step5_glob):
        parts = step5_file.relative_to(catalog_path).parts

        if len(parts) == 2:
            # catalog_path is already a CSP directory (e.g. data_pythonsdk/aws)
            csp = catalog_path.name
            service = parts[0]
        elif len(parts) >= 3:
            csp = parts[0]
            service = parts[1]
        else:
            logger.warning(f"Unexpected path structure (skipped): {step5_file}")
            stats["skipped"] += 1
            continue

        try:
            with open(step5_file) as f:
                catalog = json.load(f)
        except Exception as exc:
            logger.error(f"Failed to parse {step5_file}: {exc}")
            stats["errors"] += 1
            continue

        # Detect format and extract resource rows:
        #
        #   Format A — AWS/OCI/AliCloud/IBM:  {"resources": {"resource_type": {...}}}
        #   Format B — Azure flat:            {"resource": "NAME", "resource_independent_methods": [...]}
        #   Format C — GCP nested:            {"services": {"svc": {"resources": {...}}}}
        resource_rows: List[Dict[str, Any]] = []

        if catalog.get("services"):
            # Format C: GCP — nested under services.{svc_name}.resources
            for svc_name, svc_data in catalog["services"].items():
                svc_resources = svc_data.get("resources", {})
                primary_rt = _find_primary_resource_type(svc_resources)
                for rt, info in svc_resources.items():
                    resource_rows.append(
                        _extract_row(csp, svc_name, rt, info,
                                     service_primary_resource_type=primary_rt)
                    )

        elif catalog.get("resources"):
            # Format A: AWS / OCI / AliCloud / IBM
            resources = catalog["resources"]
            primary_rt = _find_primary_resource_type(resources)
            for rt, info in resources.items():
                resource_rows.append(
                    _extract_row(csp, service, rt, info,
                                 service_primary_resource_type=primary_rt)
                )

        elif catalog.get("resource"):
            # Format B: Azure flat (single resource per file)
            resource_rows.append(_extract_row_flat(csp, service, catalog))

        else:
            # Empty or unknown format — skip quietly (e.g. generated but empty files)
            logger.debug(f"No resources in {step5_file} — skipping")
            stats["skipped"] += 1
            continue

        if not resource_rows:
            stats["skipped"] += 1
            continue

        for row in resource_rows:
            rows.append(row)
            if dry_run:
                logger.info(
                    f"[DRY RUN] {csp}.{row['service']}.{row['resource_type']}: "
                    f"arn_entity={row['arn_entity']}, "
                    f"root_ops={len(row['root_ops'])}, "
                    f"enrich_ops={len(row['enrich_ops'])}, "
                    f"can_inventory_from_roots={row['can_inventory_from_roots']}"
                )
            else:
                result = _upsert_row(conn, row)
                stats[result] += 1

    if conn:
        conn.commit()
        conn.close()

    total = stats["inserted"] + stats["updated"] + stats["skipped"] + stats["errors"]
    logger.info(
        f"Loaded resource_inventory_identifier: "
        f"{stats['inserted']} inserted, {stats['updated']} updated, "
        f"{stats['skipped']} skipped, {stats['errors']} errors "
        f"(total rows processed: {total})"
    )

    if dry_run:
        logger.info(f"[DRY RUN] Would process {len(rows)} resource type entries.")

    return stats


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_primary_resource_type(resources: Dict[str, Any]) -> Optional[str]:
    """
    Find the primary (root) resource_type in a service's resource map.

    The primary resource is the one that:
      1. Has root_ops (inventory.ops with independent=true), OR
      2. Is explicitly classified as PRIMARY_RESOURCE with can_inventory_from_roots=true
      3. Tie-break: prefer the resource_type whose name matches the service name

    Returns None if the service has only one resource type (no ambiguity needed)
    or if no clear primary can be determined.
    """
    if not resources or len(resources) == 1:
        return next(iter(resources), None)

    candidates = []
    for rt, info in resources.items():
        root_ops = info.get("inventory", {}).get("ops", [])
        has_root = bool(root_ops)
        classification = info.get("classification", "")
        can_from_roots = info.get("can_inventory_from_roots", has_root)

        if has_root or (classification == "PRIMARY_RESOURCE" and can_from_roots):
            candidates.append(rt)

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        # Prefer the shortest / most general name (e.g. "bucket" over "bucket_acl")
        return min(candidates, key=len)

    return None


# ── Row extraction ────────────────────────────────────────────────────────────

def _extract_row(
    csp: str,
    service: str,
    resource_type: str,
    resource_info: Dict[str, Any],
    service_primary_resource_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Parse a single step5 resource block (Format A: AWS/OCI/AliCloud/IBM, Format C: GCP)
    into a DB row dict.

    Normalizes ops from all CSP variants to canonical shape via _normalize_op().

    Canonical op shape:
      {"operation": str, "independent": bool, "required_params": [str],
       "python_method": str|None, "kind": str|None,
       "param_sources": {param: {from_field, from_asset_field, parent_resource_type}}}

    Classification logic (applied in order, explicit step5 values always win):

      PRIMARY_RESOURCE  — has root/independent ops; inventoriable as standalone Asset.
                          Pass 1 creates the Asset.

      SUB_RESOURCE      — no root ops; has its own ARN/identity (has_arn=True or arn_entity set).
                          Pass 1 promotes it to create a separate Asset.
                          Pass 2 also enriches the parent Asset.
                          can_inventory_from_roots=False.

      CONFIGURATION     — no root ops; NO own ARN/identity. Pure configuration/property data
                          belonging entirely to the parent. Pass 2 ONLY — merges into parent
                          Asset's configuration JSONB. No separate Asset created.
                          can_inventory_from_roots=True (means "don't promote to Pass 1").

      ACTION_ENDPOINT   — should_inventory=False. Skip entirely (write ops, name checks, etc.)

    Args:
        service_primary_resource_type: The primary (root) resource_type of this service.
            Used to populate parent_resource_type for sub-resources / config resources.
    """
    identifier = resource_info.get("identifier", {})

    # ── Step 1: Raw ops ──────────────────────────────────────────────────────
    raw_root_ops   = resource_info.get("inventory",        {}).get("ops", [])
    raw_enrich_ops = resource_info.get("inventory_enrich", {}).get("ops", [])
    has_root = bool(raw_root_ops)

    # ── Step 2: has_arn / identifier_type ───────────────────────────────────
    # Derive early — needed to decide can_inventory_from_roots below.
    has_arn = resource_info.get("has_arn")
    if has_arn is None:
        id_type = (
            identifier.get("identifier_type")
            or resource_info.get("identifier_type", "")
        )
        has_arn = id_type.lower() == "arn"

    identifier_type = (
        identifier.get("identifier_type")
        or resource_info.get("identifier_type", "id")
    )
    primary_param = (
        identifier.get("primary_param")
        or resource_info.get("primary_param")
    )

    # ── Step 3: Parent relationship ──────────────────────────────────────────
    # A resource is a child of the service's primary resource when it has no
    # root ops and is not the primary resource itself.
    explicit_parent_rt = resource_info.get("parent_resource_type")
    parent_resource_type = (
        explicit_parent_rt
        or (
            service_primary_resource_type
            if not has_root and service_primary_resource_type != resource_type
            else None
        )
    )
    parent_service = service if parent_resource_type else None

    # ── Step 4: Normalize ops ────────────────────────────────────────────────
    # For primary resources (parent_resource_type=None) the enrich ops are
    # self-referential: "Bucket" in get_bucket_versioning refers to the bucket
    # itself. Pass resource_type as enrich parent so _infer_param_source maps
    # "bucket" == "bucket" → resource_id/name (not resource_uid).
    enrich_parent_rt = parent_resource_type or resource_type
    root_ops   = [_normalize_op(op, parent_resource_type=None)            for op in raw_root_ops   if isinstance(op, dict)]
    enrich_ops = [_normalize_op(op, parent_resource_type=enrich_parent_rt) for op in raw_enrich_ops if isinstance(op, dict)]

    # ── Step 5: should_inventory ─────────────────────────────────────────────
    should_inventory = resource_info.get("should_inventory", True)

    # ── Step 6: can_inventory_from_roots ─────────────────────────────────────
    #
    # Explicit step5 flag always wins.  When not set, derive from ops + identity:
    #
    #   ROOT OPS present            → True   (independently listable; Pass 1 creates Asset)
    #
    #   No root ops + OWN IDENTITY  → False  (SUB_RESOURCE: has own ARN; orchestrator
    #                                          promotes to Pass 1 AND enriches parent)
    #
    #   No root ops + NO identity   → True   (CONFIGURATION: enrich parent only,
    #                                          no separate Asset)
    #
    #   ACTION_ENDPOINT (any)       → True   (never create a separate Asset regardless
    #                                          of ARN; orchestrator decides enrich-vs-skip
    #                                          by checking parent_resource_type)
    #
    # Orchestrator rule:
    #   can_inventory_from_roots=False → add to root_records (creates separate Asset)
    #   can_inventory_from_roots=True  → Pass 2 enrichment only (or skip if no parent)
    can_inventory = resource_info.get("can_inventory_from_roots")
    if can_inventory is None:
        if root_ops:
            can_inventory = True
        elif not should_inventory:
            # ACTION_ENDPOINT: never a standalone Asset; orchestrator handles enrich-vs-skip
            can_inventory = True
        else:
            own_identity = bool(has_arn) or bool(resource_info.get("arn_entity"))
            # Own ARN  → False → promoted to Pass 1 as separate Asset
            # No ARN   → True  → Pass 2 enrichment only, no separate Asset
            can_inventory = not own_identity

    # ── Step 7: Classification ───────────────────────────────────────────────
    #
    # ACTION_ENDPOINT is stored with parent_resource_type when it has a known parent.
    # The orchestrator reads parent_resource_type to decide:
    #   ACTION_ENDPOINT + parent_resource_type → enrich parent in Pass 2
    #   ACTION_ENDPOINT + no parent            → skip entirely (write/utility op)
    classification = resource_info.get("classification")
    if not classification:
        if not should_inventory:
            classification = "ACTION_ENDPOINT"
        elif root_ops:
            classification = "PRIMARY_RESOURCE"
        elif parent_resource_type:
            own_identity = bool(has_arn) or bool(resource_info.get("arn_entity"))
            classification = "SUB_RESOURCE" if own_identity else "CONFIGURATION"
        else:
            # No root ops, no parent — single resource in service or unknown parent
            classification = "PRIMARY_RESOURCE"
    elif not should_inventory:
        # Explicit classification overridden to ACTION_ENDPOINT
        classification = "ACTION_ENDPOINT"

    return {
        "csp": csp,
        "service": service,
        "resource_type": resource_type,
        "classification": classification,
        "has_arn": bool(has_arn),
        "arn_entity": resource_info.get("arn_entity"),
        "identifier_type": identifier_type,
        "primary_param": primary_param,
        "identifier_pattern": resource_info.get("identifier_pattern"),
        "can_inventory_from_roots": bool(can_inventory),
        "should_inventory": bool(should_inventory),
        "parent_service": parent_service,
        "parent_resource_type": parent_resource_type,
        "root_ops": root_ops,
        "enrich_ops": enrich_ops,
        "raw_catalog": resource_info,
    }


def _extract_row_flat(csp: str, service: str, catalog: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a single-resource step5 file (Format B: Azure flat) into a DB row.

    Format:
      {
        "service": "managementgroups",
        "resource": "MANAGEMENTGROUPS",
        "identifier_type": "id",
        "pattern": "/subscriptions/{sub}/...",
        "resource_identifiers": "id",
        "resource_independent_methods": ["list", ...],
        "resource_dependent_methods": ["create_or_update", ...],
      }

    Methods are plain strings (method names only) — normalized to canonical op shape.
    """
    resource_name = catalog.get("resource", "").lower().replace(" ", "_")
    root_methods = catalog.get("resource_independent_methods", [])
    enrich_methods = catalog.get("resource_dependent_methods", [])

    root_ops = [
        _normalize_op({
            "operation": m,
            "independent": True,
            "python_method": _to_snake(m) if m else None,
        })
        for m in root_methods
        if isinstance(m, str) and m
    ]
    enrich_ops = [
        _normalize_op({
            "operation": m,
            "independent": False,
            "python_method": _to_snake(m) if m else None,
        })
        for m in enrich_methods
        if isinstance(m, str) and m
    ]

    identifier_type = catalog.get("identifier_type", "id")
    has_arn = identifier_type.lower() == "arn"

    # Respect explicit should_inventory flag (e.g. action endpoints marked False)
    should_inventory = catalog.get("should_inventory", True)

    # can_inventory_from_roots: same logic as _extract_row —
    #   root ops present   → True  (independently listable)
    #   no root ops + ARN  → False (has own identity; promote to Pass 1 as separate Asset)
    #   no root ops + no ARN → True (CONFIGURATION; enrich parent only, no separate Asset)
    can_inventory = catalog.get("can_inventory_from_roots")
    if can_inventory is None:
        if root_ops:
            can_inventory = True
        else:
            own_identity = has_arn  # Azure flat: no arn_entity field
            can_inventory = not own_identity

    # Classification:
    #   ACTION_ENDPOINT  → should_inventory=False
    #   PRIMARY_RESOURCE → has root ops, or no root ops but has own ARN with unknown parent
    #   CONFIGURATION    → no root ops, no ARN, pure dependent enrichment
    if not should_inventory:
        classification = "ACTION_ENDPOINT"
    elif root_ops:
        classification = "PRIMARY_RESOURCE"
    elif has_arn:
        classification = "PRIMARY_RESOURCE"  # own ARN but unknown parent (Azure single-resource files)
    else:
        classification = "CONFIGURATION"

    return {
        "csp": csp,
        "service": service,
        "resource_type": resource_name or service,
        "classification": classification,
        "has_arn": has_arn,
        "arn_entity": None,
        "identifier_type": identifier_type,
        "primary_param": catalog.get("resource_identifiers"),
        "identifier_pattern": catalog.get("pattern"),
        "can_inventory_from_roots": bool(can_inventory),
        "should_inventory": bool(should_inventory),
        "root_ops": root_ops,
        "enrich_ops": enrich_ops,
        "raw_catalog": catalog,
    }


# ── DB operations ─────────────────────────────────────────────────────────────

def _upsert_row(conn, row: Dict[str, Any]) -> str:
    """
    Upsert a single row into resource_inventory_identifier.

    Returns "inserted", "updated", or "errors".
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO resource_inventory_identifier (
                    csp, service, resource_type, classification,
                    has_arn, arn_entity, identifier_type, primary_param, identifier_pattern,
                    can_inventory_from_roots, should_inventory,
                    parent_service, parent_resource_type,
                    root_ops, enrich_ops, raw_catalog, loaded_at, updated_at
                ) VALUES (
                    %(csp)s, %(service)s, %(resource_type)s, %(classification)s,
                    %(has_arn)s, %(arn_entity)s, %(identifier_type)s, %(primary_param)s,
                    %(identifier_pattern)s,
                    %(can_inventory_from_roots)s, %(should_inventory)s,
                    %(parent_service)s, %(parent_resource_type)s,
                    %(root_ops)s::jsonb, %(enrich_ops)s::jsonb, %(raw_catalog)s::jsonb,
                    NOW(), NOW()
                )
                ON CONFLICT (csp, service, resource_type) DO UPDATE SET
                    classification           = EXCLUDED.classification,
                    has_arn                  = EXCLUDED.has_arn,
                    arn_entity               = EXCLUDED.arn_entity,
                    identifier_type          = EXCLUDED.identifier_type,
                    primary_param            = EXCLUDED.primary_param,
                    identifier_pattern       = EXCLUDED.identifier_pattern,
                    can_inventory_from_roots = EXCLUDED.can_inventory_from_roots,
                    should_inventory         = EXCLUDED.should_inventory,
                    parent_service           = EXCLUDED.parent_service,
                    parent_resource_type     = EXCLUDED.parent_resource_type,
                    root_ops                 = EXCLUDED.root_ops,
                    enrich_ops               = EXCLUDED.enrich_ops,
                    raw_catalog              = EXCLUDED.raw_catalog,
                    updated_at               = NOW()
                """,
                {
                    **row,
                    "parent_service": row.get("parent_service"),
                    "parent_resource_type": row.get("parent_resource_type"),
                    "root_ops": json.dumps(row["root_ops"]),
                    "enrich_ops": json.dumps(row["enrich_ops"]),
                    "raw_catalog": json.dumps(row["raw_catalog"]) if row["raw_catalog"] else None,
                },
            )
            if cur.rowcount and cur.statusmessage and "INSERT" in cur.statusmessage:
                return "inserted"
            return "updated"
    except Exception as exc:
        logger.error(
            f"Failed to upsert {row['csp']}.{row['service']}.{row['resource_type']}: {exc}"
        )
        conn.rollback()
        return "errors"


def _get_db_connection(db_url: Optional[str] = None):
    """Get a psycopg2 connection to threat_engine_inventory."""
    import psycopg2

    if db_url:
        return psycopg2.connect(db_url)

    host = os.getenv("INVENTORY_DB_HOST", os.getenv("DB_HOST", "localhost"))
    port = os.getenv("INVENTORY_DB_PORT", os.getenv("DB_PORT", "5432"))
    dbname = os.getenv("INVENTORY_DB_NAME", "threat_engine_inventory")
    user = os.getenv("INVENTORY_DB_USER", os.getenv("DB_USER", "postgres"))
    password = os.getenv("INVENTORY_DB_PASSWORD", os.getenv("DB_PASSWORD", ""))

    return psycopg2.connect(
        host=host,
        port=int(port),
        dbname=dbname,
        user=user,
        password=password,
    )


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Load step5 resource catalog into resource_inventory_identifier table"
    )
    parser.add_argument(
        "--catalog-path",
        default=None,
        help="Path to data_pythonsdk root (overrides DATA_PYTHONSDK_PATH env var)",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="PostgreSQL DSN for threat_engine_inventory (overrides INVENTORY_DB_* env vars)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse catalogs and log without writing to DB",
    )
    parser.add_argument(
        "--csp",
        default=None,
        help="Only load a specific CSP (aws | azure | gcp | oci | alicloud | ibm)",
    )

    args = parser.parse_args()

    # If CSP filter: run loader on filtered path
    catalog_base = args.catalog_path or os.getenv(
        "DATA_PYTHONSDK_PATH", str(_DEFAULT_CATALOG_PATH)
    )
    if args.csp:
        catalog_base = str(Path(catalog_base) / args.csp)
        logger.info(f"Filtering to CSP: {args.csp}")

    stats = load_catalog_into_db(
        catalog_base_path=catalog_base,
        db_url=args.db_url,
        dry_run=args.dry_run,
    )
    print(f"\nResult: {stats}")
    sys.exit(0 if stats["errors"] == 0 else 1)
