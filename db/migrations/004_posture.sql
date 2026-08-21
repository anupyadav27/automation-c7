-- 004 — posture findings with lifecycle (open ⇄ resolved computed at ingest).

CREATE TABLE IF NOT EXISTS posture_findings (
    finding_id             UUID PRIMARY KEY,      -- uuid5(rule_id, resource identity)
    tenant_id              VARCHAR(255) NOT NULL,
    rule_id                VARCHAR(255) NOT NULL REFERENCES rules_definitions(rule_id),
    resource_uid           TEXT,                  -- NULL = unresolved, still shown
    resource_id            VARCHAR(255),
    resource_key           VARCHAR(255),
    account_id             VARCHAR(255),
    region                 VARCHAR(100),
    severity               VARCHAR(20) NOT NULL,
    domain                 VARCHAR(20) NOT NULL,
    exposure               VARCHAR(50),
    evidence               JSONB,
    status                 VARCHAR(20) NOT NULL DEFAULT 'open',  -- open | resolved
    first_detected_scan_id VARCHAR(255) NOT NULL,
    first_detected_at      TIMESTAMPTZ NOT NULL,
    last_seen_scan_id      VARCHAR(255) NOT NULL,
    last_seen_at           TIMESTAMPTZ NOT NULL,
    resolved_scan_id       VARCHAR(255),
    resolved_at            TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_findings_tenant_status ON posture_findings (tenant_id, status, severity);
CREATE INDEX IF NOT EXISTS idx_findings_resource      ON posture_findings (tenant_id, resource_uid);
CREATE INDEX IF NOT EXISTS idx_findings_rule          ON posture_findings (tenant_id, rule_id);
