import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 1100 } });
const errs = [];
p.on("pageerror", (e) => errs.push(String(e)));
await p.goto("http://localhost:3200/architecture", { waitUntil: "networkidle" });
await p.waitForTimeout(2500);

const tab = p.locator("[data-canvas] button", { hasText: /security-group/ }).first();
const n = await tab.count();
if (!n) {
  console.log("no tab");
  await b.close();
  process.exit(0);
}
console.log("tab:", (await tab.textContent()).trim().slice(0, 34));
await tab.scrollIntoViewIfNeeded();
await tab.click();
await p.waitForTimeout(700);

const open = await p.locator('[aria-label="close list"]').count();
console.log("list open:", open > 0);
if (open) {
  const panel = p
    .locator('[aria-label="close list"]')
    .first()
    .locator('xpath=ancestor::div[contains(@class,"fixed")][1]');
  await panel.scrollIntoViewIfNeeded();
  await p.screenshot({ path: "/tmp/inline.png" });
  const rows = panel.locator("button").filter({ hasNotText: "✕" });
  console.log("rows:", await rows.count());
  const target = panel.locator("button", { hasText: /eks-cluster-sg/ }).first();
  console.log("hovering:", (await target.textContent()).trim().slice(0, 34));
  await target.hover();
  await p.waitForTimeout(500);
  const d = await p.evaluate(() => {
    // Scope to the canvas: the list is portalled to body and its rows carry
    // no dim, so counting them made every chip read as lit.
    const c = [...document.querySelectorAll("[data-canvas] [data-node]")];
    const lit = c.filter((x) => getComputedStyle(x).opacity === "1");
    return {
      chips: c.length,
      lit: lit.length,
      names: lit.slice(0, 4).map((x) => x.textContent.trim().slice(0, 22)),
    };
  });
  console.log("chips:", d.chips, "| lit:", d.lit, d.names);
  await p.screenshot({ path: "/tmp/inline-hover.png" });
}
console.log(errs.length ? "ERRORS: " + errs.slice(0, 2).join(" | ") : "no page errors");
await b.close();
