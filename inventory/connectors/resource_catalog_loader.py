"""
Resource Catalog Loader

Loads resource catalog metadata from the resource_inventory_identifier table
(threat_engine_inventory DB) to provide per-service ARN extraction and
operation classification for the inventory engine.

=== DATA SOURCE ===
Table: threat_engine_inventory.resource_inventory_identifier

Populated by:
  data_pythonsdk/scripts/generate_{csp}_step5_catalog.py
      → writes step5_resource_catalog_inventory_enrich.json per service
  engine_inventory/inventory_engine/connectors/load_resource_inventory_identifier.py
      → seeds/upserts all step5 JSON files into resource_inventory_identifier

Key columns used at scan-time:
  arn_entity            VARCHAR  — dot-path to ARN in emitted_fields: "appsync.graphql_api_arn"
  root_ops              JSONB    — [{"operation": "ListGraphqlApis", "independent": true, ...}]
  enrich_ops            JSONB    — [{"operation": "ListSourceApiAssociations", "independent": false,
                                     "required_params": ["apiId"], ...}]
  can_inventory_from_roots BOOL  — false → resource only reachable via enrichment ops
  should_inventory         BOOL  — false → skip this resource_type entirely
  identifier_pattern    VARCHAR  — ARN template: "arn:${Partition}:appsync:${Region}:${Account}:api/${Id}"

=== KEY CONCEPTS ===
- arn_entity:  "{service}.{snake_field}" dot-path → navigates emitted_fields to find ARN
- independent: true  → root operation   → creates Asset in Pass 1
- independent: false → enrichment op    → enriches existing Asset in Pass 2
- can_inventory_from_roots: false → resource only available via dependent ops;
                                    still created as Asset (promoted to Pass 1)

=== CONNECTION ===
DB: threat_engine_inventory
Env vars (in priority order):
  INVENTORY_DB_HOST  / DB_HOST     (default: localhost)
  INVENTORY_DB_PORT  / DB_PORT     (default: 5432)
  INVENTORY_DB_NAME                (default: threat_engine_inventory)
  INVENTORY_DB_USER  / DB_USER     (default: postgres)
  INVENTORY_DB_PASSWORD / DB_PASSWORD
Or pass db_url (full DSN) directly to the constructor.
===
"""

import os
import re
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class ResourceCatalogLoader:
    """
    Loads and caches step5 resource catalogs from resource_inventory_identifier (DB).

    Provides:
      - ARN extraction from emitted_fields using arn_entity dot-path
      - Root vs dependent operation classification using independent flag
      - Resource type resolution per discovery operation
      - Dependency chain inspection (required_params)

    All catalog data is read exclusively from threat_engine_inventory DB.
    The resource_inventory_identifier table must be seeded before running scans
    (use load_resource_inventory_identifier.py).
    """

    def __init__(self, db_url: Optional[str] = None):
        """
        Args:
            db_url: Full PostgreSQL DSN for threat_engine_inventory.
                    Falls back to INVENTORY_DB_* / DB_* env vars when not supplied.
        """
        self._db_url = db_url

        # {csp.service: catalog_dict or {}}
        self._cache: Dict[str, Dict[str, Any]] = {}

    # ─── Catalog loading ─────────────────────────────────────────────────────

    def get_catalog(self, csp: str, service: str) -> Dict[str, Any]:
        """
        Return the step5 catalog for (csp, service).

        Resolution order:
          1. In-memory cache  (avoids repeated DB round-trips per scan)
          2. resource_inventory_identifier table in threat_engine_inventory

        Returns an empty dict when the service is not yet seeded in the DB.
        """
        key = f"{csp}.{service}"
        if key in self._cache:
            return self._cache[key]

        catalog = self._load_from_db(csp, service)
        self._cache[key] = catalog
        return catalog

    def _load_from_db(self, csp: str, service: str) -> Dict[str, Any]:
        """
        Query resource_inventory_identifier for all resource_types of a service
        and reconstruct the catalog dict in the same shape as the step5 JSON file.

        Returns {} when the service has no rows or the DB is unreachable.
        """
        conn = self._get_db_conn()
        if not conn:
            logger.error(
                f"ResourceCatalogLoader: cannot connect to inventory DB — "
                f"catalog for {csp}/{service} unavailable. "
                f"Ensure INVENTORY_DB_* env vars are set and resource_inventory_identifier "
                f"is seeded via load_resource_inventory_identifier.py."
            )
            return {}

        try:
            from psycopg2.extras import RealDictCursor

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT resource_type, classification, has_arn, arn_entity,
                           identifier_type, primary_param, identifier_pattern,
                           can_inventory_from_roots, should_inventory,
                           parent_service, parent_resource_type,
                           root_ops, enrich_ops
                    FROM   resource_inventory_identifier
                    WHERE  csp = %s AND service = %s
                    """,
                    (csp, service),
                )
                rows = cur.fetchall()

            if not rows:
                logger.debug(
                    f"ResourceCatalogLoader: no rows in resource_inventory_identifier "
                    f"for {csp}/{service} — heuristic classifier will be used"
                )
                return {}

            resources = {}
            for row in rows:
                rt = row["resource_type"]
                resources[rt] = {
                    "resource_type": rt,
                    "classification": row["classification"],
                    "has_arn": row["has_arn"],
                    "arn_entity": row["arn_entity"],
                    "can_inventory_from_roots": row["can_inventory_from_roots"],
                    "should_inventory": row["should_inventory"],
                    "parent_service": row["parent_service"],
                    "parent_resource_type": row["parent_resource_type"],
                    "identifier": {
                        "primary_param": row["primary_param"],
                        "identifier_type": row["identifier_type"],
                    },
                    "identifier_pattern": row["identifier_pattern"],
                    "inventory":        {"ops": row["root_ops"]   or []},
                    "inventory_enrich": {"ops": row["enrich_ops"] or []},
                }

            catalog = {"service": service, "csp": csp, "resources": resources}
            logger.debug(
                f"ResourceCatalogLoader: loaded {csp}/{service} from DB "
                f"({len(resources)} resource types)"
            )
            return catalog

        except Exception as exc:
            logger.warning(
                f"ResourceCatalogLoader: DB query failed for {csp}/{service}: {exc}"
            )
            return {}
        finally:
            conn.close()

    def _get_db_conn(self):
        """
        Open and return a psycopg2 connection to threat_engine_inventory.
        Returns None on connection failure.
        """
        try:
            import psycopg2

            if self._db_url:
                return psycopg2.connect(self._db_url)

            return psycopg2.connect(
                host=os.getenv("INVENTORY_DB_HOST", os.getenv("DB_HOST", "localhost")),
                port=int(os.getenv("INVENTORY_DB_PORT", os.getenv("DB_PORT", "5432"))),
                dbname=os.getenv("INVENTORY_DB_NAME", "threat_engine_inventory"),
                user=os.getenv("INVENTORY_DB_USER", os.getenv("DB_USER", "postgres")),
                password=os.getenv("INVENTORY_DB_PASSWORD", os.getenv("DB_PASSWORD", "")),
            )
        except Exception as exc:
            logger.warning(f"ResourceCatalogLoader: cannot connect to inventory DB: {exc}")
            return None

    def get_resource_info(
        self, csp: str, service: str, resource_type: str
    ) -> Optional[Dict[str, Any]]:
        """Return the catalog resource block for a specific resource_type, or None."""
        catalog = self.get_catalog(csp, service)
        return catalog.get("resources", {}).get(resource_type)

    # ─── Operation classification ─────────────────────────────────────────────

    @staticmethod
    def _to_snake(name: str) -> str:
        """CamelCase → snake_case (e.g. ListGraphqlApis → list_graphql_apis)."""
        s1 = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
        return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

    @staticmethod
    def _to_camel(snake: str) -> str:
        """snake_case → CamelCase (e.g. graphql_api_arn → GraphqlApiArn)."""
        return "".join(word.capitalize() for word in snake.split("_"))

    def _match_op(self, candidate: str, stored_op: str, stored_python_method: str = "") -> bool:
        """
        Flexible operation name matching across all CSP naming conventions.

        Handles:
          - Exact match (normalized snake_case)
          - Full GCP path match: "gcp.compute.instances.aggregatedList" == stored full path
          - Last-segment match: "aws.ec2.describe_instances" → last="describe_instances"
            matched against stored "describe_instances"
          - Python method match: "list_graphql_apis" against python_method field

        Args:
            candidate: Operation from discovery_findings.discovery_id (full path or short name)
            stored_op: Operation stored in resource_inventory_identifier root_ops/enrich_ops
            stored_python_method: python_method field from the stored op (optional)
        """
        if not candidate or not stored_op:
            return False

        cand_snake = self._to_snake(candidate)
        stor_snake = self._to_snake(stored_op)

        # 1. Exact full-path match (GCP: "gcp.compute.instances.aggregatedList")
        if cand_snake == stor_snake:
            return True

        # 2. Last-segment match — covers AWS "aws.ec2.describe_instances" → "describe_instances"
        #    and GCP where we extract the last verb: "list", "get", etc.
        cand_last = self._to_snake(candidate.split(".")[-1])
        stor_last = self._to_snake(stored_op.split(".")[-1])
        if cand_last and stor_last and cand_last == stor_last:
            # Narrow by requiring the second-to-last segments also match when both have them,
            # to avoid generic collisions on "list" / "get" across different resources.
            cand_parts = [p for p in candidate.split(".") if p]
            stor_parts = [p for p in stored_op.split(".") if p]
            if len(cand_parts) >= 2 and len(stor_parts) >= 2:
                cand_parent = self._to_snake(cand_parts[-2])
                stor_parent = self._to_snake(stor_parts[-2])
                if cand_parent == stor_parent:
                    return True
            elif len(cand_parts) == 1 or len(stor_parts) == 1:
                # Short name with no prefix — allow direct last-segment match
                return True

        # 3. python_method match (normalizer may emit snake_case method names)
        if stored_python_method:
            pm_snake = self._to_snake(stored_python_method)
            if cand_snake == pm_snake or cand_last == pm_snake:
                return True

        return False

    def is_root_operation(self, csp: str, service: str, operation: str) -> Optional[bool]:
        """
        Check if an operation is root/independent using the DB catalog.

        Args:
            csp: Cloud provider (aws, azure, gcp, oci, alicloud, ibm)
            service: Service name (s3, ec2, appsync, compute, …)
            operation: Full discovery_id or short operation name
                       (e.g. "gcp.compute.instances.aggregatedList" or "list_graphql_apis")

        Returns:
            True  → independent/root op (creates Asset in Pass 1)
            False → dependent/enrichment op (enriches existing Asset in Pass 2)
            None  → operation not found in DB catalog (caller falls back to heuristics)
        """
        catalog = self.get_catalog(csp, service)
        if not catalog:
            return None

        for resource_info in catalog.get("resources", {}).values():
            for op in resource_info.get("inventory", {}).get("ops", []):
                if isinstance(op, str):
                    if self._match_op(operation, op, ""):
                        return True
                    continue
                if self._match_op(operation, op.get("operation", ""), op.get("python_method", "")):
                    return op.get("independent", True)

            for op in resource_info.get("inventory_enrich", {}).get("ops", []):
                if isinstance(op, str):
                    if self._match_op(operation, op, ""):
                        return False
                    continue
                if self._match_op(operation, op.get("operation", ""), op.get("python_method", "")):
                    return op.get("independent", False)

        return None

    def get_resource_type_for_operation(
        self, csp: str, service: str, operation: str
    ) -> Optional[str]:
        """
        Return the resource_type that a discovery operation maps to.

        Checks both root (inventory) and enrichment (inventory_enrich) op lists.
        Returns None when the operation is not found in the DB catalog.
        """
        catalog = self.get_catalog(csp, service)
        if not catalog:
            return None

        for resource_type, resource_info in catalog.get("resources", {}).items():
            if not resource_info.get("should_inventory", True):
                continue
            for section in ("inventory", "inventory_enrich"):
                for op in resource_info.get(section, {}).get("ops", []):
                    if isinstance(op, str):
                        if self._match_op(operation, op, ""):
                            return resource_type
                        continue
                    if self._match_op(
                        operation, op.get("operation", ""), op.get("python_method", "")
                    ):
                        return resource_type

        return None

    def can_inventory_from_roots(
        self, csp: str, service: str, resource_type: str
    ) -> bool:
        """
        True if resource_type is discoverable from root/independent operations.
        False means it is only reachable via enrichment ops (requires parent context).
        When not found in DB, defaults to True (assume root-discoverable).
        """
        info = self.get_resource_info(csp, service, resource_type)
        if info is None:
            return True
        return bool(info.get("can_inventory_from_roots", True))

    # ─── ARN extraction ───────────────────────────────────────────────────────

    def extract_arn(
        self,
        csp: str,
        service: str,
        resource_type: str,
        emitted_fields: Dict[str, Any],
        discovery_record: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Extract the ARN for a resource using the step5 arn_entity path from DB.

        Resolution order:
          1. discovery_record["resource_arn"]        (explicit column — most reliable)
          2. arn_entity dot-path in emitted_fields   (from resource_inventory_identifier)
          3. Standard ARN field names (Arn, ARN, *Arn, …)
          4. discovery_record["resource_uid"]        (last fallback)
        """
        if not isinstance(emitted_fields, dict):
            emitted_fields = {}

        # 1. Explicit resource_arn column set by the discovery engine
        if discovery_record:
            arn = discovery_record.get("resource_arn", "")
            if arn and isinstance(arn, str) and arn.startswith("arn:"):
                return arn

        # 2. arn_entity dot-path from resource_inventory_identifier
        info = self.get_resource_info(csp, service, resource_type)
        if info:
            arn_entity = info.get("arn_entity", "")
            if arn_entity:
                arn = self._extract_by_arn_entity(arn_entity, service, emitted_fields)
                if arn:
                    return arn

        # 3. Well-known ARN field names (flat + one level deep)
        arn = self._extract_standard_arn_fields(emitted_fields)
        if arn:
            return arn

        # 4. resource_uid fallback
        if discovery_record:
            uid = discovery_record.get("resource_uid", "")
            if uid and isinstance(uid, str):
                return uid

        return None

    def _extract_by_arn_entity(
        self,
        arn_entity: str,
        service: str,
        emitted_fields: Dict[str, Any],
    ) -> Optional[str]:
        """
        Navigate emitted_fields using the arn_entity dot-path.

        arn_entity format: "{entity_service}.{field_snake}"
        e.g. "appsync.graphql_api_arn"

        Strategies (in order):
          a. emitted_fields[entity_service][field_snake]
          b. emitted_fields[entity_service][CamelCase(field_snake)]
          c. emitted_fields[CamelCase(field_snake)]   (flat, CamelCase)
          d. emitted_fields[field_snake]              (flat, snake_case)
          e. One-level deep search in all nested dicts
        """
        if "." not in arn_entity:
            return None

        entity_service, field_snake = arn_entity.split(".", 1)
        field_camel = self._to_camel(field_snake)

        # a/b. Nested under service key
        for svc_key in (entity_service, service):
            nested = emitted_fields.get(svc_key)
            if isinstance(nested, dict):
                val = nested.get(field_snake) or nested.get(field_camel)
                if isinstance(val, str) and val:
                    return val

        # c. Flat CamelCase
        val = emitted_fields.get(field_camel)
        if isinstance(val, str) and val:
            return val

        # d. Flat snake_case
        val = emitted_fields.get(field_snake)
        if isinstance(val, str) and val:
            return val

        # e. One-level deep scan (skip private keys)
        for key, nested in emitted_fields.items():
            if key.startswith("_") or not isinstance(nested, dict):
                continue
            val = nested.get(field_camel) or nested.get(field_snake)
            if isinstance(val, str) and val.startswith("arn:"):
                return val

        return None

    @staticmethod
    def _extract_standard_arn_fields(emitted_fields: Dict[str, Any]) -> Optional[str]:
        """
        Try well-known ARN field names in emitted_fields (flat + one level deep).
        Covers common patterns across all CSPs.
        """
        _ARN_FIELDS = (
            "Arn", "ARN", "arn", "resource_arn",
            "BucketArn", "FunctionArn", "TopicArn", "CertificateArn",
            "PolicyArn", "QueueArn", "StreamArn", "TableArn",
            "ClusterArn", "DBClusterArn", "DBInstanceArn",
            "LoadBalancerArn", "TargetGroupArn",
            "ExecutionArn", "StateMachineArn",
            "GraphqlApiArn", "ApiArn",
        )

        for field in _ARN_FIELDS:
            val = emitted_fields.get(field)
            if isinstance(val, str) and val.startswith("arn:"):
                return val

        for key, nested in emitted_fields.items():
            if key.startswith("_") or not isinstance(nested, dict):
                continue
            for field in _ARN_FIELDS:
                val = nested.get(field)
                if isinstance(val, str) and val.startswith("arn:"):
                    return val

        return None

    # ─── Dependency chain inspection ─────────────────────────────────────────

    def get_enrich_ops(
        self, csp: str, service: str, resource_type: str
    ) -> List[Dict[str, Any]]:
        """
        Return the enrichment operations for a resource_type from the DB catalog.

        Each op dict has:
          {
            "operation":      "ListSourceApiAssociations",
            "independent":    false,
            "required_params": ["apiId"],
            "python_method":  "list_source_api_associations"
          }
        """
        info = self.get_resource_info(csp, service, resource_type)
        if not info:
            return []
        return info.get("inventory_enrich", {}).get("ops", [])

    def get_root_ops(
        self, csp: str, service: str, resource_type: str
    ) -> List[Dict[str, Any]]:
        """Return root/independent ops for a resource_type from the DB catalog."""
        info = self.get_resource_info(csp, service, resource_type)
        if not info:
            return []
        return info.get("inventory", {}).get("ops", [])

    def list_services(self, csp: str) -> List[str]:
        """
        Return all services that have catalog rows in resource_inventory_identifier
        for the given CSP. Queries the DB directly.
        """
        conn = self._get_db_conn()
        if not conn:
            return []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT service
                    FROM   resource_inventory_identifier
                    WHERE  csp = %s
                    ORDER  BY service
                    """,
                    (csp,),
                )
                return [row[0] for row in cur.fetchall()]
        except Exception as exc:
            logger.warning(f"ResourceCatalogLoader.list_services({csp}): {exc}")
            return []
        finally:
            conn.close()
