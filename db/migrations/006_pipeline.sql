-- 006 — pipeline run bookkeeping (the Runs table) and stage artifacts.

CREATE TABLE IF NOT EXISTS pipeline_runs (
    scan_run_id  VARCHAR(255) PRIMARY KEY,
    tenant_id    VARCHAR(255) NOT NULL,
    trigger      VARCHAR(20)  NOT NULL DEFAULT 'manual',   -- manual | scheduled | api
    triggered_by VARCHAR(255),
    providers    JSONB DEFAULT '[]',
    accounts     JSONB DEFAULT '[]',
    regions      JSONB DEFAULT '[]',
    stages       JSONB NOT NULL DEFAULT '{}',
    totals       JSONB DEFAULT '{}',
    status       VARCHAR(20) NOT NULL,                     -- running | success | partial | failed
    started_at   TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_runs_tenant_started ON pipeline_runs (tenant_id, started_at DESC);

CREATE TABLE IF NOT EXISTS pipeline_run_artifacts (
    scan_run_id VARCHAR(255) NOT NULL REFERENCES pipeline_runs(scan_run_id) ON DELETE CASCADE,
    stage       VARCHAR(30) NOT NULL,
    kind        VARCHAR(30) NOT NULL,      -- scene | findings | recommendations | assets
    content     JSONB,
    path        VARCHAR(500),
    records     INTEGER,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (scan_run_id, stage, kind)
);
