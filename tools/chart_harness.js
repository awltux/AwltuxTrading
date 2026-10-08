/* Exercise the dashboard's chart drawing in Node, with a stub DOM.
 *
 * The bug this exists to catch is a `ReferenceError`, which `node --check` cannot see
 * and which no test in the suite touches: introducing the cached palette moved
 * `muted` into `drawChart`'s scope while `drawEmptyChart` -- reached only when an
 * instrument has fewer than two stored bars -- still referenced it. A normal
 * instrument page exercises the *other* branch, so the page looks fine.
 *
 * So all three shapes are drawn: no points, one point (the lone-dot branch inside
 * `drawEmptyChart`), and a real series. Any throw fails the run.
 *
 * The property sets are recorded through setters rather than read back afterwards,
 * so this also asserts the palette and the type scale are read from the stylesheet:
 * the stub reports `--muted` and a 17px root, and the drawn colours and font sizes
 * must be derived from them.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SOURCE = path.join(__dirname, "..", "src", "awltux", "web", "static", "app.js");

// What the stub stylesheet reports, matching src/awltux/web/static/style.css.
const PALETTE = {
  "--line": "#39434f",
  "--muted": "#afb9c6",
  "--good": "#4fd35f",
  "--bad": "#ff7b72",
  "--link": "#8cc8ff"
};
const ROOT_FONT_PX = 17;

function makeContext(rootFontPx) {
  const calls = [];
  const record = (name) => (...args) => { calls.push({ name, args }); };

  const gradient = { addColorStop: record("addColorStop") };
  const ctx = {
    clearRect: record("clearRect"),
    beginPath: record("beginPath"),
    closePath: record("closePath"),
    moveTo: record("moveTo"),
    lineTo: record("lineTo"),
    stroke: record("stroke"),
    fill: record("fill"),
    fillText: record("fillText"),
    arc: record("arc"),
    scale: record("scale"),
    createLinearGradient: () => { calls.push({ name: "createLinearGradient" }); return gradient; },
    measureText: (text) => ({ width: String(text).length * 7 })
  };

  // Record assignment of the styling properties the chart sets.
  for (const property of ["strokeStyle", "fillStyle", "font", "lineWidth", "textAlign"]) {
    let value;
    Object.defineProperty(ctx, property, {
      get: () => value,
      set: (next) => { value = next; calls.push({ name: "set:" + property, args: [next] }); }
    });
  }

  const canvas = {
    width: 0,
    height: 0,
    clientWidth: 600,
    dataset: { series: "[]", dates: "[]" },
    getAttribute: (name) => (name === "height" ? "180" : null),
    getContext: () => ctx
  };

  const sandbox = {
    document: {
      readyState: "complete",
      cookie: "",
      documentElement: {},
      createElement: () => ({ style: {}, appendChild() {}, remove() {}, classList: { add() {}, remove() {} } }),
      getElementById: (id) => (id === "price-chart" ? canvas : null),
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener: () => {}
    },
    window: {
      devicePixelRatio: 2,
      location: { href: "http://localhost/instrument/X", origin: "http://localhost", reload() {} },
      history: { pushState() {} },
      sessionStorage: { getItem: () => null, setItem() {} },
      addEventListener: () => {},
      setInterval: () => 0,
      setTimeout: () => 0,
      Intl: undefined
    },
    getComputedStyle: () => ({
      getPropertyValue: (name) => PALETTE[name] || "",
      fontSize: (rootFontPx || ROOT_FONT_PX) + "px"
    }),
    console,
    URL,
    fetch: () => Promise.reject(new Error("no network in the harness"))
  };

  return { sandbox, canvas, calls };
}

function draw(series, dates, markers, rootFontPx) {
  const { sandbox, canvas, calls } = makeContext(rootFontPx);
  canvas.dataset.series = JSON.stringify(series);
  canvas.dataset.dates = JSON.stringify(dates || []);
  canvas.dataset.markers = JSON.stringify(markers || []);

  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox, { filename: SOURCE });

  return { canvas, calls };
}

const values = (calls, property) =>
  calls.filter((c) => c.name === "set:" + property).map((c) => c.args[0]);
const texts = (calls) => calls.filter((c) => c.name === "fillText").map((c) => c.args[0]);

let failures = 0;

function check(label, fn) {
  try {
    fn();
    console.log(`  ok    ${label}`);
  } catch (err) {
    failures += 1;
    console.log(`  FAIL  ${label}: ${err.message}`);
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

console.log("=== every shape the chart is drawn in, without throwing");

check("no stored bars draws the waiting panel", () => {
  const { calls } = draw([], []);
  assert(calls.length > 0, "nothing was drawn at all");
  assert(texts(calls).includes("Waiting for data"), "expected the waiting sentence");
});

// The branch that held the ReferenceError: one bar takes the lone-dot path inside
// drawEmptyChart, which a two-point instrument page never reaches.
check("one stored bar draws the lone point (drawEmptyChart)", () => {
  const { calls } = draw([123.45], ["2026-10-01"]);
  assert(calls.some((c) => c.name === "arc"), "expected the lone-point dot");
  assert(values(calls, "fillStyle").includes(PALETTE["--muted"]),
    `the dot should be --muted, got ${JSON.stringify(values(calls, "fillStyle"))}`);
  assert(texts(calls).includes("Waiting for data"), "expected the waiting sentence under the dot");
});

check("a real series draws a price line and the axis extremes", () => {
  const { calls } = draw([1, 2, 3, 2, 4], ["2026-10-01", "2026-10-05"]);
  assert(calls.filter((c) => c.name === "stroke").length > 6, "expected axes, grid and the line");
  const labels = texts(calls);
  assert(labels.includes("1.00") && labels.includes("4.00"), `expected axis extremes, got ${JSON.stringify(labels)}`);
});

check("a rising series strokes with --good, a falling one with --bad", () => {
  const rising = draw([1, 2, 3, 4], []);
  assert(values(rising.calls, "strokeStyle").includes(PALETTE["--good"]), "rising line should be --good");

  const falling = draw([4, 3, 2, 1], []);
  assert(values(falling.calls, "strokeStyle").includes(PALETTE["--bad"]), "falling line should be --bad");
});

console.log("\n=== the reader's own executions on the line");

const MARKER = { date: "2026-10-05", price: 2.5, letter: "B" };

check("a marker draws a dot and its letter", () => {
  const { calls } = draw([1, 2, 3, 2, 4], ["2026-10-01", "2026-10-05"], [MARKER]);
  assert(calls.some((c) => c.name === "arc"), "no dot was drawn");
  assert(texts(calls).includes("B"), `expected the marker letter, got ${JSON.stringify(texts(calls))}`);
  assert(values(calls, "fillStyle").includes(PALETTE["--link"]),
    "the marker should be --link, which no trend colour uses");
});

check("a marker on a date the chart does not have is skipped, not misplaced", () => {
  const { calls } = draw([1, 2, 3, 2, 4], ["2026-10-01", "2026-10-05"],
    [{ date: "1999-01-01", price: 2, letter: "S" }]);
  assert(!texts(calls).includes("S"), "a marker with no bar must not be drawn anywhere");
});

// The position may have been bought above today's whole range -- the case worth seeing.
check("the axis widens to reach a marker outside the stored series", () => {
  const { calls } = draw([1, 2, 3], ["2026-10-01", "2026-10-05"],
    [{ date: "2026-10-05", price: 9.5, letter: "B" }]);
  assert(texts(calls).includes("9.50"), `the top of the axis should reach the paid price, got ${JSON.stringify(texts(calls))}`);
});

console.log("\n=== the chart reads the stylesheet rather than a literal");
check("the axes are stroked in --line", () => {
  const { calls } = draw([1, 2, 3], []);
  assert(values(calls, "strokeStyle").includes(PALETTE["--line"]), "the frame should be --line");
});

check("the axis labels are filled with --muted", () => {
  const { calls } = draw([1, 2, 3], []);
  assert(values(calls, "fillStyle").includes(PALETTE["--muted"]), "labels should be --muted");
});

// The point of `chartFont`: a canvas has no `rem`, so the stylesheet's single
// `html { font-size }` has to reach it by arithmetic. The property is that every font
// *scales with* that one number, so the same page is drawn at two root sizes and each
// font must be the other's ratio -- which a hardcoded 12px literal cannot be. (It used
// to be checked against a list of literals, and 0.75rem rounded to 13px at 17px, so a
// correct size read as the bug.)
check("the canvas type scale follows the root font size", () => {
  const series = [1, 2, 3];
  const dates = ["2026-10-01", "2026-10-05"];
  const markers = [{ date: "2026-10-05", price: 2, letter: "B" }];
  const at17 = values(draw(series, dates, markers, 17).calls, "font");
  const at34 = values(draw(series, dates, markers, 34).calls, "font");

  assert(at17.length > 0, "no font was set at all");
  assert(at17.length === at34.length, "the two runs set a different number of fonts");
  at17.forEach((font, index) => {
    // Within a pixel: each size is rounded to a whole pixel, so doubling the *rounded*
    // value can be half a pixel out at the second scale.
    const doubled = parseFloat(font) * 2;
    const scaled = parseFloat(at34[index]);
    assert(Math.abs(scaled - doubled) <= 1,
      `${font} at 17px became ${at34[index]} at 34px -- not the root size times a rem`);
  });
  assert(at17.some((f) => f.startsWith("14px ")),
    `expected a 14px axis font from 0.8rem at 17px, got ${JSON.stringify(at17)}`);
});

console.log(failures === 0 ? "\nAll chart paths drew without throwing." : `\n${failures} chart check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
