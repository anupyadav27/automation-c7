/**
 * Packing a band of category lanes into balanced columns.
 *
 * A band holds one lane per category — datastore, integration, serverless — and
 * each lane holds subcategory blocks. Drawn as one column per lane, the band is
 * as tall as its WORST lane while its best lanes use a fraction of that height.
 * On the live estate that is 518px of band because datastore stacks object,
 * nosql and file, next to two lanes 62px tall. Everything below 518px in those
 * two columns is dead canvas.
 *
 * The fix is to spend width on the tall ones: datastore drawn as
 * object │ nosql │ file side by side is a third of the height it was. Balancing
 * by column ALLOCATION rather than by ragged packing is what lets the grid stay
 * a grid — `measureContainer` puts the reason plainly, "ragged cells read as
 * misalignment, not as data".
 *
 * Everything here is pure arithmetic over measured heights. No React, no DOM,
 * no scene vocabulary — the renderer measures, this decides, the renderer draws.
 */

/** One subcategory's worth of a lane: object, nosql, file. Already measured. */
export type Block = { key: string; h: number };

/** A category lane, in the reading order its subcategory ranks gave it. */
export type LaneShape<T extends Block = Block> = { key: string; rank: number; blocks: T[] };

/** Vertical space between stacked blocks. Mirrors GAP in layout-metrics. */
const GAP = 6;

/** A run of blocks drawn as one column: their heights, plus the gaps between. */
export const columnHeight = (blocks: Block[]) =>
  blocks.reduce((t, b) => t + b.h, 0) + Math.max(0, blocks.length - 1) * GAP;

/**
 * Split one lane's blocks into `cols` columns, minimising the tallest.
 *
 * **Contiguous**, always. Subcategories carry `sub_rank`, which is reading
 * order, so a split may choose WHERE to cut but never which side a block lands.
 * A free assignment would pack marginally better and would reorder the lane.
 *
 * Exhaustive rather than clever: a lane has at most a handful of subcategories
 * — eight is the largest any category in the model declares — so every cut is
 * tried and the best kept. Anything asymptotically better would be harder to
 * predict without being more correct at this size.
 */
export function splitLane<T extends Block>(blocks: T[], cols: number): T[][] {
  const n = blocks.length;
  if (n === 0) return [];
  // More columns than blocks cannot help: a block is indivisible, so the extra
  // columns would be empty and the height would not move.
  const k = Math.max(1, Math.min(cols, n));
  if (k === 1) return [blocks];
  if (k === n) return blocks.map((b) => [b]);

  let best: T[][] | null = null;
  let bestTallest = Infinity;

  const cut = (start: number, left: number, parts: T[][], tallest: number) => {
    if (left === 1) {
      const last = blocks.slice(start);
      const height = Math.max(tallest, columnHeight(last));
      // Strict `<`, so the FIRST arrangement of a given height wins and the
      // answer never depends on iteration order.
      if (height < bestTallest) {
        bestTallest = height;
        best = [...parts, last];
      }
      return;
    }
    for (let end = start + 1; end <= n - left + 1; end += 1) {
      const part = blocks.slice(start, end);
      const height = Math.max(tallest, columnHeight(part));
      // Already worse than the best complete answer, and adding columns can
      // only keep it or raise it.
      if (height >= bestTallest) continue;
      cut(end, left - 1, [...parts, part], height);
    }
  };
  cut(0, k, [], 0);
  return best ?? [blocks];
}

/** The tallest column a lane would have if it were given `cols` columns. */
export const laneHeight = (lane: LaneShape<Block>, cols: number) =>
  Math.max(0, ...splitLane(lane.blocks, cols).map(columnHeight));

/**
 * How many columns each lane gets, spending `budget` to make the band short.
 *
 * Greedy water-filling: every lane starts with one column, then each spare
 * column goes to whichever lane is currently tallest and can still use one. The
 * band's height is the tallest lane, so lowering the tallest is the only move
 * that lowers the band — every other spend is wasted width.
 *
 * A lane that already has one column per block is skipped: a block is
 * indivisible, so more columns would buy nothing and take width from a lane
 * that could have used it.
 *
 * Ties break on lane key. Without it the result would depend on Map iteration
 * order, which is insertion order, which is whatever the scene happened to
 * serialise — the same estate could pack two ways.
 */
export function allocate(lanes: LaneShape<Block>[], budget: number): Map<string, number> {
  const cols = new Map<string, number>(lanes.map((l) => [l.key, 1]));
  if (!lanes.length) return cols;

  let spare = budget - lanes.length;
  while (spare > 0) {
    let pick: LaneShape<Block> | null = null;
    let tallest = -1;
    for (const lane of lanes) {
      const has = cols.get(lane.key)!;
      if (has >= lane.blocks.length) continue; // nothing left to split
      const h = laneHeight(lane, has);
      if (h > tallest || (h === tallest && pick && lane.key < pick.key)) {
        tallest = h;
        pick = lane;
      }
    }
    if (!pick) break; // every lane is fully split; the rest of the budget is spare
    cols.set(pick.key, cols.get(pick.key)! + 1);
    spare -= 1;
  }
  return cols;
}

/** The tallest lane in a band — which is the band's own height. */
export const bandHeight = (lanes: LaneShape<Block>[], cols: Map<string, number>) =>
  Math.max(0, ...lanes.map((l) => laneHeight(l, cols.get(l.key) ?? 1)));

/**
 * Flow lanes into rows, never exceeding `perRow` columns in one row.
 *
 * **Rank order is not negotiable.** Reading order is the traffic path (A1), so a
 * later lane is never pulled forward to fill a gap, however much better it would
 * pack. A lane that will not fit starts a new row.
 *
 * A lane wider than a whole row gets its own row rather than being dropped —
 * overflowing is visible and recoverable, vanishing is neither.
 */
export function packRows<T extends Block>(
  lanes: LaneShape<T>[],
  cols: Map<string, number>,
  perRow: number,
): LaneShape<T>[][] {
  const ordered = [...lanes].sort((a, b) => a.rank - b.rank || a.key.localeCompare(b.key));
  const rows: LaneShape<T>[][] = [];
  let row: LaneShape<T>[] = [];
  let used = 0;
  for (const lane of ordered) {
    const width = Math.max(1, cols.get(lane.key) ?? 1);
    if (row.length && used + width > Math.max(1, perRow)) {
      rows.push(row);
      row = [];
      used = 0;
    }
    row.push(lane);
    used += width;
  }
  if (row.length) rows.push(row);
  return rows;
}

/**
 * How many columns the band may spend.
 *
 * The width is not ours to choose: the container is already as wide as its
 * widest child — the VPC — and a band narrower than that leaves dead space to
 * its right while a wider one makes the container grow for nothing. So the band
 * takes the room that already exists and spends it on being short.
 *
 * Deliberately NOT scored against `ASPECT`. That target is right for a container
 * free to choose its own shape and wrong for a band whose width is fixed by its
 * siblings: a band is already wider than it is tall, so aspect scoring picks the
 * fewest columns every time and the tall lane never gets split.
 *
 * Measured, never observed — `widest` comes from the same bottom-up pass that
 * sizes everything else, so one estate gives one answer on any screen.
 */
export function columnBudget(widest: number, columnWidth: number, lanes: number) {
  if (!(widest > 0) || !(columnWidth > 0)) return lanes;
  return Math.max(lanes, Math.floor((widest + GAP) / (columnWidth + GAP)));
}
