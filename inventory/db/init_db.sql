-- Consolidated Schema for threat_engine_inventory
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id VARCHAR(255) PRIMARY KEY,
    customer_id VARCHAR(255),
    provider VARCHAR(50),
    tenant_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Table used for scan summaries (referred to as inventory_report in code)
CREATE TABLE IF NOT EXISTS inventory_report (
    scan_run_id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50) NOT NULL,
    total_assets INTEGER NOT NULL DEFAULT 0,
    total_relationships INTEGER NOT NULL DEFAULT 0,
    assets_by_provider JSONB DEFAULT '{}',
    assets_by_resource_type JSONB DEFAULT '{}',
    assets_by_region JSONB DEFAULT '{}',
    providers_scanned JSONB DEFAULT '[]',
    accounts_scanned JSONB DEFAULT '[]',
    regions_scanned JSONB DEFAULT '[]',
    errors_count INTEGER NOT NULL DEFAULT 0,
    scan_metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
);

-- Latest findings
CREATE TABLE IF NOT EXISTS inventory_findings (
    asset_id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    resource_uid TEXT NOT NULL,
    provider VARCHAR(50) NOT NULL,
    account_id VARCHAR(255) NOT NULL,
    region VARCHAR(100),
    resource_type VARCHAR(255) NOT NULL,
    resource_id VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    tags JSONB DEFAULT '{}',
    labels JSONB DEFAULT '{}',
    properties JSONB DEFAULT '{}',
    configuration JSONB DEFAULT '{}',
    scan_run_id VARCHAR(255),
    latest_scan_run_id VARCHAR(255),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    source_discovery_ids JSONB DEFAULT '[]',
    identifier_key TEXT,
    scope TEXT,
    category TEXT,
    managed_by TEXT,
    is_container BOOLEAN DEFAULT FALSE,
    container_parent TEXT,
    CONSTRAINT fk_tenant_asset FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    CONSTRAINT unique_resource_tenant UNIQUE (resource_uid, tenant_id)
);

-- Historical scan data
CREATE TABLE IF NOT EXISTS inventory_scan_data (
    id SERIAL PRIMARY KEY,
    inventory_scan_id VARCHAR(255) NOT NULL,
    tenant_id VARCHAR(255) NOT NULL,
    asset_id VARCHAR(255) NOT NULL,
    resource_uid TEXT NOT NULL,
    provider VARCHAR(50) NOT NULL,
    account_id VARCHAR(255) NOT NULL,
    region VARCHAR(100),
    resource_type VARCHAR(255) NOT NULL,
    resource_id VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    tags JSONB DEFAULT '{}',
    labels JSONB DEFAULT '{}',
    properties JSONB DEFAULT '{}',
    configuration JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Relationships
CREATE TABLE IF NOT EXISTS inventory_relationships (
    relationship_id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    scan_run_id VARCHAR(255) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    account_id VARCHAR(255) NOT NULL,
    region VARCHAR(100),
    relation_type VARCHAR(100) NOT NULL,
    from_uid TEXT NOT NULL,
    to_uid TEXT NOT NULL,
    from_resource_type VARCHAR(255),
    to_resource_type VARCHAR(255),
    source_resource_uid TEXT,
    target_resource_uid TEXT,
    relationship_type VARCHAR(100),
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT fk_tenant_rel FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
);

-- Drift records
CREATE TABLE IF NOT EXISTS inventory_drift (
    drift_id UUID PRIMARY KEY,
    inventory_scan_id VARCHAR(255) NOT NULL,
    previous_scan_id VARCHAR(255),
    tenant_id VARCHAR(255) NOT NULL,
    resource_uid TEXT NOT NULL,
    provider VARCHAR(50) NOT NULL,
    resource_type VARCHAR(255) NOT NULL,
    change_type VARCHAR(50) NOT NULL,
    previous_state JSONB DEFAULT '{}',
    current_state JSONB DEFAULT '{}',
    changes_summary JSONB DEFAULT '{}',
    severity VARCHAR(20) DEFAULT 'medium',
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
