import { describe, expect, it } from "vitest";
import {
  emptyCells,
  gridCols,
  gridRows,
  layoutGrid,
  moveToCell,
  seedCells,
  step,
  validCell,
  type Cells,
} from "./grid";

const u = (...keys: string[]) => keys.map((key) => ({ key }));
const shape = <T extends { key: string }>(placed: { unit: T; row: number; col: number }[]) =>
  placed.map((p) => `${p.unit.key}@${p.row},${p.col}`);

describe("validCell", () => {
  it("accepts two non-negative integers in bounds", () => {
    expect(validCell([0, 0], 3)).toBe(true);
    expect(validCell([4, 2], 3)).toBe(true);
  });

  it("rejects anything else", () => {
    for (const bad of [null, [0], [0, 1, 2], ["0", 1], [-1, 0], [0, -1], [0.5, 0], [0, 3]]) {
      expect(validCell(bad, 3)).toBe(false);
    }
  });
});

describe("gridCols", () => {
  it("is the engine's own count when nothing is placed", () => {
    expect(gridCols(undefined, 3)).toBe(3);
    expect(gridCols({}, 2)).toBe(2);
  });

  it("widens to hold a box parked past the engine's last column", () => {
    // Otherwise the reader's arrangement is overruled without being told.
    expect(gridCols({ a: [0, 5] }, 3)).toBe(6);
  });

  it("never narrows below the engine", () => {
    expect(gridCols({ a: [0, 0] }, 4)).toBe(4);
  });
});

describe("layoutGrid", () => {
  it("returns null when the reader has placed nothing", () => {
    expect(layoutGrid(u("a", "b"), undefined, 2)).toBeNull();
    expect(layoutGrid(u("a", "b"), {}, 2)).toBeNull();
  });

  it("honours stored cells", () => {
    const cells: Cells = { a: [1, 1], b: [0, 0] };
    expect(shape(layoutGrid(u("a", "b"), cells, 2)!)).toEqual(["b@0,0", "a@1,1"]);
  });

  /* The whole reason this module exists: a deliberate hole must survive. */
  it("preserves a gap rather than filling it", () => {
    const cells: Cells = { a: [0, 0], b: [0, 2] };
    const out = layoutGrid(u("a", "b", "c"), cells, 3)!;
    // `c` is unplaced. It must NOT land in the empty (0,1) the reader left.
    expect(shape(out)).toEqual(["a@0,0", "b@0,2", "c@1,0"]);
  });

  it("appends new arrivals after the last occupied cell", () => {
    const cells: Cells = { a: [0, 0] };
    const out = layoutGrid(u("a", "new1", "new2"), cells, 2)!;
    expect(shape(out)).toEqual(["a@0,0", "new1@0,1", "new2@1,0"]);
  });

  it("never drops a unit, however corrupt the cells", () => {
    const cells = { a: [0, 0], b: "nonsense", c: [-3, 9], d: [0, 0] } as unknown as Cells;
    const out = layoutGrid(u("a", "b", "c", "d"), cells, 2)!;
    expect(out).toHaveLength(4);
    expect([...out.map((p) => p.unit.key)].sort()).toEqual(["a", "b", "c", "d"]);
  });

  it("gives a duplicated cell to the first unit only", () => {
    // First writer wins, so the answer never depends on object key order.
    const cells: Cells = { a: [0, 0], b: [0, 0] };
    const out = layoutGrid(u("a", "b"), cells, 2)!;
    expect(out.find((p) => p.unit.key === "a")).toMatchObject({ row: 0, col: 0 });
    expect(out.find((p) => p.unit.key === "b")).not.toMatchObject({ row: 0, col: 0 });
  });

  it("never places two units in one cell", () => {
    const cells: Cells = { a: [0, 0], b: [0, 0], c: [0, 0] };
    const out = layoutGrid(u("a", "b", "c", "d"), cells, 2)!;
    const seen = new Set(out.map((p) => `${p.row},${p.col}`));
    expect(seen.size).toBe(out.length);
  });
});

describe("emptyCells", () => {
  it("offers a spare row past the last occupied one", () => {
    // Without it, "put it below everything" is impossible.
    const placed = layoutGrid(u("a"), { a: [0, 0] }, 2)!;
    expect(emptyCells(placed, 2)).toContainEqual([1, 0]);
  });

  it("offers the gaps inside the arrangement", () => {
    const placed = layoutGrid(u("a", "b"), { a: [0, 0], b: [0, 2] }, 3)!;
    expect(emptyCells(placed, 3)).toContainEqual([0, 1]);
  });

  it("never offers an occupied cell", () => {
    const placed = layoutGrid(u("a", "b"), { a: [0, 0], b: [0, 1] }, 2)!;
    const taken = new Set(placed.map((p) => `${p.row},${p.col}`));
    for (const [r, c] of emptyCells(placed, 2)) expect(taken.has(`${r},${c}`)).toBe(false);
  });
});

describe("moveToCell", () => {
  const placed = () => layoutGrid(u("a", "b", "c"), { a: [0, 0], b: [0, 1], c: [1, 0] }, 2)!;

  it("moves into empty space", () => {
    expect(moveToCell(placed(), "c", 1, 1)).toMatchObject({ c: [1, 1] });
  });

  it("swaps with an occupant rather than evicting it", () => {
    const out = moveToCell(placed(), "a", 0, 1);
    expect(out["a"]).toEqual([0, 1]);
    expect(out["b"]).toEqual([0, 0]);
  });

  it("conserves the arrangement — same units, same cell count", () => {
    const out = moveToCell(placed(), "a", 1, 0);
    expect(Object.keys(out).sort()).toEqual(["a", "b", "c"]);
    expect(new Set(Object.values(out).map(String)).size).toBe(3);
  });

  it("is a no-op for a key it does not hold", () => {
    const out = moveToCell(placed(), "ghost", 0, 0);
    expect(out).toMatchObject({ a: [0, 0], b: [0, 1], c: [1, 0] });
  });

  it("round-trips through layoutGrid", () => {
    const moved = moveToCell(placed(), "c", 0, 0);
    const out = layoutGrid(u("a", "b", "c"), moved, 2)!;
    expect(shape(out)).toContain("c@0,0");
    expect(shape(out)).toContain("a@1,0");
  });
});

describe("step", () => {
  it("moves one cell and clamps at the edges", () => {
    expect(step([1, 1], "left", 3)).toEqual([1, 0]);
    expect(step([1, 0], "left", 3)).toEqual([1, 0]);
    expect(step([1, 2], "right", 3)).toEqual([1, 2]);
    expect(step([0, 1], "up", 3)).toEqual([0, 1]);
  });

  it("lets a box go down into a new row", () => {
    expect(step([0, 1], "down", 3)).toEqual([1, 1]);
  });
});

describe("seedCells", () => {
  it("freezes the current reading order into cells", () => {
    expect(seedCells(u("a", "b", "c"), 2)).toEqual({ a: [0, 0], b: [0, 1], c: [1, 0] });
  });

  it("is a fixed point — seeding then laying out changes nothing", () => {
    const units = u("a", "b", "c", "d", "e");
    const seeded = seedCells(units, 3);
    expect(shape(layoutGrid(units, seeded, 3)!)).toEqual([
      "a@0,0",
      "b@0,1",
      "c@0,2",
      "d@1,0",
      "e@1,1",
    ]);
  });
});
