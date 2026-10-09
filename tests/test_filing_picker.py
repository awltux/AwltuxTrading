"""The way from an "out by" figure into the filing that produced it.

Asked for directly: *"if the accounts for a period are based on government xbrl, convert the
'out by Y' field into links that open the relevant government report in a separate tab e.g.
10-K for USA. Use a url property that indicates the accounting total the source 'out by Y' is
related to. Allow the user to click xbrl values in the government report which adds them to
Account section indicated by the url property."*

So three properties, and the third is the one with teeth:

* a residual on a government-XBRL period becomes a link into the stored filing, and the link
  carries the period and the line -- the "url property" the request names;
* it is offered **only** where the accounts are the filer's own submission *and* we hold the
  document, because a link into a copy, or into an EDGAR fetch, is a different offer;
* the picker page is served under a policy that runs our script and nothing of the filing's,
  while the ordinary document route keeps the bare ``sandbox`` it has always had.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from awltux.db import Filing
from tests.helpers import make_instrument, make_period

REPO_ROOT = Path(__file__).resolve().parent.parent
PICKER_JS = REPO_ROOT / "src" / "awltux" / "web" / "static" / "filing-picker.js"
NODE_TESTS = REPO_ROOT / "tests" / "js" / "filing_picker.test.mjs"

CIK = "0000320193"
ACCN = "0001193125-26-323660"
#: One tagged fact, in the shape EDGAR serves it: the text as printed, the scale it is printed
#: at, and the coordinates. Every attribute the picker reads is on it.
FILING_HTML = """<html><head><title>10-K</title>
<script>window.alert("the filer's own script")</script>
</head><body>
<p>Total assets <ix:nonFraction id="F_assets" name="us-gaap:Assets"
   contextRef="C_1" unitRef="U_USD" scale="6" decimals="-6"
   format="ixt:num-dot-decimal">758,376</ix:nonFraction></p>
<p>Nothing here <ix:nonFraction id="F_nil" name="us-gaap:CommitmentsAndContingencies"
   contextRef="C_1" unitRef="U_USD" xsi:nil="true"></ix:nonFraction></p>
</body></html>"""

FIGURES = {
    "revenue": 1_000.0,
    "cost_of_goods_sold": 600.0,
    "gross_profit": 400.0,
    "sga_expense": 150.0,
    "operating_income": 250.0,
    "net_income": 200.0,
    "cash_and_equivalents": 200.0,
    "receivables": 100.0,
    "current_assets": 300.0,
    # Stated 100 higher than the lines we hold, so the check has a residual to link.
    "total_assets": 400.0,
    "total_liabilities": 100.0,
    "total_equity": 300.0,
}


def _store(session, settings, *, source: str = "xbrl_companyfacts", with_document: bool = True):
    """A filer, one period, and the filing the government's tags came from."""
    session.add(make_instrument("TEST_US_EQ", name="Test Co", sec_cik=CIK))
    session.flush()
    filing = Filing(
        instrument_t212_ticker="TEST_US_EQ",
        source="edgar",
        filing_type="10-K",
        title="Test Co 10-K",
        filed_at=dt.datetime(2026, 8, 1, tzinfo=dt.UTC),
        period_end=dt.date(2024, 12, 31),
        url=f"https://www.sec.gov/Archives/edgar/data/320193/{ACCN.replace('-', '')}/x.htm",
        content_type="text/html",
        status="fetched",
    )
    session.add(filing)
    session.flush()
    if with_document:
        relative = Path("raw") / "filings" / "TEST_US_EQ" / "filing.htm"
        path = settings.data_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(FILING_HTML, encoding="utf-8")
        filing.raw_path = str(relative)
    period = make_period(
        "TEST_US_EQ",
        dt.date(2024, 12, 31),
        dict(FIGURES),
        source=source,
        currency="USD",
    )
    period.metric_sources = {
        "revenue": {"source": source, "span": "us-gaap:Revenues", "accession": ACCN},
        "total_assets": {"source": source, "span": "us-gaap:Assets", "accession": ACCN},
    }
    session.add(period)
    session.flush()
    session.commit()
    return period, filing


class TestTheResidualBecomesAWayIntoTheFiling:
    def test_the_out_by_text_opens_the_filing_with_the_line_in_the_url(
        self, client, session, settings
    ):
        """The `awltux_line` property is the "accounting total the source is related to": it is
        how the picker knows which line of the accounts a clicked figure belongs on."""
        period, filing = _store(session, settings)

        soup = BeautifulSoup(client.get(f"/accounts/{period.id}/balance_sheet").text, "lxml")
        row = next(
            item
            for item in soup.select("table.ledger tbody tr")
            if "Total assets" in item.get_text(" ")
        )
        link = row.select_one("a.work")

        assert link is not None, "the residual is not a link into the filing"
        assert link["target"] == "_blank", "it opens in a separate tab"
        assert f"/filing/{filing.id}/pick" in link["href"]
        assert f"awltux_period={period.id}" in link["href"]
        assert "awltux_line=total_assets" in link["href"]
        assert "awltux_statement=balance_sheet" in link["href"]
        # The period end goes too: a filing prints the current year and the prior year in one
        # row under one caption, both tagged, and the script marks a figure clicked out of the
        # wrong column rather than letting it be written in.
        assert "awltux_period_end=2024-12-31" in link["href"]
        assert "out by" in link.get_text(" ")

    def test_the_hover_working_survives_the_link(self, client, session, settings):
        """The calculation a reader was already shown on hover has to stay: the link adds an
        action, it does not replace the explanation."""
        period, _ = _store(session, settings)

        soup = BeautifulSoup(client.get(f"/accounts/{period.id}/balance_sheet").text, "lxml")
        row = next(
            item
            for item in soup.select("table.ledger tbody tr")
            if "Total assets" in item.get_text(" ")
        )
        work = row.select_one("[data-work]")["data-work"]

        assert "from the filing: 400" in work
        assert "out by 100" in work

    def test_the_health_row_links_for_the_line_it_audits(self, client, session, settings):
        """The composition check measures one caption, so the row can open the filing at it. The
        equation and the roll-forward measure the accounts rather than one line, and stay
        plain rather than offering a link to the whole 10-K."""
        period, _ = _store(session, settings)

        soup = BeautifulSoup(client.get(f"/accounts/{period.id}/health").text, "lxml")
        row = next(
            item
            for item in soup.select("table.grid tbody tr")
            if "Components sum to stated total assets" in item.get_text(" ")
        )

        assert "awltux_line=total_assets" in row.select_one("a.work")["href"]

        equation = next(
            item
            for item in soup.select("table.grid tbody tr")
            if "Assets = liabilities + equity" in item.get_text(" ")
        )
        assert equation.select_one("a.work") is None

    def test_the_page_says_where_a_residual_link_goes(self, client, session, settings):
        """A table of underlined figures with no explanation reads as decoration. The note is
        also the plain *open the 10-K* link, which is the first half of the request on its own:
        a separate tab, and the relevant government report."""
        period, filing = _store(session, settings)

        body = client.get(f"/accounts/{period.id}").text

        assert f'href="/filing/{filing.id}/document"' in body
        assert 'target="_blank"' in body
        assert "click the number the filer actually tagged" in body
        assert "10-K" in body

    def test_no_note_and_no_link_where_there_is_no_filing_to_open(
        self, client, session, settings
    ):
        period, _ = _store(session, settings, source="yahoo_statements")

        body = client.get(f"/accounts/{period.id}").text

        assert "/pick" not in body
        assert "filer's own tagged accounts" not in body

    def test_a_period_from_another_source_gets_no_link(self, client, session, settings):
        """A residual against a copy is a residual against a copy. Opening the real 10-K beside
        it would invite the reader to correct our figures from a source the page has already
        decided not to use."""
        period, _ = _store(session, settings, source="yahoo_statements")

        soup = BeautifulSoup(client.get(f"/accounts/{period.id}/balance_sheet").text, "lxml")
        row = next(
            item
            for item in soup.select("table.ledger tbody tr")
            if "Total assets" in item.get_text(" ")
        )

        assert row.select_one("span.work") is not None, "the working is still shown"
        assert row.select_one("a.work") is None

    def test_a_filing_we_do_not_hold_gets_no_link(self, client, session, settings):
        """The accession alone would mean an EDGAR fetch on the reader's click, and this page
        makes no provider calls."""
        period, filing = _store(session, settings, with_document=False)

        assert filing.raw_path is None
        soup = BeautifulSoup(client.get(f"/accounts/{period.id}/balance_sheet").text, "lxml")
        row = next(
            item
            for item in soup.select("table.ledger tbody tr")
            if "Total assets" in item.get_text(" ")
        )

        assert row.select_one("a.work") is None


class TestThePickerPage:
    def test_the_picker_runs_our_script_and_not_the_filing_s(self, client, session, settings):
        """The filing is third-party HTML. Its own scripts are removed rather than left to be
        blocked by the policy, because a `<script src>` from a host the filer chose is a
        network request this page has no business making."""
        _, filing = _store(session, settings)

        body = client.get(f"/filing/{filing.id}/pick").text

        assert "window.alert" not in body, "the filing's own script is still in the document"
        assert '/static/filing-picker.js' in body
        assert "758,376" in body, "the figures are still there to click"

    def test_the_picker_is_sandboxed_with_scripts_and_nothing_else_it_does_not_need(
        self, client, session, settings
    ):
        """`allow-popups-to-escape-sandbox` is the load-bearing one: without it the confirmation
        page opened from here would *inherit* the sandbox and load in an opaque origin, where it
        could neither keep a session nor run its own script. `allow-same-origin` is absent, and
        must stay absent -- it would hand the filing back the origin the sandbox removes."""
        _, filing = _store(session, settings)

        policy = client.get(f"/filing/{filing.id}/pick").headers["content-security-policy"]

        assert policy.startswith("sandbox ")
        assert "allow-scripts" in policy
        assert "allow-popups-to-escape-sandbox" in policy
        assert "allow-same-origin" not in policy
        assert "allow-forms" not in policy, "the picker posts nothing; it links"
        # The one script the page may run, named by origin because an opaque origin matches no
        # `'self'`. Inline handlers in the filing are blocked by the same directive.
        assert "script-src http://testserver" in policy

    def test_the_plain_document_route_keeps_the_policy_it_has_always_had(
        self, client, session, settings
    ):
        """The regression this guards: `sandbox` with nothing allowed is what stops a filing
        from reaching this application's origin, and relaxing it for the picker must not
        relax it for the route every filing is read through."""
        _, filing = _store(session, settings)

        response = client.get(f"/filing/{filing.id}/document")

        assert response.headers["content-security-policy"] == "sandbox"
        assert response.headers["x-content-type-options"] == "nosniff"

    def test_a_filing_with_no_stored_document_is_a_404(self, client, session, settings):
        """Both routes resolve the path the same way, and both refuse the same filings."""
        _, filing = _store(session, settings, with_document=False)

        assert client.get(f"/filing/{filing.id}/pick").status_code == 404
        assert client.get(f"/filing/{filing.id}/document").status_code == 404

    def test_an_unknown_filing_is_a_404(self, client, session, settings):
        assert client.get("/filing/999999/pick").status_code == 404

    def test_the_script_it_serves_is_the_one_on_disk(self, client, session, settings):
        """A picker page pointing at a script the application does not serve would be a dead
        click for every reader, and nothing else in the suite touches static files."""
        response = client.get("/static/filing-picker.js")

        assert response.status_code == 200
        assert "ix:nonfraction" in response.text


class TestTheConfirmPageTakesWhatWasClicked:
    def test_a_clicked_figure_lands_on_the_line_the_property_named(
        self, client, session, settings
    ):
        period, filing = _store(session, settings)

        soup = BeautifulSoup(
            client.get(
                f"/accounts/{period.id}/corrections/new",
                params={
                    "statement": "balance_sheet",
                    "metric": "total_assets",
                    "value": "758376000000",
                    "tag": "us-gaap:Assets",
                    "origin": "filing",
                    "url": f"/filing/{filing.id}/document#F_assets",
                    "note": "filed as: Total assets",
                },
            ).text,
            "lxml",
        )

        assert soup.select_one("select[name=metric] option[selected]")["value"] == "total_assets"
        assert soup.select_one("input[name=value]")["value"] == "758376000000"
        assert soup.select_one("input[name=tag]")["value"] == "us-gaap:Assets"
        assert soup.select_one("input[name=origin]")["value"] == "filing"
        assert soup.select_one("input[name=url]")["value"].endswith("#F_assets")
        # The filing's own caption for the line, so the record says where the figure was read
        # from in the filer's words rather than in a taxonomy's.
        assert soup.select_one("input[name=note]")["value"] == "filed as: Total assets"
        # And the page says where it came from, so a reader who arrived by a click knows why the
        # form is already filled in.
        assert "clicked in the filing rather than typed" in soup.get_text(" ")

    def test_the_origin_is_recorded_so_the_panel_can_say_it_was_read_not_typed(
        self, client, session, settings
    ):
        period, filing = _store(session, settings)

        client.post(
            f"/accounts/{period.id}/corrections/add",
            data={
                "metric": "other_noncurrent_assets",
                "value": "168",
                "statement": "balance_sheet",
                "tag": "us-gaap:OperatingLeaseRightOfUseAssetNoncurrent",
                "origin": "filing",
                "url": f"/filing/{filing.id}/document#F_x",
            },
        )

        row = session.get(type(period), period.id)
        session.expire_all()
        row = session.get(type(period), period.id)
        assert row.corrections["added"]["other_noncurrent_assets"]["origin"] == "filing"

    @pytest.mark.parametrize(
        "bad", ["javascript:alert(1)", "data:text/html,<script>", "//evil.example/x"]
    )
    def test_a_link_the_filing_chose_is_not_stored(self, client, session, settings, bad):
        """The picker's query string is writer-controlled -- a filing builds the link the reader
        presses -- and the value becomes an `href` on the accounts page. So anything that is
        not an http(s) URL or a path on this application is dropped rather than stored."""
        period, _ = _store(session, settings)

        client.post(
            f"/accounts/{period.id}/corrections/add",
            data={
                "metric": "other_noncurrent_assets",
                "value": "1",
                "statement": "balance_sheet",
                "origin": "filing",
                "url": bad,
            },
        )

        session.expire_all()
        row = session.get(type(period), period.id)
        assert row.corrections["added"]["other_noncurrent_assets"]["url"] == ""


class TestTheJavaScript:
    """The picker's value rule is the one part of this feature no browser runs in this suite."""

    def test_the_script_parses(self):
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not installed, so the picker's script cannot be parsed here")
        result = subprocess.run(
            [node, "--check", str(PICKER_JS)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    def test_the_value_rule_reads_a_figure_the_way_the_stored_one_does(self):
        """Run with node rather than asserted by eye: a scale applied the wrong way, or a
        ``sign="-"`` ignored, writes a figure onto the balance sheet that is out by a factor of
        a million and looks perfectly plausible.

        The case is live: Microsoft's 2026 10-K tags total assets as ``758,376`` with
        ``scale="6"``, and the period we store for it holds 758,376,000,000.
        """
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not installed, so the picker's arithmetic cannot be run here")
        result = subprocess.run(
            [node, "--test", str(NODE_TESTS)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_rule_the_script_documents_is_the_rule_the_tests_run(self):
        """A binding guard: the exported pair is what the node tests exercise, so a rename in
        the script that left the export behind would make every one of those tests vacuous."""
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not installed")
        script = (
            "const p = require(process.argv[1]);"
            "if (typeof p.figureOf !== 'function' || typeof p.transform !== 'function') "
            "{ console.error('not exported'); process.exit(2); }"
            "const f = p.figureOf({textContent:'1,000',getAttribute:n=>n==='scale'?'3':null,"
            "hasAttribute:()=>false});"
            "if (f.value !== 1000000) { console.error('wrong value ' + f.value); process.exit(3); }"
            "console.log(JSON.stringify(f));"
        )
        result = subprocess.run(
            [node, "-e", script, str(PICKER_JS)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["value"] == 1_000_000


def test_the_picker_marker_does_not_reach_the_plain_document(client, session, settings):
    """The whole point of a second route: a reader who opens the filing to read it gets the
    filing *as it was filed*, not the filing with our script and our tray attached. Its own
    `<script>` is still in there, and harmless: the bare `sandbox` policy means it never runs."""
    _, filing = _store(session, settings)
    stored = (settings.data_dir / filing.raw_path).read_bytes()

    response = client.get(f"/filing/{filing.id}/document")

    assert response.content == stored, "served byte for byte"
    assert "filing-picker.js" not in response.text
    assert "<script" in response.text, "the fixture carries one, and it is left alone"
