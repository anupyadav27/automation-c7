"""
Service Metadata Loader
Loads CSV-enhanced service metadata from RDS database at startup
Provides pattern-based ARN/ID generation and resource classifications
"""

import psycopg2
import json
import os
from typing import Dict, List, Optional
from dataclasses import dataclass
from functools import lru_cache


@dataclass
class ServiceMetadata:
    """Service metadata from database"""
    service_id: str
    csp_id: str
    service_name: str
    resource_types: List[str]
    independent_methods: List[str]
    dependent_methods: List[str]
    data_quality: str
    primary_identifier_pattern: Optional[str]
    resource_identifier_type: str


@dataclass
class ResourceInventoryMetadata:
    """Resource classification metadata"""
    resource_type: str
    classification: str
    should_inventory: bool
    has_arn: bool
    root_operations: List[str]
    dependent_operations: List[str]


class ServiceMetadataLoader:
    """
    Loads CSV-enhanced service metadata from RDS database
    Used by inventory engine for pattern-based ARN generation and classifications
    """

    def __init__(self, db_connection=None, db_config=None):
        """
        Initialize metadata loader

        Args:
            db_connection: Existing database connection (optional)
            db_config: Dict with host, port, database, user, password (optional)
        """
        if db_connection:
            self.db = db_connection
            self.own_connection = False
        elif db_config:
            self.db = psycopg2.connect(**db_config)
            self.own_connection = True
        else:
            # Try to connect using environment variables or default config
            self.db = self._create_default_connection()
            self.own_connection = True

        self.cursor = self.db.cursor()
        self._services_cache = {}
        self._inventory_cache = {}
        self._load_all_services()

    def _create_default_connection(self):
        """Create database connection using environment variables"""
        # Use environment variables or hardcoded RDS Mumbai credentials
        host = os.getenv('PYTHONSDK_DB_HOST', 'postgres-vulnerability-db.cbm92xowvx2t.ap-south-1.rds.amazonaws.com')
        port = int(os.getenv('PYTHONSDK_DB_PORT', '5432'))
        database = os.getenv('PYTHONSDK_DB_NAME', 'threat_engine_pythonsdk')
        user = os.getenv('PYTHONSDK_DB_USER', 'postgres')
        password = os.getenv('PYTHONSDK_DB_PASSWORD', 'jtv2BkJF8qoFtAKP')

        return psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )

    def _load_all_services(self):
        """Load all services from database at startup"""
        query = """
        SELECT
            service_id, csp_id, service_name, resource_types,
            independent_methods, dependent_methods, data_quality,
            primary_arn_pattern, primary_resource_id_pattern,
            resource_identifier_type
        FROM services
        WHERE (independent_methods IS NOT NULL AND ARRAY_LENGTH(independent_methods, 1) > 0)
           OR (dependent_methods IS NOT NULL AND ARRAY_LENGTH(dependent_methods, 1) > 0)
        """

        self.cursor.execute(query)

        for row in self.cursor.fetchall():
            # Determine which pattern column to use
            identifier_pattern = row[7] if row[7] else row[8]  # ARN or resource_id pattern

            service = ServiceMetadata(
                service_id=row[0],
                csp_id=row[1],
                service_name=row[2],
                resource_types=row[3] or [],
                independent_methods=row[4] or [],
                dependent_methods=row[5] or [],
                data_quality=row[6] or 'basic',
                primary_identifier_pattern=identifier_pattern,
                resource_identifier_type=row[9] or 'arn'
            )
            self._services_cache[service.service_id] = service

        print(f"✅ ServiceMetadataLoader: Loaded {len(self._services_cache)} services from database")

    @lru_cache(maxsize=1000)
    def get_service_metadata(self, csp: str, service_name: str) -> Optional[ServiceMetadata]:
        """
        Get service metadata by CSP and service name

        Args:
            csp: Cloud provider (aws, azure, gcp, etc.)
            service_name: Service name (s3, ec2, storage, etc.)

        Returns:
            ServiceMetadata object or None if not found
        """
        service_id = f"{csp}.{service_name}"
        return self._services_cache.get(service_id)

    @lru_cache(maxsize=2000)
    def get_identifier_pattern(self, csp: str, service_name: str) -> Optional[str]:
        """
        Get ARN/ID pattern for service

        Args:
            csp: Cloud provider
            service_name: Service name

        Returns:
            Pattern string (e.g., "arn:aws:s3:::${BucketName}") or None
        """
        metadata = self.get_service_metadata(csp, service_name)
        return metadata.primary_identifier_pattern if metadata else None

    @lru_cache(maxsize=2000)
    def get_resource_types(self, csp: str, service_name: str) -> List[str]:
        """Get resource types for service"""
        metadata = self.get_service_metadata(csp, service_name)
        return metadata.resource_types if metadata else []

    @lru_cache(maxsize=2000)
    def get_independent_operations(self, csp: str, service_name: str) -> List[str]:
        """
        Get independent (discovery) operations for service

        These are operations that can discover resources without needing other data

        Returns:
            List of operation names (e.g., ['list_buckets', 'list_directory_buckets'])
        """
        metadata = self.get_service_metadata(csp, service_name)
        return metadata.independent_methods if metadata else []

    @lru_cache(maxsize=2000)
    def get_dependent_operations(self, csp: str, service_name: str) -> List[str]:
        """
        Get dependent (enrichment) operations for service

        These operations enrich discovered resources with additional details

        Returns:
            List of operation names (e.g., ['get_bucket_acl', 'get_bucket_encryption', ...])
        """
        metadata = self.get_service_metadata(csp, service_name)
        return metadata.dependent_methods if metadata else []

    def get_inventory_classification(self, csp: str, service_name: str, resource_type: str) -> Optional[str]:
        """
        Get resource classification from inventory data

        Args:
            csp: Cloud provider
            service_name: Service name
            resource_type: Resource type (e.g., 'instance', 'bucket')

        Returns:
            Classification string:
                - PRIMARY_RESOURCE: Should be inventoried
                - SUB_RESOURCE: Only for enrichment
                - EPHEMERAL: Skip (changes too often)
                - CONFIGURATION: Only for enrichment
        """
        service_id = f"{csp}.{service_name}"

        # Check cache
        cache_key = f"{service_id}.{resource_type}"
        if cache_key in self._inventory_cache:
            return self._inventory_cache[cache_key]

        # Query database
        query = """
        SELECT inventory_data
        FROM resource_inventory
        WHERE service_id = %s
        """

        self.cursor.execute(query, (service_id,))
        row = self.cursor.fetchone()

        if row and row[0]:
            try:
                # Handle both JSON string and dict
                inventory_data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                resources = inventory_data.get('resources', [])

                for resource in resources:
                    if resource.get('resource_type') == resource_type:
                        classification = resource.get('classification')
                        self._inventory_cache[cache_key] = classification
                        return classification
            except Exception as e:
                print(f"⚠️  Error parsing inventory data for {service_id}: {e}")

        return None

    def should_inventory_resource(self, csp: str, service_name: str, resource_type: str) -> bool:
        """
        Determine if resource should be inventoried

        Args:
            csp: Cloud provider
            service_name: Service name
            resource_type: Resource type

        Returns:
            True if should create inventory item, False otherwise

        Decision logic:
            - PRIMARY_RESOURCE: True (always inventory)
            - SUB_RESOURCE: False (only for enrichment)
            - EPHEMERAL: False (skip)
            - CONFIGURATION: False (only for enrichment)
        """
        classification = self.get_inventory_classification(csp, service_name, resource_type)

        # PRIMARY_RESOURCE: Always inventory
        # SUB_RESOURCE: Only for enrichment
        # EPHEMERAL: Skip
        # CONFIGURATION: Only for enrichment

        return classification == 'PRIMARY_RESOURCE'

    def get_all_services_for_csp(self, csp: str) -> List[ServiceMetadata]:
        """Get all services for a specific CSP"""
        return [s for s in self._services_cache.values() if s.csp_id == csp]

    def get_statistics(self) -> Dict[str, any]:
        """Get loader statistics"""
        stats = {
            'total_services': len(self._services_cache),
            'by_csp': {},
            'with_discovery': 0,
            'with_enrichment': 0
        }

        for service in self._services_cache.values():
            # Count by CSP
            if service.csp_id not in stats['by_csp']:
                stats['by_csp'][service.csp_id] = 0
            stats['by_csp'][service.csp_id] += 1

            # Count services with operations
            if service.independent_methods:
                stats['with_discovery'] += 1
            if service.dependent_methods:
                stats['with_enrichment'] += 1

        return stats

    def close(self):
        """Close database connection if we own it"""
        if self.own_connection:
            if self.cursor:
                self.cursor.close()
            if self.db:
                self.db.close()


# Singleton instance for global use
_global_loader = None


def get_metadata_loader(db_connection=None, db_config=None) -> ServiceMetadataLoader:
    """
    Get global metadata loader instance (creates if needed)

    Args:
        db_connection: Optional database connection
        db_config: Optional database config dict

    Returns:
        ServiceMetadataLoader instance
    """
    global _global_loader

    if _global_loader is None:
        _global_loader = ServiceMetadataLoader(db_connection, db_config)

    return _global_loader
