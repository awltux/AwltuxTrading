"""Which Companies House record is the listed company, and which is a namesake.

Measured 2026-10-25 on the live database: **44 of the 115 stored company numbers did not name the
listed issuer.** 40 were private limited companies, most of them a subsidiary or an unrelated
company with a similar name:

| instrument | stored number | the register says |
|---|---|---|
| `CLAl_EQ` Celsius Resources | 12616617 | `CELSIUS LTD` (ltd, micro-entity accounts: £21,766 net assets) |
| `SUSl_EQ` S&U | 11461608 | `S&U DISTRIBUTION LTD` (ltd -- the group's own subsidiary) |
| `TMGl_EQ` Mission | 03530454 | `MISSION LTD` (ltd, **dissolved** 2015) |
| `MPOl_EQ` Macau Property Opportunities | LP012801 | `THREADNEEDLE UK OPPORTUNITIES PROPERTY FUND` (a different fund) |
| `MOONl_EQ` Moonpig | 13096622 | `MOONPIG GROUP PLC` — correct |

`match_company`'s docstring always said a weak match "can be recorded for human review without
being acted on", and `resolve_uk_companies` acted on every match it was given, at 0.4 and 0.5 as
readily as at 0.9. Two rules now stand between a name and a number being written: the candidate has
to be an entity a listed share can be, and the match has to be exact.
"""

from __future__ import annotations

from awltux.db import Instrument, InstrumentAlias, InstrumentBlocker
from awltux.ingest.fundamentals import (
    MIN_MATCH_CONFIDENCE,
    listed_entity_problem,
    match_company,
    repair_uk_company_numbers,
    resolve_uk_companies,
)
from tests.helpers import make_instrument

CIK = "0000000001"


def _instrument(name: str, *, number: str | None = None) -> Instrument:
    return make_instrument(
        "TESTl_EQ",
        name=name,
        exchange_name="LSE",
        yahoo_symbol="TEST.L",
        sec_cik=None,
        ch_company_number=number,
    )


def _store(session, instrument: Instrument, *numbers: str) -> None:
    session.add(instrument)
    session.flush()
    for number in numbers or (instrument.ch_company_number,):
        if number:
            session.add(
                InstrumentAlias(
                    instrument_t212_ticker=instrument.t212_ticker,
                    provider="companies_house",
                    symbol=number,
                    confidence=0.5,
                    method="partial_name",
                    is_manual=False,
                    note="stored by an older matcher",
                )
            )
    session.commit()


class TestWhatAListedShareCannotBe:
    def test_a_private_company_is_refused_whatever_the_name(self):
        """The measured failure: a perfect name match on a `ltd` is exactly the wrong answer."""
        problem = listed_entity_problem(
            {"company_name": "CELSIUS LTD", "company_number": "12616617", "type": "ltd"}
        )

        assert "private" in problem or "ltd" in problem

    def test_a_dissolved_company_is_refused(self):
        problem = listed_entity_problem(
            {"company_name": "MISSION LTD", "type": "plc", "company_status": "dissolved"}
        )

        assert "dissolved" in problem

    def test_a_company_in_administration_is_not_refused(self):
        """`PFCl_EQ` Petrofac is `FC042865 PETROFAC LIMITED`, an oversea-company in administration.
        It is still the company whose accounts a reader wants."""
        assert listed_entity_problem(
            {"company_name": "PETROFAC LIMITED", "type": "oversea-company",
             "company_status": "administration"}
        ) == ""

    def test_an_overseas_entity_is_not_refused(self):
        """`GRXl_EQ` GreenX Metals is `OE020671`, a registered overseas entity, not a plc."""
        assert listed_entity_problem(
            {"company_name": "GREENX METALS LIMITED", "type": "registered-overseas-entity",
             "company_status": "registered"}
        ) == ""

    def test_a_record_with_no_entity_type_cannot_be_checked(self):
        assert "entity type" in listed_entity_problem(
            {"company_name": "SOMETHING LTD", "company_number": "1"}
        )


class TestMatching:
    def test_a_namesake_cannot_win_even_as_a_token_overlap(self):
        """Celsius Resources against `CELSIUS LTD`: the tokens overlap and the legal form rules it
        out, so nothing is returned at all rather than a low-confidence candidate."""
        instrument = _instrument("Celsius Resources")

        match = match_company(
            instrument,
            [
                {"title": "CELSIUS LTD", "company_number": "12616617", "company_type": "ltd",
                 "company_status": "active"},
                {"title": "CELSIUS AIRCON LTD", "company_number": "12027180",
                 "company_type": "ltd", "company_status": "dissolved"},
            ],
        )

        assert match is None

    def test_the_listed_company_is_matched_exactly(self):
        match = match_company(
            _instrument("Moonpig"),
            [{"title": "MOONPIG GROUP PLC", "company_number": "13096622", "company_type": "plc",
              "company_status": "active"}],
        )

        assert match is not None
        assert match.company_number == "13096622"
        assert match.confidence == 0.9
        assert match.confidence >= MIN_MATCH_CONFIDENCE

    def test_a_partial_match_is_returned_as_a_candidate_and_not_a_resolution(self):
        """Kept rather than dropped, because the best candidate and its score are what the blocker
        names -- but it is below the threshold, so the caller will not write it."""
        match = match_company(
            _instrument("Angus Energy"),
            [{"title": "ANGUS ENERGY SERVICES PLC", "company_number": "09999999",
              "company_type": "plc", "company_status": "active"}],
        )

        assert match is not None
        assert match.confidence < MIN_MATCH_CONFIDENCE

    def test_a_dissolved_plc_is_skipped(self):
        assert match_company(
            _instrument("Mission"),
            [{"title": "MISSION PLC", "company_number": "03530454", "company_type": "plc",
              "company_status": "dissolved"}],
        ) is None


class _Provider:
    configured = True

    def __init__(self, candidates=None, profile=None):
        self._candidates = candidates or []
        self._profile = profile or {}

    def search_companies(self, name, **kwargs):
        return self._candidates

    def get_company(self, number):
        return self._profile


class TestTheResolverWritesOnlyADependableMatch:
    def _number(self, session) -> str | None:
        return session.execute(
            Instrument.__table__.select().with_only_columns(Instrument.ch_company_number)
        ).scalar_one()

    def test_a_candidate_below_the_threshold_is_recorded_and_not_written(self, session, settings):
        instrument = _instrument("Angus Energy")
        session.add(instrument)
        session.commit()

        summary = resolve_uk_companies(
            session,
            settings=settings,
            provider=_Provider(
                [
                    {"title": "ANGUS ENERGY SERVICES PLC", "company_number": "09999999",
                     "company_type": "plc", "company_status": "active"}
                ]
            ),
        )

        session.refresh(instrument)
        assert instrument.ch_company_number is None
        assert summary["matched"] == 0
        assert summary["candidates"] == 1
        blocker = session.query(InstrumentBlocker).filter_by(
            instrument_t212_ticker="TESTl_EQ", job="uk_companies", stage="company_number"
        ).one()
        assert "ANGUS ENERGY SERVICES PLC" in blocker.reason
        assert "below" in blocker.reason

    def test_an_exact_match_is_written_with_its_alias(self, session, settings):
        instrument = _instrument("Moonpig")
        session.add(instrument)
        session.commit()

        summary = resolve_uk_companies(
            session,
            settings=settings,
            provider=_Provider(
                [{"title": "MOONPIG GROUP PLC", "company_number": "13096622",
                  "company_type": "plc", "company_status": "active"}]
            ),
        )

        session.refresh(instrument)
        assert instrument.ch_company_number == "13096622"
        assert summary["matched"] == 1
        alias = session.query(InstrumentAlias).filter_by(
            instrument_t212_ticker="TESTl_EQ", provider="companies_house"
        ).one()
        assert alias.symbol == "13096622"


class TestTheRepair:
    def test_a_private_namesake_is_cleared_with_its_alias(self, session, settings):
        instrument = _instrument("Celsius Resources", number="12616617")
        _store(session, instrument, "12616617")
        provider = _Provider(
            profile={"company_name": "CELSIUS LTD", "type": "ltd",
                     "company_status": "active"}
        )

        report = repair_uk_company_numbers(session, settings=settings, provider=provider,
                                          dry_run=False)

        session.expire_all()
        stored = session.get(Instrument, "TESTl_EQ")
        assert stored.ch_company_number is None
        assert report["cleared"][0]["number"] == "12616617"
        assert "CELSIUS LTD" in report["cleared"][0]["registered_as"]
        assert session.query(InstrumentAlias).filter_by(
            instrument_t212_ticker="TESTl_EQ"
        ).count() == 0
        blocker = session.query(InstrumentBlocker).filter_by(
            instrument_t212_ticker="TESTl_EQ", job="uk_companies"
        ).one()
        assert "cleared" in blocker.reason

    def test_a_namesake_with_a_plausible_legal_form_is_cleared_by_the_name_check(
        self, session, settings
    ):
        """Macau Property Opportunities held `THREADNEEDLE UK OPPORTUNITIES PROPERTY FUND`, a
        limited partnership -- an eligible form on the wrong fund. The name check is what catches
        it."""
        instrument = _instrument("Macau Property Opportunities F", number="LP012801")
        _store(session, instrument, "LP012801")
        provider = _Provider(
            profile={"company_name": "THREADNEEDLE UK OPPORTUNITIES PROPERTY FUND",
                     "type": "limited-partnership", "company_status": "active"}
        )

        report = repair_uk_company_numbers(session, settings=settings, provider=provider)

        session.expire_all()
        assert session.get(Instrument, "TESTl_EQ").ch_company_number is None
        assert "not this instrument" in report["cleared"][0]["reason"]

    def test_the_listed_company_is_kept(self, session, settings):
        instrument = _instrument("Moonpig", number="13096622")
        _store(session, instrument, "13096622")
        provider = _Provider(
            profile={"company_name": "MOONPIG GROUP PLC", "type": "plc",
                     "company_status": "active"}
        )

        report = repair_uk_company_numbers(session, settings=settings, provider=provider)

        session.expire_all()
        assert session.get(Instrument, "TESTl_EQ").ch_company_number == "13096622"
        assert report["kept"] == 1 and report["cleared"] == []

    def test_an_alias_a_reader_set_by_hand_is_left_alone(self, session, settings):
        instrument = _instrument("Celsius Resources", number="12616617")
        session.add(instrument)
        session.flush()
        session.add(
            InstrumentAlias(
                instrument_t212_ticker="TESTl_EQ",
                provider="companies_house",
                symbol="12616617",
                confidence=1.0,
                method="manual",
                is_manual=True,
                note="picked by a reader",
            )
        )
        session.commit()
        provider = _Provider(profile={"company_name": "CELSIUS LTD", "type": "ltd"})

        report = repair_uk_company_numbers(session, settings=settings, provider=provider)

        session.expire_all()
        assert session.get(Instrument, "TESTl_EQ").ch_company_number == "12616617"
        assert report["manual"][0]["number"] == "12616617"
        assert report["cleared"] == []

    def test_a_dry_run_writes_nothing(self, session, settings):
        instrument = _instrument("Celsius Resources", number="12616617")
        _store(session, instrument, "12616617")
        provider = _Provider(profile={"company_name": "CELSIUS LTD", "type": "ltd"})

        report = repair_uk_company_numbers(
            session, settings=settings, provider=provider, dry_run=True
        )

        session.expire_all()
        assert session.get(Instrument, "TESTl_EQ").ch_company_number == "12616617"
        assert len(report["cleared"]) == 1
        assert session.query(InstrumentBlocker).count() == 0
