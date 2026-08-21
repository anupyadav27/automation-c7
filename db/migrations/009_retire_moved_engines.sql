-- Compliance and FinOps moved to the threat-engine platform; their tables did
-- not move with them.
--
-- Their API routes are already gone (`/posture/findings`,
-- `/finops/recommendations`, and the `include=rollups` path that read both and
-- 500'd on every call, costing the console every asset it had). What remains is
-- schema nothing writes and nothing reads.
--
-- Dropped rather than left empty: an empty table is indistinguishable from a
-- feature that has no data yet, and the next person to open the schema should
-- not have to work out which of the two this is.

DROP TABLE IF EXISTS finops_recommendations;
DROP TABLE IF EXISTS finops_pricing_catalog;
DROP TABLE IF EXISTS posture_findings;
