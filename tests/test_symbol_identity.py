"""Resolving a provider symbol by looking the company up, rather than guessing it.

Every candidate list in this file is **real provider output**, captured while
investigating why 92 of 500 instruments failed every price run. That matters more
than usual here: the rule being tested exists to tell a company apart from a
warrant on the same company, and an invented fixture would not contain the case
that nearly broke it -- `KDKRW`, "Kodiak AI, Inc. Warrants", which sits second in
the results for Kodiak AI and whose name *contains* the company's.
"""

from __future__ import annotations

from awltux.ingest.identity import (
    APPLY_FLOOR,
    SymbolCandidate,
    choose_symbol,
    describe,
    score_candidate,
)


def _candidate(symbol, name, exchange=None, quote_type="EQUITY", score=None):
    entry = {"symbol": symbol, "name": name, "exchange": exchange, "quote_type": quote_type}
    if score is not None:
        entry["score"] = score
    return entry


# --- captured from yfinance.Search against the failing instruments ----------- #

KODIAK = [
    _candidate("KDK", "Kodiak AI, Inc.", "NGM", "EQUITY", 12000.0),
    _candidate("KDKRW", "Kodiak AI, Inc. Warrants", "NCM", "EQUITY", 200.0),
    _candidate("V7U.F", "Kodiak AI Inc.                R", "FRA", "EQUITY", 100.0),
]
HUMACYTE = [_candidate("HUMA", "Humacyte, Inc.", "NMS", "EQUITY", 20000.0)]
BEACON = [
    _candidate("BCE.L", "BEACON ENERGY PLC ORD NPV", "LSE", "EQUITY", 15000.0),
    _candidate("BZP0.F", "Beacon Energy PLC             R", "FRA", "EQUITY", 90.0),
]
ABERDEEN = [
    _candidate("AEI.L", "ABERDEEN EQUITY INCOME TRUST PL", "LSE", "EQUITY", 9000.0),
    _candidate("AEIL.XC", "aberdeen Equity Income Trust pl", "CXE", "EQUITY", 300.0),
]
PARVUS = [
    _candidate("AEET.L", "PARVUS ENERGY EFFICIENCY TRUST ", "LSE", "EQUITY", 8000.0),
    _candidate("GB00BN6JYS78.SG", "Aquila Energy Efficiency Trust ", "STU", "EQUITY", 50.0),
]


class TestItResolvesTheRealCases:
    def test_humacyte_is_found_by_the_isin_the_ticker_could_not_reach(self):
        """T212 calls it AHAC_US_EQ; it trades as HUMA. Deriving cannot recover."""
        found = choose_symbol(
            HUMACYTE,
            instrument_name="Humacyte",
            instrument_exchange="NASDAQ",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        assert found is not None
        assert found.symbol == "HUMA"
        assert found.usable
        assert found.method == "isin"

    def test_a_share_is_not_confused_with_a_warrant_on_the_same_company(self):
        """`KDKRW` "Kodiak AI, Inc. Warrants" contains the company's name, so a
        containment match scores it highly -- and a warrant has its own price
        series that would look entirely plausible."""
        found = choose_symbol(
            KODIAK,
            instrument_name="Kodiak AI",
            instrument_exchange="NASDAQ",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        assert found is not None
        assert found.symbol == "KDK"

        warrant = next(
            score_candidate(
                SymbolCandidate(symbol="KDKRW", name="Kodiak AI, Inc. Warrants"),
                instrument_name="Kodiak AI",
                instrument_exchange="NASDAQ",
                instrument_type="STOCK",
                queried_by_isin=True,
            )
            for _ in [0]
        )
        assert warrant.confidence == 0.0
        assert "warrant" in " ".join(warrant.reasons)

    def test_a_uk_company_is_found_under_its_current_name(self):
        found = choose_symbol(
            BEACON,
            instrument_name="Beacon Energy",
            instrument_exchange="LSE",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        assert found is not None
        assert found.symbol == "BCE.L"

    def test_a_renamed_trust_resolves_to_its_listed_symbol(self):
        """The company renamed; the ISIN did not."""
        found = choose_symbol(
            PARVUS,
            instrument_name="Parvus Energy Efficiency Trust",
            instrument_exchange="LSE",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        assert found is not None
        assert found.symbol == "AEET.L"

    def test_the_best_of_two_share_listings_is_chosen(self):
        found = choose_symbol(
            ABERDEEN,
            instrument_name="aberdeen Equity Income Trust",
            instrument_exchange="LSE",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        assert found is not None
        assert found.symbol == "AEI.L"


class TestItRefusesWhatItShould:
    def test_an_unrelated_company_is_not_accepted(self):
        found = choose_symbol(
            [_candidate("ZZZZ", "Something Else Entirely", "NMS")],
            instrument_name="Humacyte",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        assert found is None

    def test_a_weak_match_is_recorded_but_not_applied(self):
        """Attaching another company's prices produces confident, completely wrong
        analysis -- worse than an instrument that is visibly unresolved."""
        weak = score_candidate(
            SymbolCandidate(symbol="X", name="Acme Industrial Holdings"),
            instrument_name="Acme Holdings Group",
            instrument_exchange="NASDAQ",
            instrument_type="STOCK",
            queried_by_isin=False,
        )
        assert weak.confidence < APPLY_FLOOR
        assert weak.worth_recording
        assert not weak.usable

    def test_a_name_only_match_is_discounted(self):
        """A name does not survive a rename; an ISIN does."""
        by_isin = score_candidate(
            SymbolCandidate(symbol="A", name="Acme Holdings"),
            instrument_name="Acme Holdings",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        by_name = score_candidate(
            SymbolCandidate(symbol="A", name="Acme Holdings"),
            instrument_name="Acme Holdings",
            instrument_type="STOCK",
            queried_by_isin=False,
        )
        assert by_isin.confidence > by_name.confidence

    def test_a_type_disagreement_is_penalised(self):
        """An ETF and a share in the same company are different instruments."""
        share = score_candidate(
            SymbolCandidate(symbol="A", name="Acme", quote_type="EQUITY"),
            instrument_name="Acme",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        fund = score_candidate(
            SymbolCandidate(symbol="A", name="Acme", quote_type="MUTUALFUND"),
            instrument_name="Acme",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        assert fund.confidence < share.confidence
        assert any("type disagrees" in reason for reason in fund.reasons)

    def test_an_exchange_disagreement_lowers_confidence_without_vetoing(self):
        """Corroboration, not identification: an ISIN match on the wrong venue is
        still the right company."""
        agreeing = score_candidate(
            SymbolCandidate(symbol="A", name="Acme", exchange="NASDAQ"),
            instrument_name="Acme",
            instrument_exchange="NASDAQ",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        elsewhere = score_candidate(
            SymbolCandidate(symbol="A", name="Acme", exchange="FRA"),
            instrument_name="Acme",
            instrument_exchange="NASDAQ",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        assert elsewhere.confidence < agreeing.confidence
        assert elsewhere.confidence > 0

    def test_a_cross_listing_on_another_market_is_refused(self):
        """Found by reading the first real run rather than its count: 79 of 92
        resolved, and two were cross-listings -- a Nasdaq instrument came back as
        ``DOO.TO`` in Toronto and another as ``EVTA.F`` in Frankfurt.

        An ISIN identifies the *company*; a company can be listed in several places,
        and the venue decides the price, currency and liquidity.
        """
        from awltux.ingest.identity import _venue_disagrees

        toronto = SymbolCandidate(symbol="DOO.TO", name="BRP Inc.", exchange="TOR")
        frankfurt = SymbolCandidate(symbol="EVTA.F", name="Evotec SE", exchange="FRA")
        nasdaq = SymbolCandidate(symbol="DOOO", name="BRP Inc.", exchange="NMS")

        assert _venue_disagrees(toronto, "NASDAQ")
        assert _venue_disagrees(frankfurt, "NASDAQ")
        assert not _venue_disagrees(nasdaq, "NASDAQ")

        scored = score_candidate(
            toronto,
            instrument_name="BRP",
            instrument_exchange="NASDAQ",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        assert not scored.usable, "a Toronto price must not be applied to a Nasdaq row"
        assert any("different market" in reason for reason in scored.reasons)

    def test_a_uk_instrument_is_not_refused_its_london_listing(self):
        """The penalty must not break the case it was measured on."""
        from awltux.ingest.identity import _venue_disagrees

        assert not _venue_disagrees(
            SymbolCandidate(symbol="BCE.L", exchange="LSE"), "LSE"
        )

    def test_an_unknown_venue_is_not_treated_as_a_mismatch(self):
        """An unrecognised venue is not evidence of anything, and penalising it
        would drop correct resolutions for every exchange this has never heard of."""
        from awltux.ingest.identity import _venue_disagrees

        assert not _venue_disagrees(
            SymbolCandidate(symbol="XYZ", exchange="Some Exchange"), "NASDAQ"
        )

    def test_a_provider_placeholder_is_not_a_resolution(self):
        """``DUMY0001134`` came back for BioKey and its name matched exactly, so it
        applied. A placeholder carries no price series: resolving to one just moves
        the failure one step later and makes it look like success in the meantime."""
        scored = score_candidate(
            SymbolCandidate(symbol="DUMY0001134", name="BioKey, Inc.", exchange="PNK"),
            instrument_name="BioKey",
            instrument_exchange="NASDAQ",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        assert not scored.usable
        assert scored.confidence == 0.0
        assert any("placeholder" in reason for reason in scored.reasons)

    def test_no_candidates_at_all_is_none(self):
        assert choose_symbol([], instrument_name="Acme") is None
        assert choose_symbol([{"name": "no symbol"}], instrument_name="Acme") is None


class TestTheDecisionIsExplainable:
    def test_the_note_says_which_side_of_the_floor_it_landed_on(self):
        applied = choose_symbol(
            HUMACYTE, instrument_name="Humacyte", queried_by_isin=True
        )
        assert "applied" in describe(applied, instrument_name="Humacyte")

        weak = choose_symbol(
            [_candidate("X", "Acme Industrial Holdings")],
            instrument_name="Acme Holdings Group",
            queried_by_isin=False,
        )
        note = describe(weak, instrument_name="Acme Holdings Group")
        assert "not applied" in note
        assert "0.70" in note

    def test_a_total_failure_asks_for_a_human(self):
        note = describe(None, instrument_name="Aura FAT Projects")
        assert "needs a human" in note

    def test_the_reasons_name_the_evidence(self):
        found = choose_symbol(
            HUMACYTE,
            instrument_name="Humacyte",
            instrument_exchange="NASDAQ",
            instrument_type="STOCK",
            queried_by_isin=True,
        )
        assert found is not None
        joined = " ".join(found.reasons)
        assert "ISIN" in joined
        assert "matches exactly" in joined

    def test_the_same_inputs_always_produce_the_same_answer(self):
        first = choose_symbol(KODIAK, instrument_name="Kodiak AI", queried_by_isin=True)
        second = choose_symbol(KODIAK, instrument_name="Kodiak AI", queried_by_isin=True)
        assert first is not None and second is not None
        assert first.symbol == second.symbol == "KDK"


class TestTheJob:
    """End to end, with the provider replaced by the captured candidates."""

    def _stuck(self, session, ticker="AHAC_US_EQ", name="Humacyte", **overrides):
        from tests.helpers import make_instrument

        values = {
            "isin": "US44486Q1031",
            "yahoo_symbol": "AHAC",
            "exchange_name": "NASDAQ",
            "in_universe": True,
        }
        values.update(overrides)
        session.add(make_instrument(ticker, name=name, **values))
        session.flush()
        return ticker

    def _provider(self, monkeypatch, results):
        from awltux.providers import yahoo as yahoo_module

        calls: list[str] = []

        def search(self, query, *, max_results=6):
            calls.append(query)
            return results.get(query, [])

        monkeypatch.setattr(yahoo_module.YahooProvider, "search_symbols", search)
        return calls

    def test_it_resolves_a_stuck_instrument_and_records_why(self, settings, monkeypatch):
        from awltux.db import Instrument, InstrumentAlias, session_scope
        from awltux.ingest.jobs import resolve_symbols

        with session_scope() as session:
            self._stuck(session)
        calls = self._provider(monkeypatch, {"US44486Q1031": HUMACYTE})

        result = resolve_symbols()

        assert result.items_written == 1
        assert calls == ["US44486Q1031"], "it must search by ISIN first"
        with session_scope() as session:
            instrument = session.get(Instrument, "AHAC_US_EQ")
            assert instrument.yahoo_symbol == "HUMA"
            assert instrument.mapping_confidence >= APPLY_FLOOR
            alias = session.query(InstrumentAlias).filter_by(
                instrument_t212_ticker="AHAC_US_EQ", provider="yahoo"
            ).one()
            assert alias.symbol == "HUMA"
            assert alias.method == "isin"
            assert "applied" in alias.note

    def test_it_falls_back_to_the_name_when_the_isin_finds_nothing(self, settings, monkeypatch):
        from awltux.db import session_scope
        from awltux.ingest.jobs import resolve_symbols

        with session_scope() as session:
            self._stuck(
                session,
                ticker="AFAR_US_EQ",
                name="Aura FAT Projects",
                isin="KYG063621000",
                yahoo_symbol="AFAR",
            )
        calls = self._provider(
            monkeypatch,
            {"KYG063621000": [], "Aura FAT Projects": HUMACYTE},
        )

        resolve_symbols()

        assert calls == ["KYG063621000", "Aura FAT Projects"], (
            "the ISIN is tried first and the name only once it finds nothing"
        )

    def test_a_weak_match_is_recorded_but_not_applied(self, settings, monkeypatch):
        from awltux.db import Instrument, InstrumentAlias, session_scope
        from awltux.ingest.jobs import resolve_symbols

        with session_scope() as session:
            self._stuck(session)
        self._provider(
            monkeypatch,
            {"US44486Q1031": [_candidate("ZZZZ", "Something Else Entirely", "NMS")]},
        )

        result = resolve_symbols()

        assert result.items_written == 0
        with session_scope() as session:
            instrument = session.get(Instrument, "AHAC_US_EQ")
            assert instrument.yahoo_symbol == "AHAC", "the symbol must be left alone"
            alias = session.query(InstrumentAlias).filter_by(
                instrument_t212_ticker="AHAC_US_EQ", provider="yahoo"
            ).one()
            assert alias.note

    def test_a_manual_alias_is_never_overwritten(self, settings, monkeypatch):
        from awltux.db import Instrument, InstrumentAlias, session_scope
        from awltux.ingest.jobs import resolve_symbols

        with session_scope() as session:
            self._stuck(session)
            session.add(
                InstrumentAlias(
                    instrument_t212_ticker="AHAC_US_EQ",
                    provider="yahoo",
                    symbol="HAND_PICKED",
                    confidence=1.0,
                    method="manual",
                    is_manual=True,
                )
            )
        self._provider(monkeypatch, {"US44486Q1031": HUMACYTE})

        resolve_symbols()

        with session_scope() as session:
            assert session.get(Instrument, "AHAC_US_EQ").yahoo_symbol == "AHAC"
            alias = session.query(InstrumentAlias).filter_by(
                instrument_t212_ticker="AHAC_US_EQ", provider="yahoo"
            ).one()
            assert alias.symbol == "HAND_PICKED"

    def test_an_instrument_that_already_has_prices_is_not_looked_up(self, settings, monkeypatch):
        """Hundreds of searches a day to confirm what already works is waste."""
        import datetime as dt

        from awltux.db import session_scope
        from awltux.ingest.jobs import resolve_symbols
        from tests.helpers import make_bars

        with session_scope() as session:
            ticker = self._stuck(session)
            for bar in make_bars(ticker, [1.0], start=dt.date(2026, 1, 2)):
                session.add(bar)
        calls = self._provider(monkeypatch, {"US44486Q1031": HUMACYTE})

        result = resolve_symbols()

        assert calls == []
        assert result.note is not None
        assert "no symbol left to resolve" in result.note
