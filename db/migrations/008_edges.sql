-- Derived edges: what points at what, and how we know.
--
-- These had no home. The catalog tables (`rule_diagram_relationship` and
-- friends) hold the RULES — 2,780 declared paths from one type to another —
-- but the edges those rules actually produced against a real account lived
-- only in `out/edges.csv`. So nothing could ask "what is this resource
-- connected to" without reading a file off the pipeline host, and the API had
-- no way to answer it at all.
--
-- Keyed on (source, target, edge_type) rather than on a surrogate id, because
-- that triple IS the identity of a relationship: the same pair related two
-- ways — attached-to AND protected-by — is two edges, and the same pair found
-- by four different paths is one.

CREATE TABLE IF NOT EXISTS inventory_edges (
    tenant_id        VARCHAR(255) NOT NULL,
    source_asset_id  TEXT NOT NULL,
    target_asset_id  TEXT NOT NULL,
    edge_type        VARCHAR(64)  NOT NULL,

    source_key       VARCHAR(255),
    target_key       VARCHAR(255),

    -- Provenance. Without it every row in a panel looks equally certain, and a
    -- human-verified c7n path and a mined inference are not the same claim.
    via              TEXT,
    mechanism        VARCHAR(64),
    confidence       VARCHAR(16),

    -- How many independent paths found this same relationship. Several paths
    -- agreeing is evidence the edge is real, and it is the only thing that
    -- survives collapsing duplicate rows.
    corroborations   INTEGER DEFAULT 1,

    -- An edge whose target was never collected is KEPT and marked, not
    -- dropped: a reference to something absent from the estate is a finding,
    -- and hiding it makes a resource look like it stands alone.
    resolved         BOOLEAN DEFAULT TRUE,

    value            TEXT,
    attributes       JSONB DEFAULT '{}',

    last_seen_scan_id VARCHAR(255),
    last_seen_at      TIMESTAMPTZ,

    PRIMARY KEY (tenant_id, source_asset_id, target_asset_id, edge_type)
);

-- Both directions are queried. A resource's panel asks "what do I point at"
-- AND "what points at me" — a security group's whole answer is the second one.
CREATE INDEX IF NOT EXISTS idx_edges_source ON inventory_edges (tenant_id, source_asset_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON inventory_edges (tenant_id, target_asset_id);
CREATE INDEX IF NOT EXISTS idx_edges_type   ON inventory_edges (tenant_id, edge_type);
