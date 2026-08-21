import { chromium } from "playwright";

const URL = "http://localhost:3200/architecture";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1800, height: 1200 } });
const errs = [];
p.on("pageerror", (e) => errs.push(String(e)));
p.on("console", (m) => m.type() === "error" && errs.push(m.text()));

const log = (name, ok, detail = "") =>
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);

await p.goto(URL, { waitUntil: "networkidle" });
await p.waitForTimeout(2500);

// ── 1. reorder ────────────────────────────────────────────────────────────
const order = () =>
  p.evaluate(() => {
    const wrap = document.querySelector("[data-canvas] .group\\/ord")?.parentElement;
    return [...(wrap?.children ?? [])]
      .map((c) => c.querySelector("[data-node]")?.getAttribute("data-node") ?? "?")
      .slice(0, 5);
  });

const before = await order();
const firstBox = p.locator("[data-canvas] .group\\/ord").first();
await firstBox.scrollIntoViewIfNeeded();
await firstBox.hover();
await p.waitForTimeout(300);
const later = firstBox.locator('button[aria-label^="move"][aria-label$="later"]').first();
const hasCtl = await later.count();
await later.click();
await p.waitForTimeout(500);
const after = await order();
log(
  "reorder: box moves later",
  hasCtl > 0 && JSON.stringify(before) !== JSON.stringify(after),
  `${before[0]} -> ${after[0]}`,
);

// ── 2. save button appears ────────────────────────────────────────────────
const save = p.locator("button", { hasText: "save preferences" });
log("preference bar: save appears when dirty", (await save.count()) > 0);
const customised = await p.locator("text=layout customised").count();
log("preference bar: 'layout customised' shown", customised > 0);

// ── 3. persistence across reload ──────────────────────────────────────────
await save.first().click();
await p.waitForTimeout(400);
const stored = await p.evaluate(() =>
  Object.keys(localStorage).filter((k) => k.startsWith("cloud-estate.diagram.prefs")),
);
log("save: written to localStorage", stored.length > 0, stored.join(","));

await p.reload({ waitUntil: "networkidle" });
await p.waitForTimeout(2500);
const afterReload = await order();
log(
  "persistence: order survives reload",
  JSON.stringify(afterReload) === JSON.stringify(after),
  JSON.stringify(afterReload),
);

// ── 4. open a list panel, drag it ─────────────────────────────────────────
const tab = p.locator("[data-canvas] button").filter({ hasText: /\S/ }).nth(3);
await tab.scrollIntoViewIfNeeded();
await tab.click();
await p.waitForTimeout(700);
const panel = p
  .locator('[aria-label="close list"]')
  .first()
  .locator('xpath=ancestor::div[contains(@class,"fixed")][1]');
const opened = await panel.count();
log("panel: a list opens", opened > 0);

let dragOk = false,
  pinOk = false,
  placeOk = false;
if (opened) {
  const box0 = await panel.boundingBox();
  const header = panel.locator("div").first();
  await header.hover();
  await p.mouse.down();
  await p.mouse.move(box0.x + 260, box0.y + 190, { steps: 12 });
  await p.mouse.up();
  await p.waitForTimeout(500);
  const box1 = await panel.boundingBox();
  dragOk = Math.abs(box1.x - box0.x) > 40 || Math.abs(box1.y - box0.y) > 40;
  log(
    "panel: drags by header",
    dragOk,
    `(${Math.round(box0.x)},${Math.round(box0.y)}) -> (${Math.round(box1.x)},${Math.round(box1.y)})`,
  );

  const placed = await p.evaluate(() => {
    const k = Object.keys(localStorage).find((x) => x.startsWith("cloud-estate.diagram.prefs"));
    return k ? JSON.parse(localStorage.getItem(k)).places : {};
  });
  // places only lands in storage after an explicit save
  const saveBtn = p.locator("button", { hasText: "save preferences" });
  if (await saveBtn.count()) await saveBtn.first().click();
  await p.waitForTimeout(400);
  const placed2 = await p.evaluate(() => {
    const k = Object.keys(localStorage).find((x) => x.startsWith("cloud-estate.diagram.prefs"));
    return k ? JSON.parse(localStorage.getItem(k)).places : {};
  });
  placeOk = Object.keys(placed2).length > 0;
  const sample = Object.values(placed2)[0];
  log("placement: stored as corner+offset", placeOk, JSON.stringify(sample));

  const pin = panel.locator('[aria-label="pin this panel"]').first();
  if (await pin.count()) {
    await pin.click();
    await p.waitForTimeout(400);
    pinOk = (await panel.locator('[aria-label="unpin this panel"]').count()) > 0;
  }
  log("panel: pin toggles", pinOk);
}

// ── 5. bulk connection toggle ─────────────────────────────────────────────
const showConn = p.locator("button", { hasText: "show connections" });
let connOk = false;
if (await showConn.count()) {
  await showConn.first().click();
  await p.waitForTimeout(1200);
  /* The overlay is portalled to `body`, not nested in the canvas — that is what
     lets a connection line paint above a panel instead of behind it. Scoping
     this probe to `[data-canvas]` was measuring the old arrangement. */
  const paths = await p.evaluate(
    () => document.querySelectorAll("svg.fixed path[stroke-width='1.5']").length,
  );
  connOk = paths > 0;
  log("connections: bulk toggle draws lines", connOk, `${paths} paths`);
}

await p.screenshot({ path: "/tmp/personalisation.png", fullPage: false });
console.log(
  "\n" + (errs.length ? "PAGE ERRORS:\n" + errs.slice(0, 6).join("\n") : "no page errors"),
);
await b.close();
