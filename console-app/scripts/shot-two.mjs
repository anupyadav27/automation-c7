import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1800, height: 1200 } });
const errs = [];
p.on("pageerror", (e) => errs.push(String(e)));
await p.goto("http://localhost:3200/architecture", { waitUntil: "networkidle" });
await p.waitForTimeout(2500);
const tab = p.locator("[data-canvas] button", { hasText: /security-group/ }).first();
await tab.scrollIntoViewIfNeeded();
await tab.click();
await p.waitForTimeout(600);
const close = p.locator('[aria-label="close list"]');
console.log("list open:", (await close.count()) > 0);
const panel = close.first().locator('xpath=ancestor::div[contains(@class,"fixed")][1]');
const rows = panel.locator("button").filter({ hasNotText: "✕" });
console.log("rows:", await rows.count());
// hover -> preview appears
await rows.nth(2).hover();
await p.waitForTimeout(700);
console.log("preview after hover:", (await p.locator('[aria-label="close preview"]').count()) > 0);
await p.screenshot({ path: "/tmp/two-hover.png" });
// hover a different row -> preview follows
const head = () =>
  p
    .locator('[aria-label="close preview"]')
    .first()
    .locator("xpath=ancestor::div[1]")
    .textContent()
    .catch(() => "");
const before = await head();
await rows.nth(4).hover();
await p.waitForTimeout(700);
const after = await head();
console.log("preview follows hover:", before !== after, "|", (after || "").trim().slice(0, 26));
// click pins
await rows.nth(6).click();
await p.waitForTimeout(500);
console.log("pinned:", (await p.locator("text=pinned").count()) > 0);
await p.screenshot({ path: "/tmp/two-pinned.png" });
console.log(errs.length ? "ERRORS: " + errs.slice(0, 2).join(" | ") : "no page errors");
await b.close();
