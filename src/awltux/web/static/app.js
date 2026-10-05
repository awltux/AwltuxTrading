/* AwltuxTrading dashboard behaviour.
 *
 * Only the things the server cannot do: consume the live news stream, draw the
 * price sparkline, trigger a job, and tell the server which clock the reader is
 * on. Everything else -- sorting, filtering, paging -- is a plain URL so it works
 * without this file.
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
  var MAX_TICKER_ITEMS = 40;

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  function tickerElement(item) {
    var link = document.createElement("a");
    link.className = "ticker-item mat-" + (item.materiality || "none");
    // The local page, not the publisher. The article is the input to an
    // assessment; the assessment is what a reader needs, and it does not expire,
    // move behind a paywall or get rewritten.
    link.href = item.local_url || ("/news/" + item.id);
    link.rel = "noopener noreferrer";
    if (item.relevant === false) link.classList.add("not-relevant");

    var scepticism = item.scepticism || null;
    var title = item.title + (item.tickers && item.tickers.length ? " — " + item.tickers.join(", ") : "");
    if (item.priority != null) title += " · priority " + item.priority;
    if (scepticism) {
      title += " · " + (scepticism.grade || "unrated") + " evidence";
      if (scepticism.credibility != null) {
        title += ", weight " + Math.round(scepticism.credibility * 100) + "%";
      }
      if (scepticism.source) title += " · " + scepticism.source;
    }
    link.title = title;

    var html = "";
    if (item.tickers && item.tickers.length) {
      html += '<span class="chip">' + escapeHtml(item.tickers.join(", ")) + "</span>";
    }
    html += '<span class="ticker-title">' + escapeHtml(item.title) + "</span>";
    if (item.direction) {
      html += '<span class="dir dir-' + escapeHtml(item.direction) + '">' + escapeHtml(item.direction) + "</span>";
    }
    if (item.relevant !== true) {
      html += '<span class="badge unknown" title="Nothing has judged whether this is a claim about a share price">unassessed</span>';
    }
    // One entry per event: say how many other stories reported it, because the
    // grouping is the thing the reader cannot see from a single headline.
    if (item.event && item.event.size > 1) {
      html += '<span class="badge ok" title="' + item.event.size +
        ' stories cover this event; open for the list">' + item.event.size + "&times;</span>";
    }
    // The provenance travels with the headline here too, so a live-pushed item
    // cannot look more established than the same item rendered by the server.
    if (scepticism) {
      html += gradeBadge(scepticism);
    }
    link.innerHTML = html;
    return link;
  }

  function gradeBadge(scepticism) {
    var grade = scepticism.grade || "unrated";
    var classes = {
      strong: "good", moderate: "ok", mixed: "warn", weak: "bad", unsupported: "bad"
    };
    var html = '<span class="badge ' + (classes[grade] || "unknown") + '">' +
      escapeHtml(grade) + "</span>";

    var flags = scepticism.flags || [];
    if (flags.indexOf("manipulative_framing") !== -1) {
      html += '<span class="badge bad" title="Written to provoke rather than inform">framing</span>';
    }
    if (flags.indexOf("unconfirmed") !== -1) {
      html += '<span class="badge warn" title="A material claim from a single source — a lead, not a fact">unconfirmed</span>';
    }
    return html;
  }

  function startTicker() {
    var root = document.getElementById("news-flash");
    var track = document.getElementById("ticker-items");
    if (!root || !track || !window.EventSource) return;

    // Seed with the server-rendered fragment so the bar is never empty while
    // the stream connects, then let live events take over.
    fetch(root.dataset.fallbackUrl)
      .then(function (response) { return response.text(); })
      .then(function (html) {
        if (html.trim()) track.innerHTML = html;
      })
      .catch(function () { /* offline: the seed is cosmetic only */ });

    var seen = new Set();
    var source = new EventSource(root.dataset.streamUrl);

    source.addEventListener("news", function (event) {
      var item;
      try {
        item = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (seen.has(item.id)) return;
      seen.add(item.id);

      // A reconnect replays history; drop the placeholder on first real item.
      var placeholder = track.querySelector(".muted");
      if (placeholder) track.innerHTML = "";

      // Newest first, so a market-moving headline is at the left edge.
      track.insertBefore(tickerElement(item), track.firstChild);
      while (track.children.length > MAX_TICKER_ITEMS) {
        track.removeChild(track.lastChild);
      }
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
  function drawChart() {
    var canvas = document.getElementById("price-chart");
    if (!canvas) return;

    var series, dates;
    try {
      series = JSON.parse(canvas.dataset.series || "[]");
      dates = JSON.parse(canvas.dataset.dates || "[]");
    } catch (err) {
      return;
    }
    if (!series || series.length < 2) return;

    var ratio = window.devicePixelRatio || 1;
    var width = canvas.clientWidth || 600;
    var height = Number(canvas.getAttribute("height")) || 180;
    canvas.width = width * ratio;
    canvas.height = height * ratio;

    var ctx = canvas.getContext("2d");
    ctx.scale(ratio, ratio);
    ctx.clearRect(0, 0, width, height);

    var min = Math.min.apply(null, series);
    var max = Math.max.apply(null, series);
    if (max === min) { max = min + 1; }

    var pad = 8;
    var plotWidth = width - pad * 2;
    var plotHeight = height - pad * 2 - 14;

    function x(i) { return pad + (i / (series.length - 1)) * plotWidth; }
    function y(value) { return pad + plotHeight - ((value - min) / (max - min)) * plotHeight; }

    // Grid
    ctx.strokeStyle = "#2a323c";
    ctx.lineWidth = 1;
    for (var g = 0; g <= 4; g++) {
      var gy = pad + (g / 4) * plotHeight;
      ctx.beginPath();
      ctx.moveTo(pad, gy);
      ctx.lineTo(width - pad, gy);
      ctx.stroke();
    }

    // Price line, coloured by whether the period ended up or down.
    var rising = series[series.length - 1] >= series[0];
    ctx.strokeStyle = rising ? "#3fb950" : "#f85149";
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    series.forEach(function (value, index) {
      if (index === 0) ctx.moveTo(x(index), y(value));
      else ctx.lineTo(x(index), y(value));
    });
    ctx.stroke();

    var gradient = ctx.createLinearGradient(0, pad, 0, pad + plotHeight);
    gradient.addColorStop(0, rising ? "rgba(63,185,80,.22)" : "rgba(248,81,73,.22)");
    gradient.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = gradient;
    ctx.lineTo(x(series.length - 1), pad + plotHeight);
    ctx.lineTo(x(0), pad + plotHeight);
    ctx.closePath();
    ctx.fill();

    // Axis labels: only the extremes, so the chart stays readable.
    ctx.fillStyle = "#8b95a4";
    ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
    ctx.fillText(max.toFixed(2), pad + 2, pad + 10);
    ctx.fillText(min.toFixed(2), pad + 2, pad + plotHeight - 2);
    if (dates.length) {
      ctx.fillText(dates[0], pad, height - 3);
      var lastLabel = dates[dates.length - 1];
      ctx.fillText(lastLabel, width - pad - ctx.measureText(lastLabel).width, height - 3);
    }
  }

  // ---------------------------------------------------------------- job runs
  function wireJobButtons() {
    document.querySelectorAll(".run-job").forEach(function (button) {
      button.addEventListener("click", function () {
        var jobId = button.dataset.job;
        var original = button.textContent;
        button.disabled = true;
        button.textContent = "Running…";

        fetch("/api/jobs/" + encodeURIComponent(jobId) + "/run", { method: "POST" })
          .then(function (response) {
            return response.json().then(function (body) {
              return { ok: response.ok, body: body };
            });
          })
          .then(function (result) {
            if (!result.ok) {
              button.textContent = "Failed";
              button.title = result.body.detail || "job failed";
            } else {
              var body = result.body;
              button.textContent = "Wrote " + (body.items_written || 0);
              window.setTimeout(function () {
                window.location.reload();
              }, 900);
            }
          })
          .catch(function () {
            button.textContent = "Error";
          })
          .finally(function () {
            window.setTimeout(function () {
              button.disabled = false;
              button.textContent = original;
            }, 2500);
          });
      });
    });
  }

  function init() {
    startTicker();
    drawChart();
    wireJobButtons();
    window.addEventListener("resize", drawChart);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
