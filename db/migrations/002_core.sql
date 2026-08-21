-- 002 — core registry + the inventory rename that kills the naming trap.
-- Idempotent: fresh databases create clean tables; existing databases are
-- renamed in place with compat views for old readers.

CREATE TABLE IF NOT EXISTS core_tenants (
    tenant_id    VARCHAR(255) PRIMARY KEY,
    customer_id  VARCHAR(255),
    provider     VARCHAR(50),
    tenant_name  VARCHAR(255),
    display_name VARCHAR(255),
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

DO $$
BEGIN
    IF to_regclass('tenants') IS NOT NULL AND to_regclass('core_tenants') IS NOT NULL THEN
        INSERT INTO core_tenants (tenant_id, customer_id, provider, tenant_name, created_at)
        SELECT tenant_id, customer_id, provider, tenant_name, created_at FROM tenants
        ON CONFLICT (tenant_id) DO NOTHING;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS core_accounts (
    tenant_id   VARCHAR(255) NOT NULL,
    provider    VARCHAR(50)  NOT NULL,
    account_id  VARCHAR(255) NOT NULL,
    alias       VARCHAR(255),
    environment VARCHAR(50),
    PRIMARY KEY (tenant_id, provider, account_id)
);

-- inventory_findings stores assets; rename, or create fresh.
DO $$
BEGIN
    IF to_regclass('inventory_findings') IS NOT NULL
       AND to_regclass('inventory_assets') IS NULL THEN
        ALTER TABLE inventory_findings RENAME TO inventory_assets;
        EXECUTE 'CREATE VIEW inventory_findings AS SELECT * FROM inventory_assets';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS inventory_assets (
    resource_uid   TEXT NOT NULL,
    tenant_id      VARCHAR(255) NOT NULL,
    provider       VARCHAR(50)  NOT NULL,
    account_id     VARCHAR(255) NOT NULL,
    region         VARCHAR(100),
    scope          VARCHAR(20)  NOT NULL DEFAULT 'regional',
    resource_type  VARCHAR(255) NOT NULL,
    resource_id    VARCHAR(255) NOT NULL,
    name           VARCHAR(255),
    tags           JSONB DEFAULT '{}',
    metadata       JSONB DEFAULT '{}',
    topology       JSONB DEFAULT '{}',
    hash_sha256    VARCHAR(64),
    PRIMARY KEY (tenant_id, resource_uid)
);

-- Columns the UI spec added (safe on both fresh and renamed tables)
ALTER TABLE inventory_assets ADD COLUMN IF NOT EXISTS monthly_cost_usd   NUMERIC(12,2);
ALTER TABLE inventory_assets ADD COLUMN IF NOT EXISTS first_seen_scan_id VARCHAR(255);
ALTER TABLE inventory_assets ADD COLUMN IF NOT EXISTS first_seen_at      TIMESTAMPTZ;
ALTER TABLE inventory_assets ADD COLUMN IF NOT EXISTS last_seen_scan_id  VARCHAR(255);
ALTER TABLE inventory_assets ADD COLUMN IF NOT EXISTS last_seen_at       TIMESTAMPTZ;
ALTER TABLE inventory_assets ADD COLUMN IF NOT EXISTS metadata           JSONB DEFAULT '{}';
ALTER TABLE inventory_assets ADD COLUMN IF NOT EXISTS topology           JSONB DEFAULT '{}';
ALTER TABLE inventory_assets ADD COLUMN IF NOT EXISTS scope              VARCHAR(20) DEFAULT 'regional';
ALTER TABLE inventory_assets ADD COLUMN IF NOT EXISTS hash_sha256        VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_assets_tenant_provider ON inventory_assets (tenant_id, provider);
CREATE INDEX IF NOT EXISTS idx_assets_tenant_account  ON inventory_assets (tenant_id, account_id);
CREATE INDEX IF NOT EXISTS idx_assets_tenant_type     ON inventory_assets (tenant_id, resource_type);
CREATE INDEX IF NOT EXISTS idx_assets_tenant_region   ON inventory_assets (tenant_id, region);
CREATE INDEX IF NOT EXISTS idx_assets_tags            ON inventory_assets USING GIN (tags);

-- History + drift keep their tables; standard names arrive as views.
DO $$
BEGIN
    IF to_regclass('inventory_scan_data') IS NOT NULL
       AND to_regclass('inventory_asset_snapshots') IS NULL THEN
        EXECUTE 'CREATE VIEW inventory_asset_snapshots AS SELECT * FROM inventory_scan_data';
    END IF;
    IF to_regclass('inventory_drift') IS NOT NULL
       AND to_regclass('inventory_drift_events') IS NULL THEN
        EXECUTE 'CREATE VIEW inventory_drift_events AS SELECT * FROM inventory_drift';
    END IF;
END $$;
