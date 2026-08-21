import { chromium } from "playwright";

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1800, height: 1200 } });
const errs = [];
p.on("pageerror", (e) => errs.push(String(e)));
const log = (n, ok, d = "") => console.log(`${ok ? "PASS" : "FAIL"}  ${n}${d ? "  — " + d : ""}`);

await p.goto("http://localhost:3200/architecture", { waitUntil: "networkidle" });
await p.evaluate(() => localStorage.clear());
await p.reload({ waitUntil: "networkidle" });
await p.waitForTimeout(2500);

// The regression: text inside a box must be selectable again.
const selectable = await p.evaluate(() => {
  const box = document.querySelector("[data-canvas] .group\\/ord");
  if (!box) return null;
  // A `draggable` ancestor is what suppressed selection across the subtree.
  let n = box,
    draggableAncestors = 0;
  while (n && n !== document.body) {
    if (n.getAttribute?.("draggable") === "true") draggableAncestors++;
    n = n.parentElement;
  }
  return draggableAncestors;
});
log("box is not itself draggable", selectable === 0, `${selectable} draggable ancestors`);

const grips = await p.locator('[aria-label^="drag to reorder"]').count();
log("grip handles exist", grips > 0, `${grips} grips`);

// Order of the top-level units, read from the shared parent.
const order = () =>
  p.evaluate(() => {
    const first = document.querySelector("[data-canvas] .group\\/ord");
    return [...(first?.parentElement?.children ?? [])].map(
      (c) => c.textContent?.trim().slice(0, 22) ?? "?",
    );
  });

const before = await order();

// Real HTML5 drag: grip of unit 0 -> body of unit 2.
const src = p.locator("[data-canvas] .group\\/ord").nth(0);
const dst = p.locator("[data-canvas] .group\\/ord").nth(2);
await src.scrollIntoViewIfNeeded();
await src.hover();
await p.waitForTimeout(250);
const grip = src.locator('[aria-label^="drag to reorder"]').first();
const g = await grip.boundingBox();
const d = await dst.boundingBox();
if (g && d) {
  await p.mouse.move(g.x + g.width / 2, g.y + g.height / 2);
  await p.mouse.down();
  await p.mouse.move(d.x + d.width / 2, d.y + 20, { steps: 20 });
  await p.mouse.move(d.x + d.width / 2, d.y + 24, { steps: 5 });
  await p.mouse.up();
  await p.waitForTimeout(700);
}
const after = await order();
log("drag by grip reorders", JSON.stringify(before) !== JSON.stringify(after));
console.log("   before:", JSON.stringify(before.slice(0, 3)));
console.log("   after: ", JSON.stringify(after.slice(0, 3)));

/* A reorder PERMUTES — the same units, in a different sequence. Counting
   tiles is the wrong probe (groups collapse to one tile each, so 1,033
   resources draw as ~59); what must hold is that nothing was added, dropped,
   or swallowed by a neighbouring container. */
const sameSet =
  before.length === after.length &&
  JSON.stringify([...before].sort()) === JSON.stringify([...after].sort());
log("reorder permutes, never adds or drops", sameSet, `${before.length} units both sides`);

const shown = await p.evaluate(
  () => document.body.textContent.match(/([\d,]+) of ([\d,]+) resources shown/)?.[0],
);
log(
  "resource count unchanged by the drag",
  /^([\d,]+) of \1 resources shown$/.test(shown ?? ""),
  shown,
);

console.log(errs.length ? "\nERRORS:\n" + errs.slice(0, 4).join("\n") : "\nno page errors");
await b.close();
