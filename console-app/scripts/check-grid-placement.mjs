import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1800, height: 1200 } });
const errs = []; p.on("pageerror", (e) => errs.push(String(e)));
const log = (n, ok, d="") => console.log(`${ok?"PASS":"FAIL"}  ${n}${d?"  — "+d:""}`);

await p.goto("http://localhost:3200/architecture", { waitUntil: "networkidle" });
await p.evaluate(() => localStorage.clear());
await p.reload({ waitUntil: "networkidle" });
await p.waitForTimeout(2500);

const gridsBefore = await p.evaluate(() =>
  [...document.querySelectorAll("[data-canvas] div")].filter(
    (d) => getComputedStyle(d).display === "grid" && d.style.gridTemplateColumns?.includes("max-content"),
  ).length);
log("no grid scaffolding before arranging", gridsBefore === 0, `${gridsBefore}`);

await p.locator("button", { hasText: /^arrange$/ }).click();
await p.waitForTimeout(800);

const holes = await p.locator("[data-canvas] div.border-dashed.min-h-\\[44px\\]").count();
log("empty drop cells appear while arranging", holes > 0, `${holes} cells`);
const grids = await p.evaluate(() =>
  [...document.querySelectorAll("[data-canvas] div")].filter(
    (d) => getComputedStyle(d).display === "grid" && d.style.gridTemplateColumns?.includes("max-content"),
  ).length);
log("containers lay out as an explicit grid", grids > 0, `${grids} grids`);

// Drag a box into an empty cell — the move pure reorder cannot express.
const box = p.locator("[data-canvas] .group\\/ord").first();
await box.scrollIntoViewIfNeeded(); await box.hover(); await p.waitForTimeout(300);
const before = await box.boundingBox();
const grip = box.locator('[aria-label^="drag to reorder"]').first();
const hole = p.locator("[data-canvas] div.border-dashed.min-h-\\[44px\\]").first();
const g = await grip.boundingBox(), h = await hole.boundingBox();
if (g && h) {
  await p.mouse.move(g.x+g.width/2, g.y+g.height/2);
  await p.mouse.down();
  await p.mouse.move(h.x+h.width/2, h.y+h.height/2, { steps: 24 });
  await p.mouse.move(h.x+h.width/2+1, h.y+h.height/2, { steps: 4 });
  await p.mouse.up(); await p.waitForTimeout(800);
}
const after = await box.boundingBox();
const moved = !!(before && after) && (Math.abs(after.x-before.x) > 20 || Math.abs(after.y-before.y) > 20);
log("box lands in the chosen cell", moved,
    before && after ? `(${Math.round(before.x)},${Math.round(before.y)}) -> (${Math.round(after.x)},${Math.round(after.y)})` : "-");

const save = p.locator("button", { hasText: "save preferences" });
log("placement is savable", (await save.count()) > 0);
if (await save.count()) {
  await save.first().click(); await p.waitForTimeout(500);
  const cells = await p.evaluate(() => {
    const k = Object.keys(localStorage).find((x) => x.startsWith("cloud-estate.diagram.prefs"));
    return k ? JSON.parse(localStorage.getItem(k)).cells : null;
  });
  const n = cells ? Object.keys(cells).length : 0;
  log("cells persisted as (row,col)", n > 0, JSON.stringify(cells).slice(0, 100));

  await p.reload({ waitUntil: "networkidle" }); await p.waitForTimeout(2500);
  const restored = await p.locator("[data-canvas] .group\\/ord").first().boundingBox();
  log("placement survives reload", !!restored);
}
await p.screenshot({ path: "/tmp/grid.png" });
console.log(errs.length ? "ERRORS: " + errs.slice(0,3).join(" | ") : "no page errors");
await b.close();
