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
  "--warn": "#e3b341",
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
      // The chart draws every canvas carrying a series -- an instrument's price line and a
      // sector's index -- so the stub answers that selector rather than only the one id.
      querySelectorAll: (selector) =>
        selector === "canvas[data-series]" ? [canvas] : [],
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

function draw(series, dates, markers, rootFontPx, valuations) {
  const { sandbox, canvas, calls } = makeContext(rootFontPx);
  canvas.dataset.series = JSON.stringify(series);
  canvas.dataset.dates = JSON.stringify(dates || []);
  canvas.dataset.markers = JSON.stringify(markers || []);
  canvas.dataset.valuations = JSON.stringify(valuations || []);

  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox, { filename: SOURCE });

  return { canvas, calls };
}

const values = (calls, property) =>
  calls.filter((c) => c.name === "set:" + property).map((c) => c.args[0]);
const texts = (calls) => calls.filter((c) => c.name === "fillText").map((c) => c.args[0]);

/** Every stroked path as `{ from: [x, y], to: [x, y] }`, in draw order. */
function segments(calls) {
  const found = [];
  let from = null;
  for (const call of calls) {
    if (call.name === "moveTo") from = call.args;
    else if (call.name === "lineTo" && from) { found.push({ from, to: call.args }); from = null; }
  }
  return found;
}

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

console.log("\n=== the model's fair value, as a step per calculation");

// Five bars, two calculations. The plot is 584px wide with its padding, so bar 1 sits at
// 154, bar 3 at 446 and the last bar at 592 -- the assertions are about which bar each
// step *starts and ends on*, which is the whole contract with the server.
const STEP_DATES = ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"];
const STEP_PRICES = [10, 11, 12, 11, 13];
const STEPS = [
  { date: "2026-10-02", base: 20, low: 18, high: 22 },
  { date: "2026-10-04", base: 25, low: 21, high: 29 }
];

check("a step is drawn flat from its own bar to the next calculation", () => {
  const { calls } = draw(STEP_PRICES, STEP_DATES, [], undefined, STEPS);
  const flat = segments(calls).filter((s) => s.from[1] === s.to[1] && s.to[0] > s.from[0]);
  // Three flat lines exist: four grid rules and the two steps. The steps are the ones
  // that start at a bar the date list names and stop at another one.
  assert(flat.some((s) => s.from[0] === 154 && s.to[0] === 446),
    `expected a step from bar 1 to bar 3, got ${JSON.stringify(flat.map((s) => [s.from[0], s.to[0]]))}`);
  assert(flat.some((s) => s.from[0] === 446 && s.to[0] === 592),
    `expected the last step to run to the right edge, got ${JSON.stringify(flat.map((s) => [s.from[0], s.to[0]]))}`);
});

check("the range is a vertical bar at the start of the step", () => {
  const { calls } = draw(STEP_PRICES, STEP_DATES, [], undefined, STEPS);
  // The y axis is a vertical line too, at x = pad, so the bars are found by the bar
  // they start on rather than by counting verticals.
  const bars = segments(calls).filter((s) => s.from[0] === s.to[0] && s.from[1] !== s.to[1]);
  const at = (px) => bars.filter((s) => s.from[0] === px);
  assert(at(154).length === 1 && at(446).length === 1,
    `expected one range bar at each step's start, got ${JSON.stringify(bars)}`);

  const span = (segment) => Math.abs(segment.from[1] - segment.to[1]);
  assert(span(at(446)[0]) > span(at(154)[0]),
    "the wider range (21-29) must draw a taller bar than 18-22");
});

check("the line is red, the range is yellow, and they are not each other's", () => {
  const { calls } = draw(STEP_PRICES, STEP_DATES, [], undefined, STEPS);
  const strokes = values(calls, "strokeStyle");
  assert(strokes.includes(PALETTE["--bad"]) && strokes.includes(PALETTE["--warn"]),
    `expected both the fair-value red and the range yellow, got ${JSON.stringify(strokes)}`);
  assert(PALETTE["--bad"] !== PALETTE["--warn"], "the two readings must not be one colour");
});

check("the range bar is capped at both ends, one pixel either side", () => {
  const { calls } = draw(STEP_PRICES, STEP_DATES, [], undefined, STEPS);
  const caps = segments(calls).filter((s) => s.from[1] === s.to[1] && Math.abs(s.to[0] - s.from[0]) === 2);
  assert(caps.length === 4, `expected a cap at each end of two ranges, got ${JSON.stringify(caps)}`);
  assert(caps.every((s) => s.from[0] === 153 || s.from[0] === 445),
    "a cap belongs at the start of its own step, one pixel left of the bar");
  // Two per range, at the range's two ends rather than both at one of them.
  const tops = caps.filter((s) => s.from[0] === 153).map((s) => s.from[1]);
  assert(new Set(tops).size === 2, "the two caps of one range sit at different heights");
});

check("the axis widens to reach the fair value", () => {
  const { calls } = draw(STEP_PRICES, STEP_DATES, [], undefined, STEPS);
  // The prices run 10-13; the second range reaches 29.
  assert(texts(calls).includes("29.00"),
    `the top of the axis should reach the fair value, got ${JSON.stringify(texts(calls))}`);
});

check("no valuations leaves the chart exactly as it was", () => {
  const withNone = draw(STEP_PRICES, STEP_DATES, []).calls;
  const withEmpty = draw(STEP_PRICES, STEP_DATES, [], undefined, []).calls;
  assert(JSON.stringify(withNone) === JSON.stringify(withEmpty),
    "an absent and an empty valuation list must draw the same chart");
  assert(!values(withNone, "strokeStyle").includes(PALETTE["--bad"]),
    "a rising series with no valuations must not stroke anything in the fair-value red");
});

check("a step on a bar the chart does not hold is skipped, not misplaced", () => {
  const { calls } = draw(STEP_PRICES, STEP_DATES, [], undefined,
    [{ date: "1999-01-01", base: 20, low: 18, high: 22 }]);
  assert(!texts(calls).includes("22.00") && !texts(calls).includes("18.00"),
    "an undrawable step must not widen the axis either");
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
