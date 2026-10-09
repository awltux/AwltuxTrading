/* The value rule inside the filing picker, which no browser runs in the Python suite.
 *
 * `src/awltux/web/static/filing-picker.js` hands its two pure functions to node when there is no
 * `document` (see the export in that file). They are the part of the picker that decides what a
 * clicked figure *is*, and the whole feature rests on them: a scale applied the wrong way, or a
 * `sign="-"` ignored, writes a figure onto the balance sheet that is out by a factor of a
 * million and looks perfectly plausible.
 *
 * Run by `tests/test_filing_picker.py`, which skips when node is not installed.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const picker = require("../../src/awltux/web/static/filing-picker.js");

/** The three things `figureOf` asks an element for, and nothing else. */
function element(attributes, text) {
  return {
    textContent: text,
    getAttribute: (name) => (name in attributes ? attributes[name] : null),
    hasAttribute: (name) => name in attributes,
  };
}

test("a scaled figure is the printed number times ten to the scale", () => {
  // The live case this was built against: Microsoft's 2026 10-K tags total assets as
  // "758,376" with scale="6", and `fundamental_period.metrics.total_assets` holds
  // 758376000000.0 for the same year.
  const figure = picker.figureOf(
    element(
      {
        name: "us-gaap:Assets",
        contextRef: "C_ca004a37",
        unitRef: "U_USD",
        scale: "6",
        decimals: "-6",
        format: "ixt:num-dot-decimal",
      },
      "758,376"
    )
  );

  assert.equal(figure.value, 758376000000);
  // As the filing printed it, separators and all: the tray shows this beside the scale, so a
  // reader can check the arithmetic rather than take the figure on trust.
  assert.equal(figure.raw, "758,376");
  assert.equal(figure.scale, 6);
  assert.equal(figure.tag, "us-gaap:Assets");
  assert.equal(figure.unit, "U_USD");
  assert.equal(figure.context, "C_ca004a37");
});

test("a figure with nothing to apply is the number as printed", () => {
  assert.equal(picker.figureOf(element({ name: "us-gaap:X" }, "1,234.5")).value, 1234.5);
  assert.equal(picker.figureOf(element({ name: "us-gaap:X" }, "$1,234")).value, 1234);
  assert.equal(picker.figureOf(element({ name: "us-gaap:X" }, "\u00a01 234\u00a0")).value, 1234);
});

test("sign='-' negates, and so does a figure in parentheses", () => {
  assert.equal(picker.figureOf(element({ name: "us-gaap:X", sign: "-" }, "500")).value, -500);
  assert.equal(picker.figureOf(element({ name: "us-gaap:X" }, "(500)")).value, -500);
  // Both at once is a credit printed as a deduction: one negation, not two.
  assert.equal(picker.figureOf(element({ name: "us-gaap:X", sign: "-" }, "(500)")).value, 500);
});

test("a negative scale divides", () => {
  assert.equal(picker.figureOf(element({ name: "us-gaap:X", scale: "-2" }, "500")).value, 5);
});

test("a comma-decimal filing is not read as a dot-decimal one", () => {
  const figure = picker.figureOf(
    element({ name: "us-gaap:X", format: "ixt:num-comma-decimal" }, "1.234,56")
  );

  assert.equal(figure.value, 1234.56);
});

test("a zero transform is zero whatever the text says", () => {
  assert.equal(picker.figureOf(element({ name: "us-gaap:X", format: "ixt:fixed-zero" }, "-")).value, 0);
  assert.equal(picker.figureOf(element({ name: "us-gaap:X", format: "ixt:zerodash" }, "\u2014")).value, 0);
});

test("a nil figure is refused rather than read as zero", () => {
  // The filing writes a caption it has nothing for as an empty nil element. Reading that as 0
  // would put a figure the filer did not state onto the accounts.
  const figure = picker.figureOf(
    element({ name: "us-gaap:CommitmentsAndContingencies", "xsi:nil": "true" }, "")
  );

  assert.equal(figure.value, undefined);
  assert.match(figure.reason, /nil/);
});

test("a continued figure is refused rather than read from half of it", () => {
  const figure = picker.figureOf(
    element({ name: "us-gaap:X", continuedat: "F_next" }, "1,2")
  );

  assert.equal(figure.value, undefined);
  assert.match(figure.reason, /continued/);
});

test("a transform that is not a number is refused rather than guessed", () => {
  // A date or a boolean tagged in the same document would otherwise be read as whatever
  // `Number` makes of it.
  const figure = picker.figureOf(
    element({ name: "us-gaap:X", format: "ixt:date-month-day-year" }, "2026-06-30")
  );

  assert.equal(figure.value, undefined);
  assert.match(figure.reason, /format/);

  const text = picker.figureOf(element({ name: "us-gaap:X" }, "not a number"));
  assert.equal(text.value, undefined);
});

test("the scale and the sign travel with the figure, so the tray can show the working", () => {
  const figure = picker.figureOf(
    element({ name: "us-gaap:X", scale: "3", sign: "-" }, "12")
  );

  assert.equal(figure.value, -12000);
  assert.equal(figure.scale, 3);
  assert.equal(figure.sign, "-");
});

/* The caption: which line of the filing the figure sits on, in the filer's own words.
 *
 * Most tagged figures are in a table row whose first cell names the line, and that name is what
 * a reader matches against the account they are putting the figure on. A stand-in for the row
 * is a handful of plain objects, which is why the walk in `captionOf` is by hand rather than
 * `closest`. */

function cell(text, kind = "td") {
  return { tagName: kind.toUpperCase(), textContent: text, parentElement: null, children: [] };
}

function rowOf(cells) {
  const row = { tagName: "TR", textContent: "", parentElement: null, children: cells };
  for (const child of cells) child.parentElement = row;
  return row;
}

test("the first cell of the row is the caption", () => {
  const caption = cell("Property and equipment, net");
  const value = cell("12,345");
  const fact = { tagName: "IX:NONFRACTION", textContent: "12,345", parentElement: value };
  value.children.push(fact);
  rowOf([caption, value]);

  assert.equal(picker.captionOf(fact), "Property and equipment, net");
});

test("a caption's whitespace is collapsed, because a filing's tables are full of it", () => {
  const caption = cell("  Total\n   current\u00a0liabilities  ");
  const value = cell("1");
  const fact = { tagName: "IX:NONFRACTION", textContent: "1", parentElement: value };
  value.children.push(fact);
  rowOf([caption, value]);

  assert.equal(picker.captionOf(fact), "Total current liabilities");
});

test("a figure that is itself the first cell has no caption, and none is invented", () => {
  // Widely used for a row of figures under one heading: the number *is* the first cell, so the
  // only text available is the number, and captioning a figure with itself helps nobody.
  const value = cell("12");
  const fact = { tagName: "IX:NONFRACTION", textContent: "12", parentElement: value };
  value.children.push(fact);
  rowOf([value, cell("13")]);

  assert.equal(picker.captionOf(fact), "");
});

test("a figure outside a table row has no caption", () => {
  const fact = { tagName: "IX:NONFRACTION", textContent: "1", parentElement: null };

  assert.equal(picker.captionOf(fact), "");
});

test("a header cell names the line as well as a body cell does", () => {
  const caption = cell("Goodwill", "th");
  const value = cell("80");
  const fact = { tagName: "IX:NONFRACTION", textContent: "80", parentElement: value };
  value.children.push(fact);
  rowOf([caption, value]);

  assert.equal(picker.captionOf(fact), "Goodwill");
});

test("a fact nested deeper in a cell is still captioned by the row it sits in", () => {
  // The tagged element is often wrapped in a span or a bold, and the caption still belongs to
  // the row rather than to the wrapper.
  const caption = cell("Net income");
  const value = cell("133,749");
  const wrapper = { tagName: "SPAN", textContent: "133,749", parentElement: value, children: [] };
  const fact = { tagName: "IX:NONFRACTION", textContent: "133,749", parentElement: wrapper };
  wrapper.children.push(fact);
  value.children.push(wrapper);
  rowOf([caption, value]);

  assert.equal(picker.captionOf(fact), "Net income");
});

/* Which column of the filing's table a figure came from.
 *
 * A filing prints the current year and the prior year side by side under one caption and tags
 * both. Measured on Microsoft's 2026 10-K: the row captioned "Total assets" carries
 * `us-gaap:Assets` twice, 758,376 and 619,003, and nothing but the `contextRef` tells them
 * apart. Clicking the wrong column with the right caption is the easiest mistake here. */

function context(id, parts) {
  const wrapper = { tagName: "XBRLLI:PERIOD", textContent: "", parentElement: null, children: parts };
  for (const part of parts) part.parentElement = wrapper;
  const element = {
    tagName: "XBRLI:CONTEXT",
    textContent: "",
    parentElement: null,
    children: parts,
    getAttribute: (name) => (name === "id" ? id : null),
  };
  return element;
}

function datePart(tag, text) {
  return { tagName: tag.toUpperCase(), textContent: text, parentElement: null, children: [] };
}

test("an instant context is the date the figure is as at", () => {
  const found = picker.dateInContext(
    context("C_1", [datePart("xbrli:instant", "2026-06-30")])
  );

  assert.deepEqual(found, { date: "2026-06-30", instant: true });
});

test("an end date is the period the figure is for", () => {
  const found = picker.dateInContext(
    context("C_2", [
      datePart("xbrli:startDate", "2025-07-01"),
      datePart("xbrli:endDate", "2026-06-30"),
    ])
  );

  assert.deepEqual(found, { date: "2026-06-30", instant: false });
});

test("a context with no date at all is left out rather than shown blank", () => {
  assert.equal(picker.dateInContext(context("C_3", [])), null);

  const map = picker.contextDates([context("C_3", []), context("C_4", [datePart("xbrli:instant", "2025-06-30")])]);

  assert.deepEqual(Object.keys(map), ["C_4"]);
});

test("the two columns of one row get their own dates, which is the whole point", () => {
  const map = picker.contextDates([
    context("C_now", [datePart("xbrli:instant", "2026-06-30")]),
    context("C_before", [datePart("xbrli:instant", "2025-06-30")]),
  ]);

  assert.equal(map["C_now"].date, "2026-06-30");
  assert.equal(map["C_before"].date, "2025-06-30");
});

test("a context with neither an id nor a date is skipped without throwing", () => {
  const map = picker.contextDates([
    { tagName: "XBRLI:CONTEXT", textContent: "", children: [] },
    context("C_5", [datePart("xbrli:endDate", "2024-12-31")]),
  ]);

  assert.deepEqual(Object.keys(map), ["C_5"]);
});

/* The payload. This is the contract between the filing page and the confirmation page, and the
 * property the request named: `metric` is the accounting total the clicked figure is related to,
 * so it is what decides which line of the accounts the figure can be put on. */

const FIGURE = {
  value: 758376000000,
  raw: "758,376",
  scale: 6,
  sign: "",
  tag: "us-gaap:Assets",
  unit: "U_USD",
  context: "C_1",
};

test("the link names the period, the line and the figure", () => {
  const url = new URL(
    picker.confirmUrl(
      "http://127.0.0.1:8092/filing/278/pick?awltux_period=178",
      278,
      178,
      "balance_sheet",
      "total_assets",
      FIGURE,
      "",
      "F_assets"
    )
  );

  assert.equal(url.pathname, "/accounts/178/corrections/new");
  assert.equal(url.searchParams.get("statement"), "balance_sheet");
  assert.equal(url.searchParams.get("metric"), "total_assets");
  // A plain decimal string, not `758376000000` with an exponent or grouping: the confirmation
  // form parses this with `float()`.
  assert.equal(url.searchParams.get("value"), "758376000000");
  assert.equal(url.searchParams.get("tag"), "us-gaap:Assets");
  assert.equal(url.searchParams.get("origin"), "filing");
  assert.equal(url.searchParams.get("url"), "/filing/278/document#F_assets");
});

test("the filing's own name for the line rides along as the note", () => {
  const url = new URL(
    picker.confirmUrl(
      "http://127.0.0.1:8092/filing/278/pick",
      278,
      178,
      "balance_sheet",
      "net_ppe",
      FIGURE,
      "Property and equipment, net",
      ""
    )
  );

  assert.equal(url.searchParams.get("note"), "filed as: Property and equipment, net");
  assert.equal(url.searchParams.get("url"), null, "no anchor when the element has no id");
});

test("the link is absolute on this application, whatever the document's <base> says", () => {
  // A filing may carry a `<base href="https://www.sec.gov/...">`, and a root-relative href in
  // that document resolves against it -- sending the reader to EDGAR with our query string.
  // Resolving against `location.href` is what prevents that, so it is asserted rather than
  // assumed.
  const url = picker.confirmUrl(
    "http://192.168.1.189:8092/filing/278/pick?awltux_period=178",
    278,
    178,
    "balance_sheet",
    "total_assets",
    FIGURE,
    "",
    ""
  );

  assert.ok(url.startsWith("http://192.168.1.189:8092/accounts/178/"), url);
});

test("a figure too large for an exponent notation is still a figure", () => {
  // `Number.prototype.toString` gives `1e+21` past 21 digits; `float()` on the other side
  // would then raise, and the reader's click would be refused for no reason.
  const huge = Object.assign({}, FIGURE, { value: 1e21 });
  const url = new URL(
    picker.confirmUrl("http://x/filing/1/pick", 1, 1, "balance_sheet", "total_assets", huge, "", "")
  );

  assert.ok(!url.searchParams.get("value").includes("e"), url.searchParams.get("value"));
});


