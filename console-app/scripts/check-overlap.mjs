/**
 * Does anything on the canvas sit on top of anything else?
 *
 * The one property the whole clearance scheme exists to guarantee, checked the
 * only way it can be: against the rendered page. `railClearance` is arithmetic
 * and tested as arithmetic, but whether a box actually reserved what its arms
 * need depends on the box passing the right layer count — and that is a wiring
 * question no unit test sees.
 */
import { chromium } from "playwright";

const URL = process.argv[2] ?? "http://localhost:3200/architecture";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1800, height: 1400 } });
await page.goto(URL, { waitUntil: "networkidle" });
await page.waitForTimeout(2500);

const report = await page.evaluate(() => {
  const rects = (els) =>
    els
      .map((e) => {
        const r = e.getBoundingClientRect();
        return {
          e,
          x: r.x,
          y: r.y,
          w: r.width,
          h: r.height,
          t: (e.textContent || "").trim().slice(0, 26),
        };
      })
      .filter((r) => r.w > 0 && r.h > 0);

  // A rail tab: a button whose label runs vertically, or one on a row rail.
  const tabs = rects(
    [...document.querySelectorAll("button")].filter((b) => {
      const s = getComputedStyle(b);
      const c = typeof b.className === "string" ? b.className : "";
      return (
        s.writingMode.startsWith("vertical") || c.includes("border-t-0") || c.includes("border-b-0")
      );
    }),
  );
  // A container: the bordered boxes the diagram nests.
  const boxes = rects(
    [...document.querySelectorAll("div.rounded-md")].filter((d) => {
      const s = getComputedStyle(d);
      return parseFloat(s.borderTopWidth) >= 1 && d.querySelector(".label-caps");
    }),
  );

  const over = (a, b) => {
    const dx = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
    const dy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
    return dx > 1 && dy > 1 ? Math.round(dx * dy) : 0;
  };

  const hits = [];
  // A tab may sit inside its OWN box's ancestors; what it must never do is
  // cover a box's border region or another tab.
  for (let i = 0; i < tabs.length; i += 1) {
    for (let j = i + 1; j < tabs.length; j += 1) {
      const a = tabs[i],
        b = tabs[j];
      const area = over(a, b);
      if (area)
        hits.push({
          kind: "tab/tab",
          a: a.t,
          b: b.t,
          area,
          ar: [Math.round(a.x), Math.round(a.y), Math.round(a.w), Math.round(a.h)],
          br: [Math.round(b.x), Math.round(b.y), Math.round(b.w), Math.round(b.h)],
        });
    }
    for (const box of boxes) {
      // Only a real intrusion counts: the tab must lie outside every box it is
      // not inside, so an overlap with a box it does not belong to is the bug.
      if (box.e.contains(tabs[i].e)) continue;
      const area = over(tabs[i], box);
      if (area) hits.push({ kind: "tab/box", a: tabs[i].t, b: box.t, area });
    }
  }
  const bodyW = document.documentElement.scrollWidth;
  return {
    tabs: tabs.length,
    boxes: boxes.length,
    hits: hits.slice(0, 12),
    total: hits.length,
    scrollWidth: bodyW,
    viewport: window.innerWidth,
  };
});

console.log(JSON.stringify(report, null, 1));
await browser.close();
process.exit(report.total ? 1 : 0);
