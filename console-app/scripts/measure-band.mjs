/**
 * What the regional band actually measures, in the browser.
 *
 *   node scripts/measure-band.mjs out.png
 *
 * The packer is tested offline, but only the page can say whether the numbers
 * it chose survive contact with real content — a group is 166px wide whatever
 * the track says, and a squeezed track makes it overflow rather than fit.
 */
import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1800, height: 1400 } });
await p.goto("http://localhost:3200/architecture", { waitUntil: "networkidle" });
await p.waitForTimeout(2500);
const out = await p.evaluate(() => {
  const heads = [...document.querySelectorAll("button.label-caps")];
  const lanes = heads
    .filter((h) =>
      /^(datastore|integration|serverless|application|api|analytics)$/i.test(
        h.textContent.replace(/\d+|▾|▸/g, "").trim(),
      ),
    )
    .map((h) => {
      const box = h.closest("div.rounded-md");
      const r = box.getBoundingClientRect();
      const grid = box.querySelector("div.grid");
      return {
        lane: h.textContent.replace(/\d+|▾|▸/g, "").trim(),
        w: Math.round(r.width),
        h: Math.round(r.height),
        cols: grid ? getComputedStyle(grid).gridTemplateColumns.split(" ").length : 0,
      };
    });
  return { lanes, band: Math.max(0, ...lanes.map((l) => l.h)) };
});
console.log(JSON.stringify(out, null, 1));
await p.screenshot({ path: process.argv[2], fullPage: true });
await b.close();
