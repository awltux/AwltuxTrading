/* AwltuxTrading dashboard behaviour.
 *
 * Only the things the server cannot do: consume the live news stream, draw the
 * price sparkline, trigger a job, swap a table's page in place, and tell the server
 * which clock the reader is on. Everything else -- sorting, filtering, paging -- is a
 * plain URL so it works without this file. The paging below is an enhancement rather
 * than a mechanism: the links are still links.
 */
(function () {
  "use strict";

  // ----------------------------------------------------------- display zone
  // The server has no idea what clock the reader is on, and guessing from an IP
  // address or a language header is wrong often enough to matter. So the browser
  // states it once, in a cookie, and every rendered time is then correct --
  // including after the reader travels or the clocks change.
  var ZONE_COOKIE = "awltux_tz";

  function cookieValue(name) {
    var match = document.cookie.match(new RegExp("(?:^|;\\s*)" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function syncDisplayZone() {
    try {
      if (!window.Intl || !Intl.DateTimeFormat) return;
      var zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (!zone || cookieValue(ZONE_COOKIE) === zone) return;

      // Only reload once per detected zone. If cookies are blocked the cookie
      // will never stick, and without this guard the page would reload forever.
      var asked = null;
      try { asked = window.sessionStorage.getItem("awltux_tz_asked"); } catch (e) { /* private mode */ }
      if (asked === zone) return;
      try { window.sessionStorage.setItem("awltux_tz_asked", zone); } catch (e) { /* private mode */ }

      document.cookie = ZONE_COOKIE + "=" + encodeURIComponent(zone) +
        ";path=/;max-age=31536000;SameSite=Lax";
      window.location.reload();
    } catch (e) {
      // No Intl, no storage, or a hostile environment: the server-rendered zone
      // stays, and it is labelled on the page, so nothing is ambiguous.
    }
  }

  syncDisplayZone();

  // ------------------------------------------------------------- news ticker
  //
  // The ticker is rendered **only** by the server. This used to hold a second renderer
  // (`tickerElement` / `gradeBadge`) for items pushed down the stream, and the two drifted:
  // the JS built the badge classes itself, and the live path showed every relevant story
  // one-per-story while the server showed one entry per *event*, ranked and floored. Two
  // renderers meant two answers to "what belongs in the ticker".
  //
  // So the stream now says only *that* something changed, and this re-fetches the same
  // fragment the first paint used.

  //: Bursts arrive together -- one sweep stores dozens of stories in a minute -- and each
  //: one would otherwise re-render the whole track. The fragment is idempotent, so waiting
  //: and fetching once loses nothing.
  var TICKER_REFRESH_DEBOUNCE_MS = 1500;

  function startTicker() {
    var root = document.getElementById("news-flash");
    var track = document.getElementById("ticker-items");
    if (!root || !track || !window.EventSource) return;

    function loadFragment() {
      return fetch(root.dataset.fallbackUrl)
        .then(function (response) { return response.text(); })
        .then(function (html) {
          // Replaced wholesale rather than appended to: the server decides what the
          // ticker shows, and appending to an old render is how it stops agreeing.
          if (html.trim()) track.innerHTML = html;
        });
    }

    // Seed with the server-rendered fragment so the bar is never empty while the stream
    // connects.
    loadFragment().catch(function () { /* offline: the seed is cosmetic only */ });

    var pending = null;
    function scheduleRefresh() {
      if (pending) return;
      pending = window.setTimeout(function () {
        pending = null;
        // A failed refresh leaves the current contents alone and waits for the next
        // signal, rather than emptying a bar that is still telling the truth.
        loadFragment().catch(function () { /* keep what we have */ });
      }, TICKER_REFRESH_DEBOUNCE_MS);
    }

    var source = new EventSource(root.dataset.streamUrl);

    source.addEventListener("refresh", scheduleRefresh);

    // Delegated, because the track's contents are replaced wholesale on every refresh --
    // a listener bound to the button would be thrown away with the element it was bound to.
    track.addEventListener("click", function (event) {
      var button = event.target.closest(".ticker-dismiss");
      if (!button) return;
      event.preventDefault();

      // Removed first so the click feels answered, then re-rendered from the server: that
      // is what fills the gap with the next story rather than leaving the bar one short.
      // If the POST failed the entry comes back, which is the honest outcome.
      var entry = button.closest(".ticker-item");
      if (entry) entry.remove();
      fetch(button.dataset.dismissUrl, {
        method: "POST",
        headers: { "X-Requested-With": "fetch" }
      }).then(loadFragment, loadFragment);
    });

    // EventSource reconnects on its own; surface the break without spamming.
    source.addEventListener("error", function () {
      root.classList.add("stream-down");
    });
    source.addEventListener("open", function () {
      root.classList.remove("stream-down");
    });
  }

  // ------------------------------------------------------------- price chart
  //
  // The frame is drawn even when there is nothing to draw inside it.
  //
  // This used to return early on fewer than two points, so an instrument with no
  // stored bars rendered a blank panel that was indistinguishable from a chart
  // that had failed to load. The axes and the waiting message are now drawn on the
  // empty canvas, so the panel always says what it is waiting for.
  //
  // **The palette and the type size are read from the stylesheet, not written here.**
  // They were literals, and they drifted: when the interface's text was enlarged and
  // its greys brightened, the axis labels stayed at 11px in the old grey because they
  // were the one place the values were typed twice. The custom properties are the
  // single source now, and the font comes off the root element so it follows the same
  // `html { font-size }` as everything else.
  //
  // The fallbacks live in one map rather than at each call site: they exist only for
  // the case where a property is missing from `:root`, and four copies of that case
  // is four chances for two of them to disagree about what `--muted` used to be.
  var PALETTE_FALLBACK = {
    "--line": "#39434f",
    "--muted": "#afb9c6",
    "--good": "#4fd35f",
    "--bad": "#ff7b72"
  };

  // Read once each. `getComputedStyle` forces a style recalculation, and the chart
  // is drawn on every resize tick, so re-reading the same four colours per frame was
  // paying for a layout flush to learn something that cannot change: there is no
  // theme switcher, and the palette is fixed for the life of the page.
  var paletteCache = {};
  var rootFontPx = null;

  /** One CSS custom property from `:root`, resolved and cached. */
  function styleValue(name) {
    if (!(name in paletteCache)) {
      var value = getComputedStyle(document.documentElement).getPropertyValue(name);
      paletteCache[name] = (value || "").trim() || PALETTE_FALLBACK[name] || "";
    }
    return paletteCache[name];
  }

  /** The root font size in pixels -- the one number the whole stylesheet scales from. */
  function rootFontSize() {
    if (rootFontPx === null) {
      rootFontPx = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    }
    return rootFontPx;
  }

  /** A palette hex at an alpha, so the fill under the price line tracks the palette. */
  function withAlpha(hex, alpha) {
    var text = String(hex).replace("#", "");
    if (text.length === 3) {
      text = text[0] + text[0] + text[1] + text[1] + text[2] + text[2];
    }
    var number = parseInt(text, 16);
    if (isNaN(number)) return hex;
    return "rgba(" + ((number >> 16) & 255) + "," + ((number >> 8) & 255) + "," +
      (number & 255) + "," + alpha + ")";
  }

  /** A size in rem, resolved against the root font size, as a canvas font string. */
  function chartFont(rem) {
    return Math.round(rem * rootFontSize()) + "px ui-sans-serif, system-ui, sans-serif";
  }

  function drawChart() {
    var canvas = document.getElementById("price-chart");
    if (!canvas) return;

    // Parsed independently: the dates only label the axis, so a malformed date
    // list must not take the price line down with it. It did once -- see the note
    // on the attribute quoting in instrument.html.
    var series = parseList(canvas.dataset.series);
    var dates = parseList(canvas.dataset.dates);

    var line = styleValue("--line");
    var muted = styleValue("--muted");
    var up = styleValue("--good");
    var down = styleValue("--bad");

    var ratio = window.devicePixelRatio || 1;
    var width = canvas.clientWidth || 600;
    var height = Number(canvas.getAttribute("height")) || 180;
    canvas.width = width * ratio;
    canvas.height = height * ratio;

    var ctx = canvas.getContext("2d");
    ctx.scale(ratio, ratio);
    ctx.clearRect(0, 0, width, height);

    var pad = 8;
    // Room under the plot for the two date labels, which grew with the type size.
    var labelSpace = 20;
    var plotWidth = width - pad * 2;
    var plotHeight = height - pad * 2 - labelSpace;

    // The axes are drawn first and unconditionally, so an empty panel has the
    // same shape as a full one and reads as "nothing yet" rather than "broken".
    ctx.strokeStyle = line;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad, pad);
    ctx.lineTo(pad, pad + plotHeight);
    ctx.lineTo(width - pad, pad + plotHeight);
    ctx.stroke();

    // Grid
    for (var g = 0; g <= 4; g++) {
      var gy = pad + (g / 4) * plotHeight;
      ctx.beginPath();
      ctx.moveTo(pad, gy);
      ctx.lineTo(width - pad, gy);
      ctx.stroke();
    }

    if (series.length < 2) {
      drawEmptyChart(ctx, width, pad, plotWidth, plotHeight, series);
      return;
    }

    var min = Math.min.apply(null, series);
    var max = Math.max.apply(null, series);
    if (max === min) { max = min + 1; }

    function x(i) { return pad + (i / (series.length - 1)) * plotWidth; }
    function y(value) { return pad + plotHeight - ((value - min) / (max - min)) * plotHeight; }

    // Price line, coloured by whether the period ended up or down.
    var rising = series[series.length - 1] >= series[0];
    var trend = rising ? up : down;
    ctx.strokeStyle = trend;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    series.forEach(function (value, index) {
      if (index === 0) ctx.moveTo(x(index), y(value));
      else ctx.lineTo(x(index), y(value));
    });
    ctx.stroke();

    var gradient = ctx.createLinearGradient(0, pad, 0, pad + plotHeight);
    gradient.addColorStop(0, withAlpha(trend, 0.22));
    gradient.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = gradient;
    ctx.lineTo(x(series.length - 1), pad + plotHeight);
    ctx.lineTo(x(0), pad + plotHeight);
    ctx.closePath();
    ctx.fill();

    // Axis labels: only the extremes, so the chart stays readable.
    ctx.fillStyle = muted;
    ctx.font = chartFont(0.8);
    ctx.fillText(max.toFixed(2), pad + 2, pad + 10);
    ctx.fillText(min.toFixed(2), pad + 2, pad + plotHeight - 2);
    if (dates.length) {
      ctx.fillText(dates[0], pad, height - 3);
      var lastLabel = dates[dates.length - 1];
      ctx.fillText(lastLabel, width - pad - ctx.measureText(lastLabel).width, height - 3);
    }
  }

  /** Parse a JSON list out of a data attribute; [] if absent or malformed. */
  function parseList(raw) {
    try {
      var value = JSON.parse(raw || "[]");
      return Array.isArray(value) ? value : [];
    } catch (err) {
      return [];
    }
  }

  /** The empty frame: the axes, a flat baseline, and any lone point. */
  function drawEmptyChart(ctx, width, pad, plotWidth, plotHeight, series) {
    var middle = pad + plotHeight / 2;

    // One bar is still a fact, so plot it rather than pretending there is none.
    // Its height is arbitrary -- with a single point there is no scale to place it
    // on -- so it sits mid-plot and the sentence below says what it is.
    var textOffset = 4;
    if (series.length === 1) {
      ctx.fillStyle = styleValue("--muted");
      ctx.beginPath();
      ctx.arc(pad + plotWidth / 2, middle, 2.5, 0, Math.PI * 2);
      ctx.fill();
      // Under the dot, not through it.
      textOffset = 26;
    }

    // Only the headline is drawn here. The reason it is waiting belongs in the
    // sentence underneath, which is selectable, translatable and reachable by a
    // screen reader -- none of which canvas text is, so repeating it there would
    // be duplication without the benefit.
    ctx.textAlign = "center";
    ctx.fillStyle = styleValue("--muted");
    ctx.font = chartFont(0.95);
    ctx.fillText("Waiting for data", width / 2, middle + textOffset);
    ctx.textAlign = "start";
  }

  // ---------------------------------------------------------------- job runs
  //
  // Every button for a job is updated together, and the running state is read
  // back from the server rather than remembered here.
  //
  // Two bugs made this necessary. The handler used to act on the clicked element
  // alone, so a job listed in both "Run these next" and "Scheduled jobs" would
  // show "Running…" in one table and an enabled "Run now" in the other -- offering
  // to start a job that was already running. And on success it reloaded the page
  // after 900ms, which reset every *other* running job's button while those jobs
  // were still going, leaving no way to tell they were alive.
  var runningJobs = new Set();

  function buttonsFor(jobId) {
    return document.querySelectorAll('.run-job[data-job="' + jobId + '"]');
  }

  function setRunning(jobId, running) {
    buttonsFor(jobId).forEach(function (button) {
      if (running) {
        button.disabled = true;
        button.textContent = "Running…";
        button.title = "A run is in progress";
      } else {
        button.disabled = false;
        button.textContent = "Run now";
        button.title = "";
      }
    });
  }

  function refreshRunning() {
    fetch("/api/jobs")
      .then(function (response) { return response.json(); })
      .then(function (body) {
        var inFlight = new Set(body.in_flight || []);
        // Clear jobs that finished, set jobs that started elsewhere -- another
        // tab, the scheduler, a previous page load.
        runningJobs.forEach(function (jobId) {
          if (!inFlight.has(jobId)) setRunning(jobId, false);
        });
        inFlight.forEach(function (jobId) { setRunning(jobId, true); });
        runningJobs = inFlight;
      })
      .catch(function () { /* the page still works without the poll */ });
  }

  function wireJobButtons() {
    var buttons = document.querySelectorAll(".run-job");
    if (!buttons.length) return;

    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        var jobId = button.dataset.job;
        setRunning(jobId, true);
        runningJobs.add(jobId);

        fetch("/api/jobs/" + encodeURIComponent(jobId) + "/run", { method: "POST" })
          .then(function (response) {
            return response.json().then(function (body) {
              return { ok: response.ok, body: body };
            });
          })
          .then(function (result) {
            if (!result.ok) {
              // A refusal is the server's answer, so show it rather than
              // pretending the run happened.
              buttonsFor(jobId).forEach(function (other) {
                other.disabled = false;
                other.textContent = "Failed";
                other.title = result.body.detail || "job failed";
              });
              runningJobs.delete(jobId);
              return;
            }
            // Reload to refresh the history and the coverage counts. Safe now that
            // the server renders which jobs are still running: the other buttons
            // come back as "Running…" instead of being quietly reset.
            window.setTimeout(function () { window.location.reload(); }, 900);
          })
          .catch(function () {
            buttonsFor(jobId).forEach(function (other) {
              other.disabled = false;
              other.textContent = "Error";
            });
            runningJobs.delete(jobId);
          });
      });
    });

    // The scheduler runs jobs on its own schedule, so the page has to notice
    // starts it did not initiate. Polling is deliberately slow: this is a status
    // display, not a control loop.
    refreshRunning();
    window.setInterval(refreshRunning, 5000);
  }

  // --------------------------------------------------------- paging in place
  // A page change used to be a full navigation, which puts the reader back at the
  // head of the document -- so "next page" on a long table meant losing your place
  // and scrolling back down to it.
  //
  // The pager links are untouched: they are still real URLs, they still work with
  // this file absent, and everything else about them -- the query string the server
  // built, the filters it carries -- is reused rather than reconstructed here. All
  // this does is fetch the region the server already knows how to render on its own
  // and put it back, leaving the scroll position alone.

  function swapRegion(region, url) {
    region.setAttribute("aria-busy", "true");
    return fetch(url, { headers: { "X-Requested-With": "fetch" } })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.text();
      })
      .then(function (html) {
        var holder = document.createElement("div");
        holder.innerHTML = html;
        var replacement = holder.firstElementChild;
        // A region that did not come back as a region is not something to put on the
        // page: better to fall back to a navigation than to render half a page.
        if (!replacement || !replacement.dataset.partial) throw new Error("not a region");
        region.replaceWith(replacement);
        replacement.setAttribute("tabindex", "-1");
        // Focused so a keyboard reader lands in the rows that changed rather than on
        // a link that no longer exists -- and preventScroll so that focus does not
        // undo the whole point by jumping to the region.
        try { replacement.focus({ preventScroll: true }); } catch (e) { /* older browsers */ }
      });
  }

  function wirePartialPaging() {
    document.addEventListener("click", function (event) {
      if (!event.target.closest) return;
      var link = event.target.closest("[data-partial] .pager a");
      if (!link) return;
      // New tab, new window, download: let the browser do what the reader asked for.
      if (event.defaultPrevented || event.button !== 0 || event.metaKey ||
          event.ctrlKey || event.shiftKey || event.altKey) return;

      var region = link.closest("[data-partial]");
      if (!region || !region.dataset.partial) return;
      event.preventDefault();

      // The query comes from the link because the server built it and it is also what
      // the address bar should end up showing.
      var query = "";
      try { query = new URL(link.href, window.location.origin).search; } catch (e) { query = ""; }

      swapRegion(region, region.dataset.partial + query)
        .then(function () {
          // Pushed so the page is still shareable and Back still works. Without it the
          // table would show page 3 while the address bar said page 1.
          window.history.pushState({ region: region.id }, "", link.href);
        })
        .catch(function () {
          // A swap that failed is a reason to fall back to the thing that always works,
          // not to leave the reader on a page whose pager does nothing.
          window.location.href = link.href;
        });
    });

    window.addEventListener("popstate", function () {
      var region = document.querySelector("[data-partial]");
      if (!region || !region.dataset.partial) return;
      swapRegion(region, region.dataset.partial + window.location.search).catch(function () {
        window.location.reload();
      });
    });
  }

  function init() {
    startTicker();
    drawChart();
    wireJobButtons();
    wirePartialPaging();
    window.addEventListener("resize", drawChart);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
