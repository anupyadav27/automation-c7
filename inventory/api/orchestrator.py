"""
Scan Orchestrator

Orchestrates inventory scan execution: collection → normalization → graph → index

=== DATABASE & TABLE MAP ===
This module reads from TWO upstream databases and writes to ONE downstream database:

READS FROM:
  1. threat_engine_discoveries (DISCOVERIES DB) — via get_discovery_reader()
     Tables: discovery_report   → get_latest_scan_id()
             discovery_findings  → read_discovery_records(scan_id) — yields one dict per resource

WRITES TO:
  3. threat_engine_inventory (INVENTORY DB) — via PostgresIndexWriter(db_url)
     Tables: inventory_report        → write_scan_summary(ScanSummary)
             inventory_findings      → write_asset_index(assets)  — UPSERT per asset
             inventory_relationships → write_relationship_index(relationships)

LOCAL FILE OUTPUT (optional):
  Path: INVENTORY_OUTPUT_DIR/{tenant_id}/{scan_run_id}/normalized/
  Files: assets.ndjson, relationships.ndjson, summary.json, drift.ndjson

=== STEP5 CATALOG INTEGRATION ===
The orchestrator uses ResourceCatalogLoader to enhance the two-pass scan:

  Pass 1 (root records → create assets):
    - Classifies operations as root/dependent using catalog "independent" flag
    - Extracts ARN from emitted_fields using catalog "arn_entity" dot-path when
      resource_arn column is missing in discovery_findings
    - Resolves resource_type per discovery operation from catalog catalog

  Pass 2 (dependent records → enrich assets):
    - Uses catalog "inventory_enrich.ops" to understand the dependency chain
    - Matches enrichment records to existing assets by resource_uid/ARN

  Catalog files: {DATA_PYTHONSDK_PATH}/{csp}/{service}/step5_resource_catalog_inventory_enrich.json
  Fallback: catalog is optional — if catalog missing, original heuristic classifier is used.
===
"""

import os
import json
import uuid as _uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

from ..schemas.asset_schema import Asset, Provider, Scope, compute_asset_hash
from ..schemas.relationship_schema import Relationship
from ..schemas.summary_schema import ScanSummary
from ..schemas.drift_schema import DriftRecord
from ..connectors.discovery_reader_factory import get_discovery_reader
from ..connectors.resource_catalog_loader import ResourceCatalogLoader
from ..normalizer.asset_normalizer import AssetNormalizer
from ..normalizer.relationship_builder import RelationshipBuilder
from ..drift.drift_detector import DriftDetector
from ..index.index_writer import PostgresIndexWriter


class ScanOrchestrator:
    """Orchestrates inventory scan execution (DB-first)."""
    
    def __init__(
        self,
        tenant_id: str,
        db_url: Optional[str] = None,
    ):
        """
        Initialize Scan Orchestrator.
        
        Args:
            tenant_id: Tenant identifier
            db_url: PostgreSQL database URL (required for DB-first indexing)
        """
        self.tenant_id = tenant_id
        self.db_url = db_url
        # DB-first only: no direct cloud API calls (AWSConnector) and no S3 (boto3).

        # Catalog catalog loader for ARN extraction and op classification
        # Passes db_url so it reuses the same inventory DB connection config;
        # falls back to INVENTORY_DB_* env vars when db_url is None.
        self.catalog = ResourceCatalogLoader(db_url=db_url)

        # Relationship rules are loaded from the inventory DB at scan time —
        # no startup sync needed (rules live in resource_security_relationship_rules table).
    
    def run_scan(
        self,
        providers: List[str],
        accounts: List[str],
        regions: List[str],
        services: Optional[List[str]] = None,
        previous_scan_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run inventory scan (DB-first only).

        This engine no longer calls cloud provider APIs. It derives assets/relationships
        from providers stored in the Discoveries DB.
        
        Returns:
            Scan result with scan_run_id and artifact paths
        """
        return self.run_scan_from_discovery(
            discovery_scan_id="latest",
            providers=providers,
            accounts=accounts,
            previous_scan_id=previous_scan_id,
        )
    
    def _save_artifacts(
        self,
        scan_run_id: str,
        assets: List[Asset],
        relationships: List[Relationship],
        drift_records: List[DriftRecord],
        raw_refs: List[str],
        started_at: datetime,
        completed_at: datetime
    ) -> Dict[str, str]:
        """Save normalized artifacts"""
        artifacts = {}
        # DB-first only: write artifacts locally (optional), never to S3.
        from providers.common.storage_paths import get_project_root
        base = os.getenv("INVENTORY_OUTPUT_DIR") or str(get_project_root() / "engine_output" / "engine_inventory" / "output")
        base_path = base
        normalized_dir = os.path.join(base_path, self.tenant_id, scan_run_id, "normalized")
        os.makedirs(normalized_dir, exist_ok=True)
        
        # Save assets.ndjson
        assets_path = os.path.join(normalized_dir, "assets.ndjson")
        with open(assets_path, 'w') as f:
            for asset in assets:
                f.write(json.dumps(asset.dict(), default=str) + "\n")
        artifacts["assets"] = assets_path
        
        # Save relationships.ndjson
        rels_path = os.path.join(normalized_dir, "relationships.ndjson")
        with open(rels_path, 'w') as f:
            for rel in relationships:
                f.write(json.dumps(rel.dict(), default=str) + "\n")
        artifacts["relationships"] = rels_path
        
        # Save summary.json
        summary = self._generate_summary(scan_run_id, assets, relationships, raw_refs, started_at, completed_at)
        summary_path = os.path.join(normalized_dir, "summary.json")
        with open(summary_path, 'w') as f:
            json.dump(summary.dict(), f, default=str)
        artifacts["summary"] = summary_path
        
        # Save drift.ndjson
        if drift_records:
            drift_path = os.path.join(normalized_dir, "drift.ndjson")
            with open(drift_path, 'w') as f:
                for drift in drift_records:
                    f.write(json.dumps(drift.dict(), default=str) + "\n")
            artifacts["drift"] = drift_path
        
        return artifacts
    
    def _generate_summary(
        self,
        scan_run_id: str,
        assets: List[Asset],
        relationships: List[Relationship],
        raw_refs: List[str],
        started_at: datetime,
        completed_at: datetime
    ) -> ScanSummary:
        """Generate scan summary"""
        from ..schemas.summary_schema import ScanSummary
        
        # Count by provider
        assets_by_provider = {}
        for asset in assets:
            provider = asset.provider.value
            assets_by_provider[provider] = assets_by_provider.get(provider, 0) + 1
        
        # Count by resource type
        assets_by_resource_type = {}
        for asset in assets:
            rtype = asset.resource_type
            assets_by_resource_type[rtype] = assets_by_resource_type.get(rtype, 0) + 1
        
        # Count by region
        assets_by_region = {}
        for asset in assets:
            region = asset.region
            assets_by_region[region] = assets_by_region.get(region, 0) + 1
        
        # Extract unique providers, accounts, regions
        providers_scanned = list(set(asset.provider.value for asset in assets))
        accounts_scanned = list(set(asset.account_id for asset in assets))
        regions_scanned = list(set(asset.region for asset in assets))
        
        return ScanSummary(
            scan_run_id=scan_run_id,
            tenant_id=self.tenant_id,
            started_at=started_at,
            completed_at=completed_at,
            status="completed",
            total_assets=len(assets),
            total_relationships=len(relationships),
            assets_by_provider=assets_by_provider,
            assets_by_resource_type=assets_by_resource_type,
            assets_by_region=assets_by_region,
            providers_scanned=providers_scanned,
            accounts_scanned=accounts_scanned,
            regions_scanned=regions_scanned,
            errors_count=0,
            raw_refs=raw_refs
        )
    
    def _load_previous_scan(self, previous_scan_id: str) -> tuple[List[Asset], List[Relationship]]:
        """
        Load previous scan assets and relationships from inventory DB.

        Uses inventory_scan_data (historical snapshots per scan) instead of
        inventory_findings (which only holds the latest scan_run_id and gets
        overwritten on every UPSERT, making old scan IDs unfindable).
        Falls back to inventory_findings if no snapshot rows exist.
        """
        if not self.db_url:
            logger.warning("Cannot load previous scan: no inventory DB URL configured")
            return [], []

        assets: List[Asset] = []
        relationships: List[Relationship] = []

        try:
            import psycopg2
            import psycopg2.extras

            conn = psycopg2.connect(self.db_url)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    # ── Load assets from scan snapshots (preferred) ──────────────
                    cur.execute(
                        """
                        SELECT resource_uid, provider, account_id, region,
                               resource_type, resource_id, name,
                               tags, labels, properties, configuration,
                               inventory_scan_id AS latest_scan_run_id
                        FROM   inventory_scan_data
                        WHERE  tenant_id = %s
                          AND  inventory_scan_id = %s
                        """,
                        (self.tenant_id, previous_scan_id),
                    )
                    rows = cur.fetchall()

                    # Fallback: if no snapshot rows, try inventory_findings
                    if not rows:
                        logger.debug(
                            f"No snapshot rows for scan {previous_scan_id}, "
                            f"falling back to inventory_findings"
                        )
                        cur.execute(
                            """
                            SELECT resource_uid, provider, account_id, region,
                                   resource_type, resource_id, name,
                                   tags, labels, properties, configuration,
                                   latest_scan_run_id
                            FROM   inventory_findings
                            WHERE  tenant_id = %s
                              AND  latest_scan_run_id = %s
                            """,
                            (self.tenant_id, previous_scan_id),
                        )
                        rows = cur.fetchall()

                    for row in rows:
                        try:
                            def _as_dict(v):
                                if v is None:
                                    return {}
                                return v if isinstance(v, dict) else json.loads(v)

                            metadata: Dict[str, Any] = {}
                            metadata["configuration"] = _as_dict(row["configuration"])
                            metadata["labels"] = _as_dict(row["labels"])
                            metadata.update(_as_dict(row["properties"]))

                            tags = _as_dict(row["tags"])

                            region = row["region"] or "global"
                            scope = Scope.GLOBAL if region in ("", "global", None) else Scope.REGIONAL

                            asset = Asset(
                                tenant_id=self.tenant_id,
                                scan_run_id=row["latest_scan_run_id"],
                                provider=Provider(row["provider"]),
                                account_id=row["account_id"] or "",
                                region=region,
                                scope=scope,
                                resource_type=row["resource_type"] or "unknown",
                                resource_id=row["resource_id"] or "",
                                resource_uid=row["resource_uid"],
                                name=row["name"] or "",
                                tags=tags,
                                metadata=metadata,
                                hash_sha256="",  # placeholder before compute
                            )
                            asset.hash_sha256 = compute_asset_hash(asset)
                            assets.append(asset)
                        except Exception as row_err:
                            logger.debug(f"Skipped previous asset row: {row_err}")

                    # ── Load relationships ────────────────────────────────────────
                    cur.execute(
                        """
                        SELECT from_uid, to_uid, relation_type,
                               provider, account_id, region, properties
                        FROM   inventory_relationships
                        WHERE  tenant_id = %s
                          AND  scan_run_id = %s
                        """,
                        (self.tenant_id, previous_scan_id),
                    )
                    for row in cur.fetchall():
                        try:
                            props = row["properties"] or {}
                            if isinstance(props, str):
                                props = json.loads(props)

                            rel = Relationship(
                                tenant_id=self.tenant_id,
                                scan_run_id=previous_scan_id,
                                provider=Provider(row["provider"]),
                                account_id=row["account_id"] or "",
                                region=row["region"] or "global",
                                relation_type=row["relation_type"],
                                from_uid=row["from_uid"],
                                to_uid=row["to_uid"],
                                properties=props,
                            )
                            relationships.append(rel)
                        except Exception as row_err:
                            logger.debug(f"Skipped previous relationship row: {row_err}")
            finally:
                conn.close()

        except Exception as exc:
            logger.warning(f"Failed to load previous scan {previous_scan_id}: {exc}")

        logger.info(
            f"Loaded previous scan {previous_scan_id}: "
            f"{len(assets)} assets, {len(relationships)} relationships"
        )
        return assets, relationships
    
    def _classify_record(
        self,
        discovery_record: Dict[str, Any],
        csp: str,
    ) -> tuple:
        """
        Classify a discovery record using catalog catalog.

        Returns:
            (should_inventory: bool,
             is_root: bool | None,   ← None means "catalog has no info, use heuristic classifier"
             resource_type: str | None,
             arn: str | None)
        """
        service = discovery_record.get("service", "")
        discovery_id = discovery_record.get("discovery_id", "")
        # Pass the full discovery_id for matching. The catalog loader handles both:
        #   - Full GCP paths: "gcp.compute.instances.aggregatedList"
        #   - AWS-style short names: "describe_instances" (last segment matched internally)
        op_name = discovery_id

        emitted_fields = discovery_record.get("emitted_fields", {})
        if not isinstance(emitted_fields, dict):
            emitted_fields = {}

        # Resolve resource_type from catalog
        resource_type = self.catalog.get_resource_type_for_operation(csp, service, op_name)

        # Determine root vs dependent from catalog "independent" flag.
        # Returns None when the operation is not found in the catalog (unknown service).
        is_root: Optional[bool] = self.catalog.is_root_operation(csp, service, op_name)

        # Determine should_inventory and parent from catalog resource info.
        # ACTION_ENDPOINT (should_inventory=False) with a known parent_resource_type
        # should still enrich the parent in Pass 2 — only skip when there is no parent
        # (pure utility/write ops with no enrichment value).
        should_inventory = True
        action_endpoint_with_parent = False
        if resource_type:
            info = self.catalog.get_resource_info(csp, service, resource_type)
            if info is not None:
                should_inventory = info.get("should_inventory", True)
                if not should_inventory and info.get("parent_resource_type"):
                    # Has a parent → route to Pass 2 enrichment instead of skipping
                    action_endpoint_with_parent = True
                    should_inventory = True  # allow through the filter below

        # Extract ARN using catalog arn_entity if resource_arn column is missing
        arn = None
        if resource_type:
            arn = self.catalog.extract_arn(
                csp, service, resource_type, emitted_fields, discovery_record
            )

        # Note: is_root may be None — callers must handle the None case
        return should_inventory, is_root, resource_type, arn, action_endpoint_with_parent

    @staticmethod
    def _match_op_name(candidate: str, stored: str) -> bool:
        """Quick operation name match (last segment comparison)."""
        if not candidate or not stored:
            return False
        import re
        def snake(s):
            s1 = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', s)
            return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        c_last = snake(candidate.split(".")[-1])
        s_last = snake(stored.split(".")[-1])
        return c_last == s_last or snake(candidate) == snake(stored)

    @staticmethod
    def _find_parent_by_param_sources(
        discovery_record: Dict[str, Any],
        param_sources: Dict[str, Any],
        assets_by_resource_type: Dict[str, List],
    ):
        """
        Find the parent asset for an enrichment record using param_sources.

        For each required_param in param_sources:
          1. Extract the param's value from discovery_record (from_field)
          2. Find assets of parent_resource_type
          3. Match assets where asset.<from_asset_field> == param_value

        Returns the matching Asset or None.
        """
        emitted = discovery_record.get("emitted_fields") or {}
        if not isinstance(emitted, dict):
            emitted = {}

        for param_name, source in param_sources.items():
            if not isinstance(source, dict):
                continue

            parent_rt = source.get("parent_resource_type")
            from_field = source.get("from_field", "resource_id")
            from_asset_field = source.get("from_asset_field", "resource_id")

            if not parent_rt:
                continue

            # Extract the param value from the discovery record
            param_value = (
                discovery_record.get(from_field)
                or emitted.get(param_name)          # direct field name match
                or emitted.get(from_field)           # field alias
            )
            if not param_value or not isinstance(param_value, str):
                continue

            # Search parent assets of the right resource_type
            for asset in assets_by_resource_type.get(parent_rt, []):
                asset_value = (
                    getattr(asset, from_asset_field, None)
                    or getattr(asset, "resource_id", None)
                    or asset.resource_uid
                )
                if asset_value and str(asset_value) == str(param_value):
                    return asset

        return None

    def run_scan_from_discovery(
        self,
        discovery_scan_id: str,
        check_scan_id: Optional[str] = None,
        providers: Optional[List[str]] = None,
        accounts: Optional[List[str]] = None,
        previous_scan_id: Optional[str] = None,
        scan_run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run inventory scan from discovery output (DB-first, two-pass).

        Two-pass approach:
          Pass 1 — Root discoveries (independent ops like list_buckets, list_roles):
                   Create primary Asset records. Root records carry _dependent_data
                   with all enrichment already embedded.
                   Catalog catalog provides: root classification, ARN extraction via
                   arn_entity, resource_type resolution.

          Pass 2 — Dependent discoveries (get_bucket_versioning, list_source_api_associations, etc.):
                   Merge their operation-specific data into existing assets'
                   metadata.configuration. Catalog inventory_enrich.ops define
                   the dependency chain and required_params for each operation.

        Args:
            discovery_scan_id: Discovery scan ID (or "latest")
            check_scan_id: Optional check scan ID for posture enrichment
            providers: Optional filter by providers
            accounts: Optional filter by accounts
            previous_scan_id: Optional previous scan for drift detection
            scan_run_id: Optional scan ID (from orchestration). Auto-generated if not provided.

        Returns:
            Scan result with scan_run_id and artifact paths
        """
        from ..normalizer.resource_classifier import InventoryDecision

        scan_run_id = scan_run_id or str(_uuid.uuid4())
        started_at = datetime.now(timezone.utc)

        discovery_reader = get_discovery_reader(tenant_id=self.tenant_id)
        reader_account_id: Optional[str] = accounts[0] if accounts and len(accounts) == 1 else None
        reader_account_ids: Optional[List[str]] = accounts if accounts and len(accounts) > 1 else None

        # ═══════════════════════════════════════════════════════════════
        # Catalog-driven two-pass resource extraction
        # ═══════════════════════════════════════════════════════════════
        normalizer = AssetNormalizer(self.tenant_id, scan_run_id)

        root_records = []
        enrichment_records = []
        filtered_count = 0

        for discovery_record in discovery_reader.read_discovery_records(
            discovery_scan_id,
            account_id=reader_account_id,
            account_ids=reader_account_ids,
        ):
            provider_str = discovery_record.get("provider", "aws").lower()
            account_id = discovery_record.get("account_id")
            if not account_id:
                account_id = discovery_record.get("account_id", "")
                discovery_record["account_id"] = account_id

            # Apply provider / account filters
            if providers and provider_str not in providers:
                continue
            if accounts and account_id not in accounts:
                continue

            # ── Classification using Catalog catalog (primary) ──
            should_inventory, is_root, resource_type, catalog_arn, action_endpoint_with_parent = self._classify_record(
                discovery_record, csp=provider_str
            )

            if not should_inventory:
                filtered_count += 1
                continue

            # If catalog extracted a better ARN, inject it into the record for the normalizer
            if catalog_arn and not discovery_record.get("resource_arn"):
                # Work on a copy so we don't mutate the DB row dict
                discovery_record = dict(discovery_record)
                discovery_record["resource_arn"] = catalog_arn
                logger.debug(
                    f"Catalog ARN extracted for {provider_str}.{discovery_record.get('service')}"
                    f".{resource_type}: {catalog_arn}"
                )

            # ACTION_ENDPOINT with a parent: force enrichment-only routing.
            # These are read ops (GetBucketAnalyticsConfiguration etc.) whose data
            # should be merged into the parent Asset's configuration — never a
            # separate Asset of their own.
            if action_endpoint_with_parent:
                enrichment_records.append(discovery_record)
                continue

            # is_root is None when catalog has no catalog for this service/op.
            # Fall back to the full heuristic classifier in that case.
            if is_root is None:
                decision = normalizer.classifier.classify_discovery_record(discovery_record)
                if decision == InventoryDecision.FILTER:
                    filtered_count += 1
                    continue
                if decision == InventoryDecision.ENRICHMENT_ONLY:
                    # Heuristic index says enrichment-only, but pythonsdk may know better.
                    # Independent operations (no required params) ARE root even if the
                    # classification index doesn't list them — e.g. describe_instances.
                    pythonsdk_root = normalizer.classifier.is_root_operation(discovery_record)
                    is_root = pythonsdk_root  # True = independent op → Pass 1
                else:
                    is_root = normalizer.classifier.is_root_operation(discovery_record)

            service = discovery_record.get("service", "")

            if is_root:
                root_records.append(discovery_record)
            else:
                # Dependent ops always feed enrichment.
                # If the resource_type has can_inventory_from_roots=false (only reachable via
                # dependent ops), we also add it to root_records so it becomes an Asset.
                if resource_type and not self.catalog.can_inventory_from_roots(
                    provider_str, service, resource_type
                ):
                    root_records.append(discovery_record)
                enrichment_records.append(discovery_record)

        logger.info(
            f"[{scan_run_id}] Classification: {len(root_records)} root, "
            f"{len(enrichment_records)} enrichment, {filtered_count} filtered "
            f"(scan_id={discovery_scan_id})"
        )

        # ── Pass 1: Create assets from root discoveries ──
        all_assets: List[Asset] = []
        raw_refs: List[str] = []
        assets_by_uid: Dict[str, Asset] = {}  # For enrichment lookup in Pass 2

        for discovery_record in root_records:
            raw_ref = (
                f"discovery:{discovery_scan_id}:"
                f"{discovery_record.get('discovery_id', 'unknown')}"
            )
            asset = normalizer.normalize_from_discovery(
                discovery_record, raw_ref, skip_classification=True
            )
            if not asset:
                continue

            uid = asset.resource_uid
            if uid in assets_by_uid:
                # Duplicate UID from multiple root records for the same resource
                # (e.g. same bucket returned by both list_buckets and get_bucket for
                #  different CSP regions, or overlapping discovery ops).
                # Merge configurations from both records — never discard either side.
                existing = assets_by_uid[uid]
                existing_cfg = (existing.metadata or {}).get("configuration", {})
                new_cfg = (asset.metadata or {}).get("configuration", {})

                if not existing.metadata:
                    existing.metadata = {}

                # Smart merge: non-empty values win; existing wins when both non-empty
                def _smart_merge(base: dict, overlay: dict) -> dict:
                    merged = {}
                    for k in set(base) | set(overlay):
                        bv, ov = base.get(k), overlay.get(k)
                        if bv not in (None, "", {}, []):
                            merged[k] = bv
                        elif ov not in (None, "", {}, []):
                            merged[k] = ov
                        else:
                            merged[k] = bv
                    return merged

                existing.metadata["configuration"] = _smart_merge(existing_cfg, new_cfg)

                # Merge emitted_fields — critical for relationships.
                # e.g. describe_instances carries IamInstanceProfile/SubnetId while
                # describe_instance_image_metadata may have None for these fields.
                # Non-empty values win; existing non-empty takes priority over new non-empty.
                existing_ef = existing.metadata.get("emitted_fields", {})
                new_ef = (asset.metadata or {}).get("emitted_fields", {})
                if new_ef and isinstance(new_ef, dict) and isinstance(existing_ef, dict):
                    existing.metadata["emitted_fields"] = _smart_merge(existing_ef, new_ef)

                # Also merge tags — new record may carry additional tags
                if asset.tags:
                    existing.tags = {**asset.tags, **existing.tags}
            else:
                all_assets.append(asset)
                assets_by_uid[uid] = asset
                raw_refs.append(raw_ref)

        logger.info(
            f"[{scan_run_id}] Pass 1: {len(all_assets)} unique assets from root discoveries"
        )

        # ── Pass 2: Enrich existing assets with dependent discoveries ──
        #
        # Matching strategy (in order):
        #   1. Direct resource_uid match — discovery engine preserved parent's uid
        #   2. param_sources match — use the enrich op's param_sources to find the
        #      parent asset by matching the required_param value against parent fields
        #      (handles cases where resource_uid was not propagated correctly)
        enriched_count = 0
        param_match_count = 0
        unmatched_by_service: Dict[str, int] = {}

        # Build a lookup index for param_sources matching:
        # {resource_type: {field_value: asset}} for fast lookups
        assets_by_resource_type: Dict[str, List] = {}
        for asset in all_assets:
            rt = asset.resource_type or "unknown"
            assets_by_resource_type.setdefault(rt, []).append(asset)

        for discovery_record in enrichment_records:
            # ── Strategy 1: Direct resource_uid match ──
            target_uid = normalizer.extract_enrichment_uid(discovery_record)
            if target_uid and target_uid in assets_by_uid:
                normalizer.enrich_asset(assets_by_uid[target_uid], discovery_record)
                enriched_count += 1
                continue

            # ── Strategy 2: param_sources match ──
            # Use the catalog catalog's param_sources to find the parent asset
            # by matching required_param values against parent asset fields.
            csp_str = discovery_record.get("provider", "aws").lower()
            svc = discovery_record.get("service", "unknown")
            op = discovery_record.get("discovery_id", "")
            matched = False

            resource_type_for_op = self.catalog.get_resource_type_for_operation(csp_str, svc, op)
            if resource_type_for_op:
                enrich_ops = self.catalog.get_enrich_ops(csp_str, svc, resource_type_for_op)
                for enrich_op in enrich_ops:
                    if not self._match_op_name(op, enrich_op.get("operation", "")):
                        continue
                    param_sources = enrich_op.get("param_sources", {})
                    if not param_sources:
                        break

                    # Try to find the parent asset using param_sources
                    parent_asset = self._find_parent_by_param_sources(
                        discovery_record, param_sources, assets_by_resource_type
                    )
                    if parent_asset:
                        normalizer.enrich_asset(parent_asset, discovery_record)
                        enriched_count += 1
                        param_match_count += 1
                        matched = True
                        break

            if not matched:
                unmatched_by_service[svc] = unmatched_by_service.get(svc, 0) + 1

        logger.info(
            f"[{scan_run_id}] Pass 2: enriched {enriched_count} asset records "
            f"({param_match_count} via param_sources fallback) "
            f"from {len(enrichment_records)} dependent discoveries"
        )
        if unmatched_by_service:
            unmatched_total = sum(unmatched_by_service.values())
            logger.warning(
                f"[{scan_run_id}] Pass 2: {unmatched_total} enrichment records had no "
                f"matching root asset. Breakdown by service: {unmatched_by_service}. "
                f"Check that the discovery engine called parent ops before dependent ops."
            )

        # NOTE: Check posture enrichment was removed — it was dead code in
        # pipeline flow (inventory = Stage 2, check = Stage 3) and has been
        # moved to the BFF layer where it runs at query time via HTTP fan-out.

        # Step 2: Build relationships per CSP using DB-driven rules from
        # resource_security_relationship_rules (inventory DB). One shared connection is
        # opened here and passed to each RelationshipBuilder instance so we
        # avoid reconnecting for every CSP.
        all_relationships: List[Relationship] = []
        assets_by_csp: Dict[str, List[Asset]] = {}
        for asset in all_assets:
            csp_key = asset.provider.value
            assets_by_csp.setdefault(csp_key, []).append(asset)

        _rel_conn = None
        try:
            if self.db_url:
                import psycopg2
                _rel_conn = psycopg2.connect(self.db_url)
        except Exception as _e:
            logger.warning(f"[{scan_run_id}] Could not open inventory DB for relationship rules: {_e}")

        for csp_key, csp_assets in assets_by_csp.items():
            try:
                rb = RelationshipBuilder(
                    self.tenant_id, scan_run_id,
                    csp_id=csp_key, db_conn=_rel_conn,
                )
                csp_rels = rb.build_relationships(csp_assets)
                all_relationships.extend(csp_rels)
                logger.info(
                    f"[{scan_run_id}] Relationships built for {csp_key}: "
                    f"{len(csp_assets)} assets → {len(csp_rels)} edges"
                )
            except Exception as rel_err:
                logger.warning(f"[{scan_run_id}] Relationship build failed for {csp_key}: {rel_err}")

        if _rel_conn:
            try:
                _rel_conn.close()
            except Exception:
                pass

        # Step 3: Detect drift
        # Auto-resolve previous_scan_id if not provided — look for the latest
        # completed scan in inventory_report so drift runs automatically.
        drift_records = []
        effective_prev_scan = previous_scan_id
        if not effective_prev_scan and self.db_url:
            try:
                import psycopg2 as _pg
                _drift_conn = _pg.connect(self.db_url)
                with _drift_conn.cursor() as _cur:
                    _cur.execute(
                        "SELECT scan_run_id FROM inventory_report "
                        "WHERE tenant_id = %s AND status = 'completed' "
                        "ORDER BY completed_at DESC LIMIT 1",
                        (self.tenant_id,),
                    )
                    _row = _cur.fetchone()
                    if _row:
                        effective_prev_scan = _row[0]
                _drift_conn.close()
            except Exception as exc:
                logger.warning(f"Auto-resolve previous_scan_id failed: {exc}")

        if effective_prev_scan and effective_prev_scan != scan_run_id:
            logger.info(f"Drift detection: comparing against previous scan {effective_prev_scan}")
            previous_assets, previous_relationships = self._load_previous_scan(effective_prev_scan)
            drift_detector = DriftDetector(self.tenant_id, scan_run_id)
            drift_records = drift_detector.detect_drift(
                all_assets, all_relationships,
                previous_assets, previous_relationships
            )

        # Step 4: Save normalized artifacts
        completed_at = datetime.now(timezone.utc)
        artifact_paths = self._save_artifacts(
            scan_run_id, all_assets, all_relationships, drift_records, raw_refs, started_at, completed_at
        )

        # Step 5: Write indexes (DB-first output)
        if self.db_url:
            summary = self._generate_summary(
                scan_run_id, all_assets, all_relationships, raw_refs, started_at, completed_at
            )
            index_writer = PostgresIndexWriter(self.db_url)
            index_writer.write_scan_summary(summary)
            index_writer.write_asset_index(all_assets)
            index_writer.write_relationship_index(all_relationships)

            # Step 5b: Write scan snapshot (historical retention — keeps 5 scans)
            try:
                index_writer.write_scan_snapshot(all_assets)
            except Exception as exc:
                logger.warning(f"Failed to write scan snapshot: {exc}")

            # Step 5c: Write drift records to inventory_drift table
            if drift_records and effective_prev_scan:
                try:
                    index_writer.write_drift_index(
                        drift_records, scan_run_id, effective_prev_scan, self.tenant_id
                    )
                except Exception as exc:
                    logger.warning(f"Failed to write drift index: {exc}")

            # Step 5d: Purge old scan data (keep only 5 most recent)
            try:
                index_writer.purge_old_scans(self.tenant_id, keep_count=5)
            except Exception as exc:
                logger.warning(f"Failed to purge old scans: {exc}")

        return {
            "scan_run_id": scan_run_id,
            "status": "completed",
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "total_assets": len(all_assets),
            "total_relationships": len(all_relationships),
            "total_drift": len(drift_records),
            "artifact_paths": artifact_paths
        }

