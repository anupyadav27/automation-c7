-- 001b — catalog reference data.
-- The catalog_* tables (catalog_resource_types, catalog_relations,
-- catalog_arn_recipes, catalog_layers, …) are created BY catalog-sync from
-- each CSV's header (all-TEXT columns): the CSVs are build-generated and
-- their columns evolve with the build tools, so hand-maintaining DDL here
-- would only drift. This migration owns just the sync bookkeeping.

CREATE TABLE IF NOT EXISTS catalog_sync_state (
    source_file   VARCHAR(500) PRIMARY KEY,   -- repo-relative path
    table_name    VARCHAR(255) NOT NULL,
    content_hash  VARCHAR(64)  NOT NULL,      -- sha256 of file bytes
    row_count     INTEGER      NOT NULL,
    loaded_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
