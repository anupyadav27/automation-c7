/**
 * The reader's overrides, held for the session and written when they say so.
 *
 * **Saving is explicit.** A reader rearranging six panels and three containers
 * is experimenting, and an autosave turns every experiment into a commitment —
 * the arrangement they were happy with last week is gone before they notice it
 * changed. So edits live in memory, the bar says there is something unsaved,
 * and one button writes it. The same button is what makes "next time, the same
 * layout" a promise the reader made rather than one the console made for them.
 *
 * **Loading happens after mount, never during render.** This app renders on the
 * server, where there is no `localStorage`: reading preferences during render
 * would produce markup the client could not reproduce, and React would throw
 * away the whole tree on hydration. The cost is one frame of engine-default
 * diagram before a saved arrangement lands, which is the correct trade — the
 * engine's answer is never wrong, it is only not yet personalised.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  clearPrefs,
  emptyPrefs,
  encode,
  isCustomised,
  loadPrefs,
  prune,
  savePrefs,
  type Prefs,
} from "@/lib/preferences";

export type PrefsApi = {
  prefs: Prefs;
  /** True once the stored document has been read (or found absent). */
  loaded: boolean;
  /** Pins whose subject the estate no longer holds, dropped on load. */
  dropped: number;
  /** Anything at all overriding the engine. Drives the reset affordance. */
  customised: boolean;
  /** In-memory state differs from what is on disk. Drives the save button. */
  dirty: boolean;
  /** Last save failed — quota, or storage unavailable. */
  failed: boolean;
  update: (fn: (p: Prefs) => Prefs) => void;
  save: () => void;
  /** Forget everything, on disk and in memory. */
  reset: () => void;
};

/**
 * @param scope   `account/region` — a fixture's document must never reach a
 *                live account, so the scope is part of the storage key AND
 *                re-checked on decode.
 * @param enabled Whether to touch storage at all. Off for a fixture scene:
 *                saving a layout against invented data would restore against
 *                real data the moment a scan lands.
 * @param alive   Every node key the current scene holds, for pruning orphans.
 */
export function usePreferences(
  scope: string,
  enabled: boolean,
  alive: ReadonlySet<string>,
): PrefsApi {
  const [prefs, setPrefs] = useState<Prefs>(() => emptyPrefs(scope));
  const [loaded, setLoaded] = useState(false);
  const [dropped, setDropped] = useState(0);
  const [failed, setFailed] = useState(false);
  /** What is actually on disk, encoded. `null` means nothing is. */
  const [clean, setClean] = useState<string | null>(null);

  /* `alive` is rebuilt on every render of the caller, so it cannot be a
     dependency — it would re-run this effect forever. The scene is a build-time
     constant, so reading the current set once at mount is correct and the ref
     is what keeps the effect honest about that. */
  const aliveRef = useRef(alive);
  aliveRef.current = alive;

  useEffect(() => {
    if (!enabled) {
      setLoaded(true);
      return;
    }
    const stored = loadPrefs(scope);
    if (!stored) {
      setLoaded(true);
      return;
    }
    const { prefs: kept, dropped: gone } = prune(stored, aliveRef.current);
    setPrefs(kept);
    setDropped(gone);
    /* The CLEAN baseline is what was READ, not what was kept. Pruning is a
       real change to the document, so a load that dropped two dead pins leaves
       the reader with something worth saving — and the bar says so. */
    setClean(encode(stored));
    setLoaded(true);
  }, [scope, enabled]);

  const update = useCallback((fn: (p: Prefs) => Prefs) => {
    setFailed(false);
    setPrefs(fn);
  }, []);

  const save = useCallback(() => {
    if (!enabled) return;
    const ok = savePrefs(prefs);
    setFailed(!ok);
    if (ok) setClean(encode(prefs));
  }, [enabled, prefs]);

  const reset = useCallback(() => {
    if (enabled) clearPrefs(scope);
    setPrefs(emptyPrefs(scope));
    setDropped(0);
    setFailed(false);
    setClean(null);
  }, [enabled, scope]);

  const customised = useMemo(() => isCustomised(prefs), [prefs]);
  /* Compared on the ENCODED form, so key order and object identity cannot make
     an untouched document read as dirty. `savedAt` is stamped inside
     `savePrefs` rather than on the value held here, which is what keeps this
     comparison stable across a save. */
  const dirty = useMemo(
    () => loaded && enabled && (clean ?? encode(emptyPrefs(scope))) !== encode(prefs),
    [loaded, enabled, clean, prefs, scope],
  );

  return { prefs, loaded, dropped, customised, dirty, failed, update, save, reset };
}
