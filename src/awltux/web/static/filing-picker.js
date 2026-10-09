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
      context: element.getAttribute("contextRef") || ""
    };
  }

  function confirmUrl(base, filingId, period, statement, line, figure, caption, elementId) {
    /* Where a clicked figure goes: the confirmation page, with everything the reader clicked.
     *
     * This is the interface between the two pages, so it is one named function rather than
     * lines inside the tray -- the query-string property names are a contract, and `metric`
     * ("the accounting total the source is related to", in the request's words) is what decides
     * which line of the accounts the figure lands on.
     *
     * Resolved against `base` -- the page's own `location.href` -- rather than against the
     * document's `<base>`, because a filing may carry one and it would send our link to sec.gov.
     * The caption goes into `note`: the record then says which line of the filing the figure was
     * read from, in the filer's words rather than in a taxonomy's.
     */
    var target = new URL("/accounts/" + encodeURIComponent(period) + "/corrections/new", base);
    target.searchParams.set("statement", statement);
    target.searchParams.set("metric", line);
    target.searchParams.set("value", figureString(figure.value));
    target.searchParams.set("tag", figure.tag);
    target.searchParams.set("origin", "filing");
    if (caption) target.searchParams.set("note", "filed as: " + caption);
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
    var node = element.parentElement;
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
      elementId: element.getAttribute("id") || ""
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
      captionOf: captionOf,
      factFrom: factFrom,
      pick: pick,
      dateInContext: dateInContext,
      contextDates: contextDates,
      confirmUrl: confirmUrl,
      figureString: figureString,
    };
    return;
  }

  var params = new URLSearchParams(window.location.search);
  var period = params.get("awltux_period");
  var line = params.get("awltux_line");
  var label = params.get("awltux_label") || line;
  var statement = params.get("awltux_statement") || "profit_and_loss";
  // The period end the accounts are for, so a figure clicked out of the *other* column can be
  // marked as the other column rather than written in silently.
  var periodEnd = params.get("awltux_period_end") || "";
  var filingId = (window.location.pathname.match(/\/filing\/(\d+)\//) || [])[1] || "";
  if (!period || !line) return;

  var dates = contextDates(document.getElementsByTagName("xbrli:context"));

  /* ----------------------------------------------------------------- the tray */

  var tray = document.createElement("aside");
  tray.className = "awltux-tray";
  tray.setAttribute("aria-label", "Figures picked out of this report");

  var heading = document.createElement("p");
  heading.className = "awltux-tray-head";
  heading.textContent = "Picked from this report \u2014 add one to " + label;
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

  function addFigure(figure, elementId, caption) {
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
    // what it was scaled by, and the sign it carried.
    var working = document.createElement("span");
    working.className = "awltux-tray-working";
    var steps = [figure.raw];
    if (figure.scale) steps.push("\u00d7 10^" + figure.scale);
    if (figure.sign === "-") steps.push("sign \u2212");
    working.textContent = " = " + steps.join(" ");
    item.appendChild(working);

    var tag = document.createElement("code");
    tag.textContent = figure.tag;
    item.appendChild(tag);

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
      line,
      figure,
      caption,
      elementId
    );
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "Add to " + label;
    item.appendChild(link);

    list.insertBefore(item, list.firstChild);
  }

  /* ------------------------------------------------------------ the document */

  function factFrom(node) {
    /* The nearest `ix:nonFraction` at or above this node -- which is how a click anywhere on a
     * figure, including on a `<span>` inside it, finds the fact.
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
      addFigure(picked.figure, picked.elementId, picked.caption);
    },
    true
  );

  var style = document.createElement("style");
  style.textContent = [
    ".awltux-fact{cursor:pointer;border-bottom:1px dotted rgba(120,120,120,.75)}",
    ".awltux-fact:hover{background:rgba(227,179,65,.18)}",
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
    if (!markFacts()) {
      hint.textContent =
        "This report holds no tagged figures to click. It may be the wrong document -- the " +
        "accounts can still be corrected by hand from the accounts page.";
    }
  }

  // The script is loaded with `defer`, so the document is parsed and `body` exists by the time
  // it runs; the listener is the belt for any browser that runs it earlier.
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
