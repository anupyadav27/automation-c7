/**
 * What a reader changed about the diagram, and how it survives a rescan.
 *
 * The engine decides the picture (`diagram-layout-spec.md` §10 — one estate,
 * one diagram). This module holds the small set of things a READER is allowed
 * to overrule on top of it: the sequence siblings are drawn in, which panels
 * are pinned and where, which connection lines stay drawn, and which categories
 * the filter is letting through.
 *
 * Three rules govern everything here, and they exist because a stored
 * preference outlives the estate it was stored against:
 *
 * 1. **A bad document is no document.** Anything that fails to decode returns
 *    `null` and the console renders as if nothing was ever saved. A corrupt
 *    blob must never be able to blank the page — the diagram is the product,
 *    the preference is a convenience, and the failure mode has to reflect that.
 * 2. **Orphans drop silently.** Autoscaled instances and interfaces get new IDs
 *    every scan. A pin whose subject no longer exists is discarded on load and
 *    COUNTED, so the reset affordance can say what happened rather than leaving
 *    a reader wondering where their panel went.
 * 3. **A version bump invalidates.** When the shape of what is stored changes,
 *    an old document is dropped whole rather than partially applied. Half a
 *    preference is harder to diagnose than none.
 *
 * Pure data in, pure data out. The storage adapter at the foot is the only part
 * that touches the browser, and it is guarded for SSR because this app renders
 * on the server first.
 */

/**
 * Bumped when the SHAPE of a stored document changes.
 *
 * Not when the console changes. A new field with a safe default is a decode
 * concern, not a version concern — `decode` fills anything absent, so adding
 * `traces` to a document written before traces existed costs nothing. Bump this
 * only when an existing field would be MISREAD, which is the one case where
 * keeping the document is worse than dropping it.
 */
export const PREFS_VERSION = 1;

/** Where the console stores a reader's preferences. One key per scope. */
export const PREFS_KEY = "cloud-estate.diagram.prefs";

/* ── placement ─────────────────────────────────────────────────────────── */

/** Which corner of the viewport a placement is measured from. */
export type Corner = "tl" | "tr" | "bl" | "br";

/**
 * Where a panel sits, expressed so it survives a different screen.
 *
 * NOT `{x, y}`. Panels are `position: fixed`, so a raw coordinate is a viewport
 * coordinate, and the viewport is not the same thing twice: a panel saved at
 * `x: 1900` on a 2560px monitor restores entirely off-screen on a 1440px
 * laptop. That is the failure that makes people stop trusting saved layouts,
 * and it happens the first time someone opens the console on another machine.
 *
 * A corner and an offset is what window managers use and what people actually
 * mean — "I put it in the top right" — so a panel placed top-right comes back
 * top-right at any size. See `placement.ts` for the arithmetic.
 */
export type Placement = { corner: Corner; dx: number; dy: number };

/* ── the document ──────────────────────────────────────────────────────── */

/** One panel a reader pinned, and the state it should come back in. */
export type PanelPref = {
  kind: "list" | "detail";
  /** The host key (a list) or node key (a detail) the panel is about. */
  subject: string;
  /**
   * A list's heading, and the resources it holds.
   *
   * Stored rather than recomputed, because a list's membership depends on WHAT
   * OPENED IT — a rail tab's four interfaces, a container's whole subtree, a
   * service tile's fifty-five buckets — and the host key alone does not say
   * which. Node keys only; the scene resolves them back to resources on load,
   * so a pinned list cannot carry a stale copy of a resource's fields.
   */
  label?: string;
  members?: string[];
  place?: Placement;
  collapsed?: boolean;
  /** Stacking order, so a restored arrangement keeps its front-to-back. */
  z?: number;
};

export type Prefs = {
  version: number;
  /** `account/region` — a fixture's preferences must never reach a live scene. */
  scope: string;
  savedAt: string;
  /** Container key -> the sequence its children are drawn in. */
  order: Record<string, string[]>;
  /**
   * Container key -> unit key -> the (row, column) the reader put it in.
   *
   * Supersedes `order` for any container that has cells: a cell says both which
   * comes first AND where it sits, so honouring a sequence as well would be two
   * answers to one question. `order` stays for containers arranged before cells
   * existed, and for the surfaces where a sequence is the whole story.
   */
  cells: Record<string, Record<string, [number, number]>>;
  /** Pinned panels. These restore OPEN. */
  panels: PanelPref[];
  /**
   * Subject key -> where its panel goes when opened.
   *
   * Separate from `panels` on purpose. `panels` says "this is my workspace,
   * bring it back"; `places` says "whenever you show me this VPC's list, it
   * goes here". Collapsed into one, a panel would have to stay pinned in order
   * to keep its position, which is not what a reader means by moving it.
   */
  places: Record<string, Placement>;
  /** Source keys whose connection lines stay drawn. */
  traces: string[];
  /** The category filter — `hidden` in the renderer. */
  filter: { hidden: string[] };
  toggles: { showArtifacts: boolean };
};

export const scopeOf = (account: string, region: string) => `${account}/${region}`;

export function emptyPrefs(scope: string): Prefs {
  return {
    version: PREFS_VERSION,
    scope,
    savedAt: "",
    order: {},
    cells: {},
    panels: [],
    places: {},
    traces: [],
    filter: { hidden: [] },
    toggles: { showArtifacts: false },
  };
}

/* ── decoding ──────────────────────────────────────────────────────────── */

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

const strings = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];

const CORNERS: Corner[] = ["tl", "tr", "bl", "br"];

/** A placement, or nothing. A half-read position is worse than a default one. */
export function decodePlacement(v: unknown): Placement | undefined {
  if (!isObj(v)) return undefined;
  const corner = v["corner"];
  const dx = v["dx"];
  const dy = v["dy"];
  if (typeof corner !== "string" || !CORNERS.includes(corner as Corner)) return undefined;
  if (!Number.isFinite(dx) || !Number.isFinite(dy)) return undefined;
  return { corner: corner as Corner, dx: Number(dx), dy: Number(dy) };
}

function decodePanel(v: unknown): PanelPref | null {
  if (!isObj(v)) return null;
  const kind = v["kind"];
  const subject = v["subject"];
  if (kind !== "list" && kind !== "detail") return null;
  if (typeof subject !== "string" || !subject) return null;
  const place = decodePlacement(v["place"]);
  const collapsed = v["collapsed"];
  const z = v["z"];
  const label = v["label"];
  const members = strings(v["members"]);
  return {
    kind,
    subject,
    ...(typeof label === "string" && label ? { label } : {}),
    ...(members.length ? { members } : {}),
    ...(place ? { place } : {}),
    ...(typeof collapsed === "boolean" ? { collapsed } : {}),
    ...(Number.isFinite(z) ? { z: Number(z) } : {}),
  };
}

/**
 * Read a stored document, or decide there isn't one.
 *
 * Every field is taken defensively rather than trusted, because the input is
 * whatever was in `localStorage` — which includes documents written by an older
 * console, by a half-finished write, or by a reader editing devtools. The
 * shape is small enough that hand-checking it is cheaper than a schema library
 * and leaves the failure explicit.
 *
 * Scope mismatch is a REJECTION, not a migration. A fixture session and a live
 * account are different estates whose keys look alike, and letting one's saved
 * order apply to the other would rebind every preference onto the wrong thing.
 */
export function decode(raw: unknown, scope: string): Prefs | null {
  const v = typeof raw === "string" ? safeParse(raw) : raw;
  if (!isObj(v)) return null;
  if (v["version"] !== PREFS_VERSION) return null;
  const storedScope = v["scope"];
  if (typeof storedScope !== "string" || storedScope !== scope) return null;

  const base = emptyPrefs(scope);
  const rawOrder = v["order"];
  const order: Record<string, string[]> = {};
  if (isObj(rawOrder)) {
    for (const [key, seq] of Object.entries(rawOrder)) {
      const list = strings(seq);
      // An empty sequence is indistinguishable from no preference and would
      // otherwise light the "customised" indicator for nothing.
      if (list.length) order[key] = list;
    }
  }
  const rawCells = v["cells"];
  const cells: Record<string, Record<string, [number, number]>> = {};
  if (isObj(rawCells)) {
    for (const [container, map] of Object.entries(rawCells)) {
      if (!isObj(map)) continue;
      const inner: Record<string, [number, number]> = {};
      for (const [key, c] of Object.entries(map)) {
        // Two non-negative integers or nothing. `layoutGrid` tolerates junk,
        // but a document that never carried it is one less thing to tolerate.
        if (
          Array.isArray(c) &&
          c.length === 2 &&
          Number.isInteger(c[0]) &&
          Number.isInteger(c[1]) &&
          (c[0] as number) >= 0 &&
          (c[1] as number) >= 0
        ) {
          inner[key] = [c[0] as number, c[1] as number];
        }
      }
      if (Object.keys(inner).length) cells[container] = inner;
    }
  }
  const rawPlaces = v["places"];
  const places: Record<string, Placement> = {};
  if (isObj(rawPlaces)) {
    for (const [key, p] of Object.entries(rawPlaces)) {
      const place = decodePlacement(p);
      if (place) places[key] = place;
    }
  }
  const savedAt = v["savedAt"];
  const panels = v["panels"];
  const filter = v["filter"];
  const toggles = v["toggles"];
  return {
    ...base,
    savedAt: typeof savedAt === "string" ? savedAt : "",
    order,
    cells,
    places,
    panels: Array.isArray(panels)
      ? panels.map(decodePanel).filter((p): p is PanelPref => p !== null)
      : [],
    traces: strings(v["traces"]),
    filter: { hidden: strings(isObj(filter) ? filter["hidden"] : []) },
    toggles: {
      showArtifacts: isObj(toggles) && toggles["showArtifacts"] === true,
    },
  };
}

function safeParse(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export const encode = (p: Prefs): string => JSON.stringify(p);

/* ── reconciling against a rescanned estate ────────────────────────────── */

/**
 * Drop what the estate no longer has, and say how much was dropped.
 *
 * `alive` is every node key the current scene holds. Anything a preference
 * names that is not in it has been destroyed, renamed or replaced since the
 * document was written — an autoscaled instance, an interface, a rebuilt
 * subnet. Those pins and traces cannot be honoured, so they go.
 *
 * `order` sequences are deliberately NOT pruned against `alive`. A sequence is
 * a list of unit keys, and a unit is not always a node — a service group is
 * keyed by its service, a rule wrap by its rule, a zone row by its members —
 * so testing them against node keys would delete valid preferences. `applyOrder`
 * already ignores keys it does not find, which is the correct place for it: it
 * sees what is actually on screen, and this function does not.
 */
export function prune(prefs: Prefs, alive: ReadonlySet<string>): { prefs: Prefs; dropped: number } {
  /* The two panel kinds are checked differently, and conflating them dropped
     every pinned list on load: a DETAIL panel's subject is a node key, but a
     LIST's is a host key — `box:vpc:vpc-a`, `flat:Supporting`, a service name —
     which is not in the scene's node index and never was. A list is judged by
     its MEMBERS instead, which are node keys, and survives as long as it still
     has something to show. */
  const panels: PanelPref[] = [];
  for (const p of prefs.panels) {
    if (p.kind === "detail") {
      if (alive.has(p.subject)) panels.push(p);
      continue;
    }
    const members = (p.members ?? []).filter((k) => alive.has(k));
    // A list whose every member is gone has nothing left to be about.
    if (!members.length) continue;
    panels.push(members.length === p.members?.length ? p : { ...p, members });
  }
  const traces = prefs.traces.filter((k) => alive.has(k));
  const dropped = prefs.panels.length - panels.length + (prefs.traces.length - traces.length);
  if (!dropped && panels.every((p, i) => p === prefs.panels[i])) return { prefs, dropped: 0 };
  return { prefs: { ...prefs, panels, traces }, dropped };
}

/**
 * Whether anything is overriding the engine.
 *
 * Drives the "layout customised · reset" indicator. Without it, a reader with a
 * six-month-old saved order sees a diagram that disagrees with the engine and
 * has no way to find out why — which is the one failure that makes the whole
 * feature untrustworthy rather than merely wrong.
 *
 * The filter is included: it is the most invisible override of the four, since
 * a hidden category leaves nothing behind to notice.
 */
export function isCustomised(p: Prefs): boolean {
  return (
    Object.keys(p.order).length > 0 ||
    Object.keys(p.cells).length > 0 ||
    p.panels.length > 0 ||
    Object.keys(p.places).length > 0 ||
    p.traces.length > 0 ||
    p.filter.hidden.length > 0 ||
    p.toggles.showArtifacts
  );
}

/* ── storage ───────────────────────────────────────────────────────────── */

/**
 * One key per scope, so two accounts do not overwrite each other.
 *
 * v1 is `localStorage`, which means preferences do not follow a reader between
 * machines. That is a stated limitation rather than an oversight: the document
 * above is transport-agnostic, so moving to a per-user API record is a swap of
 * the two functions below.
 */
const keyFor = (scope: string) => `${PREFS_KEY}.${scope}`;

const store = (): Storage | null => {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    // Private browsing and blocked third-party storage both throw on ACCESS,
    // not on use. Losing preferences is acceptable; refusing to render is not.
    return null;
  }
};

export function loadPrefs(scope: string): Prefs | null {
  const s = store();
  if (!s) return null;
  try {
    const raw = s.getItem(keyFor(scope));
    return raw ? decode(raw, scope) : null;
  } catch {
    return null;
  }
}

export function savePrefs(prefs: Prefs): boolean {
  const s = store();
  if (!s) return false;
  try {
    s.setItem(keyFor(prefs.scope), encode({ ...prefs, savedAt: new Date().toISOString() }));
    return true;
  } catch {
    // Quota, most likely. The reader keeps the arrangement they can see; it
    // just will not be there next time, and the save control reports that.
    return false;
  }
}

export function clearPrefs(scope: string): void {
  const s = store();
  if (!s) return;
  try {
    s.removeItem(keyFor(scope));
  } catch {
    /* nothing to do — the caller is already resetting in-memory state */
  }
}
