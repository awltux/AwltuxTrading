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
  "--bad": "#ff7b72"
};
const ROOT_FONT_PX = 17;

function makeContext() {
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
      fontSize: ROOT_FONT_PX + "px"
    }),
    console,
    URL,
    fetch: () => Promise.reject(new Error("no network in the harness"))
  };

  return { sandbox, canvas, calls };
}

function draw(series, dates) {
  const { sandbox, canvas, calls } = makeContext();
  canvas.dataset.series = JSON.stringify(series);
  canvas.dataset.dates = JSON.stringify(dates || []);

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
// `html { font-size }` has to reach it by arithmetic. 0.8rem at 17px is 14px.
check("the canvas type scale follows the root font size", () => {
  const { calls } = draw([1, 2, 3], []);
  const fonts = values(calls, "font");
  assert(fonts.some((f) => f.startsWith("14px ")), `expected a 14px axis font from 0.8rem, got ${JSON.stringify(fonts)}`);
  assert(fonts.every((f) => !/\b(11|12|13)px\b/.test(f)), `a pre-change font size survived: ${JSON.stringify(fonts)}`);
});

console.log(failures === 0 ? "\nAll chart paths drew without throwing." : `\n${failures} chart check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
