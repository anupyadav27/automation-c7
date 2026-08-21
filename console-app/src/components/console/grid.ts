/**
 * Placing a box in a CELL, rather than merely ahead of its neighbour.
 *
 * `order.ts` lets a reader change the SEQUENCE its siblings are drawn in. That
 * answers "which comes first" and not "put it over there" — a dropped box takes
 * a position in a run and everything shuffles around it, so a reader who wants
 * a gap, or two things side by side with nothing between, cannot say so.
 *
 * This is the next notch of freedom, and deliberately not the last one. A cell
 * is a (row, column) in the container's own grid, which buys three things a
 * stored pixel coordinate cannot:
 *
 * - **Boxes still cannot overlap.** A cell holds one unit. Overlap is not a
 *   state the reader can reach, so nothing has to repair it when a box grows
 *   between scans.
 * - **Intrinsic sizing survives.** Columns are `max-content`, so a box is still
 *   as wide as what it holds and the engine still decides its size. Only WHERE
 *   it sits becomes the reader's.
 * - **It still reflows, and still exports.** A grid re-lays itself at any
 *   width; absolute coordinates do not, and the same estate would then print
 *   differently from how it drew.
 *
 * Pure arithmetic over keys and integers. No React, no DOM.
 */

export type Unit = { key: string };
/** Zero-based (row, column) within one container's grid. */
export type Cell = [row: number, col: number];
export type Cells = Record<string, Cell>;

export type Placed<T> = { unit: T; row: number; col: number };

const at = (row: number, col: number) => `${row},${col}`;

/** A cell that is actually a cell: two non-negative integers, in bounds. */
export function validCell(c: unknown, cols: number): c is Cell {
  return (
    Array.isArray(c) &&
    c.length === 2 &&
    Number.isInteger(c[0]) &&
    Number.isInteger(c[1]) &&
    c[0] >= 0 &&
    c[1] >= 0 &&
    c[1] < cols
  );
}

/**
 * How wide the grid has to be to hold what the reader arranged.
 *
 * At least the engine's own column count, and at least one past the furthest
 * column anything was placed in — otherwise a box parked at column 5 of a
 * three-column container would be silently pulled back to a column that exists,
 * which is the reader's arrangement being overruled without being told.
 */
export function gridCols(cells: Cells | undefined, engineCols: number): number {
  let widest = 0;
  for (const c of Object.values(cells ?? {})) {
    if (Array.isArray(c) && Number.isInteger(c[1])) widest = Math.max(widest, c[1] + 1);
  }
  return Math.max(1, engineCols, widest);
}

/**
 * Resolve every unit to a cell.
 *
 * Returns `null` when the reader has placed nothing — the caller then draws the
 * container exactly as it always did, which is what keeps the determinism
 * contract true for anyone who never arranges anything.
 *
 * Three rules, each of which is a test:
 *
 * 1. **A stored cell is honoured**, unless it is malformed or already taken by
 *    an earlier unit. First writer wins, so the result never depends on object
 *    key order.
 * 2. **Gaps are preserved.** An unplaced unit does NOT fill the first hole it
 *    finds — a hole is very often the point of the arrangement. It lands after
 *    the last occupied cell in reading order, which is the same "new arrivals
 *    append" rule the sequence override uses.
 * 3. **Nothing is ever dropped.** Every unit comes back with a cell, so a
 *    corrupt preference can misplace a box but can never disappear one.
 */
export function layoutGrid<T extends Unit>(
  units: T[],
  cells: Cells | undefined,
  cols: number,
): Placed<T>[] | null {
  if (!cells || !Object.keys(cells).length) return null;
  const width = Math.max(1, cols);
  const taken = new Map<string, T>();
  const placed: Placed<T>[] = [];
  const rest: T[] = [];

  for (const u of units) {
    const c = cells[u.key];
    if (validCell(c, width) && !taken.has(at(c[0], c[1]))) {
      taken.set(at(c[0], c[1]), u);
      placed.push({ unit: u, row: c[0], col: c[1] });
    } else {
      rest.push(u);
    }
  }

  // Where the arrangement ends, in reading order. Everything new lands after it.
  let cursor = -1;
  for (const p of placed) cursor = Math.max(cursor, p.row * width + p.col);

  for (const u of rest) {
    do cursor += 1;
    while (taken.has(at(Math.floor(cursor / width), cursor % width)));
    const row = Math.floor(cursor / width);
    const col = cursor % width;
    taken.set(at(row, col), u);
    placed.push({ unit: u, row, col });
  }

  return placed.sort((a, b) => a.row - b.row || a.col - b.col);
}

/** Rows the grid needs, given what is placed in it. */
export const gridRows = <T>(placed: Placed<T>[]) =>
  placed.reduce((m, p) => Math.max(m, p.row + 1), 1);

/**
 * Spare rows offered below the arrangement, for moving DOWN into.
 *
 * Two, not one. One spare row means the vertical range is exactly one step: a
 * reader drags a box to the bottom, the grid grows by a row, and the only
 * target below is again a single row away — so moving something a clear
 * distance down takes as many separate drags as rows travelled, and the
 * gesture reads as though it will not go any further. Two rows makes the
 * headroom visible, which is what tells a reader the direction is available at
 * all.
 */
export const SPARE_ROWS = 2;

/**
 * The cells to draw as empty drop targets while arranging.
 *
 * Spare rows beyond the last occupied one, so a reader can always move a box
 * DOWN into new space. Without them the grid can only be rearranged within the
 * bounds it already has, and "put it below everything" — the most obvious thing
 * to want — is the one move that is impossible.
 */
export function emptyCells<T>(placed: Placed<T>[], cols: number, spare = SPARE_ROWS): Cell[] {
  const taken = new Set(placed.map((p) => at(p.row, p.col)));
  const rows = gridRows(placed) + Math.max(1, spare);
  const out: Cell[] = [];
  for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < Math.max(1, cols); c += 1) {
      if (!taken.has(at(r, c))) out.push([r, c]);
    }
  }
  return out;
}

/**
 * Put `key` in a cell, and say what the whole container looks like afterwards.
 *
 * Returns a FULL map rather than a patch, for the same reason the sequence
 * override stores a full order: a patch needs the engine's answer in order to
 * be interpreted, and the engine's answer changes between scans.
 *
 * Landing on an occupied cell SWAPS. Displacing the occupant into the mover's
 * old cell keeps the arrangement conserved — no box is evicted to nowhere, and
 * no hole opens where the reader did not ask for one. Dropping onto empty space
 * simply moves.
 */
export function moveToCell<T extends Unit>(
  placed: Placed<T>[],
  key: string,
  row: number,
  col: number,
): Cells {
  const out: Cells = {};
  for (const p of placed) out[p.unit.key] = [p.row, p.col];
  const from = out[key];
  if (!from) return out;
  const occupant = placed.find((p) => p.row === row && p.col === col && p.unit.key !== key);
  out[key] = [row, col];
  if (occupant) out[occupant.unit.key] = from;
  return out;
}

/** One step from a cell, clamped into the grid. Used by the keyboard path. */
export function step(cell: Cell, dir: "up" | "down" | "left" | "right", cols: number): Cell {
  const [r, c] = cell;
  if (dir === "left") return [r, Math.max(0, c - 1)];
  if (dir === "right") return [r, Math.min(Math.max(0, cols - 1), c + 1)];
  if (dir === "up") return [Math.max(0, r - 1), c];
  return [r + 1, c];
}

/**
 * The cells a container starts from, when a reader first arranges it.
 *
 * Arranging has to begin from what is already on screen, or the first drag
 * would rearrange everything else as a side effect. This freezes the engine's
 * current reading order into explicit cells, after which the reader is moving
 * boxes rather than authoring a layout from nothing.
 */
export function seedCells<T extends Unit>(units: T[], cols: number): Cells {
  const width = Math.max(1, cols);
  const out: Cells = {};
  units.forEach((u, i) => {
    out[u.key] = [Math.floor(i / width), i % width];
  });
  return out;
}
