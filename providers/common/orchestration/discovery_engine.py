"""
Common Discovery Engine - CSP-Agnostic Orchestration Layer

Scan-then-upload model:
  1. Enumerate all (service, region) pairs upfront
  2. Pre-load all discovery configs in one batch DB call
  3. Scan all pairs via single asyncio.Semaphore — NO DB writes during scan
  4. After all scans complete, bulk upload results via DiscoveryUploader

This layer is 100% CSP-agnostic. All provider-specific logic is delegated
to the scanner implementation via the DiscoveryScanner interface.
"""

import asyncio
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import logging

def _project_root() -> Path:
    # providers/common/orchestration/ → repo root is three levels up
    return Path(__file__).resolve().parent.parent.parent.parent


from providers.common.database.database_manager import DatabaseManager
from providers.common.database.check_db_reader import CheckDBReader
from providers.common.storage.discovery_uploader import DiscoveryUploader
from providers.common.utils.phase_logger import PhaseLogger
from providers.common.utils.progressive_output import ProgressiveOutputWriter
from providers.common.models.provider_interface import DiscoveryScanner, DiscoveryError
from providers.common.utils.database_feature_manager import DatabaseFeatureManager

logger = logging.getLogger(__name__)

# AWS services that return identical data across all regions.
AWS_GLOBAL_SERVICES = {
    'controlcatalog', 'savingsplans', 'ce', 'cur',
    'gamelift', 'outposts', 'osis',
    'iam', 'organizations', 'sts', 'route53', 'cloudfront',
    'waf', 'wafv2', 'shield', 'globalaccelerator',
    'importexport', 'support', 'trustedadvisor',
}

PRIMARY_REGIONS = {
    'aws': 'us-east-1', 'azure': 'eastus', 'gcp': 'us-central1',
    'oci': 'us-ashburn-1', 'alicloud': 'cn-hangzhou',
    'ibm': 'us-south', 'k8s': 'cluster',
}

DEFAULT_REGIONS = {
    'aws': ['us-east-1', 'us-west-2', 'eu-west-1'],
    'azure': ['eastus', 'westus2', 'westeurope'],
    'gcp': ['us-central1', 'us-east1', 'europe-west1'],
    'oci': ['us-ashburn-1', 'us-phoenix-1'],
    'alicloud': ['cn-hangzhou', 'cn-shanghai'],
    'ibm': ['us-south', 'us-east', 'eu-de'],
    'k8s': ['cluster'],
}


class DiscoveryEngine:
    """
    CSP-Agnostic Discovery Engine — flat-scheduling model.

    All (service, region) pairs compete for a single concurrency pool.
    No nested semaphores — eliminates head-of-line blocking.
    """

    def __init__(
        self,
        scanner: DiscoveryScanner,
        db_manager: DatabaseManager = None,
        use_database: Optional[bool] = None,
    ):
        self.scanner = scanner
        self.db = db_manager
        self.use_database = self._determine_mode(use_database)

        provider = getattr(scanner, 'provider', 'aws')
        self.feature_manager = DatabaseFeatureManager(provider=provider)
        self.phase_logger = None
        self.output_writer = None

        self.config_source = os.getenv('DISCOVERY_CONFIG_SOURCE', 'database').lower()
        self.check_db_reader = None
        if self.config_source in ('database', 'db', 'yaml_first'):
            try:
                self.check_db_reader = CheckDBReader()
                if self.check_db_reader.check_connection():
                    logger.info(f"CheckDBReader initialized (config_source={self.config_source})")
                else:
                    logger.warning("CheckDBReader connection failed, will use YAML only")
                    self.check_db_reader = None
            except Exception as e:
                logger.warning(f"Failed to initialize CheckDBReader: {e}")
                self.check_db_reader = None

        if self.use_database and not self.db:
            raise ValueError("DatabaseManager required when using database mode")

    def _determine_mode(self, use_database: Optional[bool]) -> bool:
        if use_database is not None:
            return use_database
        env_mode = os.getenv('DISCOVERY_MODE', '').lower()
        if env_mode in ('database', 'db', 'production'):
            return True
        elif env_mode in ('file', 'local', 'ndjson'):
            return False
        if self.db:
            try:
                conn = self.db._get_connection()
                self.db._return_connection(conn)
                return True
            except Exception:
                logger.warning("Database connection failed, using file-only mode")
                return False
        return False

    # ── Main entry point ────────────────────────────────────────────────

    async def run_scan(self, metadata: Dict[str, Any]) -> str:
        """
        Scan-then-upload discovery scan.

        Phase 1 — SCAN: All (service, region) pairs run through a single
        asyncio.Semaphore.  Results are collected in memory.  NO DB writes
        happen during this phase, so the semaphore is released as soon as
        the AWS API call finishes.

        Phase 2 — UPLOAD: After all scans complete, DiscoveryUploader
        writes results to discovery_findings sequentially.  No concurrency
        pressure on the DB connection pool.
        """
        scan_id = metadata['scan_run_id']
        provider = metadata['provider']
        customer_id = metadata.get('customer_id', 'default')
        tenant_id = metadata.get('tenant_id', 'default-tenant')
        account_id = metadata['account_id']
        hierarchy_type = metadata.get('hierarchy_type', 'account')
        include_services = metadata.get('include_services')
        include_regions = metadata.get('include_regions')
        exclude_regions = metadata.get('exclude_regions') or []

        max_concurrent = int(os.getenv('MAX_CONCURRENT_TASKS', '400'))

        # Setup logging
        output_base = os.getenv("OUTPUT_DIR")
        if output_base:
            base_output_dir = Path(output_base)
        else:
            base_output_dir = _project_root() / "engine_output" / f"engine_discoveries_{provider}" / "output"
        output_dir = base_output_dir / "discoveries" / scan_id
        self.phase_logger = PhaseLogger(scan_id, 'discovery', output_dir)
        self.output_writer = ProgressiveOutputWriter(scan_id, output_dir, 'discovery')

        self.phase_logger.info(f"Starting discovery scan: {scan_id}")
        self.phase_logger.info(f"  Provider: {provider}, Hierarchy: {account_id}")

        # ── Step 1: Batch-load all service configs ──────────────────────
        all_configs = self._get_all_configs(provider, include_services)
        if not all_configs:
            self.phase_logger.warning("No services with discovery enabled")
            return scan_id

        services = list(all_configs.keys())
        self.phase_logger.info(f"  Services loaded: {len(services)}")

        # ── Step 1b: Determine which services need dependent discoveries ──
        # Services with check rules need full discovery (independent + dependent).
        # Services without check rules only need independent (asset inventory).
        check_services = self._get_check_services(provider)
        full_scan_count = sum(1 for s in services if s in check_services)
        asset_only_count = len(services) - full_scan_count
        self.phase_logger.info(
            f"  Full scan (with dependents): {full_scan_count} services | "
            f"Asset-only (independent only): {asset_only_count} services"
        )

        # Create scan record
        if self.use_database and self.db:
            self.db.create_scan(
                scan_id=scan_id,
                customer_id=customer_id,
                tenant_id=tenant_id,
                provider=provider,
                account_id=account_id,
                hierarchy_type=hierarchy_type,
            )

        account_id = getattr(self.scanner, 'account_id', None) or account_id

        # ── Step 2: Resolve regions ─────────────────────────────────────
        if include_regions:
            scan_regions = [r for r in include_regions if r not in exclude_regions]
        else:
            scan_regions = await self._discover_available_regions(provider, exclude_regions)
        self.phase_logger.info(f"  Regions: {len(scan_regions)} → {scan_regions}")

        # ── Step 3: Build flat (service, region) work items ─────────────
        primary_region = PRIMARY_REGIONS.get(provider, 'us-east-1')
        work_items: List[Tuple[str, str]] = []
        for service in services:
            config = all_configs[service]
            scope = config.get('scope', 'regional')
            if provider == 'aws' and service in AWS_GLOBAL_SERVICES:
                scope = 'global'
            if scope == 'global':
                work_items.append((service, primary_region))
            else:
                for region in scan_regions:
                    work_items.append((service, region))

        total_tasks = len(work_items)
        self.phase_logger.info(
            f"  Work items: {total_tasks} (flat pool, max_concurrent={max_concurrent})"
        )

        # ── Phase 1: SCAN — collect results in memory, NO DB writes ────
        # Dedicated thread pool for boto3 calls.  Python's default executor
        # has only min(32, cpu+4) threads — on a 2-CPU pod that's 6 threads,
        # far too few for 1000 concurrent service scans.
        # Cap threads at 100 — each thread uses ~8MB stack, so 100 threads
        # = ~800MB.  The async workers (max_concurrent) queue onto these threads.
        scan_threads = min(max_concurrent, int(os.getenv('SCAN_THREAD_POOL', '400')))
        scan_executor = ThreadPoolExecutor(
            max_workers=scan_threads,
            thread_name_prefix='disc-scan',
        )
        loop = asyncio.get_event_loop()
        loop.set_default_executor(scan_executor)

        sem = asyncio.Semaphore(max_concurrent)

        # Thread-safe collection of results: (service, region) → [items]
        all_results: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        results_lock = asyncio.Lock()

        completed = 0
        total_discoveries = 0
        scan_start = time.time()

        # Per-service timeout: if run_service_async hangs, don't block the
        # entire scan.  Default 120s should be plenty for any single service.
        service_timeout = int(os.getenv('SERVICE_SCAN_TIMEOUT', '120'))

        async def scan_one(service: str, region: str) -> int:
            """Scan a single service/region — NO DB writes."""
            nonlocal completed, total_discoveries
            async with sem:
                config = all_configs[service]
                items = []
                try:
                    # Create a task so we can abandon it on timeout instead
                    # of cancelling.  asyncio.wait_for() cancels the task,
                    # which can deadlock aioboto3's context-manager cleanup.
                    # Skip dependent discoveries for services without check rules
                    # (asset inventory only needs independent/primary discoveries).
                    # If check_services is empty (DB unavailable), run full for all.
                    needs_dependents = (not check_services) or (service in check_services)
                    task = asyncio.ensure_future(
                        self.scanner.scan_service(
                            service=service,
                            region=region,
                            config=config,
                            skip_dependents=not needs_dependents,
                        )
                    )
                    done, _ = await asyncio.wait(
                        {task}, timeout=service_timeout
                    )
                    if done:
                        result = task.result()
                        discoveries = result[0] if isinstance(result, tuple) else result
                        items = list(discoveries) if discoveries else []
                    else:
                        # Task didn't finish — abandon it (don't cancel, let it drain)
                        logger.warning(
                            f"Scan timed out ({service_timeout}s): {service}/{region} — abandoning"
                        )
                except Exception as e:
                    logger.error(f"Scan failed: {service}/{region}: {e}")
                    items = []

            # Semaphore released — store results in memory
            count = len(items)
            if items:
                async with results_lock:
                    all_results[(service, region)] = items

            completed += 1
            total_discoveries += count

            if count > 0 or completed % 50 == 0 or completed == total_tasks:
                elapsed = time.time() - scan_start
                self.phase_logger.info(
                    f"  [{completed}/{total_tasks}] {service}/{region}: "
                    f"{count} items | total={total_discoveries} | {elapsed:.0f}s"
                )

            return count

        # Process work items via a bounded worker pool.  Unlike
        # asyncio.gather(*[... for all 6134 items]), this only creates
        # max_concurrent tasks at a time, preventing aioboto3/aiohttp
        # from initialising thousands of sessions simultaneously and
        # freezing the event loop.
        work_queue: asyncio.Queue = asyncio.Queue()
        for item in work_items:
            work_queue.put_nowait(item)

        async def worker():
            while True:
                try:
                    svc, rgn = work_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                await scan_one(svc, rgn)

        await asyncio.gather(*[worker() for _ in range(max_concurrent)])

        scan_executor.shutdown(wait=False)

        scan_elapsed = time.time() - scan_start
        self.phase_logger.info(
            f"Phase 1 (scan) complete: {total_discoveries} discoveries "
            f"in {scan_elapsed:.0f}s ({total_tasks} tasks)"
        )

        # ── Phase 2: UPLOAD — sequential bulk write to DB ──────────────
        if all_results and self.use_database and self.db:
            self.phase_logger.info(
                f"Phase 2 (upload): writing {total_discoveries} discoveries "
                f"from {len(all_results)} service-region pairs"
            )
            uploader = DiscoveryUploader(self.db)
            uploaded = uploader.upload_scan_results(
                scan_id=scan_id,
                customer_id=customer_id,
                tenant_id=tenant_id,
                provider=provider,
                account_id=account_id,
                hierarchy_type=hierarchy_type,
                results=all_results,
            )
            self.phase_logger.info(f"Phase 2 (upload) complete: {uploaded} rows written")

        # Complete scan
        if self.use_database and self.db:
            self.db.update_scan_status(scan_id, 'completed')

        elapsed = time.time() - scan_start
        self.phase_logger.info(
            f"Discovery scan completed: {total_discoveries} discoveries "
            f"in {elapsed:.0f}s ({total_tasks} tasks, {max_concurrent} concurrent)"
        )

        return scan_id

    # ── Helpers ──────────────────────────────────────────────────────────

    def _get_all_configs(
        self, provider: str, include_services: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Batch-load all discovery configs from check DB in one query."""
        if not self.check_db_reader:
            logger.warning("CheckDBReader not available")
            return {}
        try:
            all_configs = self.check_db_reader.read_all_discoveries_configs(provider=provider)
            if include_services:
                all_configs = {k: v for k, v in all_configs.items() if k in include_services}
            return all_configs
        except Exception as e:
            logger.error(f"Failed to load discovery configs: {e}")
            return {}

    def _get_check_services(self, provider: str) -> set:
        """Return set of services that have check rules in rule_metadata.

        Services in this set need full discovery (independent + dependent).
        Services NOT in this set only need independent discoveries (asset inventory).
        """
        if not self.check_db_reader:
            # Can't determine — assume all need full scan
            logger.warning("CheckDBReader unavailable, running full scan for all services")
            return set()
        try:
            return self.check_db_reader.get_check_services(provider=provider)
        except Exception as e:
            logger.warning(f"Failed to load check services: {e} — running full scan for all")
            return set()

    async def _discover_available_regions(
        self, provider: str, exclude_regions: List[str] = None
    ) -> List[str]:
        """Pre-scan: enumerate enabled regions from cloud API."""
        try:
            regions = await self.scanner.list_available_regions()
        except Exception as e:
            logger.warning(f"list_available_regions() failed: {e}")
            regions = []

        if not regions:
            regions = DEFAULT_REGIONS.get(provider, ['us-east-1'])
            logger.info(f"Using default regions for {provider}: {regions}")

        if exclude_regions:
            regions = [r for r in regions if r not in exclude_regions]

        return regions
