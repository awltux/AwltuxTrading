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
 * a reader matches against the account they are putting the figure on. Measured on Microsoft's
 * 2026 10-K: 1,465 of its 1,583 tagged figures sit inside a `<tr>`, and 454 of the 476 rows that
 * hold one are captioned. A stand-in for the row is a handful of plain objects, which is why the
 * walk in `captionOf` is by hand rather than `closest`. */

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

/* Which node a click actually landed on.
 *
 * The click is delegated on `document`, so what arrives is whatever was under the pointer -- the
 * tagged element itself, a `<span>` inside it, or a text node's parent. `factFrom` walks up from
 * there. Measured on the live filing, the tagged element is often wrapped, so this is the step
 * that decides whether a click on a figure is seen at all. */

test("a click on the fact itself finds the fact", () => {
  const fact = { tagName: "IX:NONFRACTION", parentElement: null, children: [] };

  assert.equal(picker.factFrom(fact), fact);
});

test("a click on something inside the fact finds the fact", () => {
  const fact = { tagName: "IX:NONFRACTION", parentElement: null, children: [] };
  const inner = { tagName: "SPAN", parentElement: fact, children: [] };
  const text = { tagName: "B", parentElement: inner, children: [] };
  inner.children.push(text);
  fact.children.push(inner);

  assert.equal(picker.factFrom(text), fact);
});

test("a click on the row around a fact finds nothing, so the caption is not clickable", () => {
  // The cell and the row are around the figure, not part of it. Clicking the caption must not
  // pick up the number beside it.
  const fact = { tagName: "IX:NONFRACTION", parentElement: null, children: [] };
  const cell = { tagName: "TD", parentElement: null, children: [fact] };
  fact.parentElement = cell;
  const row = { tagName: "TR", parentElement: null, children: [cell] };
  cell.parentElement = row;

  assert.equal(picker.factFrom(row), null);
  assert.equal(picker.factFrom(cell), null);
  assert.equal(picker.factFrom(null), null);
});

/* What one click produces, end to end through the rules above. */

/** A captioned row with a tagged figure in it, as a filing lays one out. */
function captionedRow(caption, attributes, text, id = "F_1") {
  const label = cell(caption);
  const value = cell(text);
  const fact = element(Object.assign({ id }, attributes), text);
  fact.tagName = "IX:NONFRACTION";
  fact.parentElement = value;
  fact.children = [];
  value.children.push(fact);
  rowOf([label, value]);
  return fact;
}

test("a click on a figure gives the figure, the filing's caption and its id", () => {
  const fact = captionedRow(
    "Property and equipment, net",
    { name: "us-gaap:PropertyPlantAndEquipmentNet", scale: "6", contextRef: "C_1" },
    "12,345"
  );
  const dates = { C_1: { date: "2026-06-30", instant: true } };

  const picked = picker.pick(fact, dates);

  assert.equal(picked.figure.value, 12345000000);
  assert.equal(picked.figure.tag, "us-gaap:PropertyPlantAndEquipmentNet");
  assert.equal(picked.caption, "Property and equipment, net");
  assert.equal(picked.elementId, "F_1");
  assert.deepEqual(picked.figure.asOf, { date: "2026-06-30", instant: true });
});

test("a click on a figure whose context has no date still picks it, without a period", () => {
  const fact = captionedRow("Goodwill", { name: "us-gaap:Goodwill" }, "80");

  const picked = picker.pick(fact, {});

  assert.equal(picked.figure.value, 80);
  assert.equal(picked.figure.asOf, undefined, "no date is invented for it");
});

test("a click that is not on a figure picks nothing at all", () => {
  assert.equal(picker.pick(cell("Total assets"), {}), null);
});

test("a click on a figure that cannot be read reports why instead of a figure", () => {
  const fact = captionedRow(
    "Commitments and contingencies",
    { name: "us-gaap:CommitmentsAndContingencies", "xsi:nil": "true" },
    ""
  );

  const picked = picker.pick(fact, {});

  assert.equal(picked.figure, undefined);
  assert.match(picked.problem, /nil/);
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

test("the caption travels as its own property, so the form can offer it as a line", () => {
  // The confirmation page offers the filing's header as a *line to create* when the chart has
  // nothing for it -- so the caption is a parameter in its own right, not only the wording of a
  // note. The heading travels with it, because a line needs one to be printed under.
  const url = new URL(
    picker.confirmUrl(
      "http://127.0.0.1:8092/filing/278/pick",
      278,
      178,
      "balance_sheet",
      "current_liabilities",
      FIGURE,
      "Short-term unearned revenue",
      "",
      "Current liabilities"
    )
  );

  assert.equal(url.searchParams.get("caption"), "Short-term unearned revenue");
  assert.equal(url.searchParams.get("section"), "Current liabilities");
  assert.equal(url.searchParams.get("metric"), "current_liabilities", "the residual's own line");
});

test("a filing page with no heading says nothing rather than sending an empty one", () => {
  const url = new URL(
    picker.confirmUrl(
      "http://127.0.0.1:8092/filing/278/pick",
      278,
      178,
      "balance_sheet",
      "total_assets",
      FIGURE,
      "Total assets",
      "",
      ""
    )
  );

  assert.equal(url.searchParams.get("section"), null);
  assert.equal(url.searchParams.get("caption"), "Total assets");
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



/* ======================================================================
 * The untagged tables.
 *
 * A filing that carries no `ix:` elements at all still lays its accounts out in tables, and
 * the reader's need is the same. Measured 2026-10-10: 601 of the 603 stored filing documents
 * are inline XBRL, so this path covers the two that are not -- and the next filer who
 * furnishes plain HTML.
 * ==================================================================== */

/** A table row as the picker sees one: cells, and (for a header) an ancestor. */
function row(cells, { header = false } = {}) {
  const built = cells.map((text) => ({
    tagName: "TD",
    textContent: text,
    className: "",
    attributes: {},
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
    getAttribute(name) {
      return name in this.attributes ? this.attributes[name] : null;
    },
    hasAttribute(name) {
      return name in this.attributes;
    },
  }));
  return {
    tagName: "TR",
    children: built,
    parentElement: header ? { tagName: "THEAD", parentElement: null } : null,
  };
}

test("a printed number is read the way a table prints one", () => {
  assert.equal(picker.printedNumber("604,485").value, 604485);
  assert.equal(picker.printedNumber("$ 604,485").value, 604485);
  assert.equal(picker.printedNumber("1,318,854").value, 1318854);
  assert.equal(picker.printedNumber("1234.5").value, 1234.5);
  // An accounting negative: the brackets are the sign, and the space inside is layout.
  assert.equal(picker.printedNumber("(1,347,784 )").value, -1347784);
});

test("anything that is not plainly a figure is refused rather than guessed at", () => {
  // Every one of these is a cell a real 10-K contains, and none of them is a figure that
  // belongs on a balance sheet. A percentage read as 12.5 would be worse than no offer.
  for (const text of ["", " ", "\u2014", "-", "n/a", "12.5%", "2024", "1999", "1,23,456", "1 234 567 abc", "Note 4"]) {
    assert.equal(picker.printedNumber(text), null, JSON.stringify(text));
  }
});

test("a caption is matched to a line by its words, not its punctuation", () => {
  const known = [
    { label: "Trade receivables", metric: "receivables" },
    { label: "Total current assets", metric: "current_assets" },
    { label: "Cash and equivalents", metric: "cash_and_equivalents" },
  ];

  assert.equal(picker.matchLabel("Trade receivables", known), "receivables");
  assert.equal(picker.matchLabel("Trade receivables:", known), "receivables");
  assert.equal(picker.matchLabel("TOTAL CURRENT ASSETS", known), "current_assets");
  assert.equal(picker.matchLabel("Total current assets (note 4)", known), "current_assets");
  // The commonest divergence in a real filing: the filer repeats a word the chart does not.
  assert.equal(picker.matchLabel("Cash and cash equivalents", known), "cash_and_equivalents");
});

test("a subtotal is not matched to the line below it", () => {
  // The dangerous pair in every balance sheet: a strict subset of the words would make
  // "Total assets" match "Total current assets", and pre-selecting the wrong line is the kind
  // of help that costs a correction. The comparison is on the whole set, so it does not.
  const known = [{ label: "Total current assets", metric: "current_assets" }];

  assert.equal(picker.matchLabel("Total assets", known), "");
  assert.equal(picker.matchLabel("Total assets (note 4)", known), "");
  // A line on another statement is not offered either: the picker is told only the lines of
  // the statement the reader came from, and this is the assertion that it does not reach wider.
  assert.equal(picker.matchLabel("Revenues", known), "");
});

test("a row offers its caption and every figure after it", () => {
  const found = picker.rowFigures(
    row(["Cash and cash equivalents", "$ 604,485", "$ 1,318,854"]),
    [{ label: "Cash and equivalents", metric: "cash_and_equivalents" }]
  );

  assert.equal(found.caption, "Cash and cash equivalents");
  assert.equal(found.metric, "cash_and_equivalents");
  assert.deepEqual(found.values.map((v) => v.value), [604485, 1318854]);
});

test("a row whose first cell is empty is captioned by the first cell with a word in it", () => {
  // Filings indent with an empty spacer cell often enough that taking cell zero would caption
  // half the statement with nothing.
  const found = picker.rowFigures(row(["", "Total assets", "5,113,930"]), []);

  assert.equal(found.caption, "Total assets");
  assert.deepEqual(found.values.map((v) => v.value), [5113930]);
});

test("a header row of years is not offered as figures", () => {
  const found = picker.rowFigures(row(["", "December 31,", "2024", "2023"], { header: true }), []);

  assert.deepEqual(found.values, []);
});

test("a row with no caption, or nothing after it, offers nothing", () => {
  assert.deepEqual(picker.rowFigures(row(["2024", "2025"]), []).values, []);
  assert.deepEqual(picker.rowFigures(row(["Total assets"]), []).values, []);
});

test("marking a table writes the figure, the caption and the matched line onto the cell", () => {
  const target = row(["Receivables", "38,730"]);
  const marked = picker.markTableFigures([target], [
    { label: "Receivables", metric: "receivables" },
  ]);

  assert.equal(marked, 1);
  const cell = target.children[1];
  assert.equal(cell.attributes["data-awltux-value"], "38730");
  assert.equal(cell.attributes["data-awltux-raw"], "38,730");
  assert.equal(cell.attributes["data-awltux-caption"], "Receivables");
  assert.equal(cell.attributes["data-awltux-metric"], "receivables");
  assert.match(cell.className, /awltux-tablefact/);
});

test("a marked cell is read as a figure with no tag, no unit and no context", () => {
  const target = row(["Receivables", "38,730"]);
  picker.markTableFigures([target], []);
  const figure = picker.figureOf(target.children[1]);

  assert.equal(figure.value, 38730);
  assert.equal(figure.raw, "38,730");
  assert.equal(figure.origin, "table");
  assert.equal(figure.tag, "");
  // No scale to apply: the cell holds the number as printed, and saying so is the difference
  // between a figure and a figure multiplied by a million.
  assert.equal(figure.scale, 0);
});

test("a click inside a marked cell finds it, and a click on the row does not", () => {
  const target = row(["Receivables", "38,730"]);
  picker.markTableFigures([target], []);
  const cell = target.children[1];

  cell.parentElement = target;
  target.parentElement = { tagName: "TABLE", parentElement: null };
  assert.equal(picker.factFrom(cell), cell);
  // The row itself is not a figure: making it one would give the caption a click target.
  assert.equal(picker.factFrom(target), null);
});

test("a link from a table carries the figure and says where it came from", () => {
  const target = row(["Receivables", "38,730"]);
  picker.markTableFigures([target], []);
  const figure = picker.figureOf(target.children[1]);
  const url = new URL(
    picker.confirmUrl("http://x/filing/1/pick", 1, 256, "balance_sheet", "", figure, "Receivables", "", "Current assets")
  );

  assert.equal(url.searchParams.get("value"), "38730");
  assert.equal(url.searchParams.get("origin"), "table");
  assert.equal(url.searchParams.get("caption"), "Receivables");
  assert.equal(url.searchParams.get("section"), "Current assets");
  // No line to name: the form asks which one, which is the whole point of an "add a line"
  // visit. An empty `metric` would be read on the other side as a line called "".
  assert.equal(url.searchParams.get("metric"), null);
});
