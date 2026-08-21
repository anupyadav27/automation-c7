-- Inventory Engine Database Schema
-- PostgreSQL DDL for inventory indexes

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Minimal tenants table (needed for FK constraints in this DB)
-- Note: other engines have their own tenants tables; inventory DB is standalone.
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id VARCHAR(255) PRIMARY KEY,
    customer_id VARCHAR(255),
    provider VARCHAR(50),
    tenant_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Inventory Run Index
CREATE TABLE IF NOT EXISTS inventory_scans (
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
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT fk_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE
);

-- Asset Index Latest (latest state per resource_uid)
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
    latest_scan_run_id VARCHAR(255) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT fk_tenant_asset FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_scan_run FOREIGN KEY (latest_scan_run_id) REFERENCES inventory_scans(scan_run_id) ON DELETE CASCADE
);

-- Relationship Index Latest (optional - for quick lookups)
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
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT fk_tenant_rel FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_scan_run_rel FOREIGN KEY (scan_run_id) REFERENCES inventory_scans(scan_run_id) ON DELETE CASCADE
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_run_tenant ON inventory_scans(tenant_id);
CREATE INDEX IF NOT EXISTS idx_run_completed_at ON inventory_scans(completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_status ON inventory_scans(status);

CREATE INDEX IF NOT EXISTS idx_asset_tenant ON inventory_findings(tenant_id);
CREATE INDEX IF NOT EXISTS idx_asset_resource_uid ON inventory_findings(resource_uid);
CREATE INDEX IF NOT EXISTS idx_asset_provider ON inventory_findings(provider);
CREATE INDEX IF NOT EXISTS idx_asset_resource_type ON inventory_findings(resource_type);
CREATE INDEX IF NOT EXISTS idx_asset_region ON inventory_findings(region);
CREATE INDEX IF NOT EXISTS idx_asset_account ON inventory_findings(account_id);
CREATE INDEX IF NOT EXISTS idx_asset_tags_gin ON inventory_findings USING gin(tags);

CREATE INDEX IF NOT EXISTS idx_rel_tenant ON inventory_relationships(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rel_from_uid ON inventory_relationships(from_uid);
CREATE INDEX IF NOT EXISTS idx_rel_to_uid ON inventory_relationships(to_uid);
CREATE INDEX IF NOT EXISTS idx_rel_type ON inventory_relationships(relation_type);

-- Composite indexes for common queries
CREATE INDEX IF NOT EXISTS idx_asset_tenant_type ON inventory_findings(tenant_id, resource_type);
CREATE INDEX IF NOT EXISTS idx_asset_tenant_region ON inventory_findings(tenant_id, region);
CREATE INDEX IF NOT EXISTS idx_asset_tenant_provider ON inventory_findings(tenant_id, provider);

