-- 007 — drift events. The detector compares each scan's assets against the
-- previous scan's stored state; rows here are what the Runs & Drift view
-- reads. Identity-only diffing (hash + the fields that describe the resource,
-- never scan bookkeeping) keeps re-scans from reporting phantom change.

CREATE TABLE IF NOT EXISTS inventory_drift_events (
    drift_id          UUID PRIMARY KEY,
    tenant_id         VARCHAR(255) NOT NULL,
    scan_run_id       VARCHAR(255) NOT NULL,
    previous_scan_id  VARCHAR(255),
    resource_uid      TEXT NOT NULL,
    provider          VARCHAR(50),
    resource_type     VARCHAR(255),
    change_type       VARCHAR(50) NOT NULL,   -- ASSET_ADDED | ASSET_REMOVED | ASSET_CHANGED
    changes_summary   JSONB DEFAULT '{}',     -- {field: {before, after}}
    detected_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drift_scan   ON inventory_drift_events (tenant_id, scan_run_id);
CREATE INDEX IF NOT EXISTS idx_drift_uid    ON inventory_drift_events (tenant_id, resource_uid);
CREATE INDEX IF NOT EXISTS idx_drift_recent ON inventory_drift_events (detected_at DESC);
