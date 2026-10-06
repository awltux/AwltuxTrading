"""UK gilt par yields, from the Bank of England's own database.

The sterling counterpart to :mod:`awltux.providers.treasury`, and it exists because
**a discount rate has to be denominated in the currency of the cash flows it
discounts.** This application's universe is roughly 385 USD and 115 GBP instruments
-- the London Stock Exchange alone is 118 of the 500 -- and discounting sterling
cash flows at a dollar rate does not merely add noise, it silently embeds a view on
the GBP/USD basis that the model does not claim to have.

**How much it matters depends on the spread, not the level.** On 2026-10-02 the
ten-year gilt par yield was 5.334% against the US ten-year at 5.31% three days
later: about 2 basis points, or roughly 0.3% of fair value. That is a coincidence of
this month, not a property of the pair. The same source material that prompted this
work quotes long gilts around 47bp above long Treasuries within a single month, and
2022's gilt episode was far wider; at 50bp the fair-value error on a GBP instrument
is roughly 6%.

The BoE's Interactive Statistical Database serves CSV, needs no key, and carries the
nominal par yield curve daily from late 1993. Three series cover it:

    IUDSNPY  5-year      IUDMNPY  10-year      IUDLNPY  20-year

**The tenor mapping is verified, not remembered.** A wrong code would quietly return
the five-year where the ten-year was wanted, which is a modelling error that looks
entirely normal. The 5/10/20 pillar set is confirmed against an independent wrapper
of the same database (CRAN ``boe``, ``boe_yield_curve``), and each code is fetched
alone in the tests.

The endpoint is fussier than the Treasury's: a request containing a series code it
does not recognise is answered with an HTML error page rather than an error status,
so ``parse_gilt_curve`` treats anything that is not the expected CSV as no curve at
all rather than trying to salvage it.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging

from awltux.config import Settings, get_settings
from awltux.providers.http import HttpClient, ProviderError
from awltux.providers.yields import TENOR_5Y, TENOR_10Y, TENOR_20Y, YieldCurve

logger = logging.getLogger(__name__)

SOURCE = "gilt"

BASE_URL = "https://www.bankofengland.co.uk/boeapps/database"

#: BoE series codes for the nominal par yield curve, keyed by the tenor label this
#: codebase uses everywhere. The three are requested together in one call.
SERIES: dict[str, str] = {
    TENOR_5Y: "IUDSNPY",
    TENOR_10Y: "IUDMNPY",
    TENOR_20Y: "IUDLNPY",
}

#: How far back to ask for. Only the newest row is used, but a window is needed to
#: step over weekends and bank holidays; 90 days also leaves room for the endpoint
#: to be late publishing without returning nothing.
WINDOW_DAYS = 90

#: BoE dates read ``02 Oct 2026``.
_DATE_FORMAT = "%d %b %Y"


def _url(*, days: int) -> str:
    today = dt.datetime.now(dt.UTC).date()
    start = today - dt.timedelta(days=days)
    codes = ",".join(SERIES.values())
    return (
        f"{BASE_URL}/_iadb-fromshowcolumns.asp?csv.x=yes"
        f"&Datefrom={start.strftime('%d/%b/%Y')}&Dateto=now"
        f"&SeriesCodes={codes}&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N"
    )


def parse_gilt_curve(text: str) -> YieldCurve | None:
    """The newest complete row, or ``None`` if the response is not that CSV.

    Returning ``None`` rather than raising is deliberate: an unrecognised series
    code is answered with an HTML page, so "this is not the data" is an expected
    response and the caller reports it as an observation that did not happen.
    """
    if text.lstrip().startswith("<"):
        logger.warning("gilt endpoint returned HTML, which means a code was rejected")
        return None

    reader = csv.reader(io.StringIO(text.lstrip("\ufeff")))
    header = next(reader, None)
    if not header or header[0].strip().upper() != "DATE":
        return None

    # Map each column to its tenor label by the series code in the header, so a
    # change in column order cannot silently pair a rate with the wrong tenor.
    by_code = {code: tenor for tenor, code in SERIES.items()}
    tenors = [by_code.get(column.strip()) for column in header[1:]]

    newest: YieldCurve | None = None
    for row in reader:
        if not row:
            continue
        try:
            as_of = dt.datetime.strptime(row[0].strip(), _DATE_FORMAT).date()
        except (ValueError, IndexError):
            continue

        rates: dict[str, float] = {}
        for tenor, raw in zip(tenors, row[1:], strict=False):
            if tenor is None or not raw.strip():
                continue
            try:
                rates[tenor] = float(raw)
            except ValueError:
                continue
        # Rows are oldest-first, so the last usable row is the newest one.
        if rates:
            newest = YieldCurve(as_of=as_of, rates=rates)

    return newest


class GiltProvider:
    """UK nominal par yields, cached and budgeted like every other provider."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = HttpClient(
            SOURCE, settings=self.settings, headers={"Accept": "text/csv,*/*"}
        )

    def close(self) -> None:
        self._client.close()

    def yield_curve(self, *, days: int = WINDOW_DAYS, cache_ttl: float = 3600.0) -> YieldCurve:
        """The most recent published curve.

        One request for all three pillars: the endpoint accepts a comma-separated
        series list and answers with them as columns.
        """
        result = self._client.request(
            "GET", _url(days=days), cache_ttl=cache_ttl, expect_json=False
        )
        if result.status >= 400:
            raise ProviderError(
                SOURCE,
                f"gilt yield curve returned HTTP {result.status}",
                status=result.status,
            )

        curve = parse_gilt_curve(result.text())
        if curve is None:
            raise ProviderError(
                SOURCE, "no published gilt curve in the response (a series code was rejected)"
            )
        return curve
