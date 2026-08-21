import { chromium } from "playwright";
const b = await chromium.launch();
// Tall viewport so the whole sheet fits without its body scrolling.
const p = await b.newPage({ viewport: { width: 1500, height: 2400 } });
const errs = [];
p.on("pageerror", (e) => errs.push(String(e)));
await p.goto("http://localhost:3200/architecture", { waitUntil: "networkidle" });
await p.waitForTimeout(2500);

const want = process.argv[2] ?? "postgres-vul";
// Open the tile, then the row, so we land on a resource with real relations.
const tile = p.locator("[data-canvas] button", { hasText: /RDS|Lambda|EC2/ }).first();
await tile.scrollIntoViewIfNeeded();
await tile.click();
await p.waitForTimeout(600);
const list = p
  .locator('[aria-label="close list"]')
  .first()
  .locator('xpath=ancestor::div[contains(@class,"fixed")][1]');
const row = list.locator("button").filter({ hasNotText: "✕" }).first();
await row.click();
await p.waitForTimeout(500);
// "full ›" promotes the preview to the docked sheet
await p.locator('[aria-label="open the full panel"]').first().click();
await p.waitForTimeout(1200);

const sheet = p.locator('[role="dialog"]').first();
console.log("sheet:", await sheet.boundingBox());
await sheet.screenshot({ path: "/tmp/full-panel.png" });
console.log(errs.length ? "ERRORS: " + errs.slice(0, 2).join(" | ") : "no page errors");
await b.close();
