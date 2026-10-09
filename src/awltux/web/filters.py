"""The filter system: one declaration per filter, and everything else derived.

The recommendations table is driven by query parameters, so every view is a
shareable URL and the page works without JavaScript. That part was already true;
what was missing was a *system* for it.

Adding a filter used to mean editing six places that had to agree by hand: the
route signature, the call into ``queries.recommendations``, the template context,
the ``params()`` macro's dict, the search form's hidden inputs, and whatever
control the reader actually clicks. Six chances to forget one, and the failures
are quiet -- a filter that is applied but not carried by a link silently drops
the moment the reader clicks a column header, and a control whose value is not in
the macro silently resets the others.

Here a filter is declared once, in :func:`recommendation_specs`, and everything
else is computed from that declaration:

* the control the reader sees (:meth:`FilterSet.controls`);
* the querystring every link on the page carries (:meth:`FilterSet.query`);
* the chips showing what is currently applied (:meth:`FilterSet.active`).

**An unusable value renders the page and says so.** A mistyped or stale URL does
not raise: the value is dropped, the unfiltered table is shown, and the page names
what it ignored (:attr:`FilterSet.ignored`). Refusing to render would punish a
bookmark; ignoring it silently would show a table that is not what the URL asked
for, which is the failure mode this codebase keeps recording elsewhere -- an
unknown must be reported, never inferred.
"""

from __future__ import annotations

import datetime as dt
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, get_args

from awltux.analysis.relevance import MATERIALITY_ORDER
from awltux.web.queries import NewsSortKey, SortKey

#: How a filter is presented to the reader.
#:
#: ``none`` is not "hidden": the filter still appears in every URL and in the
#: active-filter chips. It means the reader sets it somewhere other than the form
#: -- ``sort`` through a column header, ``horizon`` through its own picker -- so
#: rendering a second control for it would be two ways to set one value.
#:
#: ``flag`` is a checkbox: absent means off, ``"1"`` means on. It is a kind of its own
#: rather than a two-option ``choice`` because a dropdown with "yes/no" is a worse
#: control for one binary, and because the parse rule differs -- see :meth:`FilterSet.parse`.
Kind = Literal["choice", "text", "none", "flag"]

#: The value a set flag carries in the URL. Not "true"/"on"/"yes": one spelling means a
#: link built by hand and a link built by this module cannot disagree.
FLAG_ON = "1"


@dataclass(frozen=True, slots=True)
class FilterOption:
    """One selectable value, with the label the reader understands.

    ``note`` carries the quantity that makes the option worth choosing -- how many
    instruments are in a sector, how many decisions an engine produced. A dropdown
    of bare names makes the reader guess which ones are empty.
    """

    value: str
    label: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class FilterSpec:
    """The declaration of one filter: its URL name, its control, its values."""

    name: str
    label: str
    kind: Kind = "choice"
    options: tuple[FilterOption, ...] = ()
    #: The value that means "not filtering". Omitting it from a link is what keeps
    #: `/dashboard?sector=X` clean instead of carrying five defaults, and it is why
    #: clearing a filter needs no special case: setting it back to the default
    #: removes the parameter.
    default: str = ""
    help: str = ""
    placeholder: str = ""
    #: Whether a reader-set value is worth a chip. Ordering is not filtering, so
    #: `sort` and `page` do not get one.
    chip: bool = True


@dataclass(frozen=True, slots=True)
class IgnoredValue:
    """A URL asked for something this filter cannot do."""

    name: str
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class ActiveFilter:
    """A filter the reader has applied, and the link that removes it alone."""

    name: str
    label: str
    value: str
    shown: str
    clear_query: str


class FilterSet:
    """The page's query state: what is set, how to relink it, how to change it.

    Immutable. Every method that would change it returns a querystring instead,
    because the state lives in the URL rather than in a session or a hidden field.
    """

    def __init__(
        self,
        specs: Sequence[FilterSpec],
        values: Mapping[str, str],
        ignored: Sequence[IgnoredValue] = (),
    ) -> None:
        self._specs = {spec.name: spec for spec in specs}
        self._order = [spec.name for spec in specs]
        self._values = dict(values)
        self.ignored = tuple(ignored)

    # ------------------------------------------------------------- parsing
    @classmethod
    def parse(cls, specs: Sequence[FilterSpec], params: Mapping[str, str]) -> FilterSet:
        """Read the specs' values out of a request's query parameters.

        Unknown values fall back to the default and are *recorded*. A filter with
        no ``options`` is free-form (a search box) and accepts anything.
        """
        values: dict[str, str] = {}
        ignored: list[IgnoredValue] = []

        for spec in specs:
            raw = (params.get(spec.name) or "").strip()

            if spec.kind == "flag":
                # A checkbox URL is either the marker or absent, so anything else is a
                # hand-edited or stale link. Recorded rather than coerced: `?attention=0`
                # and `?attention=banana` mean the same thing to a truthiness test, and
                # silently reading either as "on" would show a filtered table that the
                # URL did not ask for. Exactly the failure this module exists to prevent.
                if not raw or raw == spec.default:
                    values[spec.name] = spec.default
                elif raw == FLAG_ON:
                    values[spec.name] = FLAG_ON
                else:
                    values[spec.name] = spec.default
                    ignored.append(IgnoredValue(spec.name, spec.label, raw))
                continue

            if not raw or spec.kind == "text" or not spec.options:
                values[spec.name] = raw or spec.default
                continue

            allowed = {option.value for option in spec.options}
            if raw in allowed:
                values[spec.name] = raw
            else:
                values[spec.name] = spec.default
                ignored.append(IgnoredValue(spec.name, spec.label, raw))

        return cls(specs, values, ignored)

    # ------------------------------------------------------------- reading
    def value(self, name: str) -> str:
        """The current value, or the spec's default. Never ``None``."""
        return self._values.get(name, self._specs[name].default)

    def given(self, name: str) -> bool:
        """Whether the reader actually set this, as opposed to it being a default."""
        return bool(self._values.get(name)) and self._values.get(name) != self._specs[name].default

    def opt(self, name: str) -> str | None:
        """The value to hand a query, where "not filtering" is ``None``.

        A query builder that receives ``""`` has to guess whether that means "any"
        or "an empty match"; ``None`` says it once, at the boundary.
        """
        value = self.value(name)
        return value or None

    def spec(self, name: str) -> FilterSpec:
        return self._specs[name]

    def shown(self, name: str) -> str:
        """The current value as the reader chose it, for headings and chips.

        Not the same as :meth:`value`: the sector control's "unclassified" entry
        stands for an empty column, so the URL carries a sentinel while the page
        must name it in words. Falling back to the raw value keeps a free-form
        filter (the search box) reading as what was typed.
        """
        value = self.value(name)
        for option in self._specs[name].options:
            if option.value == value:
                return option.label
        return value

    @property
    def specs(self) -> tuple[FilterSpec, ...]:
        """Every declared filter, in declaration order."""
        return tuple(self._specs[name] for name in self._order)

    @property
    def controls(self) -> tuple[FilterSpec, ...]:
        """The specs the filter bar renders, in declaration order."""
        return tuple(spec for spec in self.specs if spec.kind != "none")

    @property
    def hidden(self) -> tuple[FilterSpec, ...]:
        """The state the form must carry without showing a control for it.

        Without these a submit would reset the sort order, the chosen horizon and
        the view -- the reader changes the sector, and the table silently jumps back
        to a differently sorted list. ``page`` is the one exception; see
        :data:`RESET_ON_SUBMIT`.
        """
        return tuple(
            spec
            for spec in self.specs
            if spec.kind == "none"
            and spec.name not in RESET_ON_SUBMIT
            and self.value(spec.name) != spec.default
        )

    # ------------------------------------------------------------- linking
    def query(self, **overrides: object) -> str:
        """A querystring for this state, with per-link overrides.

        ``query(sector=None)`` clears a filter; ``query(page=2)`` moves a page.
        Values equal to their default are omitted, so a link carries only what the
        reader changed.
        """
        parts: list[str] = []
        remaining = dict(overrides)

        for name in self._order:
            spec = self._specs[name]
            value = remaining.pop(name, self._values.get(name, spec.default))
            if value is None or str(value) == "" or str(value) == spec.default:
                continue
            parts.append(f"{name}={urllib.parse.quote(str(value), safe='')}")

        # A name the registry does not declare is still honoured: paging and the
        # per-page count are computed from integers the route owns, and a caller
        # should not have to register them to link to page three.
        for name, value in remaining.items():
            if value is None or str(value) == "":
                continue
            parts.append(f"{name}={urllib.parse.quote(str(value), safe='')}")

        return f"?{'&'.join(parts)}" if parts else ""

    def href(self, path: str, **overrides: object) -> str:
        """A complete link, e.g. ``/dashboard?sector=Drugs``."""
        return f"{path}{self.query(**overrides)}"

    def clear_href(self, path: str) -> str:
        """The same table with every *chip-producing* filter removed.

        Ordering and paging are not filters, so they survive: "clear the filters"
        should not also re-sort the table the reader just arranged.
        """
        return f"{path}{self.query(**{spec.name: None for spec in self.specs if spec.chip})}"

    # -------------------------------------------------------------- chips
    def active(self) -> tuple[ActiveFilter, ...]:
        """The applied filters, each with the link that clears only that one.

        Built from the specs rather than from a list maintained in the template, so
        a new filter gets a chip without anyone remembering to add one.
        """
        out: list[ActiveFilter] = []
        for spec in self.specs:
            if not spec.chip or not self.given(spec.name):
                continue
            value = self.value(spec.name)
            out.append(
                ActiveFilter(
                    name=spec.name,
                    label=spec.label,
                    value=value,
                    shown=self.shown(spec.name),
                    clear_query=self.query(**{spec.name: None}),
                )
            )
        return tuple(out)


# --------------------------------------------------------------------------- #
# the recommendations page
# --------------------------------------------------------------------------- #

#: The URL value standing for "this instrument has no sector".
#:
#: A sentinel rather than an empty string, because a URL cannot tell "the column is
#: empty" from "do not filter on this column" apart: an absent parameter already
#: means the second, so the first needs a name of its own. On the live database
#: this is not a corner: 194 of 500 instruments in the universe have no sector, so
#: a filter that could not express it would quietly hide 39% of the table.
UNCLASSIFIED = "__unclassified__"

ACTION_OPTIONS = (
    FilterOption("strong_buy", "Strong buy"),
    FilterOption("buy", "Buy"),
    FilterOption("hold", "Hold"),
    FilterOption("reduce", "Reduce"),
    FilterOption("sell", "Sell"),
    FilterOption("avoid", "Avoid"),
)

ENGINE_OPTIONS = (
    FilterOption("jev", "JEV", "calibrated"),
    FilterOption("deepseek", "DeepSeek", "uncalibrated"),
    FilterOption("offline", "offline", "deterministic fallback"),
)

HORIZON_FIT_OPTIONS = (
    FilterOption("long_term", "Long term"),
    FilterOption("short_term", "Short term"),
    FilterOption("both", "Both"),
    FilterOption("neither", "Neither"),
)

VIEW_OPTIONS = (
    FilterOption("all", "All"),
    FilterOption("suggestions", "Actionable only"),
    FilterOption("held", "My holdings"),
)

HORIZON_OPTIONS = (
    FilterOption("long_term", "Long term"),
    FilterOption("short_term", "Short term"),
)

DIRECTION_OPTIONS = (
    FilterOption("desc", "Descending"),
    FilterOption("asc", "Ascending"),
)

#: State the filter form deliberately does *not* preserve across a submit.
#:
#: A changed filter is a new query, so it starts at the first page. Carrying the
#: page number would land the reader past the end of a narrower result set -- an
#: empty table that looks like the filter matched nothing, when in fact it matched
#: three rows on page one. Every other piece of state is carried, or submitting the
#: form from a sorted, horizon-switched, holdings-only view would silently reset
#: all three.
RESET_ON_SUBMIT = ("page",)

#: Taken from the query layer's own ``SortKey`` rather than restated. The options a
#: control offers and the keys the sort understands are the same fact, and stating
#: it twice is how a page ends up linking to a sort that silently does nothing.
SORT_OPTIONS = tuple(
    FilterOption(key, key.replace("_", " ")) for key in get_args(SortKey)
)


def sector_filter(value: str | None) -> tuple[str | None, bool]:
    """Translate the sector control into the two things the query layer needs.

    Returns ``(sector, unknown_only)``. Keeping the translation here means
    :mod:`awltux.web.queries` never has to know that a URL sentinel exists: it is
    asked for a named sector, or for the instruments that have none, and each is a
    fact about the data rather than about the address bar.
    """
    if value == UNCLASSIFIED:
        return None, True
    return value, False


def sector_options(rows: Sequence[tuple[str | None, int]]) -> tuple[FilterOption, ...]:
    """Turn ``(sector, count)`` rows into dropdown entries, best populated first.

    The count is shown because it is the difference between a useful choice and a
    wasted click: sector here means the SEC SIC industry string, so the live
    universe holds 144 of them for 500 instruments and most name a single company.
    A list of bare names would hide that completely.

    Unclassified goes last rather than being sorted among the rest, because it is
    not a sector -- it is the absence of one, and it is the one entry whose count
    the reader is most likely to be surprised by.
    """
    named = sorted(
        ((name, count) for name, count in rows if name),
        key=lambda item: (-item[1], item[0]),
    )
    options = [FilterOption(name, name, str(count)) for name, count in named]

    unclassified = sum(count for name, count in rows if not name)
    if unclassified:
        options.append(FilterOption(UNCLASSIFIED, "Unclassified", str(unclassified)))

    return tuple(options)


def recommendation_specs(
    *, sectors: Sequence[FilterOption] = ()
) -> tuple[FilterSpec, ...]:
    """Every query parameter the recommendations page understands, declared once.

    ``sectors`` is passed in rather than queried here: this module decides how a
    filter is presented and linked, and :mod:`awltux.web.queries` decides what is
    in the database. Keeping the SQL out of the presentation layer is what lets
    the URL rules be tested without a database.
    """
    return (
        FilterSpec(
            "q",
            "Search",
            kind="text",
            placeholder="Ticker or name…",
            help="Matches the ticker or any part of the company name.",
        ),
        FilterSpec(
            "sector",
            "Sector",
            options=tuple(sectors),
            help=(
                "Derived from SEC SIC codes for US filers and provider industry "
                "fields for UK listings, so it is approximate."
            ),
        ),
        FilterSpec("action", "Action", options=ACTION_OPTIONS),
        FilterSpec("engine", "Engine", options=ENGINE_OPTIONS),
        FilterSpec("horizon_fit", "Suits", options=HORIZON_FIT_OPTIONS),
        FilterSpec(
            "attention",
            "Needs attention",
            kind="flag",
            help=(
                "Instruments whose figures we hold are wrong or incomplete, or that a "
                "job has recorded it cannot fetch. How strict this is comes from "
                "app.attention_level in the configuration."
            ),
        ),
        FilterSpec("view", "View", options=VIEW_OPTIONS, default="all", kind="none"),
        FilterSpec(
            "horizon",
            "Horizon",
            options=HORIZON_OPTIONS,
            default="long_term",
            kind="none",
        ),
        FilterSpec(
            "sort",
            "Sort",
            options=SORT_OPTIONS,
            default="composite_score",
            kind="none",
            chip=False,
        ),
        FilterSpec(
            "direction", "Direction", options=DIRECTION_OPTIONS, default="desc",
            kind="none", chip=False,
        ),
        FilterSpec("page", "Page", default="1", kind="none", chip=False),
        FilterSpec("per_page", "Per page", default="100", kind="none", chip=False),
    )


# --------------------------------------------------------------------------- #
# the news page
# --------------------------------------------------------------------------- #

#: The URL value standing for "no classifier has judged this story".
#:
#: ``relevant`` is nullable on purpose -- ``None`` is "not assessed", a different and
#: more actionable state than "assessed as not relevant" -- so a control offering the
#: two judged answers needs a third name for the unjudged one. It cannot be an empty
#: string: an absent parameter already means "do not filter on this", so the state needs
#: a name of its own, exactly as :data:`UNCLASSIFIED` does for the sector column.
UNASSESSED = "__unassessed__"

NEWS_RELEVANCE_OPTIONS = (
    FilterOption("relevant", "Assessed relevant"),
    FilterOption("not_relevant", "Assessed not relevant"),
    FilterOption(UNASSESSED, "Not yet assessed"),
)

#: How far back the listing looks, and the age each choice means.
#:
#: One dict so the control's options and the query's cutoff cannot disagree about what
#: "7d" is. A window rather than two date boxes: the reader arrives with "what has
#: happened lately", not with a date range, and the corpus reaches back years.
NEWS_WINDOW_AGES: dict[str, dt.timedelta] = {
    "24h": dt.timedelta(hours=24),
    "7d": dt.timedelta(days=7),
    "30d": dt.timedelta(days=30),
    "90d": dt.timedelta(days=90),
    "365d": dt.timedelta(days=365),
}

_NEWS_WINDOW_LABELS = {
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
    "90d": "Last 90 days",
    "365d": "Last year",
}

NEWS_WINDOW_OPTIONS = tuple(
    FilterOption(value, _NEWS_WINDOW_LABELS[value]) for value in NEWS_WINDOW_AGES
)

#: Taken from the query layer's own ``NewsSortKey``: the keys a column header can link
#: to and the keys the ordering understands are the same fact, and stating it twice is
#: how a table ends up linking to a sort that silently does nothing.
NEWS_SORT_OPTIONS = tuple(
    FilterOption(key, key.replace("_", " ")) for key in get_args(NewsSortKey)
)


def news_window(value: str) -> dt.timedelta | None:
    """The chosen window as an age, or ``None`` for "any time"."""
    return NEWS_WINDOW_AGES.get(value)


def source_options(rows: Sequence[tuple[str, int]]) -> tuple[FilterOption, ...]:
    """Turn ``(source, count)`` rows into dropdown entries, busiest first.

    No "unclassified" bucket, unlike :func:`sector_options`: ``source`` is not nullable
    and is set by the feed adapter that fetched the story, so there is no empty case to
    name. The count is shown for a different reason than the sector control's -- the
    corpus is dominated by one feed (26,580 of 27,884 rows are google_news), and the
    reader is better off knowing that before they filter to a source of eleven.
    """
    return tuple(
        FilterOption(name, name, str(count))
        for name, count in sorted(rows, key=lambda item: (-item[1], item[0]))
    )


def materiality_options(
    rows: Sequence[tuple[str | None, int]],
) -> tuple[FilterOption, ...]:
    """Turn ``(materiality, count)`` rows into dropdown entries, most severe first.

    Ordered by severity rather than by population. A reader opening this control is
    looking for the profit warnings, and the live database has 13,976 stories at
    ``none`` against 242 at ``critical`` -- sorted by count, the one level that matters
    would be last.

    ``None`` is left out. An unassessed story is offered by the *relevance* control,
    which is where that state belongs, and offering it twice would be two ways to ask
    one question.
    """
    counts = {level: count for level, count in rows if level}
    return tuple(
        FilterOption(level, level, str(counts[level]))
        for level in reversed(MATERIALITY_ORDER)
        if level in counts
    )


def news_specs(
    *,
    sources: Sequence[FilterOption] = (),
    materiality: Sequence[FilterOption] = (),
) -> tuple[FilterSpec, ...]:
    """Every query parameter the news page understands, declared once.

    The option lists are passed in for the same reason the sector list is: this module
    decides how a filter is presented and linked, and :mod:`awltux.web.queries` decides
    what is in the database. Keeping the SQL out of the presentation layer is what lets
    these URL rules be tested without a database.

    Long, and flat on purpose. The declarations are independent -- each names one
    parameter, its control and the sentence that explains it -- so splitting them across
    helpers would scatter one page's URL vocabulary over several functions and hide the
    whole of it from the reader who has to check that a control and a query agree. The
    length is the *help* text, which is the part a reader actually sees.
    """
    return (
        FilterSpec(
            "q",
            "Search",
            kind="text",
            placeholder="Headline or source…",
            help=(
                "Matches any part of the headline, or of the source's own name. Not the "
                "summary or the article body, which are not both stored."
            ),
        ),
        FilterSpec(
            "ticker",
            "Instrument",
            kind="text",
            placeholder="T212 ticker…",
            help=(
                "The ticker exactly as the feeds tag it, e.g. DAC_US_EQ. Matched against "
                "the instruments the story was judged to concern, which is not the same "
                "as the story mentioning the company in passing."
            ),
        ),
        FilterSpec("source", "Source", options=tuple(sources)),
        FilterSpec(
            "materiality",
            "Materiality",
            options=tuple(materiality),
            help=(
                "How much the classifier judged the story matters, if it is true. "
                "'none' is a stated judgement, not a missing one."
            ),
        ),
        FilterSpec(
            "relevance",
            "Relevance",
            options=NEWS_RELEVANCE_OPTIONS,
            help=(
                "Whether the story is a claim about a share price: it names an "
                "instrument or a sector, and carries a direction. A story nobody has "
                "classified yet is a third state, not a 'no'."
            ),
        ),
        FilterSpec(
            "window",
            "Window",
            options=NEWS_WINDOW_OPTIONS,
            help="How far back to look, by publication time.",
        ),
        FilterSpec(
            "sort",
            "Sort",
            options=NEWS_SORT_OPTIONS,
            default="published_at",
            kind="none",
            chip=False,
        ),
        FilterSpec(
            "direction", "Direction", options=DIRECTION_OPTIONS, default="desc",
            kind="none", chip=False,
        ),
        FilterSpec("page", "Page", default="1", kind="none", chip=False),
        FilterSpec("per_page", "Per page", default="50", kind="none", chip=False),
    )
