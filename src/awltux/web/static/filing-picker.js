/* Read a figure out of a filed report, and hand it to the accounts page.
 *
 * Asked for directly: *"Allow the user to click xbrl values in the government report which adds
 * them to Account section indicated by the url property."* This file is the "click" half. It is
 * loaded only by `/filing/{id}/pick`, which is a route of its own precisely so that the plain
 * `/filing/{id}/document` keeps its bare `sandbox` policy and no ordinary filing view runs a
 * script at all.
 *
 * **What it does not do.** It decides nothing. Which period and which line are fixed by the
 * query string of the URL the reader pressed -- `awltux_period`, `awltux_line`, `awltux_label`,
 * `awltux_statement` -- and nothing is *written* here: each figure clicked becomes a link to the
 * confirmation form on our own origin, which is where a person chooses a side and presses the
 * button. A page served inside a sandbox is not trusted with a write; that is what the sandbox
 * is for.
 *
 * **Why the arithmetic is here rather than on the server.** The value of an `ix:nonFraction` is
 * the text as its `format` transform leaves it, scaled by `10^scale`, negated when `sign="-"`.
 * Doing it server-side would mean putting 8.5MB of third-party HTML through a Python parser on
 * every pick; the browser has already parsed it. The cost is that this arithmetic is not
 * covered by the Python suite, so the tray prints the raw text, the scale and the sign beside
 * the figure it computed and the reader can check it. `TODO.md` records the untested gap.
 *
 * **Nothing from the filing is treated as markup.** The tag, the context and the text are all
 * written with `textContent`, and the only URL built here is absolute on this application --
 * resolved against `location.href` rather than against the document's own `<base>`, because a
 * filing may carry one and it would send our link to sec.gov.
 */
(function () {
  "use strict";

  var FACT_TAG = "ix:nonfraction";
  //: A number in a filing's table that carries no `ix:` element at all. Measured 2026-10-10:
  //: 601 of the 603 stored filing documents are inline XBRL, so this is the fallback for the
  //: two that are not (`AREC_US_EQ`'s 10-K and `BMM_US_EQ`'s 40-F) -- and for the next filer
  //: who furnishes plain HTML.
  var TABLE_CLASS = "awltux-tablefact";
  var SCRIPT_ID = "awltux-picker-script";
  var HINT = "Click a figure in the report to read it here first.";

  /* ---------------------------------------------------------------- the value */

  function transform(format, text) {
    /* The `ixt` transform on a tagged figure. Only the ones that mean something for a number
     * are handled, and anything else -- a date, a boolean -- is refused rather than guessed
     * at: writing a misread figure onto a balance sheet is worse than saying so. */
    var name = String(format || "")
      .toLowerCase()
      .split(":")
      .pop()
      .replace(/[^a-z0-9]/g, "");
    if (name === "" || name === "numdotdecimal") {
      // The ordinary case: comma thousands, dot decimal.
      return text.replace(/,/g, "");
    }
    if (name === "numcommadecimal") {
      // 1.234,56 -- dot thousands, comma decimal.
      return text.replace(/\./g, "").replace(",", ".");
    }
    if (name === "fixedzero" || name === "zerodash") return "0";
    return null;
  }

  function figureOf(element) {
    /* What this element says, or why it cannot be read. Never a guess. */
    if (element.hasAttribute("continuedat")) {
      return { reason: "this figure is continued elsewhere in the report" };
    }
    if ((element.getAttribute("xsi:nil") || "").toLowerCase() === "true") {
      return { reason: "the filer tagged this line as nil, so there is no figure here" };
    }
    // A table cell the picker marked itself, in a document that tags nothing. The value is the
    // one `printedNumber` read out of the cell, so there is no scale or sign to apply and no
    // tag, unit or context to report -- saying so is the honest answer, and the tray shows it.
    if (element.hasAttribute("data-awltux-value")) {
      var printed = element.getAttribute("data-awltux-value");
      var asNumber = Number(printed);
      if (!isFinite(asNumber)) {
        return { reason: "this cell does not hold a number" };
      }
      return {
        value: asNumber,
        raw: element.getAttribute("data-awltux-raw") || printed,
        scale: 0,
        sign: "",
        tag: "",
        unit: "",
        context: "",
        origin: "table"
      };
    }
    var text = String(element.textContent == null ? "" : element.textContent)
      .replace(/\u00a0/g, " ")
      .trim()
      .replace(/\s+/g, "");
    var negative = text.charAt(0) === "(" && text.slice(-1) === ")";
    if (negative) text = text.slice(1, -1);
    // A currency symbol is presentation: the unit is in `unitRef`.
    text = text.replace(/^[$£€¥]/, "");

    var number = transform(element.getAttribute("format"), text);
    if (number === null || number === "") {
      return { reason: "this figure uses a format this page cannot read" };
    }
    var value = Number(number);
    if (!isFinite(value)) {
      return { reason: "this figure is not a number" };
    }
    if (negative) value = -value;
    var scale = parseInt(element.getAttribute("scale") || "0", 10);
    if (!isFinite(scale)) scale = 0;
    if (scale !== 0) value = value * Math.pow(10, scale);
    var sign = (element.getAttribute("sign") || "").trim();
    if (sign === "-") value = -value;
    return {
      value: value,
      raw: text,
      scale: scale,
      sign: sign,
      tag: element.getAttribute("name") || "",
      unit: element.getAttribute("unitRef") || "",
      context: element.getAttribute("contextRef") || "",
      origin: "filing"
    };
  }

  function printedNumber(text) {
    /* A number as a *table* prints one, with no element to say what it is.
     *
     * Narrow on purpose. A figure written onto a balance sheet out of a cell the page
     * misread is the failure this whole flow makes easiest, so anything this cannot read
     * exactly -- a percentage, a footnote marker, a range, a dash, a word -- returns null
     * and the cell is not offered at all. Parentheses are a negative, a currency symbol is
     * presentation, and a comma is a thousands separator: those are the filing's own
     * conventions and are read rather than refused.
     *
     * A bare four-digit year is refused as well. A filing's tables are full of them -- the
     * date header over a column, a maturity year in a debt note -- and one of those landing
     * on a line of the accounts is worse than a line the reader has to type.
     */
    var raw = String(text == null ? "" : text)
      .replace(/\u00a0/g, " ")
      .trim();
    if (!raw) return null;
    var body = raw.replace(/^[$£€¥]\s*/, "").replace(/\s+/g, "");
    if (body.slice(-1) === "%") return null;
    var negative = body.charAt(0) === "(" && body.slice(-1) === ")";
    if (negative) body = body.slice(1, -1);
    if (!/^\d{1,3}(,\d{3})*(\.\d+)?$|^\d+(\.\d+)?$/.test(body)) return null;
    if (/^(19|20)\d{2}$/.test(body)) return null;
    var value = Number(body.replace(/,/g, ""));
    if (!isFinite(value)) return null;
    if (negative) value = -value;
    return { value: value, raw: raw };
  }

  function confirmUrl(base, filingId, period, statement, line, figure, caption, elementId, section) {
    /* Where a clicked figure goes: the confirmation page, with everything the reader clicked.
     *
     * This is the interface between the two pages, so it is one named function rather than
     * lines inside the tray -- the query-string property names are a contract, and `metric`
     * ("the accounting total the source is related to", in the request's words) is what decides
     * which line of the accounts the figure lands on.
     *
     * `caption` travels as its own parameter as well as in the note, because it is offered as a
     * **line to create** when the chart has nothing for it -- *"offer an alternative entry,
     * alongside the pre-defined, consisting of the header extracted from the 10-K"* -- and
     * `section` travels with it because a line needs a heading to be printed under.
     *
     * Resolved against `base` -- the page's own `location.href` -- rather than against the
     * document's `<base>`, because a filing may carry one and it would send our link to sec.gov.
     */
    var target = new URL("/accounts/" + encodeURIComponent(period) + "/corrections/new", base);
    target.searchParams.set("statement", statement);
    // Omitted when the reader came in without a line to fill: the confirmation form then asks
    // which line the figure belongs on, which is the question an "add a line" visit is there
    // to answer. An empty `metric` would be read as a line called "".
    if (line) target.searchParams.set("metric", line);
    target.searchParams.set("value", figureString(figure.value));
    target.searchParams.set("tag", figure.tag);
    target.searchParams.set("origin", figure.origin || "filing");
    if (caption) {
      target.searchParams.set("caption", caption);
      target.searchParams.set("note", "filed as: " + caption);
    }
    if (section) target.searchParams.set("section", section);
    // Back to the line as it was filed: the element's own id is an anchor in the plain
    // document, so the reader returns to the figure they read rather than to page one.
    if (elementId) {
      target.searchParams.set("url", "/filing/" + filingId + "/document#" + elementId);
    }
    return target.href;
  }

  function captionOf(element) {
    /* The line's name as the *filing* prints it.
     *
     * Most tagged figures sit in a table row whose first cell is the caption -- "Property and
     * equipment, net", "Total current liabilities" -- and that is the thing a reader is looking
     * for when they wonder whether this is the line they mean. The tag ("us-gaap:PropertyPlant
     * AndEquipmentNet") says the same thing to a machine and very little to a person.
     *
     * Where the figure *is* the first cell there is no caption to show and none is invented.
     * The walk is by hand rather than with `closest`, so it can be exercised without a browser.
     */
    var node = element;
    var cell = null;
    while (node) {
      var name = (node.tagName || "").toLowerCase();
      if (name === "td" || name === "th") {
        cell = node;
        break;
      }
      // Out of this row before finding a cell: a figure laid out directly in a table is not a
      // captioned row, and walking past the row would caption it with somebody else's line.
      if (name === "tr" || name === "table" || name === "body") return "";
      node = node.parentElement;
    }
    if (!cell || !cell.parentElement) return "";
    var row = cell.parentElement;
    if ((row.tagName || "").toLowerCase() !== "tr") return "";
    var first = null;
    for (var i = 0; i < row.children.length; i++) {
      var tag = (row.children[i].tagName || "").toLowerCase();
      if (tag === "td" || tag === "th") {
        first = row.children[i];
        break;
      }
    }
    if (!first || first === cell) return "";
    var text = String(first.textContent == null ? "" : first.textContent)
      .replace(/\u00a0/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    return text.slice(0, 120);
  }

  function normaliseLabel(text) {
    /* A caption reduced to the thing two spellings of it have in common.
     *
     * The filing writes "Total current assets:" and the chart writes "Total current assets".
     * Case, punctuation, a trailing colon, a bracketed note reference -- "(note 4)", "(1)",
     * "(net of allowance)" -- and a footnote marker are presentation, so they go; the words are
     * the identity. Used on *both* sides of the comparison, which is why it lives here rather
     * than on the server that sends the labels.
     */
    return String(text == null ? "" : text)
      .toLowerCase()
      .replace(/\([^)]*\)/g, " ")
      .replace(/\[[^\]]*\]/g, " ")
      .replace(/[\u2018\u2019']/g, "")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  //: Words that carry no identity in an account caption: a filing writes "Cash and cash
  //: equivalents" where the chart writes "Cash and equivalents", and the second "cash" and the
  //: "and" are the whole of the difference. Dropped before comparing, so that pair matches.
  var EMPTY_WORDS = { "and": 1, "of": 1, "the": 1, "to": 1, "for": 1, "in": 1, "on": 1 };

  function labelTokens(text) {
    /* The words of a caption, without repeats -- compared as a *set*, which is what makes the
     * matching safe in both directions:
     *
     * * "Cash and cash equivalents" and "Cash and equivalents" both reduce to
     *   {cash, equivalents}, so the commonest divergence in a real filing matches;
     * * "Total assets" reduces to {total, assets} and "Total current assets" to
     *   {total, current, assets}, which are **not** equal -- so the most dangerous pair in a
     *   balance sheet, a subtotal against the one below it, does not.
     *
     * A caption that matches nothing simply leaves the reader to choose the line in the form,
     * which is where they were going anyway. A wrong guess pre-selected costs a correction.
     */
    var words = normaliseLabel(text).split(" ").filter(Boolean);
    var seen = {};
    var out = [];
    for (var i = 0; i < words.length; i++) {
      if (EMPTY_WORDS[words[i]] || seen[words[i]]) continue;
      seen[words[i]] = 1;
      out.push(words[i]);
    }
    out.sort();
    return out;
  }

  function matchLabel(caption, known) {
    /* Which of this project's lines a filing's caption looks like, or "".
     *
     * `known` is an array of `{label, metric}` for the statement the reader came from, so a
     * caption on the balance sheet is never matched against an income-statement line.
     */
    var wanted = labelTokens(caption);
    if (!wanted.length) return "";
    for (var i = 0; i < known.length; i++) {
      var theirs = labelTokens(known[i].label);
      if (theirs.length !== wanted.length) continue;
      var same = true;
      for (var j = 0; j < wanted.length; j++) {
        if (theirs[j] !== wanted[j]) {
          same = false;
          break;
        }
      }
      if (same) return known[i].metric;
    }
    return "";
  }

  function inHeaderRow(row) {
    /* A `th` row is a heading -- "2024", "2023" -- and its cells are dates, not figures. */
    var node = row.parentElement;
    while (node) {
      var name = (node.tagName || "").toLowerCase();
      if (name === "thead") return true;
      if (name === "table" || name === "body") return false;
      node = node.parentElement;
    }
    return false;
  }

  function cellsOf(row) {
    var out = [];
    var children = row.children || [];
    for (var i = 0; i < children.length; i++) {
      var tag = (children[i].tagName || "").toLowerCase();
      if (tag === "td" || tag === "th") out.push(children[i]);
    }
    return out;
  }

  function rowFigures(row, known) {
    /* What one table row offers: the caption the filing gives it, the line it looks like, and
     * the cells that hold a readable figure.
     *
     * The caption is the **first cell with a word in it**, not simply the first cell: a filing
     * lays out an indent, a bullet or an empty spacer in front of the label often enough that
     * taking cell zero would caption half the statement with nothing. The cells that hold the
     * figures are everything after it, on the same reasoning.
     *
     * Takes a row rather than reaching for the document, so a whole table can be exercised
     * without a browser -- the same shape `contextDates` uses for contexts.
     */
    if ((row.tagName || "").toLowerCase() === "tr" && inHeaderRow(row)) {
      return { caption: "", metric: "", values: [] };
    }
    var cells = cellsOf(row);
    if (cells.length < 2) return { caption: "", metric: "", values: [] };
    var at = -1;
    for (var i = 0; i < cells.length; i++) {
      if (/[a-z]/i.test(String(cells[i].textContent || ""))) {
        at = i;
        break;
      }
    }
    if (at === -1 || at === cells.length - 1) {
      return { caption: "", metric: "", values: [] };
    }
    var caption = String(cells[at].textContent || "")
      .replace(/\u00a0/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 120);
    var values = [];
    for (var j = at + 1; j < cells.length; j++) {
      if ((cells[j].tagName || "").toLowerCase() === "th") continue;
      var figure = printedNumber(cells[j].textContent);
      if (figure) values.push({ cell: cells[j], value: figure.value, raw: figure.raw });
    }
    return { caption: caption, metric: matchLabel(caption, known), values: values };
  }

  function markTableFigures(rows, known) {
    /* Every readable figure in every table, marked so a click can find it. Returns how many.
     *
     * This is the fallback for a report with no tagged figures at all. It is deliberately not
     * run on a document that *is* tagged: there the facts are the filer's own statement of
     * what each number is, and a second reading of the same table could only disagree with it.
     */
    var marked = 0;
    for (var i = 0; i < rows.length; i++) {
      var found = rowFigures(rows[i], known);
      for (var j = 0; j < found.values.length; j++) {
        var cell = found.values[j].cell;
        cell.className =
          (cell.className ? cell.className + " " : "") + TABLE_CLASS;
        cell.setAttribute("data-awltux-value", String(found.values[j].value));
        cell.setAttribute("data-awltux-raw", found.values[j].raw);
        cell.setAttribute("data-awltux-caption", found.caption);
        if (found.metric) cell.setAttribute("data-awltux-metric", found.metric);
        marked++;
      }
    }
    return marked;
  }

  function dateInContext(context) {
    /* The date a figure is as at (a balance sheet line) or for (an income or cash line).
     *
     * Worth the walk: a filing's tables put the current year and the prior year side by side in
     * one row, under the same caption, and both are tagged. Measured on Microsoft's 2026 10-K:
     * the row captioned "Total assets" carries `us-gaap:Assets` twice, 758,376 and 619,003,
     * distinguished only by `contextRef`. A reader clicking the wrong column with the right
     * caption is the easiest mistake in this whole flow, and the context is what names it.
     *
     * The dates live in the `xbrli:context` definitions in the document's `ix:header`; this
     * walks one of them for its `endDate` (a duration) or its `instant`.
     */
    var found = { date: "", instant: false };
    var stack = [context];
    while (stack.length) {
      var current = stack.pop();
      var tag = (current.tagName || "").toLowerCase();
      var text = String(current.textContent == null ? "" : current.textContent).trim();
      if (tag === "xbrli:instant" && !found.date) {
        found = { date: text, instant: true };
      } else if (tag === "xbrli:enddate" && !found.date) {
        found = { date: text, instant: false };
      }
      var children = current.children || [];
      for (var i = 0; i < children.length; i++) stack.push(children[i]);
    }
    return found.date ? found : null;
  }

  function contextDates(contexts) {
    /* `contextRef` -> what that context says about the date, for every context in the document.
     *
     * Takes an array-like of context elements rather than reaching for the document, so it can
     * be exercised without a browser. A context with no date at all -- a dimension-only context,
     * which filings do carry -- is left out rather than shown as blank.
     */
    var map = {};
    for (var i = 0; i < contexts.length; i++) {
      var element = contexts[i];
      var id = typeof element.getAttribute === "function" ? element.getAttribute("id") : "";
      if (!id) continue;
      var found = dateInContext(element);
      if (found) map[id] = found;
    }
    return map;
  }

  function figureString(value) {
    /* No exponent form: the confirmation form parses this, and `1e+21` is not a figure. */
    return value.toLocaleString("en-US", { useGrouping: false, maximumFractionDigits: 10 });
  }

  function pick(target, dates) {
    /* What a click produced: the figure, the filing's name for its line, its id -- or why
     * nothing was picked.
     *
     * Pulled out of the event handler so that the whole decision is testable: the handler below
     * is then six lines of DOM plumbing, and everything that can be *wrong* about a click is
     * here, with the contexts passed in rather than reached for.
     */
    var element = factFrom(target);
    if (!element) return null;
    var figure = figureOf(element);
    if (figure.value === undefined) return { problem: figure.reason };
    var context = dates[figure.context];
    if (context) figure.asOf = context;
    return {
      figure: figure,
      caption: captionOf(element),
      elementId: element.getAttribute("id") || "",
      // The line this row *looks like*, for a table cell the page could match against the
      // chart. Empty for a tagged figure and for a caption nothing recognises, and the reader
      // chooses the line in the confirmation form either way.
      metric: element.getAttribute("data-awltux-metric") || ""
    };
  }

  /* Everything above decides what a clicked figure *is*, what the filing calls the line it sits
   * on, which period it belongs to and where the reader is sent with it. None of it needs a
   * document, and each of those is something that can be wrong in a way nobody notices, so they
   * are handed to `tests/test_filing_picker.py`, which drives them through `node --test`.
   * Everything below is browser wiring: building the tray and mounting it. */
  if (typeof document === "undefined" || typeof window === "undefined") {
    module.exports = {
      transform: transform,
      figureOf: figureOf,
      printedNumber: printedNumber,
      captionOf: captionOf,
      factFrom: factFrom,
      pick: pick,
      dateInContext: dateInContext,
      contextDates: contextDates,
      confirmUrl: confirmUrl,
      figureString: figureString,
      normaliseLabel: normaliseLabel,
      matchLabel: matchLabel,
      rowFigures: rowFigures,
      markTableFigures: markTableFigures,
    };
    return;
  }

  var params = new URLSearchParams(window.location.search);
  var period = params.get("awltux_period");
  var line = params.get("awltux_line");
  var label = params.get("awltux_label") || line;
  var statement = params.get("awltux_statement") || "profit_and_loss";
  // The heading the residual's own line sits under, so a line created from this filing lands
  // where the reader is already working rather than at the top of the statement.
  var section = params.get("awltux_section") || "";
  // The period end the accounts are for, so a figure clicked out of the *other* column can be
  // marked as the other column rather than written in silently.
  var periodEnd = params.get("awltux_period_end") || "";
  var filingId = (window.location.pathname.match(/\/filing\/(\d+)\//) || [])[1] || "";
  // Only the period is required. A link that names a line is the reader following up a
  // subtotal that is out by something; one that does not is the reader opening the filing to
  // find a figure the extractor never had -- which is the *only* way in when every subtotal
  // reconciles, so refusing it would leave those accounts with no route to their own filing.
  if (!period) return;

  // The chart's lines for the statement the reader came from, put on the script tag by the
  // route. Used only by the untagged-table fallback, to say which of the project's accounts a
  // row's caption looks like -- see `matchLabel`.
  var known = [];
  (function () {
    var tag = document.getElementById(SCRIPT_ID);
    var payload = tag ? tag.getAttribute("data-awltux-accounts") : "";
    if (!payload) return;
    try {
      var parsed = JSON.parse(payload);
      if (Object.prototype.toString.call(parsed) === "[object Array]") known = parsed;
    } catch (error) {
      // A payload this page cannot read means no line is pre-selected, which is where the
      // reader starts anyway. It is not a reason to refuse to instrument the document.
      known = [];
    }
  })();

  var dates = contextDates(document.getElementsByTagName("xbrli:context"));

  function labelForMetric(metric) {
    /* The chart's own name for a line recognised by a row's caption, for the tray's link. */
    if (!metric) return "";
    for (var i = 0; i < known.length; i++) {
      if (known[i].metric === metric) return known[i].label;
    }
    return "";
  }

  /* ----------------------------------------------------------------- the tray */

  var tray = document.createElement("aside");
  tray.className = "awltux-tray";
  tray.setAttribute("aria-label", "Figures picked out of this report");

  var heading = document.createElement("p");
  heading.className = "awltux-tray-head";
  heading.textContent = line
    ? "Picked from this report \u2014 add one to " + label
    : "Picked from this report \u2014 click a figure, then say which line it is";
  tray.appendChild(heading);

  var list = document.createElement("ul");
  tray.appendChild(list);

  var hint = document.createElement("p");
  hint.className = "awltux-tray-hint";
  hint.textContent = HINT;
  tray.appendChild(hint);

  var clear = document.createElement("button");
  clear.type = "button";
  clear.className = "awltux-tray-clear";
  clear.textContent = "Clear";
  clear.addEventListener("click", function () {
    list.textContent = "";
    hint.textContent = HINT;
  });
  tray.appendChild(clear);

  function addFigure(figure, elementId, caption, metric) {
    hint.textContent = HINT;
    var item = document.createElement("li");

    // The filer's own words for the line first: that is what the reader is matching against
    // the accounts, and the figure means little without it.
    if (caption) {
      var name = document.createElement("span");
      name.className = "awltux-tray-caption";
      name.textContent = caption;
      item.appendChild(name);
    }

    var figureLine = document.createElement("strong");
    figureLine.textContent = figure.value.toLocaleString("en-US");
    item.appendChild(figureLine);

    // The working, so the figure can be checked rather than taken: what the filing printed,
    // what it was scaled by, and the sign it carried. A figure read out of an untagged table
    // has none of those, and says so rather than showing an empty sum.
    var working = document.createElement("span");
    working.className = "awltux-tray-working";
    if (figure.origin === "table") {
      working.textContent = " = " + figure.raw + ", as the table prints it";
    } else {
      var steps = [figure.raw];
      if (figure.scale) steps.push("\u00d7 10^" + figure.scale);
      if (figure.sign === "-") steps.push("sign \u2212");
      working.textContent = " = " + steps.join(" ");
    }
    item.appendChild(working);

    // Only when there is one. A table cell carries no tag, and an empty code block would say
    // "we looked for a tag and found nothing" -- which is true but is not what the reader needs.
    if (figure.tag) {
      var tag = document.createElement("code");
      tag.textContent = figure.tag;
      item.appendChild(tag);
    }

    if (figure.context) {
      var context = document.createElement("span");
      context.className = "awltux-tray-context";
      context.textContent = figure.context + (figure.unit ? " \u00b7 " + figure.unit : "");
      item.appendChild(context);
    }

    // Which column of the filing's table this is. Shown always, because "the current year" and
    // "the prior year" sit in one row under one caption; marked when it is not the period the
    // accounts are for, because writing the wrong year's figure onto the right line is the
    // mistake this whole flow makes easiest.
    if (figure.asOf) {
      var when = document.createElement("span");
      var other = periodEnd && figure.asOf.date !== periodEnd;
      when.className = other ? "awltux-tray-off" : "awltux-tray-context";
      when.textContent = other
        ? "\u26a0 " +
          (figure.asOf.instant ? "as at " : "period ending ") +
          figure.asOf.date +
          " \u2014 not this period (" +
          periodEnd +
          ")"
        : (figure.asOf.instant ? "as at " : "period ending ") + figure.asOf.date;
      item.appendChild(when);
    }

    var link = document.createElement("a");
    link.href = confirmUrl(
      window.location.href,
      filingId,
      period,
      statement,
      metric || line,
      figure,
      caption,
      elementId,
      section
    );
    link.target = "_blank";
    link.rel = "noopener";
    // Named after the line the figure is going onto when one is known -- the line the reader
    // came in with, or the line the row's own caption matched -- and otherwise after what the
    // link does, because the confirmation form is where the line gets chosen.
    var onto = label || labelForMetric(metric);
    link.textContent = onto ? "Add to " + onto : "Use this figure";
    item.appendChild(link);

    list.insertBefore(item, list.firstChild);
  }

  /* ------------------------------------------------------------ the document */

  function factFrom(node) {
    /* The nearest `ix:nonFraction` at or above this node -- which is how a click anywhere on a
     * figure, including on a `<span>` inside it, finds the fact -- or, in a report that tags
     * nothing, the nearest table cell this script marked itself.
     *
     * Walked by hand rather than with `closest("ix\\:nonfraction")`: a colon in a CSS selector
     * has to be escaped, and that escaping is the kind of detail that works until the day it
     * does not.
     *
     * The facts carry no `tabindex` and no `role`: a 10-K holds well over a thousand of them
     * (measured: 1,583 in Microsoft's 2026 filing -- 1,583 `<ix:nonFraction>` elements, or 3,166
     * if the closing tags are counted too), and that many tab stops would make the document
     * unnavigable by keyboard -- worse than an affordance that is pointer-only. The tray's own
     * links are ordinary anchors, and reachable by keyboard once a figure is picked, which is
     * what the reader needs the keyboard for.
     *
     * The HTML parser uppercases `tagName`, so it is lowercased here.
     */
    while (node) {
      if (node.tagName && node.tagName.toLowerCase() === FACT_TAG) return node;
      if (node.hasAttribute && node.hasAttribute("data-awltux-value")) return node;
      node = node.parentElement;
    }
    return null;
  }

  function markFacts() {
    var all = document.getElementsByTagName(FACT_TAG);
    var marked = 0;
    for (var i = 0; i < all.length; i++) {
      var element = all[i];
      if ((element.getAttribute("xsi:nil") || "").toLowerCase() === "true") continue;
      element.className = (element.className ? element.className + " " : "") + "awltux-fact";
      marked++;
    }
    return marked;
  }

  document.addEventListener(
    "click",
    function (event) {
      var picked = pick(event.target, dates);
      if (!picked) return;
      event.preventDefault();
      if (picked.problem) {
        hint.textContent = "That figure cannot be read: " + picked.problem + ".";
        return;
      }
      addFigure(picked.figure, picked.elementId, picked.caption, picked.metric);
    },
    true
  );

  var style = document.createElement("style");
  style.textContent = [
    ".awltux-fact{cursor:pointer;border-bottom:1px dotted rgba(120,120,120,.75)}",
    ".awltux-fact:hover{background:rgba(227,179,65,.18)}",
    // An untagged table cell: the same affordance, and the same colour when the row's caption
    // matched one of this project's lines -- that row is the one the reader most likely wants.
    ".awltux-tablefact{cursor:pointer;border-bottom:1px dotted rgba(120,120,120,.75)}",
    ".awltux-tablefact:hover{background:rgba(227,179,65,.18)}",
    ".awltux-tablefact[data-awltux-metric]{border-bottom-color:rgba(138,180,248,.9)}",
    // A tray rather than a modal: the report has to stay readable while a figure is checked
    // against the statement it is going onto, and a modal would hide the thing being read.
    ".awltux-tray{position:fixed;right:12px;bottom:12px;z-index:2147483647;width:340px;",
    "max-height:60vh;overflow:auto;padding:10px 12px;border-radius:8px;",
    "background:#1b2129;color:#e8eef5;font:13px/1.45 system-ui,sans-serif;",
    "box-shadow:0 8px 28px rgba(0,0,0,.55);border:1px solid #39434f}",
    ".awltux-tray-head{margin:0 0 6px;font-weight:600}",
    ".awltux-tray ul{list-style:none;margin:0;padding:0}",
    ".awltux-tray li{padding:8px 0;border-top:1px solid #39434f}",
    ".awltux-tray code{display:block;font-size:11px;color:#afb9c6;word-break:break-all}",
    ".awltux-tray-caption{display:block;font-weight:600}",
    ".awltux-tray-working,.awltux-tray-context,.awltux-tray-hint{display:block;",
    "font-size:11px;color:#afb9c6}",
    ".awltux-tray-off{display:block;font-size:11px;color:#e3b341;font-weight:600}",
    ".awltux-tray a{color:#8ab4f8;font-weight:600}",
    ".awltux-tray-hint{margin:0}",
    ".awltux-tray-clear{margin-top:8px;background:transparent;color:#afb9c6;",
    "border:1px solid #39434f;border-radius:4px;padding:2px 8px;cursor:pointer}"
  ].join("");

  function mount() {
    document.body.appendChild(style);
    document.body.appendChild(tray);
    if (markFacts()) return;
    // No tagged figures: this filer furnished the report as plain HTML, so the tables are read
    // instead. `getElementsByTagName("tr")` is every row in the document, including the ones
    // inside the notes -- a report has hundreds of tables and the reader is looking for one
    // number in one of them, which is why the row's caption is carried onto every figure.
    var marked = markTableFigures(document.getElementsByTagName("tr"), known);
    if (marked) {
      hint.textContent =
        "This report carries no tagged figures, so the numbers in its tables are offered " +
        "instead. " +
        marked +
        " of them can be read: click the one you want and say which line it belongs on.";
      return;
    }
    hint.textContent =
      "This report holds no tagged figures and no table figures that can be read. It may be " +
      "the wrong document -- the accounts can still be corrected by hand from the accounts page.";
  }

  // The script is loaded with `defer`, so the document is parsed and `body` exists by the time
  // it runs; the listener is the belt for any browser that runs it earlier.
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
