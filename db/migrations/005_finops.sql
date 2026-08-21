-- 005 — finops recommendations (lifecycle + user dismiss) and pricing.

CREATE TABLE IF NOT EXISTS finops_recommendations (
    recommendation_id      VARCHAR(600) PRIMARY KEY,   -- '<rule_id>::<resource_uid>'
    tenant_id              VARCHAR(255) NOT NULL,
    rule_id                VARCHAR(255) NOT NULL REFERENCES rules_definitions(rule_id),
    resource_uid           TEXT NOT NULL,
    account_id             VARCHAR(255),
    region                 VARCHAR(100),
    severity               VARCHAR(20) NOT NULL,
    category               VARCHAR(50) NOT NULL,
    details                JSONB,
    current_monthly_cost_usd NUMERIC(12,2),
    savings_min_usd        NUMERIC(12,2),
    savings_max_usd        NUMERIC(12,2),
    pricing_confidence     VARCHAR(50),
    status                 VARCHAR(20) NOT NULL DEFAULT 'open',  -- open | dismissed | resolved
    dismissed_by           VARCHAR(255),
    dismissed_at           TIMESTAMPTZ,
    first_detected_scan_id VARCHAR(255) NOT NULL,
    first_detected_at      TIMESTAMPTZ NOT NULL,
    last_seen_scan_id      VARCHAR(255) NOT NULL,
    last_seen_at           TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recs_tenant_status ON finops_recommendations (tenant_id, status, savings_max_usd DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_recs_resource      ON finops_recommendations (tenant_id, resource_uid);

CREATE TABLE IF NOT EXISTS finops_pricing_catalog (
    sku_key       VARCHAR(255) PRIMARY KEY,
    region        VARCHAR(100),
    attributes    JSONB,
    on_demand_usd NUMERIC(14,6) NOT NULL,
    unit          VARCHAR(50),
    fetched_at    TIMESTAMPTZ NOT NULL
);
