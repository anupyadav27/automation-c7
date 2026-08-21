/**
 * The estate API, for the things a page asks for one at a time.
 *
 * Most of the console reads `live-data.json`, a snapshot baked at dev-server
 * start — right for a table of 1,000 assets, wrong for a panel. A panel opens
 * on one resource and wants that resource as it is NOW, not as it was when the
 * snapshot was taken.
 *
 * Every call degrades to null rather than throwing. The scene already carries
 * an answer for every node, so a dead API should make the panel stale, never
 * empty: the fetch refines what is already on screen.
 */

const BASE =
  (import.meta as { env?: Record<string, string> }).env?.["VITE_API_URL"] ??
  "http://localhost:8090";

async function get<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${BASE}${path}`);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null; // offline, CORS, or no server — the scene still has an answer
  }
}

export type ApiAsset = {
  resource_uid: string;
  resource_type: string;
  name?: string | null;
  region?: string | null;
  account_id?: string | null;
  /** Tier 2 — the catalog's columns for this type. */
  metadata?: Record<string, unknown> | null;
  tags?: Record<string, string> | null;
  last_seen_at?: string | null;
};

export type ApiRelation = {
  source_asset_id: string;
  target_asset_id: string;
  source_key?: string | null;
  target_key?: string | null;
  edge_type: string;
  direction: "in" | "out";
  via?: string | null;
  confidence?: string | null;
  corroborations?: number | null;
  resolved?: boolean | null;
};

/** `resource_uid` is an ARN, so it has to survive being a path segment. */
const uid = (id: string) => encodeURIComponent(id);

export const assetQuery = (resourceUid: string | null) => ({
  queryKey: ["asset", resourceUid],
  enabled: Boolean(resourceUid),
  queryFn: async () =>
    resourceUid
      ? ((await get<{ data: ApiAsset }>(`/api/v1/inventory/assets/${uid(resourceUid)}`))?.data ??
        null)
      : null,
});

export const relationsQuery = (resourceUid: string | null) => ({
  queryKey: ["relations", resourceUid],
  enabled: Boolean(resourceUid),
  queryFn: async () =>
    resourceUid
      ? ((
          await get<{ data: ApiRelation[] }>(
            `/api/v1/inventory/assets/${uid(resourceUid)}/relations?limit=500`,
          )
        )?.data ?? null)
      : null,
});
