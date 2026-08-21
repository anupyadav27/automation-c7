"""
Relationship Storage Layer
Handles persistence of discovered relationships to database
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid

from .discovery import DiscoveredRelationship

logger = logging.getLogger(__name__)


class RelationshipStorage:
    """
    Handles storage and retrieval of relationships
    """

    def __init__(self, db_connection):
        """
        Initialize relationship storage

        Args:
            db_connection: Database connection
        """
        self.db = db_connection

    def store_relationships(
        self,
        tenant_id: str,
        relationships: List[DiscoveredRelationship],
        batch_size: int = 1000
    ) -> int:
        """
        Store discovered relationships in database

        Args:
            tenant_id: Tenant UUID
            relationships: List of discovered relationships
            batch_size: Number of relationships to insert per batch

        Returns:
            Number of relationships stored
        """
        if not relationships:
            return 0

        stored_count = 0
        
        # Process in batches
        for i in range(0, len(relationships), batch_size):
            batch = relationships[i:i + batch_size]
            stored_count += self._store_batch(tenant_id, batch)

        logger.info(f"Stored {stored_count} relationships for tenant {tenant_id}")
        return stored_count

    def _store_batch(self, tenant_id: str, relationships: List[DiscoveredRelationship]) -> int:
        """Store a batch of relationships"""
        query = """
            INSERT INTO discovered_relationships 
            (tenant_id, source_uid, source_type, target_uid, target_type, 
             relation_type, confidence, metadata, template_id, discovered_at, last_verified)
            VALUES (%(tenant_id)s, %(source_uid)s, %(source_type)s, %(target_uid)s, 
                    %(target_type)s, %(relation_type)s, %(confidence)s, %(metadata)s::jsonb, 
                    %(template_id)s, %(discovered_at)s, %(last_verified)s)
            ON CONFLICT (tenant_id, source_uid, target_uid, relation_type) 
            DO UPDATE SET
                last_verified = EXCLUDED.last_verified,
                metadata = EXCLUDED.metadata,
                is_active = TRUE
            RETURNING id
        """

        now = datetime.now(timezone.utc)
        params = []

        for rel in relationships:
            params.append({
                'tenant_id': tenant_id,
                'source_uid': rel.source_uid,
                'source_type': rel.source_type,
                'target_uid': rel.target_uid,
                'target_type': rel.target_type,
                'relation_type': rel.relation_type,
                'confidence': rel.confidence,
                'metadata': rel.metadata or {},
                'template_id': rel.template_id,
                'discovered_at': now,
                'last_verified': now
            })

        try:
            cursor = self.db.cursor()
            cursor.executemany(query, params)
            self.db.commit()
            return cursor.rowcount
        except Exception as e:
            logger.error(f"Error storing relationship batch: {e}", exc_info=True)
            self.db.rollback()
            return 0

    def get_resource_relationships(
        self,
        tenant_id: str,
        resource_uid: str,
        relation_types: Optional[List[str]] = None,
        direction: str = 'both'  # 'outbound', 'inbound', 'both'
    ) -> List[Dict[str, Any]]:
        """
        Get all relationships for a specific resource

        Args:
            tenant_id: Tenant UUID
            resource_uid: Resource UID
            relation_types: Optional filter by relation types
            direction: Which direction to query

        Returns:
            List of relationships
        """
        conditions = ["tenant_id = %(tenant_id)s", "is_active = TRUE"]
        params = {'tenant_id': tenant_id, 'resource_uid': resource_uid}

        if direction == 'outbound':
            conditions.append("source_uid = %(resource_uid)s")
        elif direction == 'inbound':
            conditions.append("target_uid = %(resource_uid)s")
        else:  # both
            conditions.append("(source_uid = %(resource_uid)s OR target_uid = %(resource_uid)s)")

        if relation_types:
            conditions.append("relation_type = ANY(%(relation_types)s)")
            params['relation_types'] = relation_types

        query = f"""
            SELECT 
                id, source_uid, source_type, target_uid, target_type,
                relation_type, confidence, metadata, discovered_at, last_verified
            FROM discovered_relationships
            WHERE {' AND '.join(conditions)}
            ORDER BY discovered_at DESC
        """

        cursor = self.db.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

    def get_blast_radius(
        self,
        tenant_id: str,
        resource_uid: str,
        max_depth: int = 5,
        relation_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get blast radius - all resources connected within max_depth hops

        Args:
            tenant_id: Tenant UUID
            resource_uid: Starting resource UID
            max_depth: Maximum number of hops
            relation_types: Optional filter by relation types

        Returns:
            List of resources in blast radius with hop count
        """
        relation_filter = ""
        if relation_types:
            relation_filter = "AND dr.relation_type = ANY(%(relation_types)s)"

        query = f"""
            WITH RECURSIVE blast_radius AS (
                -- Start with direct relationships
                SELECT 
                    source_uid,
                    target_uid,
                    relation_type,
                    1 as hop,
                    ARRAY[source_uid, target_uid] as path
                FROM discovered_relationships dr
                WHERE tenant_id = %(tenant_id)s
                  AND source_uid = %(resource_uid)s
                  AND is_active = TRUE
                  {relation_filter}
                
                UNION ALL
                
                -- Recursive traversal
                SELECT 
                    dr.source_uid,
                    dr.target_uid,
                    dr.relation_type,
                    br.hop + 1,
                    br.path || dr.target_uid
                FROM discovered_relationships dr
                JOIN blast_radius br ON dr.source_uid = br.target_uid
                WHERE br.hop < %(max_depth)s
                  AND dr.tenant_id = %(tenant_id)s
                  AND dr.is_active = TRUE
                  AND NOT (dr.target_uid = ANY(br.path))  -- Prevent cycles
                  {relation_filter}
            )
            SELECT DISTINCT 
                target_uid as resource_uid,
                relation_type,
                MIN(hop) as min_hop
            FROM blast_radius
            GROUP BY target_uid, relation_type
            ORDER BY min_hop, target_uid
        """

        params = {
            'tenant_id': tenant_id,
            'resource_uid': resource_uid,
            'max_depth': max_depth
        }

        if relation_types:
            params['relation_types'] = relation_types

        cursor = self.db.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

    def find_attack_paths(
        self,
        tenant_id: str,
        source_resource_uid: str,
        target_resource_type: str,
        max_depth: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Find attack paths from source to target resources

        Args:
            tenant_id: Tenant UUID
            source_resource_uid: Starting resource
            target_resource_type: Target resource type pattern (e.g., 'rds.%')
            max_depth: Maximum path length

        Returns:
            List of paths with hop details
        """
        query = """
            WITH RECURSIVE attack_path AS (
                SELECT 
                    source_uid,
                    target_uid,
                    relation_type,
                    ARRAY[source_uid, target_uid] as path,
                    1 as depth
                FROM discovered_relationships
                WHERE tenant_id = %(tenant_id)s
                  AND source_uid = %(source_resource_uid)s
                  AND is_active = TRUE
                
                UNION ALL
                
                SELECT 
                    dr.source_uid,
                    dr.target_uid,
                    dr.relation_type,
                    ap.path || dr.target_uid,
                    ap.depth + 1
                FROM discovered_relationships dr
                JOIN attack_path ap ON dr.source_uid = ap.target_uid
                WHERE ap.depth < %(max_depth)s
                  AND dr.tenant_id = %(tenant_id)s
                  AND dr.is_active = TRUE
                  AND NOT (dr.target_uid = ANY(ap.path))
            )
            SELECT 
                path,
                depth,
                target_uid
            FROM attack_path
            WHERE target_uid LIKE %(target_pattern)s
            ORDER BY depth, path
            LIMIT 100
        """

        params = {
            'tenant_id': tenant_id,
            'source_resource_uid': source_resource_uid,
            'target_pattern': f"{target_resource_type}%",
            'max_depth': max_depth
        }

        cursor = self.db.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

    def cleanup_stale_relationships(
        self,
        tenant_id: str,
        cutoff_days: int = 7
    ) -> int:
        """
        Mark relationships as inactive if not verified recently

        Args:
            tenant_id: Tenant UUID
            cutoff_days: Days since last verification

        Returns:
            Number of relationships marked inactive
        """
        query = """
            UPDATE discovered_relationships
            SET is_active = FALSE
            WHERE tenant_id = %(tenant_id)s
              AND is_active = TRUE
              AND last_verified < NOW() - INTERVAL '%(cutoff_days)s days'
            RETURNING id
        """

        params = {
            'tenant_id': tenant_id,
            'cutoff_days': cutoff_days
        }

        try:
            cursor = self.db.cursor()
            cursor.execute(query, params)
            count = cursor.rowcount
            self.db.commit()
            logger.info(f"Marked {count} relationships as inactive for tenant {tenant_id}")
            return count
        except Exception as e:
            logger.error(f"Error cleaning up stale relationships: {e}")
            self.db.rollback()
            return 0

    def get_relationship_statistics(self, tenant_id: str) -> Dict[str, Any]:
        """
        Get statistics about relationships for a tenant

        Args:
            tenant_id: Tenant UUID

        Returns:
            Dictionary with statistics
        """
        query = """
            SELECT 
                COUNT(*) as total_relationships,
                COUNT(DISTINCT source_uid) as unique_sources,
                COUNT(DISTINCT target_uid) as unique_targets,
                COUNT(DISTINCT relation_type) as relation_type_count,
                COUNT(*) FILTER (WHERE confidence = 'explicit') as explicit_count,
                COUNT(*) FILTER (WHERE confidence = 'inferred') as inferred_count,
                COUNT(*) FILTER (WHERE is_active = TRUE) as active_count,
                COUNT(*) FILTER (WHERE is_active = FALSE) as inactive_count
            FROM discovered_relationships
            WHERE tenant_id = %(tenant_id)s
        """

        cursor = self.db.cursor()
        cursor.execute(query, {'tenant_id': tenant_id})
        result = cursor.fetchone()

        # Get relationship type breakdown
        type_query = """
            SELECT 
                relation_type,
                COUNT(*) as count
            FROM discovered_relationships
            WHERE tenant_id = %(tenant_id)s
              AND is_active = TRUE
            GROUP BY relation_type
            ORDER BY count DESC
        """

        cursor.execute(type_query, {'tenant_id': tenant_id})
        type_breakdown = cursor.fetchall()

        return {
            'total_relationships': result['total_relationships'],
            'unique_sources': result['unique_sources'],
            'unique_targets': result['unique_targets'],
            'relation_type_count': result['relation_type_count'],
            'explicit_count': result['explicit_count'],
            'inferred_count': result['inferred_count'],
            'active_count': result['active_count'],
            'inactive_count': result['inactive_count'],
            'type_breakdown': [dict(row) for row in type_breakdown]
        }
