"""
Drift Detector

Compares current scan with previous scan to detect changes.

=== DATABASE & TABLE MAP ===
Database: None — pure comparison logic (no direct DB access).

Input:  List[Asset] + List[Relationship] for current and previous scans
        (loaded by orchestrator from DiscoveryDBReader / InventoryDBLoader)
Output: List[DriftRecord] — ASSET_ADDED, ASSET_REMOVED, ASSET_CHANGED,
                             EDGE_ADDED, EDGE_REMOVED change records

Tables READ:  None (receives data from callers)
Tables WRITTEN: None (returns DriftRecord objects; persistence handled by orchestrator
                       writing to drift.ndjson or future inventory_drift table)
===
"""

import logging
from typing import List, Dict, Any, Optional, Set

from ..schemas.asset_schema import Asset
from ..schemas.relationship_schema import Relationship
from ..schemas.drift_schema import DriftRecord, ChangeType

logger = logging.getLogger(__name__)

# Keys inside metadata that change every scan (timestamps, transient IDs).
# Differences in these keys are noise — skip them so we surface real drift.
_METADATA_IGNORE_KEYS: Set[str] = {
    "first_seen_at", "created_at", "discovery_id", "emitted_fields",
    "enriched_from", "raw_refs", "last_scanned",
}


class DriftDetector:
    """Detects changes between scan runs."""

    def __init__(self, tenant_id: str, current_scan_id: str):
        self.tenant_id = tenant_id
        self.current_scan_id = current_scan_id

    def detect_drift(
        self,
        current_assets: List[Asset],
        current_relationships: List[Relationship],
        previous_assets: Optional[List[Asset]] = None,
        previous_relationships: Optional[List[Relationship]] = None,
    ) -> List[DriftRecord]:
        """Detect drift between current and previous scan.

        Returns:
            List of drift records with resource_type and provider populated.
        """
        drift_records: List[DriftRecord] = []

        if not previous_assets:
            # First scan — all assets are new
            for asset in current_assets:
                drift_records.append(DriftRecord(
                    tenant_id=self.tenant_id,
                    scan_run_id=self.current_scan_id,
                    change_type=ChangeType.ASSET_ADDED,
                    resource_uid=asset.resource_uid,
                    resource_type=asset.resource_type,
                    provider=asset.provider.value if hasattr(asset.provider, 'value') else str(asset.provider),
                    diff=self._build_identity_snapshot(asset),
                ))
            return drift_records

        # Build lookup maps
        current_by_uid = {a.resource_uid: a for a in current_assets}
        previous_by_uid = {a.resource_uid: a for a in previous_assets}

        current_hashes = {uid: a.hash_sha256 for uid, a in current_by_uid.items()}
        previous_hashes = {uid: a.hash_sha256 for uid, a in previous_by_uid.items()}

        # Detect asset changes
        all_uids = set(current_by_uid.keys()) | set(previous_by_uid.keys())

        for uid in all_uids:
            if uid not in previous_by_uid:
                asset = current_by_uid[uid]
                drift_records.append(DriftRecord(
                    tenant_id=self.tenant_id,
                    scan_run_id=self.current_scan_id,
                    change_type=ChangeType.ASSET_ADDED,
                    resource_uid=uid,
                    resource_type=asset.resource_type,
                    provider=asset.provider.value if hasattr(asset.provider, 'value') else str(asset.provider),
                    diff=self._build_identity_snapshot(asset),
                ))
            elif uid not in current_by_uid:
                asset = previous_by_uid[uid]
                drift_records.append(DriftRecord(
                    tenant_id=self.tenant_id,
                    scan_run_id=self.current_scan_id,
                    change_type=ChangeType.ASSET_REMOVED,
                    resource_uid=uid,
                    resource_type=asset.resource_type,
                    provider=asset.provider.value if hasattr(asset.provider, 'value') else str(asset.provider),
                    diff=self._build_identity_snapshot(asset),
                ))
            elif current_hashes.get(uid) != previous_hashes.get(uid):
                prev_asset = previous_by_uid[uid]
                curr_asset = current_by_uid[uid]
                diff = self._compute_asset_diff(prev_asset, curr_asset)
                drift_records.append(DriftRecord(
                    tenant_id=self.tenant_id,
                    scan_run_id=self.current_scan_id,
                    change_type=ChangeType.ASSET_CHANGED,
                    resource_uid=uid,
                    diff=diff,
                    resource_type=curr_asset.resource_type,
                    provider=curr_asset.provider.value if hasattr(curr_asset.provider, 'value') else str(curr_asset.provider),
                ))

        # Detect relationship changes
        if previous_relationships:
            current_edges = self._build_edge_set(current_relationships)
            previous_edges = self._build_edge_set(previous_relationships)

            for edge in current_edges - previous_edges:
                drift_records.append(DriftRecord(
                    tenant_id=self.tenant_id,
                    scan_run_id=self.current_scan_id,
                    change_type=ChangeType.EDGE_ADDED,
                    resource_uid=edge,
                ))

            for edge in previous_edges - current_edges:
                drift_records.append(DriftRecord(
                    tenant_id=self.tenant_id,
                    scan_run_id=self.current_scan_id,
                    change_type=ChangeType.EDGE_REMOVED,
                    resource_uid=edge,
                ))

        return drift_records

    # ── Field-level diff helpers ──────────────────────────────────────

    @staticmethod
    def _diff_dicts(
        prev: Dict[str, Any],
        curr: Dict[str, Any],
        prefix: str,
        ignore_keys: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Recursively diff two dicts and return a list of field changes.

        Each entry: {"path": "prefix.key", "before": <val>, "after": <val>}
        Recurses one level into nested dicts for useful context without bloat.
        """
        changes: List[Dict[str, Any]] = []
        ign = ignore_keys or set()
        all_keys = set(prev.keys()) | set(curr.keys())

        for key in sorted(all_keys):
            if key in ign:
                continue
            path = f"{prefix}.{key}" if prefix else key
            prev_val = prev.get(key)
            curr_val = curr.get(key)
            if prev_val == curr_val:
                continue

            # One-level recursion for nested dicts
            if isinstance(prev_val, dict) and isinstance(curr_val, dict):
                changes.extend(
                    DriftDetector._diff_dicts(prev_val, curr_val, path)
                )
            else:
                changes.append({
                    "path": path,
                    "before": prev_val,
                    "after": curr_val,
                })
        return changes

    def _compute_asset_diff(self, previous: Asset, current: Asset) -> Dict[str, Any]:
        """Compute field-level diff between two asset versions.

        Compares name, tags and metadata key-by-key, filtering out noisy
        scan-transient fields (timestamps, discovery IDs).
        """
        diff: List[Dict[str, Any]] = []

        # Name change (e.g. tag-derived name update)
        prev_name = previous.name or previous.resource_id or ""
        curr_name = current.name or current.resource_id or ""
        if prev_name != curr_name:
            diff.append({"path": "name", "before": prev_name, "after": curr_name})

        # Tags — full key-level diff
        if previous.tags != current.tags:
            diff.extend(self._diff_dicts(
                previous.tags or {}, current.tags or {}, "tags",
            ))

        # Metadata — key-level diff, ignoring scan-transient keys
        if previous.metadata != current.metadata:
            diff.extend(self._diff_dicts(
                previous.metadata or {}, current.metadata or {}, "metadata",
                ignore_keys=_METADATA_IGNORE_KEYS,
            ))

        # If hash changed but no individual field diffs survived filtering,
        # emit a generic entry that at least identifies the resource so the
        # drift is still visible in the timeline.
        if not diff:
            diff.append({
                "path": "cloud_configuration",
                "before": None,
                "after": "Properties updated (hash changed)",
                "context": {
                    "name": curr_name,
                    "resource_type": current.resource_type,
                    "region": current.region,
                },
            })

        return {"changes": diff}

    @staticmethod
    def _build_identity_snapshot(asset: Asset) -> Dict[str, Any]:
        """Build a lightweight identity snapshot for ASSET_ADDED / ASSET_REMOVED records.

        Captures the key descriptive fields so the drift timeline can show
        what was added or removed rather than generic placeholder text.
        """
        return {
            "snapshot": {
                "name": asset.name or asset.resource_id or asset.resource_uid,
                "resource_type": asset.resource_type,
                "region": asset.region or "",
                "account_id": asset.account_id or "",
            }
        }

    def _build_edge_set(self, relationships: List[Relationship]) -> set:
        """Build set of edge identifiers."""
        edges = set()
        for rel in relationships:
            edge_id = f"{rel.from_uid}|{rel.to_uid}|{rel.relation_type.value}"
            edges.add(edge_id)
        return edges

