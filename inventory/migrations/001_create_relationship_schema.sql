-- Migration: Create Relationship Schema for CSPM Platform
-- Version: 2.0
-- Date: 2026-01-23

-- ============================================================================
-- 1. RELATION TYPE DEFINITIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS relation_type_definitions (
    id VARCHAR(50) PRIMARY KEY,
    category VARCHAR(50) NOT NULL,
    direction VARCHAR(20) NOT NULL CHECK (direction IN ('inbound', 'outbound', 'bidirectional')),
    inverse VARCHAR(50),
    cardinality VARCHAR(20) NOT NULL CHECK (cardinality IN ('one-to-one', 'one-to-many', 'many-to-one', 'many-to-many')),
    description TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE relation_type_definitions IS 'Defines all possible relationship types in the CSPM system';

-- ============================================================================
-- 2. RESOURCE RELATIONSHIP TEMPLATES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS resource_relationship_templates (
    id SERIAL PRIMARY KEY,
    source_resource_type VARCHAR(100) NOT NULL,
    relation_type VARCHAR(50) NOT NULL REFERENCES relation_type_definitions(id),
    target_resource_type VARCHAR(100) NOT NULL,
    source_field JSONB NOT NULL,
    source_field_item VARCHAR(200),
    target_uid_pattern VARCHAR(500) NOT NULL,
    is_array BOOLEAN DEFAULT FALSE,
    conditional TEXT,
    priority INTEGER DEFAULT 100,
    enabled BOOLEAN DEFAULT TRUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT unique_template UNIQUE (source_resource_type, relation_type, target_resource_type, source_field)
);

CREATE INDEX idx_template_source_type ON resource_relationship_templates(source_resource_type) WHERE enabled = TRUE;
CREATE INDEX idx_template_relation_type ON resource_relationship_templates(relation_type);

-- ============================================================================
-- 3. DISCOVERED RELATIONSHIPS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS discovered_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    source_uid VARCHAR(500) NOT NULL,
    source_type VARCHAR(100) NOT NULL,
    target_uid VARCHAR(500) NOT NULL,
    target_type VARCHAR(100) NOT NULL,
    relation_type VARCHAR(50) NOT NULL REFERENCES relation_type_definitions(id),
    confidence VARCHAR(20) DEFAULT 'explicit' CHECK (confidence IN ('explicit', 'inferred', 'derived', 'user_defined')),
    metadata JSONB DEFAULT '{}',
    template_id INTEGER REFERENCES resource_relationship_templates(id),
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_verified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    
    CONSTRAINT unique_relationship UNIQUE (tenant_id, source_uid, target_uid, relation_type)
);

-- Critical indexes for graph traversal
CREATE INDEX idx_rel_tenant ON discovered_relationships(tenant_id) WHERE is_active = TRUE;
CREATE INDEX idx_rel_source ON discovered_relationships(tenant_id, source_uid) WHERE is_active = TRUE;
CREATE INDEX idx_rel_target ON discovered_relationships(tenant_id, target_uid) WHERE is_active = TRUE;
CREATE INDEX idx_rel_bidirectional ON discovered_relationships(tenant_id, relation_type, source_uid, target_uid) WHERE is_active = TRUE;

-- GIN index for metadata
CREATE INDEX idx_rel_metadata ON discovered_relationships USING GIN (metadata);

-- ============================================================================
-- 4. SEED DATA - RELATION TYPES
-- ============================================================================

INSERT INTO relation_type_definitions (id, category, direction, inverse, cardinality, description) VALUES
('contained_by', 'network', 'outbound', 'contains', 'many-to-one', 'Resource is contained within another'),
('connected_to', 'network', 'bidirectional', 'connected_to', 'many-to-many', 'Network connectivity'),
('routes_to', 'network', 'outbound', 'routed_from', 'many-to-many', 'Traffic routing relationship'),
('attached_to', 'security', 'outbound', 'attached_on', 'many-to-many', 'Security attachment'),
('uses', 'identity', 'outbound', 'used_by', 'many-to-one', 'Resource uses another'),
('member_of', 'identity', 'outbound', 'has_member', 'many-to-many', 'Identity membership'),
('has_policy', 'identity', 'inbound', 'policy_attached_to', 'many-to-many', 'IAM policy attachment'),
('encrypted_by', 'data', 'outbound', 'encrypts', 'many-to-one', 'Resource encrypted by key'),
('backs_up_to', 'data', 'outbound', 'backup_of', 'one-to-many', 'Backup relationship'),
('replicates_to', 'data', 'outbound', 'replica_of', 'one-to-many', 'Data replication'),
('logging_enabled_to', 'monitoring', 'outbound', 'receives_logs_from', 'many-to-many', 'Logging destination'),
('monitored_by', 'monitoring', 'outbound', 'monitors', 'many-to-many', 'Monitoring relationship'),
('triggers', 'compute', 'outbound', 'triggered_by', 'many-to-many', 'Event triggering'),
('invokes', 'compute', 'outbound', 'invoked_by', 'many-to-many', 'Service invocation'),
('serves_traffic_for', 'compute', 'outbound', 'receives_traffic_from', 'one-to-many', 'Load balancing'),
('runs_on', 'compute', 'outbound', 'hosts', 'many-to-one', 'Workload hosting'),
('publishes_to', 'messaging', 'outbound', 'receives_from', 'many-to-many', 'Message publishing'),
('subscribes_to', 'messaging', 'outbound', 'subscribed_by', 'many-to-many', 'Message subscription'),
('exposed_through', 'exposure', 'outbound', 'exposes', 'many-to-many', 'External exposure'),
('internet_accessible', 'exposure', 'outbound', NULL, 'many-to-one', 'Internet exposure'),
('resolves_to', 'network', 'outbound', 'resolved_by', 'many-to-many', 'DNS resolution'),
('depends_on', 'dependency', 'outbound', 'dependency_of', 'many-to-many', 'Generic dependency')
ON CONFLICT (id) DO NOTHING;
