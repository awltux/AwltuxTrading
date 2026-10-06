"""US Treasury par yield curve -- where the risk-free rate actually comes from.

Free, keyless, and **primary**: this is the US Treasury's own daily publication
rather than a vendor's reproduction of it. It carries every standard tenor, so the
valuation model can name the exact rate it used instead of inferring one from a
scraped index price.

**Why this exists at all.** ``risk_free_rate`` anchors the CAPM cost of equity,
which anchors every discount rate, which decides every discounted fair value. It
was a constant in ``config.yaml`` -- honest on the day it was typed and quietly
wrong afterwards. On 2026-10-05 the 10-year was 5.31% against a configured 4.2%,
and this model's own DCF loses about 14% of its fair value over that gap. A
valuation built on a stale risk-free rate is not conservative or aggressive; it is
simply anchored to a number that stopped being true.

The CSV endpoint is undocumented but stable and widely relied upon. Its shape:

    Date,"1 Mo","1.5 Month","2 Mo",...,"7 Yr","10 Yr","20 Yr","30 Yr"
    10/05/2026,4.05,4.10,4.13,...,5.19,5.31,5.70,5.66

Rows are newest-first, dates are ``MM/DD/YYYY``, and **yields are percentages** --
``5.31`` means 5.31%, which is the unit confusion this module exists to bound.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging

from awltux.config import Settings, get_settings
from awltux.providers.http import HttpClient, ProviderError
from awltux.providers.yields import DEFAULT_TENOR, YieldCurve  # noqa: F401  (re-exported)

logger = logging.getLogger(__name__)

SOURCE = "treasury"

#: One CSV per year, covering every business day of it.
BASE_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates"

#: Tenors the publication carries, for validation and display.
TENORS = (
    "1 Mo", "1.5 Month", "2 Mo", "3 Mo", "4 Mo", "6 Mo",
    "1 Yr", "2 Yr", "3 Yr", "5 Yr", "7 Yr", "10 Yr", "20 Yr", "30 Yr",
)


def _csv_url(year: int) -> str:
    return (
        f"{BASE_URL}/daily-treasury-rates.csv/{year}/all"
        f"?type=daily_treasury_yield_curve&field_tdr_date_value={year}"
        "&page&_format=csv"
    )


def parse_yield_curve(text: str) -> YieldCurve | None:
    """The newest complete row of a Treasury CSV, or ``None`` if there is none.

    Returns ``None`` rather than raising: an empty or unparseable file is a normal
    state on the first days of January, before the year's first publication, and
    the caller handles it by looking at the previous year.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    for row in reader:
        raw_date = (row.get("Date") or "").strip()
        if not raw_date:
            continue
        try:
            as_of = dt.datetime.strptime(raw_date, "%m/%d/%Y").date()
        except ValueError:
            continue

        rates: dict[str, float] = {}
        for tenor in TENORS:
            raw = (row.get(tenor) or "").strip()
            if not raw:
                continue
            try:
                rates[tenor] = float(raw)
            except ValueError:
                # A blank cell is common for tenors that did not exist yet; a
                # non-numeric one is not worth aborting the whole curve over.
                continue
        if rates:
            return YieldCurve(as_of=as_of, rates=rates)
    return None


class TreasuryProvider:
    """Daily par yield curve, cached and budgeted like every other provider."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = HttpClient(
            SOURCE, settings=self.settings, headers={"Accept": "text/csv"}
        )

    def close(self) -> None:
        self._client.close()

    def yield_curve(self, *, year: int | None = None, cache_ttl: float = 3600.0) -> YieldCurve:
        """The most recent published curve.

        ``cache_ttl`` defaults to an hour. The publication changes once a day, so a
        longer cache would be fine; an hour keeps a manual re-run honest without
        re-fetching on every valuation sweep.
        """
        today = dt.datetime.now(dt.UTC).date()
        # Try this year, then last: on 1-2 January the current file exists but has
        # no rows yet, and the newest curve is still last year's.
        for candidate in ([year] if year else [today.year, today.year - 1]):
            result = self._client.request(
                "GET",
                _csv_url(candidate),
                cache_ttl=cache_ttl,
                expect_json=False,
            )
            if result.status == 404:
                continue
            if result.status >= 400:
                raise ProviderError(
                    SOURCE,
                    f"yield curve for {candidate} returned HTTP {result.status}",
                    status=result.status,
                )
            curve = parse_yield_curve(result.text())
            if curve is not None:
                return curve

        raise ProviderError(
            SOURCE, "no published yield curve found for this year or the last"
        )
