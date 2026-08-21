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
const panel = p
  .locator('[aria-label="close list"]')
  .first()
  .locator('xpath=ancestor::div[contains(@class,"fixed")][1]');
const row = panel.locator("button", { hasText: /eks-cluster-sg-onam/ }).first();
const t0 = Date.now();
await row.hover();
await p.waitForTimeout(700);
const d = await p.evaluate(() => {
  const lit = [...document.querySelectorAll("[data-canvas] [data-node]")].filter(
    (x) => getComputedStyle(x).opacity === "1",
  ).length;
  return { traces: document.querySelectorAll("[data-canvas] svg path").length, lit };
});
console.log(`hover->paint ${Date.now() - t0}ms | lit ${d.lit} | traces ${d.traces}`);
await p.screenshot({ path: "/tmp/traces.png" });
console.log(errs.length ? "ERRORS: " + errs.slice(0, 2).join(" | ") : "no page errors");
await b.close();
