-- 003 — rule definitions + authored metadata registry.
-- rule_id convention: compliance = bare c7n name ('sg-open-ssh');
-- cost = '<provider>.<name>' ('gcp.disk-stale-snapshot') — names repeat
-- across clouds and engines, ids must not.

CREATE TABLE IF NOT EXISTS rules_definitions (
    rule_id       VARCHAR(255) PRIMARY KEY,
    rule_kind     VARCHAR(20)  NOT NULL,     -- compliance | cost
    provider      VARCHAR(50),
    resource      VARCHAR(255),
    domain        VARCHAR(20),               -- compliance | cost | governance
    severity      VARCHAR(20)  NOT NULL,
    category      VARCHAR(50),               -- finops_category (cost rules)
    action_tier   VARCHAR(20),
    automatable   BOOLEAN DEFAULT FALSE,
    graph_check   VARCHAR(50),
    parameters    JSONB DEFAULT '{}',
    savings_model JSONB,
    definition    TEXT,
    source_file   VARCHAR(500),
    enabled       BOOLEAN DEFAULT TRUE,
    content_hash  VARCHAR(64),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rules_kind ON rules_definitions (rule_kind);

CREATE TABLE IF NOT EXISTS rules_metadata (
    rule_id        VARCHAR(255) PRIMARY KEY REFERENCES rules_definitions(rule_id) ON DELETE CASCADE,
    title          VARCHAR(500) NOT NULL,
    description    TEXT,
    rationale      TEXT,
    recommendation TEXT,
    ai_fix_prompt  TEXT,
    "references"   JSONB DEFAULT '[]',
    frameworks     JSONB DEFAULT '[]',
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);
