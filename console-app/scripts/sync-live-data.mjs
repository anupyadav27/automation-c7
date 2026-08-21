/**
 * Pull the real estate from the Cloud Estate API and write it in the exact
 * shapes `src/lib/mock-data.ts` declares, so every component and route in the
 * design system renders live data without a single UI change.
 *
 *   node scripts/sync-live-data.mjs           # writes src/lib/live-data.json
 *   API=http://localhost:8090 node scripts/...
 *
 * Runs automatically before `npm run dev` (see package.json predev). If the
 * API is unreachable the file is left alone and the app falls back to the
 * generated fixtures, so the UI is never blocked by a dead backend.
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const API = process.env.API || "http://localhost:8090";
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "lib", "live-data.json");

const get = async (path, params = {}) => {
  const url = new URL(API + path);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
};

const minutesAgo = (iso) =>
  iso ? Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000)) : 0;

const PROVIDERS = new Set(["aws", "azure", "gcp", "oci", "ibm", "kubernetes"]);

function toAsset(a) {
  const topo = a.topology || {};
  return {
    provider: PROVIDERS.has(a.provider) ? a.provider : "aws",
    account_id: String(a.account_id ?? ""),
    region: a.scope === "global" ? "global" : String(a.region || "global"),
    resource_type: a.resource_type,
    resource_id: String(a.resource_id ?? ""),
    resource_uid: a.resource_uid,
    name: a.name || a.resource_id || "",
    tags: a.tags && typeof a.tags === "object" ? a.tags : {},
    topology: {
      layer_id: topo.layer_id || "L1",
      layer_name: topo.layer_name || "regional",
      zone: topo.zone || "",
      container: topo.container_uid || topo.container || "",
      uid_quality: topo.uid_quality || "real",
    },
    // rollups the design system shows in the Findings / Cost columns
    finding_counts: a.finding_counts || {},
    monthly_cost_usd: a.savings_usd ?? a.monthly_cost_usd ?? null,
  };
}

const toFinding = (f) => ({
  policy: f.rule_id || f.policy,
  domain: f.domain || "compliance",
  severity: (f.severity || "medium").toLowerCase(),
  action_tier: f.action_tier || "notify",
  automatable: f.automatable === true || f.automatable === "yes" ? "yes" : "no",
  resource_key: f.resource_key || "",
  arn: f.arn || f.resource_uid || "",
  resource_id: f.resource_id || "",
  account_id: String(f.account_id ?? ""),
  region: f.region || "global",
  layer_id: f.layer_id || "",
  name: f.name || f.resource_id || "",
  title: f.title || null,
  ai_fix_prompt: f.ai_fix_prompt || null,
});

const toRec = (r) => {
  const min = Number(r.savings_min_usd ?? r.estimated_monthly_savings_usd?.min ?? 0);
  const max = Number(r.savings_max_usd ?? r.estimated_monthly_savings_usd?.max ?? 0);
  return {
    recommendation_id: r.recommendation_id || `${r.rule_id}::${r.resource_uid}`,
    rule_name: r.rule_name || r.rule_id || "",
    resource_uid: r.resource_uid,
    severity: (r.severity || "medium").toLowerCase(),
    finops_category: r.category || r.finops_category || "waste_elimination",
    estimated_savings: r.estimated_savings || (max ? `$${min}–$${max}/mo` : "—"),
    current_monthly_cost_usd: Number(r.current_monthly_cost_usd ?? 0),
    estimated_monthly_savings_usd: { min, max },
    savings_model: "percent_range",
    description: r.title || r.description || "",
    conditions: Array.isArray(r.details?.conditions) ? r.details.conditions : [],
  };
};

const STAGES = ["discover", "assets", "architecture", "compliance", "finops"];

function toRun(run) {
  const stages = run.stages || {};
  const done = STAGES.filter((s) => stages[s]?.status === "success").length;
  const secs = STAGES.reduce((t, s) => t + (stages[s]?.duration_seconds || 0), 0);
  return {
    run_id: run.scan_run_id,
    started_at:
      String(run.started_at || "")
        .slice(0, 16)
        .replace("T", " ") + " UTC",
    stages_completed: done,
    assets: run.totals?.assets ?? 0,
    findings: run.totals?.findings ?? 0,
    recommendations: run.totals?.recommendations ?? 0,
    duration: `${Math.floor(secs / 60)}m ${String(Math.round(secs % 60)).padStart(2, "0")}s`,
    trigger: run.trigger === "scheduled" ? "scheduled" : "manual",
    status: run.status === "success" ? "success" : run.status === "failed" ? "failed" : "partial",
  };
}

/**
 * Every part is fetched independently and every part may fail.
 *
 * These used to be one `Promise.all`, so a single 500 lost the whole sync -
 * and after compliance and FinOps moved out of this repo, `/posture/findings`
 * answers 500 every time. The architecture diagram, which needs none of those
 * endpoints, went stale for a day behind an error about findings.
 */
const soft = (p, fallback) =>
  p.then(
    (r) => r,
    () => fallback,
  );

/**
 * The scene comes from the pipeline artifact first, the API second.
 *
 * `python -m orchestration.pipeline architecture` writes `out/scene.json`, and
 * that file IS the diagram - no server has to be running for the console to
 * draw the estate. The API is the fallback, not the source.
 */
function loadScene() {
  const artifact = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "out", "scene.json");
  if (existsSync(artifact)) {
    try {
      return JSON.parse(readFileSync(artifact, "utf8"));
    } catch {
      /* fall through to the API */
    }
  }
  return null;
}

try {
  const [assets, findings, recs, runs, overview, drift] = await Promise.all([
    // No `include=rollups`: the rollups are finding and cost counts, and both
    // engines left this repo. The endpoint still 500s trying to read their
    // tables, which cost the sync every asset it had.
    soft(get("/api/v1/inventory/assets", { limit: 1000 }), { data: [] }),
    soft(get("/api/v1/posture/findings", { limit: 1000 }), { data: [] }),
    soft(get("/api/v1/finops/recommendations", { limit: 1000 }), { data: [] }),
    soft(get("/api/v1/pipeline/runs", { limit: 20 }), { data: [] }),
    soft(get("/api/v1/overview"), { data: {} }),
    soft(get("/api/v1/inventory/drift", { limit: 200 }), { data: [] }),
  ]);

  const scene = loadScene() ?? (await get("/api/v1/architecture/scene").catch(() => null));

  const payload = {
    generated_at: new Date().toISOString(),
    source: API,
    assets: assets.data.map(toAsset),
    findings: findings.data.map(toFinding),
    recommendations: recs.data.map(toRec),
    runs: runs.data.map(toRun),
    drift: (drift.data || []).map((d) => ({
      id: d.drift_id,
      kind: d.change_type,
      at:
        String(d.detected_at || "")
          .slice(0, 16)
          .replace("T", " ") + " UTC",
      run_id: d.scan_run_id,
      resource_uid: d.resource_uid,
      resource_type: d.resource_type || "",
      diff: Object.entries(d.changes_summary || {}).map(([field, v]) => ({
        field,
        before: typeof v?.before === "object" ? JSON.stringify(v.before) : String(v?.before ?? ""),
        after: typeof v?.after === "object" ? JSON.stringify(v.after) : String(v?.after ?? ""),
      })),
    })),
    overview: overview.data,
    scene,
  };
  // Never overwrite good data with nothing.
  //
  // Each part can now fail on its own, which is what unblocked the diagram -
  // but it also means a dead endpoint returns an EMPTY list rather than
  // throwing, and writing that empty list would silently erase an estate the
  // last sync fetched successfully. An empty answer from a broken endpoint and
  // a genuinely empty estate look identical here, so the previous value wins.
  if (existsSync(OUT)) {
    const prior = JSON.parse(readFileSync(OUT, "utf8"));
    for (const key of ["assets", "findings", "recommendations", "runs", "drift"]) {
      if (!payload[key]?.length && prior[key]?.length) payload[key] = prior[key];
    }
    if (!payload.scene && prior.scene) payload.scene = prior.scene;
    if (!Object.keys(payload.overview ?? {}).length && prior.overview) {
      payload.overview = prior.overview;
    }
  }
  writeFileSync(OUT, JSON.stringify(payload, null, 1));
  console.log(
    `live-data.json ← ${API}: ${payload.assets.length} assets, ` +
      `${payload.findings.length} findings, ${payload.recommendations.length} recommendations, ` +
      `${payload.runs.length} runs, ${payload.drift.length} drift` +
      (payload.scene
        ? `, scene ${payload.scene.region} (${(payload.scene.edges || []).length} arrows, ` +
          `${(payload.scene.relations || []).length} relations)`
        : ", no scene"),
  );
} catch (err) {
  console.warn(`sync skipped (${err.message}) — the UI keeps its fixtures`);
}
