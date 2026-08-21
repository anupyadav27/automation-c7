/**
 * Reading order, and the reader's right to override it.
 *
 * The engine decides where a box GOES — that is `layout-metrics.ts` sizing it
 * and `pack.ts` packing it, bottom-up, with no coordinate anywhere. This module
 * decides only the SEQUENCE its siblings are drawn in, which is the one part of
 * placement a reader may reasonably disagree with: rank encodes the traffic
 * path, and an operator who reads their estate front-to-back a different way is
 * not wrong, they are looking at a different question.
 *
 * The line this must not cross is stated in `diagram-layout-spec.md` §10: one
 * estate draws one diagram. An override is therefore a PERMUTATION of what the
 * engine already produced, never a coordinate and never a filter. Nothing here
 * can add a box, remove one, or move one to a different parent — so the worst a
 * corrupt preference can do is order things oddly, and `applyOrder` with no
 * preference is the identity function.
 *
 * Pure arithmetic over keys. No React, no DOM, no scene vocabulary.
 */

/** Anything orderable: a sub-container, a rule wrap, a cluster, a lane. */
export type Unit = { key: string };

/**
 * The identity of a row of availability zones.
 *
 * Content-derived, and that is the whole point. This was `zones-${i}` — the
 * row's index in the container's row list — which is not an identity at all:
 * it names a POSITION, so the moment anything before it appears or disappears
 * the same row answers to a different name. Harmless while nothing remembered
 * it; fatal the moment a saved order does, because the preference rebinds onto
 * whichever row happens to hold that index next time.
 *
 * Sorted before joining, so the key survives the row's own members being
 * reordered — which is exactly what this module exists to let a reader do. An
 * identity that changed when its contents were rearranged would evaporate on
 * first use.
 */
export function zoneRowKey(zones: Unit[]): string {
  return `zones:${zones
    .map((z) => z.key)
    .sort()
    .join("|")}`;
}

/**
 * Reorder `units` to match a saved sequence, keeping the engine's answer for
 * everything the sequence does not mention.
 *
 * Three properties, each of which is a test:
 *
 * 1. **No preference is the identity.** An absent or empty `sequence` returns
 *    the input unchanged — same array contents, same order. This is what keeps
 *    the determinism contract true for every reader who never drags anything.
 * 2. **Unknown keys are ignored, not honoured.** A saved sequence naming a
 *    resource that no longer exists must not leave a hole or throw; the estate
 *    changed and the preference is simply stale in that one slot.
 * 3. **New keys append, in engine order.** A resource that appeared after the
 *    order was saved goes after everything the reader arranged, in the sequence
 *    the engine would have given it. Stated rather than emergent, so a reader
 *    can predict where next month's subnet will show up.
 *
 * `units` is assumed already in engine order — the caller sorts by rank first,
 * and this permutes that result rather than replacing it.
 */
export function applyOrder<T extends Unit>(units: T[], sequence?: readonly string[]): T[] {
  if (!sequence?.length || units.length < 2) return units;

  // Rank by saved position; anything unnamed sorts after everything named.
  const at = new Map<string, number>();
  sequence.forEach((key, i) => {
    // First mention wins, so a malformed preference with a duplicated key is
    // still a total order rather than an arbitrary one.
    if (!at.has(key)) at.set(key, i);
  });

  // Nothing in this container is mentioned — leave the engine's answer alone
  // rather than paying for a sort that cannot change anything.
  if (!units.some((u) => at.has(u.key))) return units;

  const saved = units.filter((u) => at.has(u.key));
  const fresh = units.filter((u) => !at.has(u.key));
  saved.sort((a, b) => at.get(a.key)! - at.get(b.key)!);
  return [...saved, ...fresh];
}

/**
 * The sequence to store after a reader moves `key` to index `to`.
 *
 * Returns the FULL order of what is currently on screen, not a sparse patch.
 * A patch would need the engine's answer to interpret it, and the engine's
 * answer changes between scans — so a stored patch means a stored order that
 * silently re-reads itself. A full list is self-contained: it says what the
 * reader saw and what they wanted, and §7's append rule handles the rest.
 */
export function moveTo<T extends Unit>(units: T[], key: string, to: number): string[] {
  const from = units.findIndex((u) => u.key === key);
  if (from < 0) return units.map((u) => u.key);
  const keys = units.map((u) => u.key);
  const [moved] = keys.splice(from, 1);
  keys.splice(Math.max(0, Math.min(to, keys.length)), 0, moved!);
  return keys;
}
