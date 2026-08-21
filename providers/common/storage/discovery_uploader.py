"""
Discovery Uploader — bulk upload scan results to discovery_findings after scan completes.

Separates scanning (AWS API calls) from storage (DB writes) so the scanner
semaphore is never held during DB writes.  This fixes the hang where 800
concurrent DB writes saturated the connection pool and blocked asyncio.

Usage:
    uploader = DiscoveryUploader(db_manager)
    count = uploader.upload_scan_results(
        scan_id=scan_id,
        customer_id=customer_id,
        tenant_id=tenant_id,
        provider='aws',
        account_id=account_id,
        hierarchy_type='account',
        results=all_results,   # {(service, region): [(item, discovery_id), ...]}
    )
"""

import logging
import time
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Discovery IDs that return catalog/pricing data, not actual customer resources.
CATALOG_DISCOVERY_IDS = {
    'aws.ec2.describe_instance_type_offerings',
    'aws.ec2.describe_reserved_instances_offerings',
    'aws.ec2.describe_spot_price_history',
    'aws.ec2.describe_fpga_images',
    'aws.ec2.get_vpn_connection_device_types',
    'aws.ec2.describe_id_format',
    'aws.ec2.describe_aggregate_id_format',
    'aws.savingsplans.describe_savings_plans_offerings',
    'aws.savingsplans.describe_savings_plans_offering_rates',
    'aws.gamelift.describe_ec2_instance_limits',
}


class DiscoveryUploader:
    """Bulk uploads discovery scan results to PostgreSQL after all scanning is done."""

    def __init__(self, db_manager):
        """
        Args:
            db_manager: DatabaseManager instance with store_discoveries_batch().
        """
        self.db = db_manager

    def upload_scan_results(
        self,
        scan_id: str,
        customer_id: str,
        tenant_id: str,
        provider: str,
        account_id: str,
        hierarchy_type: str,
        results: Dict[Tuple[str, str], List[Dict[str, Any]]],
    ) -> int:
        """
        Bulk upload all collected scan results to discovery_findings.

        Args:
            scan_id: The scan_run_id for this pipeline run.
            customer_id: Customer identifier.
            tenant_id: Tenant identifier.
            provider: Cloud provider ('aws', 'azure', 'gcp').
            account_id: Cloud account identifier.
            hierarchy_type: Account hierarchy type.
            results: Dict mapping (service, region) → list of item dicts.
                     Each item may contain '_discovery_id' key.

        Returns:
            Total number of rows written.
        """
        upload_start = time.time()
        total_items = sum(len(items) for items in results.values())
        total_uploaded = 0
        total_skipped = 0
        total_keys = len(results)

        logger.info(
            f"[UPLOADER] Starting upload: {total_items} items from "
            f"{total_keys} service-region pairs for scan {scan_id}"
        )

        for idx, ((service, region), items) in enumerate(results.items(), 1):
            if not items:
                continue

            # Group items by discovery_id (same logic as old run_one)
            by_discovery: Dict[str, List[Dict]] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                did = item.pop('_discovery_id', service)
                if did in CATALOG_DISCOVERY_IDS:
                    total_skipped += 1
                    continue
                by_discovery.setdefault(did, []).append(item)

            group_count = 0
            for did, group_items in by_discovery.items():
                written = self._store_with_retry(
                    scan_id=scan_id,
                    customer_id=customer_id,
                    tenant_id=tenant_id,
                    provider=provider,
                    discovery_id=did,
                    items=group_items,
                    account_id=account_id,
                    hierarchy_type=hierarchy_type,
                    region=region,
                    service=service,
                )
                group_count += written

            total_uploaded += group_count

            # Progress every 25 service-regions or when items found
            if group_count > 0 or idx % 25 == 0 or idx == total_keys:
                elapsed = time.time() - upload_start
                logger.info(
                    f"[UPLOADER] [{idx}/{total_keys}] {service}/{region}: "
                    f"{group_count} items | cumulative={total_uploaded}/{total_items} "
                    f"| {elapsed:.1f}s"
                )

        elapsed = time.time() - upload_start
        failed = total_items - total_uploaded - total_skipped
        msg = (
            f"[UPLOADER] Upload complete: {total_uploaded} items "
            f"in {elapsed:.1f}s ({total_keys} service-region pairs)"
        )
        if total_skipped > 0:
            msg += f" | {total_skipped} catalog items skipped"
        if failed > 0:
            msg += f" | {failed} items FAILED"
        logger.info(msg)
        return total_uploaded

    def _store_with_retry(
        self,
        scan_id: str,
        customer_id: str,
        tenant_id: str,
        provider: str,
        discovery_id: str,
        items: list,
        account_id: str,
        hierarchy_type: str,
        region: str,
        service: str,
        max_retries: int = 3,
    ) -> int:
        """Write one discovery group to DB with retries on failure.

        Returns:
            Number of items successfully written (0 if all retries failed).
        """
        for attempt in range(1, max_retries + 1):
            try:
                self.db.store_discoveries_batch(
                    scan_id=scan_id,
                    customer_id=customer_id,
                    tenant_id=tenant_id,
                    provider=provider,
                    discovery_id=discovery_id,
                    items=items,
                    account_id=account_id,
                    hierarchy_type=hierarchy_type,
                    region=region,
                    service=service,
                )
                return len(items)
            except Exception as e:
                if attempt < max_retries:
                    wait = attempt * 2  # 2s, 4s backoff
                    logger.warning(
                        f"[UPLOADER] Retry {attempt}/{max_retries} for "
                        f"{discovery_id}/{region} ({len(items)} items): {e} "
                        f"— waiting {wait}s"
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        f"[UPLOADER] FAILED after {max_retries} attempts: "
                        f"{discovery_id}/{region} ({len(items)} items): {e}"
                    )
        return 0
