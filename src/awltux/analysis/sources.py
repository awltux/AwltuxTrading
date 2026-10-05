"""Who is saying it, and what that is worth.

A news headline is not evidence. It is a claim, made by an organisation with
interests, reported with whatever care and whatever omissions that organisation
brings. This module is the part of the system that knows who the publishers are,
so every downstream number can be weighted by *who is speaking* rather than
treating "the news said so" as a fact.

Three axes, deliberately separate because collapsing them is how bad reasoning
gets in:

``kind``
    What sort of document this is: the authoritative record, the company speaking
    about itself, a wire service, an outlet with its own reporting, an aggregator
    passing someone else's copy along, a press-release distributor, or opinion.
``reliability``
    Track record for factual accuracy in *financial* reporting. This is about
    care and corrections, not about whether the outlet agrees with anyone.
``independence``
    Freedom from a stake in the story. A company's own announcement is perfectly
    reliable about what the company said and not independent at all.

**This registry is editorial judgement, not measurement.** Nobody publishes a
calibrated accuracy score for newspapers, so any such number is an opinion, and
presenting an opinion as a measurement is exactly the failure this system exists
to catch. So every entry carries the ``basis`` for its assessment, the whole
table carries :data:`REVIEWED_ON`, and the UI must show the assessment as an
assessment. Where there is no curated entry the answer is *unknown* -- not
"unreliable". Not having an opinion is a different thing from having a bad one.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from urllib.parse import urlparse

#: When a human last reviewed the table below. Stale judgements should be visible
#: as stale rather than silently inherited.
REVIEWED_ON = dt.date(2026, 10, 5)

#: Closed vocabulary of bias tags. Closed on purpose: free-text tags would drift
#: into vague accusations that cannot be tested or shown consistently in the UI.
BIAS_TAGS = frozenset(
    {
        "political_lean_left",
        "political_lean_right",
        "political_lean_centre",
        "sensationalist",
        "opinion_led",
        "market_mover",  # written for traders; structurally drawn to hype cycles
        "press_release",  # publishes company copy as news
        "state_funded",
        "aggregator",  # mostly republishes other people's reporting
        "ownership_conflict",  # owner has commercial interests in what it covers
        "paywalled",
        "contributor_written",  # unpaid or lightly-edited outside contributors
        "anonymous_sourcing",  # routinely relies on unnamed sources
    }
)

#: Document kinds, most authoritative first. ``kind`` sets the default
#: reliability/independence; individual entries override where it is warranted.
KINDS = (
    "primary_record",  # the regulator, exchange or registry that holds the fact
    "company_self",  # the company speaking about itself
    "wire",  # a news agency that sells copy to everyone else
    "quality",  # own reporting, strong corrections culture
    "mainstream",  # own reporting, generalist, variable financial depth
    "opinion",  # comment and analysis rather than reporting
    "aggregator",  # republishes others' copy
    "press_release",  # distribution of company-supplied text
    "unknown",
)

#: (reliability, independence) per kind. Self-interest is not dishonesty: this is
#: about which questions each kind of document can actually settle.
KIND_DEFAULTS: dict[str, tuple[float, float]] = {
    "primary_record": (0.97, 0.90),
    # Reliable about what the company said; carries the company's interest.
    "company_self": (0.85, 0.15),
    "wire": (0.88, 0.90),
    "quality": (0.85, 0.90),
    "mainstream": (0.72, 0.85),
    "opinion": (0.45, 0.60),
    "aggregator": (0.55, 0.30),
    # A press release is the company's own words wearing a distributor's domain.
    "press_release": (0.60, 0.10),
    "unknown": (0.50, 0.55),
}


@dataclass(frozen=True, slots=True)
class Publisher:
    """A publisher, and what its output is worth as evidence."""

    domain: str
    name: str
    kind: str
    reliability: float
    independence: float
    biases: tuple[str, ...]
    ownership: str | None
    #: Why this assessment was made. Shown in the UI: a judgement with no stated
    #: basis is indistinguishable from a prejudice.
    basis: str

    @property
    def is_primary(self) -> bool:
        return self.kind == "primary_record"

    @property
    def assessed(self) -> bool:
        return self.kind != "unknown"

    @property
    def label(self) -> str:
        """Short human label for the confidence level."""
        if not self.assessed:
            return "unrated"
        if self.reliability >= 0.85:
            return "high"
        if self.reliability >= 0.65:
            return "moderate"
        if self.reliability >= 0.5:
            return "low"
        return "very low"

    def as_dict(self) -> dict[str, object]:
        return {
            "domain": self.domain,
            "name": self.name,
            "kind": self.kind,
            "label": self.label,
            "reliability": self.reliability,
            "independence": self.independence,
            "biases": list(self.biases),
            "ownership": self.ownership,
            "basis": self.basis,
            "assessed": self.assessed,
            "reviewed_on": REVIEWED_ON.isoformat(),
        }


def _p(
    domain: str,
    name: str,
    kind: str,
    basis: str,
    *,
    biases: tuple[str, ...] = (),
    reliability: float | None = None,
    independence: float | None = None,
    ownership: str | None = None,
) -> Publisher:
    default_reliability, default_independence = KIND_DEFAULTS[kind]
    unknown_tags = set(biases) - BIAS_TAGS
    if unknown_tags:
        raise ValueError(f"{domain}: unknown bias tags {sorted(unknown_tags)}")
    return Publisher(
        domain=domain,
        name=name,
        kind=kind,
        reliability=default_reliability if reliability is None else reliability,
        independence=default_independence if independence is None else independence,
        biases=biases,
        ownership=ownership,
        basis=basis,
    )


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #
#
# Kept to publishers that actually appear in UK/US equity coverage. A long list
# would imply a thoroughness that does not exist; a short one that is honest
# about its basis is more useful than a comprehensive one that is invented.

_REGISTRY: tuple[Publisher, ...] = (
    # --- primary records -----------------------------------------------------
    _p("sec.gov", "US Securities and Exchange Commission", "primary_record",
       "The US filing registry. The filing itself is the fact; a report about it is not."),
    _p("londonstockexchange.com", "London Stock Exchange", "primary_record",
       "Holds RNS, the UK's regulated announcement service."),
    _p("companieshouse.gov.uk", "UK Companies House", "primary_record",
       "The UK statutory register of company accounts and officers. Unaudited for small filers."),
    _p("investor.gov", "SEC investor education", "primary_record",
       "Regulator's own investor guidance."),
    _p("fca.org.uk", "UK Financial Conduct Authority", "primary_record",
       "UK regulator. Its own publications are authoritative for its actions."),
    _p("federalreserve.gov", "US Federal Reserve", "primary_record",
       "Primary source for US monetary policy statements and minutes."),
    _p("bankofengland.co.uk", "Bank of England", "primary_record",
       "Primary source for UK monetary policy and financial stability publications."),
    _p("ons.gov.uk", "UK Office for National Statistics", "primary_record",
       "Primary source for UK official statistics."),
    _p("bls.gov", "US Bureau of Labor Statistics", "primary_record",
       "Primary source for US employment and inflation data."),
    _p("ecb.europa.eu", "European Central Bank", "primary_record",
       "Primary source for euro-area monetary policy."),
    _p("gov.uk", "UK Government", "primary_record",
       "Official announcements; a government statement is primary for its own policy, not for its effects."),

    # --- wires ---------------------------------------------------------------
    _p("reuters.com", "Reuters", "wire",
       "News agency selling copy to most other outlets, which is why one Reuters story "
       "reappears across dozens of domains. Own reporting, corrections policy.",
       biases=("political_lean_centre",)),
    _p("apnews.com", "Associated Press", "wire",
       "Not-for-profit agency, the other main origin of copy syndicated across domains.",
       biases=("political_lean_centre",)),
    _p("afp.com", "Agence France-Presse", "wire",
       "News agency; copy is widely republished.", biases=("political_lean_centre",)),
    _p("bloomberg.com", "Bloomberg", "wire",
       "Own reporting and terminal business. Terminal customers are also its subjects, "
       "which is a commercial relationship worth knowing about, not an accusation.",
       biases=("market_mover", "paywalled"), independence=0.85),

    # --- own reporting, strong financial desks -------------------------------
    _p("ft.com", "Financial Times", "quality",
       "Specialist financial reporting, corrections culture.", biases=("paywalled",)),
    _p("wsj.com", "The Wall Street Journal", "quality",
       "Specialist financial reporting; opinion pages are separately branded and much looser.",
       biases=("paywalled",)),
    _p("economist.com", "The Economist", "quality",
       "Analysis-led; explicitly takes editorial positions, which belongs in the opinion bucket "
       "for anything it argues rather than reports.", biases=("paywalled", "opinion_led")),
    _p("barrons.com", "Barron's", "quality",
       "Investor-facing reporting and commentary.", biases=("paywalled", "market_mover")),
    _p("thetimes.co.uk", "The Times", "quality",
       "Generalist with a business desk.", biases=("paywalled",)),
    _p("telegraph.co.uk", "The Daily Telegraph", "quality",
       "Generalist with a business desk and a stated editorial line.",
       biases=("paywalled", "political_lean_right")),
    _p("theguardian.com", "The Guardian", "quality",
       "Generalist with a business desk and a stated editorial line.",
       biases=("political_lean_left",)),
    _p("independent.co.uk", "The Independent", "mainstream",
       "Generalist; financial coverage is thinner than a specialist desk.",
       biases=("political_lean_left",)),
    _p("bbc.co.uk", "BBC News", "quality",
       "Public-service broadcaster, editorially independent by charter and licence-fee funded.",
       biases=("state_funded",)),
    _p("nytimes.com", "The New York Times", "quality",
       "Generalist with a business desk and a stated editorial line.",
       biases=("political_lean_left", "paywalled")),
    _p("washingtonpost.com", "The Washington Post", "quality",
       "Generalist with a business desk.", biases=("political_lean_left", "paywalled")),
    _p("cnbc.com", "CNBC", "mainstream",
       "Business television; structurally drawn to intraday drama, which is a scheduling "
       "incentive rather than a factual one.", biases=("market_mover", "sensationalist")),
    _p("foxbusiness.com", "Fox Business", "mainstream",
       "Business coverage within a channel with a stated editorial line.",
       biases=("political_lean_right", "market_mover")),
    _p("forbes.com", "Forbes", "mainstream",
       "Contributor-written sections sit alongside staff reporting and are not held to the "
       "same standard, so bylines matter here more than the brand.",
       biases=("contributor_written",)),
    _p("businessinsider.com", "Business Insider", "mainstream",
       "Consumer-facing business coverage; headlines are optimised for clicks.",
       biases=("sensationalist",)),
    _p("cnn.com", "CNN", "mainstream",
       "Generalist news with a business desk; financial coverage is shallower than a "
       "specialist outlet's.", biases=("political_lean_left",)),
    _p("news.sky.com", "Sky News", "mainstream", "Generalist with a business desk."),
    _p("marketwatch.com", "MarketWatch", "mainstream",
       "Investor-facing; headline framing leans on movement rather than substance.",
       biases=("market_mover",)),

    # --- aggregators and republishers ---------------------------------------
    _p("finance.yahoo.com", "Yahoo Finance", "aggregator",
       "Mostly licensed republication of wires and other outlets. The byline, not the "
       "domain, identifies who actually reported it.",
       biases=("aggregator",)),
    _p("yahoo.com", "Yahoo", "aggregator", "Licensed republication.", biases=("aggregator",)),
    _p("msn.com", "MSN", "aggregator", "Licensed republication.", biases=("aggregator",)),
    _p("news.google.com", "Google News", "aggregator",
       "A search index of other outlets' copy, never the origin of a story.",
       biases=("aggregator",)),
    _p("investing.com", "Investing.com", "aggregator",
       "Aggregated wires plus in-house commentary.", biases=("aggregator", "market_mover")),
    _p("seekingalpha.com", "Seeking Alpha", "opinion",
       "Mostly contributor-written analysis. Contributors may hold the positions they write "
       "about and are paid by readership, so treat it as an argument, not a report.",
       biases=("contributor_written", "opinion_led")),
    _p("simplywall.st", "Simply Wall St", "aggregator",
       "Algorithmically assembled summaries of company data; the numbers are usually "
       "derivable from filings, the framing is generated.", biases=("aggregator",)),
    _p("benzinga.com", "Benzinga", "aggregator",
       "Fast, high-volume market content; a large share is press release and wire derived.",
       biases=("aggregator", "market_mover")),
    _p("streetinsider.com", "StreetInsider", "aggregator",
       "Headline service relaying wires and releases.", biases=("aggregator", "market_mover")),
    _p("marketscreener.com", "MarketScreener", "aggregator",
       "Aggregated news and consensus data.", biases=("aggregator",)),

    # --- press release distribution -----------------------------------------
    _p("prnewswire.com", "PR Newswire", "press_release",
       "A distributor. Content is supplied by the issuer and is not independently checked."),
    _p("businesswire.com", "Business Wire", "press_release",
       "A distributor. Content is supplied by the issuer and is not independently checked."),
    _p("globenewswire.com", "GlobeNewswire", "press_release",
       "A distributor. Content is supplied by the issuer and is not independently checked."),
    _p("accesswire.com", "AccessWire", "press_release",
       "A distributor, with lighter editorial screening than the larger wires."),
    _p("einpresswire.com", "EIN Presswire", "press_release",
       "A distributor with minimal screening; paid placement."),
    _p("einnews.com", "EIN News", "aggregator",
       "Aggregates press releases and low-cost placements.", biases=("aggregator",)),

    # --- opinion and commentary ---------------------------------------------
    _p("zerohedge.com", "ZeroHedge", "opinion",
       "Commentary and aggregation with a consistently bearish framing; routinely cites "
       "unnamed sources and 'rumours'. Not a place to learn what happened, occasionally a "
       "place to learn what some traders believe.",
       biases=("opinion_led", "sensationalist", "anonymous_sourcing", "aggregator")),
    _p("oilprice.com", "OilPrice", "opinion",
       "Industry commentary and republished analysis; opinion pieces are common.",
       biases=("opinion_led", "aggregator")),
    _p("thestreet.com", "TheStreet", "opinion",
       "Investor commentary and stock picks alongside reporting.",
       biases=("opinion_led", "market_mover")),
    _p("dailyreckoning.com", "The Daily Reckoning", "opinion",
       "Investment-letter marketing; written to sell a subscription.",
       biases=("opinion_led", "sensationalist")),
    _p("moneymorning.com", "Money Morning", "opinion",
       "Investment-letter marketing; written to sell a subscription.",
       biases=("opinion_led", "sensationalist")),
)

REGISTRY: dict[str, Publisher] = {publisher.domain: publisher for publisher in _REGISTRY}

#: Domain fragments that identify a distributor or aggregator regardless of the
#: exact host, mapped to the registry entry they should be treated as. These
#: platforms put customer copy on country and customer subdomains, so the host is
#: not always one the registry can name exactly.
_PLATFORM_HINTS: dict[str, str] = {
    "globenewswire": "globenewswire.com",
    "prnewswire": "prnewswire.com",
    "businesswire": "businesswire.com",
    "accesswire": "accesswire.com",
}

UNKNOWN_PUBLISHER = Publisher(
    domain="",
    name="Unrecognised publisher",
    kind="unknown",
    reliability=KIND_DEFAULTS["unknown"][0],
    independence=KIND_DEFAULTS["unknown"][1],
    biases=(),
    ownership=None,
    basis=(
        "No assessment on file for this domain, which is not the same as a bad "
        "assessment: nothing is known about it either way, so its claims are treated "
        "as unverified until something else corroborates them."
    ),
)


def domain_of(url: str | None) -> str | None:
    """The host a URL points at, without ``www.``, a port or any credentials.

    Returns the *full* host rather than a registrable domain: ``finance.yahoo.com``
    and ``news.sky.com`` are distinct publishers from their parent sites, and
    collapsing to the last two labels would lose that. Resolving a subdomain to the
    organisation that owns it is :func:`lookup`'s job, not this one's.
    """
    if not url:
        return None
    try:
        host = (urlparse(url.strip()).netloc or "").lower()
    except ValueError:
        return None
    if not host:
        return None
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _host_candidates(host: str) -> list[str]:
    """``markets.ft.com`` -> ``["markets.ft.com", "ft.com"]``.

    Progressively shorter suffixes, so a publisher's subdomain resolves to the
    organisation while a host the registry knows exactly still wins. Two labels is
    the floor: a bare ``co.uk`` is not a publisher.
    """
    labels = host.split(".")
    out: list[str] = []
    for start in range(len(labels) - 1):
        candidate = ".".join(labels[start:])
        if candidate.count(".") >= 1:
            out.append(candidate)
    return out


def lookup(url_or_domain: str | None) -> Publisher:
    """The publisher behind a URL, or an explicit *unrated* placeholder.

    Resolution order: the exact host, then each parent domain, then a small set of
    platform hints. Never returns ``None`` and never guesses that an unlisted
    domain is reputable.
    """
    if not url_or_domain:
        return UNKNOWN_PUBLISHER
    candidate = url_or_domain.strip().lower()
    if "//" in candidate:
        candidate = domain_of(candidate) or candidate
    elif candidate.startswith("www."):
        candidate = candidate[4:]

    for domain in _host_candidates(candidate) or [candidate]:
        if domain in REGISTRY:
            return REGISTRY[domain]

    for hint, known in _PLATFORM_HINTS.items():
        if hint in candidate:
            return REGISTRY[known]

    return UNKNOWN_PUBLISHER


def source_weight(publisher: Publisher, *, direction: str | None = None) -> float:
    """How much this publisher's claim should count, 0..1.

    The interesting part is what self-interest does to credibility, because it does
    not move it in one direction:

    * A self-interested source reporting news **against its own interest** is more
      believable than usual -- companies do not casually announce profit warnings.
      So the discount shrinks, without becoming a bonus: reliability still caps it.
    * A self-interested source reporting **good news about itself** is the classic
      failure mode, and is discounted hard.

    Direction ``None`` means we could not tell, and gets the neutral discount.
    """
    base = publisher.reliability * (0.4 + 0.6 * publisher.independence)
    if publisher.independence >= 0.5:
        return round(min(1.0, base), 4)

    # How far the source is from being independent, 0..1.
    captured = 1.0 - publisher.independence
    if direction == "negative":
        # Speaking against interest: keep most of the reliability.
        factor = 1.0 - 0.15 * captured
    elif direction == "positive":
        # Self-promotion: discount hard, but never to zero. A company announcing a
        # contract really may have won it; it just may also have chosen the framing.
        factor = 1.0 - 0.75 * captured
    else:
        factor = 1.0 - 0.45 * captured
    return round(min(1.0, base * factor), 4)


def describe_bias(publisher: Publisher) -> str:
    """One-line, plain-language summary of the tag set, for the UI."""
    if not publisher.assessed:
        return "no assessment on file"
    if not publisher.biases:
        return "no recorded lean or structural bias"
    return ", ".join(tag.replace("_", " ") for tag in publisher.biases)
