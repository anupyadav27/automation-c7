/**
 * Intrinsic sizing — a box is as big as what it holds.
 *
 * Computed BOTTOM-UP: the chip has a fixed size, a group is as tall as the
 * chips it shows, a container is as big as the grid of groups inside it. The
 * parent never divides space among its children; the children report what they
 * need and the parent adds up.
 *
 * That inversion is the whole point. Top-down sizing asks the browser how much
 * room there is, so the same estate draws differently on a laptop and a
 * monitor, and neither matches what an export would produce. Bottom-up gives
 * one answer for one estate, on any screen, at any zoom, in any output.
 *
 * Every number here is in CSS pixels and stated once. Nothing in the renderer
 * may invent its own.
 */

/** The atoms. A chip is one line: no icon (its group carries that), one name. */
/* 190, not 150. A chip carries its name AND the codes for whatever governs it,
   and at 150 the codes won an argument they should never have been in: an
   instance rendered as `e  sg-2 iam-2 2` — one character of name, because the
   badges are fixed and the name was the only thing that could give. A name that
   cannot be recognised is not a label, and the whole point of a chip is to say
   which resource this is. */
export const CHIP_W = 190;
export const CHIP_H = 26;
export const GAP = 6;
export const PAD = 8;
export const HEADER = 22;

/* ── rails: how far a border's tabs stick out ──────────────────────────
 *
 * A tab lies WHOLLY outside the box it names, so the box has to reserve room
 * for it or the two collide — and the room needed is a function of how many
 * layers deep that arm runs, which is why it has to be computed rather than
 * picked.
 *
 * `RAIL_V` is stated, not measured, and that is the point. Left to its content
 * a vertical tab came out anywhere between 28px and 42px wide, because the
 * label runs down it and longer labels are wider. A parent cannot reserve space
 * for something whose extent depends on its text: reserve 28 and the long ones
 * overlap, reserve 42 and every short one leaves a ragged margin. Same defect
 * as a chip whose height depended on its badges, and the same fix — fix the
 * dimension and let the label truncate.
 */
/**
 * A tab's depth — how far it reaches out from the border it names.
 *
 * ONE number for all four sides. It was two — 40 out from a side wall, 20 below
 * a line — so the same object drew twice as thick on the east wall as on the
 * north, and a reader saw two kinds of tab where there is one. Depth is the
 * dimension a tab does not use to say anything: the label runs ALONG the
 * border, so across it there is only ever one line of text, and one line of
 * text is one thickness whichever way it is turned.
 *
 * 26 = an 11px line (15) + 4px of padding either side + the border. The old 40
 * left 17px of dead space inside every vertical tab and charged the diagram for
 * it on both sides of every box.
 */
export const RAIL_DEPTH = 26;
/** Kept as names for the two axes; both resolve to the same depth. */
export const RAIL_V = RAIL_DEPTH;
export const RAIL_H = RAIL_DEPTH;
/** Between two layers of the same arm. Tight: they are one set. */
export const LAYER_GAP = 4;
/** Between the outermost layer and whatever lies beyond it. */
export const EDGE_GAP = 16;

/**
 * How much room a container must reserve on one side.
 *
 * The margin the box needs so that `layers` deep of tabs sit outside it without
 * touching a sibling, a parent's border, or another container's rail. Zero when
 * the arm carries nothing — an empty arm must not pay for space it never uses,
 * or every box in the estate is indented for rails three of them do not have.
 *
 * Nesting works because this is a MARGIN, not padding: a child's tabs live
 * outside the child and inside the parent's content box, so the child's own
 * reservation is what separates it from its parent's border. Nothing has to
 * know how deep the tree goes.
 */
export function railClearance(side: "n" | "s" | "e" | "w", layers: number): number {
  if (layers <= 0) return 0;
  const depth = side === "n" || side === "s" ? RAIL_H : RAIL_V;
  return layers * depth + (layers - 1) * LAYER_GAP + EDGE_GAP;
}

/**
 * Chips a group shows before it collapses to a count.
 *
 * Five, because five is what the renderer draws. This constant said THREE for
 * as long as it has existed, while `ServiceGroup` capped its chip list at its
 * own `COLLAPSE_AT = 5` — so every group measured two chips shorter than it
 * drew, 64px each, and nothing in the toolchain compares the two numbers.
 *
 * That is the same defect as a declaration nothing reads, inverted: two numbers
 * that must agree, kept in separate files with nothing making them. The caps
 * now live here with the pixels they imply, and the renderer imports them
 * rather than declaring its own — which is what the header of this file already
 * claimed was true.
 *
 * The old comment argued three was "the largest value that keeps a group
 * shorter than the smallest real container". A reasonable argument, but it was
 * describing a layout that never shipped: groups have always drawn five.
 */
export const VISIBLE = 5;

/**
 * How long a rail tab runs along its border.
 *
 * Stated, not left to the content. `layersNeeded` divides the arm's length by
 * this to decide how many tabs fit in a column, while the tab itself was
 * capped at `max-h-[240px]` — so the arithmetic planned for 150px tabs and the
 * renderer drew up to 240px ones, and a west wall that measured as fitting
 * spilled past the bottom of the box it named. Same defect as a group that
 * measured five chips and drew seven: two numbers that must agree, kept apart.
 */
export const RAIL_TAB_LEN = 150;

/**
 * The longest a rail label may run before it truncates.
 *
 * Derived, not repeated. On a WALL the label is the tab — it runs down the
 * whole 150px — so the two are the same number by definition. On a horizontal
 * border the tab also carries an icon and a count, so the label is capped at
 * the same length and the tab comes out a little longer. Both were written as
 * a bare `150` in the markup, which is the same number twice with nothing
 * saying they were related, let alone that they must move together.
 */
export const RAIL_LABEL_MAX = RAIL_TAB_LEN;

/**
 * The narrowest a resource name may be squeezed before it stops being a name.
 *
 * A chip is `CHIP_W` wide and its badges are fixed, so the name is the only
 * thing that can give — and past this it has given too much: `onam-eks-…`
 * shortened to `e…` is not a label, it is a character. The floor is what makes
 * the chip truncate the RIGHT thing when it runs out of room.
 */
export const NAME_FLOOR = 70;

/**
 * Chips a group shows on a border rail.
 *
 * A rail runs alongside a box rather than inside it, so it has to stay shallow:
 * two names and a count, everything else on click.
 */
export const VISIBLE_TIGHT = 2;

/**
 * Target width:height for a container's grid of children.
 *
 * Landscape, because screens, slides and paper are landscape. A container that
 * packs its children into a tall thin column is technically compact and
 * practically unreadable next to its siblings.
 */
export const ASPECT = 1.6;

/* ── overlays: the panels that float over the diagram ──────────────────
 *
 * The canvas is sized bottom-up and the panels are not, and that is correct —
 * they are two different problems. A box on the canvas must be as big as what
 * it holds, because a parent has to reserve room for it. A panel has no parent
 * and no siblings; the only thing that constrains it is the window.
 *
 * What they share is the rule this file exists for: a dimension the arithmetic
 * depends on is stated ONCE. A panel's width was written twice — as
 * `w-[290px]` in the markup and as `290` passed to the placement helper — in
 * eight places between them, with nothing making the two agree. That is the
 * same defect as a group that measured five chips and drew seven, and it is
 * worse here, because the second copy decides whether the panel lands where it
 * was aimed.
 *
 * Widths are FIXED: a panel opens beside a tab, so the placement has to know
 * how wide it will be before it has drawn. Heights are a CEILING, not a size —
 * a list of two rows is 80px tall and a list of 250 is capped and scrolls,
 * because nothing downstream depends on how tall a panel turned out.
 */
export const PANEL = {
  /** Level one: the resources behind a tab, a tile or a heading. */
  list: { w: 290, maxH: 460 },
  /** Level two: one resource's detail, docked beside the list. */
  detail: { w: 360, maxH: 620 },
  /** The category filter, hanging from the bar above the canvas. */
  filter: { w: 320, maxH: 520 },
} as const;

/**
 * How many rows a list inside a panel shows before it scrolls, and how tall
 * that is.
 *
 * These two were `> 6` and `max-h-[168px]` sitting next to each other, and 168
 * only means anything as `6 × 28`. Written as literals, the day a row grew a
 * line the cell would have shown five and a half of them — the same defect as
 * a group that measured five chips and drew seven, at a smaller scale.
 */
export const PANEL_ROWS = 6;
export const PANEL_ROW_H = 28;
export const PANEL_SCROLL_AT = PANEL_ROWS * PANEL_ROW_H;

/** Between a panel and the thing it opened from. */
export const PANEL_GAP = 6;

/** Between a panel and the edge of the window. */
export const VIEWPORT_PAD = 12;

/**
 * The smallest window the console is designed to work in.
 *
 * Stated so the panel sizes can be TESTED against something rather than
 * assumed to fit. Two panels open side by side is the tightest case: a list
 * with its detail beside it must still leave the diagram visible, or the
 * reader has lost the thing they are reading about.
 */
export const MIN_VIEWPORT = { w: 1280, h: 720 };

export type Size = { w: number; h: number };

/** Which border a tab rides, and so which way its panel opens. */
export type Side = "n" | "s" | "w" | "e";

/** A rectangle a panel opens from, and the window it opens inside. */
export type Box = { x: number; y: number; w: number; h: number };

/**
 * Where a panel opens, given what it opened from and how much room there is.
 *
 * Pure, so the rule can be tested without a browser — the placement decides
 * whether a reader can see the thing they clicked, and it was previously only
 * checkable by opening the page and looking.
 *
 * Three rules, in order:
 *
 * 1. No side asked for, so it opens ON the thing. A tile, a heading or a
 *    container name sits IN the diagram, and what the panel covers is what the
 *    panel is about.
 *
 * 2. A side asked for, so it opens OUTWARD. A rail tab does not sit in the
 *    diagram, it rides a border, and the border has a side — opening on top of
 *    it puts the answer over the box the tab names.
 *
 * 3. Outward does not fit, so it FLIPS. This is what stops a detail panel
 *    landing on the list that produced it: a list opened from an east wall
 *    sits at the right edge, its detail has nowhere further right to go, and
 *    clamping put it straight over the rows the reader is moving between.
 *    The far side is the only other place it can be without covering its own
 *    parent.
 *
 * Clamping is last and only to the window. A panel pushed back on screen has
 * lost its anchor; a panel off screen has lost everything.
 */
export function placePanel(
  at: Box | undefined,
  panel: Size,
  side: Side | undefined,
  view: Size,
  gap = PANEL_GAP,
  pad = VIEWPORT_PAD,
): { left: number; top: number } {
  if (!at) return { left: 24, top: 88 };

  const fitsX = (x: number) => x >= pad && x + panel.w <= view.w - pad;
  const fitsY = (y: number) => y >= pad && y + panel.h <= view.h - pad;
  const east = at.x + at.w + gap;
  const west = at.x - panel.w - gap;
  const south = at.y + at.h + gap;
  const north = at.y - panel.h - gap;

  let x = at.x;
  let y = at.y;
  if (side === "e") x = fitsX(east) || !fitsX(west) ? east : west;
  else if (side === "w") x = fitsX(west) || !fitsX(east) ? west : east;
  else if (side === "s") y = fitsY(south) || !fitsY(north) ? south : north;
  else if (side === "n") y = fitsY(north) || !fitsY(south) ? north : south;

  return {
    left: Math.max(pad, Math.min(x, view.w - panel.w - pad)),
    top: Math.max(pad, Math.min(y, view.h - panel.h - pad)),
  };
}

/**
 * A chip. One line, always.
 *
 * It used to grow downward — a badge row, then up to four attachment lines — so
 * a Lambda carrying its aliases measured three times an S3 bucket carrying
 * nothing, and two groups of five chips came out different heights. Column
 * packing cannot fix raggedness that lives inside the cells.
 *
 * Now the tags sit on the name's own line and the attachment list has moved to
 * the panel, so every chip is `CHIP_H` and a group of n chips is a function of n
 * alone. That is what makes a band's columns line up.
 */
export function measureChip(): Size {
  return { w: CHIP_W, h: CHIP_H };
}

/**
 * A group: one row, whatever it holds.
 *
 * It used to be a header plus up to `visible` chips plus a truncation row, and
 * the height was a function of how many members happened to fit. It is now a
 * single tile — icon, name, count — because the names moved to the list panel,
 * which filters and scrolls and previews in a way a canvas cell never could.
 *
 * `members` is still taken, and still ignored for height, because the SHAPE of
 * this function is the contract: a caller passes what the group holds and gets
 * back what it will occupy. Making the count irrelevant to the answer is the
 * point — every tile is the same height, so a band's columns line up by
 * construction rather than by luck.
 */
export function measureGroup(members: Size[], _visible = VISIBLE): Size {
  const w = Math.max(...members.map((m) => m.w), CHIP_W);
  return { w: w + PAD * 2, h: CHIP_H + PAD };
}

/**
 * How many columns to arrange n children in, to land nearest the target aspect.
 *
 * This is where the container's shape is decided: `cols` is its horizontal arm
 * and `ceil(n/cols)` its vertical one. Searching every column count and keeping
 * the closest is exact and cheap — n is small, and anything cleverer would be
 * harder to predict without being more correct.
 */
export function chooseColumns(children: Size[], aspect = ASPECT): number {
  const n = children.length;
  if (n <= 1) return 1;
  const cw = Math.max(...children.map((c) => c.w));
  const ch = Math.max(...children.map((c) => c.h));
  let best = 1;
  let bestErr = Infinity;
  for (let cols = 1; cols <= n; cols += 1) {
    const rows = Math.ceil(n / cols);
    const ratio = (cols * cw) / (rows * ch);
    // Compare in log space so 2x too wide and 2x too tall score the same.
    const err = Math.abs(Math.log(ratio / aspect));
    if (err < bestErr) {
      bestErr = err;
      best = cols;
    }
  }
  return best;
}

/** A container: a grid of children, plus its own header and padding. */
export function measureContainer(
  children: Size[],
  opts: {
    cols?: number;
    header?: boolean;
    aspect?: number;
  } = {},
): Size & { cols: number } {
  if (!children.length) {
    return { w: CHIP_W + PAD * 2, h: HEADER + PAD * 2, cols: 1 };
  }
  const cols = opts.cols ?? chooseColumns(children, opts.aspect);
  const rows = Math.ceil(children.length / cols);
  // Column widths and row heights come from the widest and tallest member, so
  // a grid stays a grid - ragged cells read as misalignment, not as data.
  const cw = Math.max(...children.map((c) => c.w));
  const ch = Math.max(...children.map((c) => c.h));
  return {
    cols,
    w: cols * cw + (cols - 1) * GAP + PAD * 2,
    h: (opts.header === false ? 0 : HEADER) + rows * ch + (rows - 1) * GAP + PAD * 2,
  };
}
