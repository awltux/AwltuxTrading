"""Configuration: secrets from the environment, tunables from ``config.yaml``.

Two clearly separated sources:

* :class:`EnvSettings` -- deployment-specific values and **secrets**, read from
  the environment (and a local ``.env``). Never logged, never committed.
* :class:`YamlConfig` -- analysis/decision tunables, read from
  ``config/config.yaml``. Safe to commit and to expose in the Settings UI.

:func:`get_settings` returns both, bound together with derived paths.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

# --------------------------------------------------------------------------- #
# secrets + deployment (environment)
# --------------------------------------------------------------------------- #


class EnvSettings(BaseSettings):
    """Deployment configuration. Values come from ``AWLTUX_*`` env vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AWLTUX_",
        extra="ignore",
        case_sensitive=False,
    )

    # runtime
    data_dir: Path = Path("./data")
    config_file: Path = Path("./config/config.yaml")
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8080
    #: Restrict outbound connections to IPv4.
    #:
    #: Provider API keys can be IP-restricted, and a dual-stack machine presents a
    #: *different* address depending on which family the connection happens to use
    #: -- so allowlisting an IPv4 address is useless if the client then connects
    #: over IPv6. IPv6 privacy extensions also rotate the address, making an IPv6
    #: allowlist fragile. Pinning to IPv4 makes the address a key sees predictable.
    force_ipv4: bool = False
    #: Whether the background scheduler runs in this process.
    #:
    #: On by default, and it must stay on in every deployment. It exists so a test
    #: client can build the real application without also starting a job runner
    #: against the test database: a background job writes `ingest_run` rows, which
    #: made page-count assertions depend on whether a job happened to have fired.
    #: Explicitly off in the test fixture rather than inferred from the environment.
    scheduler_enabled: bool = True
    #: Where the scheduler process is, when it is not this one.
    #:
    #: Set by the container's entrypoint: the scheduler runs as ``awltux schedule`` and the web
    #: tier asks it what is happening over loopback. Unset means "this process owns the
    #: scheduler", which is what a test app, the CLI and a single-process run all want.
    scheduler_control_url: str | None = None
    #: The port ``awltux schedule`` answers on. Loopback only -- it can start jobs that spend
    #: provider and model budget, so it must never be published.
    control_port: int = 8099
    #: How many uvicorn workers serve the web tier.
    #:
    #: More than one is only safe with the scheduler in its own process (`serve` refuses the
    #: combination otherwise), and it is the fix for the concurrency cliff: measured 2026-10-20,
    #: one interpreter serialises concurrent page renders, so seven at once take 6.3 s each and
    #: static files stay linear.
    web_workers: int = 1
    #: How long a shutdown gives running jobs to finish before abandoning them.
    #:
    #: Must stay under the container's `stop_grace_period`, or Docker sends SIGKILL
    #: first and the wait is theatre. This is a safety net for the ordinary restart;
    #: a job known to be long-running should be headed off with `awltux quiet` before
    #: the container is replaced, which stops new work and waits without a deadline.
    #: Zero disables the wait.
    shutdown_drain_seconds: int = 20

    # Trading 212
    t212_api_key: SecretStr | None = None
    t212_api_secret: SecretStr | None = None
    t212_env: Literal["demo", "live"] = "demo"
    allow_live_orders: bool = False

    # DeepSeek
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    #: A name for the key above, so the credit banner can say *which* key a reading
    #: belongs to. Not a credential and not a secret -- the console lets keys be named, and
    #: this is the reader's own label for this one. When it is unset the banner says the
    #: key is unnamed rather than inventing one.
    #:
    #: **The balance cannot be scoped to it, and that is DeepSeek's limit rather than
    #: ours.** ``GET /user/balance`` reports the whole *account* -- every key on it and
    #: every tool using them -- and there is no per-key endpoint. Checked 2026-10-09: the
    #: per-key breakdown exists only in the console's monthly CSV export, which no job can
    #: read. So the name labels the account reading; it does not filter it, and the banner
    #: says so rather than implying the figure is this project's alone.
    deepseek_key_name: str | None = None

    # JEV / TypeSafe
    typesafe_api_key: SecretStr | None = None

    # SEC EDGAR -- the SEC rejects requests without a declared contact.
    sec_user_agent: str = "AwltuxTrading/0.1 (personal research)"

    # Companies House
    companies_house_api_key: SecretStr | None = None

    # Fal.ai -- embeddings, used to group stories covering one event. The credential
    # goes in a header rather than as a bearer token, so it is not interchangeable
    # with the others; see EmbeddingsConfig.auth_scheme.
    #
    # Two names, because the vendor's is different from ours. Every other credential
    # here takes the AWLTUX_ prefix, but Fal's own documentation says to set
    # FAL_KEY, and a key set under the name the vendor documents then silently did
    # nothing. Both work; neither is a typo to be corrected.
    falai_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("AWLTUX_FALAI_KEY", "FAL_KEY"),
    )
    #: A fal key with the scope the **billing** endpoint needs, and nothing else uses it.
    #:
    #: Separate from the key above on purpose, and it is least privilege rather than
    #: tidiness. fal's Platform APIs "may require different API key scopes", and
    #: `GET /account/billing` refuses the model key this project holds with a plain
    #: `403 authorization_error`. Reading a balance is the only thing here that needs a
    #: privileged key, so it is the only thing that gets one -- the key used for
    #: inference stays a model key, which is the credential that is actually spent.
    #:
    #: Optional. Unset is the honest default: the banner then says the balance is not
    #: readable rather than showing a zero, and spending is still counted from
    #: `llm_call`, which needs no provider co-operation at all.
    falai_admin_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("AWLTUX_FAL_ADMIN_KEY", "FAL_ADMIN_KEY"),
    )

    # news providers
    finnhub_api_key: SecretStr | None = None
    marketaux_api_key: SecretStr | None = None
    alphavantage_api_key: SecretStr | None = None
    reddit_client_id: SecretStr | None = None
    reddit_client_secret: SecretStr | None = None

    # ----------------------------------------------------------------- helpers

    @property
    def t212_base_url(self) -> str:
        """Trading 212 base URL for the configured environment.

        Demo and live keys are not interchangeable: a demo key returns 401
        against the live base and vice versa.
        """
        if self.t212_env == "live":
            return "https://live.trading212.com/api/v0"
        return "https://demo.trading212.com/api/v0"

    @property
    def t212_configured(self) -> bool:
        return bool(self.t212_api_key and self.t212_api_secret)

    @property
    def deepseek_configured(self) -> bool:
        return bool(self.deepseek_api_key)

    @property
    def jev_configured(self) -> bool:
        return bool(self.typesafe_api_key)

    def require(self, name: str, key: str) -> str:
        """Return the value of ``key`` or raise a clear, secret-safe error."""
        value = getattr(self, key, None)
        if value is None or value == "":
            raise MissingCredentialError(name, key)
        if isinstance(value, SecretStr):
            return value.get_secret_value()
        return str(value)


class MissingCredentialError(RuntimeError):
    """Raised when a provider is used without its credential configured."""

    def __init__(self, provider: str, env_key: str) -> None:
        self.provider = provider
        self.env_key = env_key
        super().__init__(
            f"{provider} is not configured. Set AWLTUX_{env_key.upper()} in your .env "
            f"(see .env.example)."
        )


# --------------------------------------------------------------------------- #
# tunables (config.yaml)
# --------------------------------------------------------------------------- #


class AppConfig(BaseModel):
    name: str = "AwltuxTrading"
    timezone: str = "Europe/London"
    require_resolved_mapping: bool = True
    #: How strict the dashboard's "Needs attention" filter is, from 1 to 3.
    #:
    #: The system is still settling, so what counts as a problem changes as coverage
    #: improves. Rather than edit the rule set each time, the reasons are graded and
    #: this picks the rung; raising it is the only change needed to make the filter
    #: stricter. The ladder is cumulative -- level N means levels 1..N.
    #:
    #: * **1 -- the figures we hold are wrong or incomplete.** The accounting equation
    #:   does not balance, the latest annual period is missing revenue or total assets,
    #:   is more than 18 months old, has no provenance, or a job has recorded a failure
    #:   for this instrument. Measured on the live universe, 2026-10-07: **25 of 500**.
    #: * **2 -- and we cannot obtain the accounts at all.** A US-listed instrument with
    #:   no SEC CIK, or an LSE one with no Companies House number: no amount of waiting
    #:   produces its accounts. Takes it to about **190 of 500**.
    #: * **3 -- and we have not finished covering it.** No accounts fetched yet, or
    #:   documents held that nothing has parsed. This is the honest long-run test and
    #:   about **90% of the table** while the extractor is unwired, which is why it is
    #:   not the default: a filter that selects almost everything discriminates nothing.
    attention_level: int = Field(default=1, ge=1, le=3)
    #: Balance in USD below which a provider is announced on every page.
    #:
    #: A floor rather than "notify me when it hits zero", because the useful warning comes
    #: while there is still time to top up: at zero the decision engine has already
    #: fallen back to the deterministic rules and the next job has already failed. Set to
    #: ``0`` to announce only a provider that says it cannot pay.
    balance_warn_below_usd: float = Field(default=5.0, ge=0.0)


class UniverseConfig(BaseModel):
    """How the analysed universe is seeded, and what counts as investable.

    ``size`` is an **initialisation** value, not a cap -- it seeds the universe the first
    time it is populated and is ignored afterwards, because membership is manual from then
    on. See ``ingest.universe.refresh_universe`` and `config.yaml`.
    """

    size: int = 500
    exchanges: list[str] = Field(default_factory=lambda: ["LSE", "NASDAQ", "NYSE"])
    min_daily_turnover_gbp: float = 250_000
    instrument_types: list[str] = Field(default_factory=lambda: ["STOCK"])


class ScheduleConfig(BaseModel):
    """How often each job runs, in seconds.

    **Every job is daily, asked for directly on 2026-10-23**: *"All the jobs can be downgraded
    to 1d trigger rate."* One cycle a day, run in dependency order by the scheduler (see
    `scheduler/service.py`), so a job whose input is produced by another runs after it.

    The floor is still an hour -- nothing here needs finer resolution, the providers are free
    tiers with rate limits, and the daily bars the model reasons about change once a day -- but
    `test_scheduler` now also asserts the product rule over the registry: nothing scheduled runs
    more often than once a day.

    **A day's ration is a run's ration now.** `decision_rotation_per_day` and
    `fundamentals_rotation_per_day` are named per day because that is what they are; with one
    run a day they are also what that run does, so a decision run still covers 500 names (about
    two hours) rather than a ninth of them.
    """

    #: When the daily cycle starts, as ``HH:MM`` in ``app.timezone``.
    #:
    #: Every job is daily, and this is the one time of day they are all anchored to: a job with
    #: no dependencies runs at this instant, its dependents ten minutes later per level of the
    #: graph (see `scheduler/service.py`). The Operations page can override it, and the override
    #: is stored in `app_setting` rather than here -- this value is the default the page starts
    #: from (`awltux/schedule_time.py`).
    #:
    #: A time of day rather than an interval, because "run the day's pipeline at six in the
    #: morning" is what a reader means and "every 86400 seconds from whenever the process
    #: started" is what the interval could express -- the second drifts with every restart.
    daily_at: str = "06:00"

    t212_instruments: int = 86_400
    #: Trading 212's order history. One page of orders a day is enough: an incremental run
    #: reads one page and stops at the newest order it already holds.
    t212_orders: int = 86_400
    t212_account: int = 86_400
    #: How often every *held* instrument is put through the full refresh sequence.
    #:
    #: One instrument's refresh costs about 100 seconds and a handful of model calls, so this
    #: is the setting that decides what keeping a position current costs. Daily now, like
    #: everything else; the instrument page's own Refresh button is what exists for "now".
    held_refresh: int = 86_400
    prices_intraday: int = 86_400
    prices_eod: int = 86_400
    #: How often each sector's price index is rebuilt. Daily, and declared separately from
    #: `prices_eod` so the two can be moved apart: the index is derived from the end-of-day
    #: bars, so running it more often than they arrive just rewrites the same line.
    sector_index: int = 86_400
    #: Instruments the end-of-day price job asks for in one run. ``0`` prices the
    #: whole universe, which is what a daily job on 500 names can afford.
    #:
    #: The cap exists so a deployment on a tighter rate limit can ration, and it is
    #: only safe to set because the job asks for the **most in need first** --
    #: never-priced instruments, then the least recently covered. Without that
    #: ordering a cap would starve the tail of the universe permanently.
    price_eod_max_per_run: int = 0
    #: Instruments the symbol-resolution job looks up in one run. Each one costs a
    #: provider search and the search endpoint is rate-limited like everything else,
    #: so a backlog drains over several runs rather than in one burst.
    symbol_resolution_per_run: int = 120
    quotes_held: int = 86_400
    fundamentals_rotation_per_day: int = 70
    #: The fundamentals sweep's own cadence, declared beside the job that reads it. It used
    #: to be a hardcoded hour in the registry because the rotation was spread across the day;
    #: with one run a day there is nothing to spread.
    fundamentals: int = 86_400
    #: Instruments the decision job decides in one run, which is now one day.
    #:
    #: Measured 2026-10-07: a decision takes about 4.1 per minute, so 500 names is a
    #: **two-hour** run. That is the longest single job in the schedule, and it is why the
    #: dispatcher waits rather than skips: everything downstream of it is due while it runs.
    decision_rotation_per_day: int = 500
    edgar_submissions: int = 86_400
    edgar_atom_events: int = 86_400
    companies_house: int = 86_400
    #: The instrument news poll, daily, and the four jobs that read what it stores.
    #:
    #: It was hourly, and hourly was wrong twice over: a walk of the universe spends the
    #: provider's whole daily allowance, so most runs could not fetch anything, and a walk
    #: that *can* fetch takes longer than an hour. `config/config.yaml` carries the
    #: measurement; the paragraph here is the one thing that is not in that file -- the
    #: rations downstream are per *run* and so are now per day.
    news_rss: int = 86_400
    #: The sector poll is eleven feeds rather than one per instrument, and it does not read
    #: the universe or the instrument poll's output. Daily like everything else; it was left
    #: hourly until 2026-10-23 because it is cheap, which is a reason to run it, not a reason
    #: for a cadence of its own.
    news_sectors: int = 86_400
    news_finnhub: int = 86_400
    news_marketaux: int = 86_400
    news_gdelt: int = 86_400
    news_analysis: int = 86_400
    news_relevance: int = 86_400
    news_embeddings: int = 86_400
    symbol_resolution: int = 86_400
    #: The Treasury publishes once per business day, so a daily read is the publication rate.
    macro_rates: int = 86_400
    sentiment_aggregate: int = 86_400
    valuation: int = 86_400
    decision: int = 86_400
    calibration: int = 86_400
    #: How often expired rows are pruned. Daily: it is a `DELETE` over two tables and the
    #: retention it enforces is counted in days and weeks.
    retention: int = 86_400
    #: How often the provider balances are refreshed. Daily now, so the warning it exists for
    #: can arrive most of a day after the spend -- the balance strip's age is printed beside
    #: the figure, and the red badge marks a breach whenever it is read.
    provider_balance: int = 86_400

    @field_validator("daily_at")
    @classmethod
    def _daily_at_is_a_time(cls, value: str) -> str:
        """Refuse anything but a 24-hour time, at load rather than at the first trigger.

        One rule, shared with the Operations form and the stored override -- see
        `awltux/schedule_time.py`. A bad value in the file should stop the process from
        starting with a schedule nobody can reason about, which a Pydantic error does.
        """
        from awltux import schedule_time

        return schedule_time.normalise(value)


class BudgetRule(BaseModel):
    """One provider's request allowance, as a count per period.

    ``reset`` says **what the period is anchored to**, and for a daily quota that is
    not a detail. A rule of "100 requests per 86400s" counted from whenever this process
    first called the provider is a *rolling* day, and a rolling day does not line up with
    the provider's own: 100 requests spent between 17:00 and 19:00 on Monday and another
    100 after the window turns over at 17:00 on Tuesday is up to 200 inside Tuesday by
    their calendar, which is how a local budget of exactly the published limit still
    earns "you have reached your daily request limit".

    ``utc_day`` anchors the window to midnight UTC, which is what every one of these
    quotas is documented against. The counter then resets when *they* reset it.

    ``min_interval_seconds`` is the second limit several of these providers keep and
    nobody writes down: Marketaux answers "too many requests in the past 60 seconds"
    alongside its daily cap, and the honest way to respect an unnumbered burst limiter
    is to space the calls out. Zero means no spacing, which is right for a provider whose
    window already implies it (`requests: 1` per window *is* a spacing).
    """

    requests: int
    window_seconds: float
    reset: Literal["window", "utc_day"] = "window"
    min_interval_seconds: float = 0.0


class ValuationConfig(BaseModel):
    #: Where the risk-free rate comes from.
    #:
    #: ``market`` reads the US Treasury's published par yield curve. ``config``
    #: keeps the constant below and is the escape hatch for an offline deployment.
    #: The constant is the fallback either way: a failed observation must not stop
    #: the universe being valued.
    risk_free_rate_source: Literal["market", "config"] = "market"
    #: Which point on the curve anchors the discount rate.
    risk_free_rate_tenor: str = "10 Yr"
    #: Fallback only, when no market rate has been observed. It anchors the CAPM
    #: cost of equity, so it decides every discounted fair value -- a stale value
    #: here is silently repriced across the whole universe.
    risk_free_rate: float = 0.042
    equity_risk_premium: float = 0.055
    default_beta: float = 1.0
    terminal_growth_cap: float = 0.025
    forecast_years: int = 7
    growth_fade_to_terminal: bool = True
    method_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "dcf": 0.35,
            "epv": 0.20,
            "residual_income": 0.15,
            "multiples": 0.20,
            "dividend_discount": 0.10,
            "graham": 0.00,
        }
    )
    scenario_spread: float = 0.25
    min_applicable_methods: int = 2
    max_method_dispersion: float = 0.60
    peer_group_min_size: int = 4


class LLMConfig(BaseModel):
    model_bulk: str = "deepseek-flash"
    model_deep: str = "deepseek-v4-pro"
    max_output_tokens: int = 8_000
    temperature: float = 0.0
    enable_prefix_cache_layout: bool = True
    monthly_budget_usd: float = 40.0
    request_timeout_seconds: float = 180.0
    max_retries: int = 3

    # price per 1M tokens (USD), peak. Used for cost accounting only.
    prices: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "deepseek-flash": {"input": 0.30, "input_cached": 0.006, "output": 1.20},
            "deepseek-v4-pro": {"input": 1.32, "input_cached": 0.044, "output": 3.96},
        }
    )


class DecisionConfig(BaseModel):
    engine_priority: list[str] = Field(default_factory=lambda: ["jev", "deepseek", "offline"])
    min_engine_for_suggestion: Literal["jev", "deepseek", "offline"] = "offline"
    jev_model: str = "jev-latest"
    jev_max_state_tokens: int = 28_000
    warn_if_fallback: bool = True

    #: Output budget for one fallback decision, in tokens.
    #:
    #: Measured, not guessed. Over the first 18 fallback decisions the *minimum*
    #: output was 2,727 tokens and the median about 3,500, so the 4,000 that used
    #: to be hardcoded here left almost no headroom: four of the eighteen hit the
    #: ceiling exactly and those instruments fell back to the deterministic engine,
    #: losing the model's judgement for a reason that was entirely about length.
    #: One decision in four. The retry uses ``llm.max_output_tokens`` instead.
    deepseek_max_tokens: int = 6_000


class HorizonDefinition(BaseModel):
    """How a horizon is presented, and what it means.

    The indicative holding period is configuration rather than model output. A
    language model asked for a holding period will invent a plausible number; a
    documented range the user can edit is honest and checkable.
    """

    label: str
    guidance: str
    description: str = ""


class HorizonsConfig(BaseModel):
    long_term: HorizonDefinition = HorizonDefinition(
        label="Long term",
        guidance="12-36 months",
        description=(
            "Driven by valuation, business quality and balance-sheet strength."
        ),
    )
    short_term: HorizonDefinition = HorizonDefinition(
        label="Short term",
        guidance="5-20 trading days",
        description=(
            "Driven by trend, momentum, volume and the direction of news. Not day trading."
        ),
    )


class CompositeConfig(BaseModel):
    long_term_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "margin_of_safety": 0.34,
            "valuation_verdict": 0.20,
            "business_quality": 0.16,
            "balance_sheet_risk": 0.12,
            "earnings_trend": 0.08,
            "news_materiality": 0.06,
            "sentiment_regime": 0.04,
        }
    )
    short_term_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "short_term_setup": 0.35,
            "short_term_drawdown_risk": 0.20,
            "news_materiality": 0.20,
            "valuation_verdict": 0.15,
            "sentiment_regime": 0.10,
        }
    )

    def weights_for(self, horizon: str) -> dict[str, float]:
        if horizon == "short_term":
            return self.short_term_weights
        return self.long_term_weights


class HorizonGateConfig(BaseModel):
    """What a given horizon requires before a call becomes actionable.

    The distinction that matters: a tactical call does not need a fresh
    discounted cash flow, but it does need current bars and real momentum
    evidence. Applying the long-term requirements to it would refuse good tactical
    calls for an irrelevant reason, and relaxing the long-term ones would let
    stale valuations through.
    """

    max_price_age_seconds: int = 129_600
    max_valuation_age_seconds: int = 604_800
    max_filing_age_seconds: int = 34_560_000
    require_valuation: bool = True
    require_filing: bool = False
    min_setup_score: float | None = None


class GateConfig(BaseModel):
    min_confidence: float = 0.70
    min_top_probability: float = 0.60
    min_confidence_fallback_engine: float = 0.80
    #: The rule engine reports no probabilities; its confidence describes evidence
    #: quality, so it is thresholded on its own scale.
    min_confidence_rule_engine: float = 0.55
    max_positions: int = 25
    max_weight_per_name: float = 0.08
    max_weight_per_sector: float = 0.30
    min_daily_turnover_gbp: float = 250_000
    long_term: HorizonGateConfig = HorizonGateConfig()
    short_term: HorizonGateConfig = HorizonGateConfig(
        max_price_age_seconds=432_000,
        require_valuation=False,
        min_setup_score=2,
    )

    def for_horizon(self, horizon: str) -> HorizonGateConfig:
        return self.short_term if horizon == "short_term" else self.long_term


class PrefilterConfig(BaseModel):
    min_title_chars: int = 25
    drop_patterns: list[str] = Field(default_factory=list)
    require_any_ticker_mention: bool = False


class ScepticismConfig(BaseModel):
    """How hard news is interrogated, and how much it is allowed to matter.

    Defaults are deliberately suspicious. The failure mode being engineered
    against is not "missed a story" -- it is "acted on a story that was one
    company's press release, repeated".
    """

    #: Appraise during ingest at all. Off leaves headlines classified but unweighted.
    enabled: bool = True
    #: Materiality at or above which a story is always appraised.
    attention_materiality: Literal[
        "none", "mild", "moderate", "material", "critical"
    ] = "material"
    #: Rhetoric score at or above which the *framing* is itself the reason to look.
    #: Matches ``rhetoric.SUSPICION_THRESHOLD``; kept in config so a deployment can
    #: raise it if the flags prove too eager.
    rhetoric_attention_threshold: float = 0.30
    #: How far either side of a story to look for other outlets carrying it.
    corroboration_window_hours: int = 72
    #: Recent items scanned to find corroboration for any one story.
    corroboration_pool: int = 400
    #: How many model-backed appraisals one run may make.
    max_deep_per_run: int = 40
    #: How many days back a run looks for stories worth appraising.
    lookback_days: int = 14
    #: Re-appraise after this long, so a stale verdict is refreshed.
    refresh_after_days: int = 7
    #: Weight given to an unappraised article's sentiment. Below 1.0 because
    #: "unexamined" must not be worth as much as "examined and found sound".
    unassessed_weight: float = 0.6
    #: Floor on how far an assessed article's sentiment can be shrunk. Non-zero so
    #: a weak story is damped rather than erased: the reader still sees it.
    min_credibility: float = 0.05


class EmbeddingsConfig(BaseModel):
    """Vector embeddings of headlines, used to collapse one event into one entry.

    A story about a profit warning reaches this system five or six times, from
    different outlets, rewritten each time. The existing corroboration layer spots
    near-duplicates by comparing word sets, which catches syndication -- the same
    text pasted everywhere -- and misses the commoner case: the same *event*
    reported in different words.

    Embeddings catch that, because they compare meaning rather than vocabulary.

    **Deliberately provider-agnostic.** ``base_url`` and ``model`` describe any
    OpenAI-compatible embeddings endpoint, which covers a hosted service and a
    local Ollama alike. There is no key requirement: pointing at
    ``http://localhost:11434/v1`` needs none, so the feature is usable without
    signing up for anything. Unset means embeddings are off and the lexical
    comparison is used, exactly as before.
    """

    #: An OpenAI-compatible base URL, e.g. ``https://api.openai.com/v1`` or a local
    #: ``http://host.docker.internal:11434/v1``. Empty disables the feature.
    base_url: str = ""
    model: str = "text-embedding-3-small"
    api_key: SecretStr | None = None
    #: The authorization scheme, and it is not always ``Bearer``.
    #:
    #: Fal.ai wants ``Authorization: Key <key>`` with the OpenAI client's own
    #: ``api_key`` set to a placeholder -- so a client that assumes ``Bearer`` gets a
    #: 401 against a perfectly valid key, which reads as "the key is wrong" rather
    #: than "the header is wrong".
    auth_scheme: str = "Bearer"
    #: Headlines embedded per request. Endpoints vary; this is conservative.
    batch_size: int = 64
    #: Items embedded per job run. The backfill is a one-off, so it is rationed like
    #: every other paid call.
    max_per_run: int = 1_000
    #: Cosine similarity at or above which two stories are the same event.
    #:
    #: 0.86 is deliberately high. The cost of joining two different events is a
    #: reader being told one thing happened when two did; the cost of missing a
    #: join is two entries instead of one. Those are not symmetric, so the threshold
    #: errs towards keeping them apart, and every cluster shows its members so a
    #: wrong join is visible rather than hidden.
    same_event_threshold: float = 0.86

    @property
    def configured(self) -> bool:
        return bool(self.base_url.strip())

    def credential(self, env: Any) -> str | None:
        """The key to send, from whichever place it was supplied.

        The YAML field wins where it is set, because a deployment that wrote it
        there meant it; otherwise the environment is the documented path. Both
        ``FAL_KEY`` (the name the vendor documents, and the one `.env` uses) and
        ``AWLTUX_FALAI_KEY`` set the same field, so either works.
        """
        if self.api_key is not None:
            return self.api_key.get_secret_value()
        key = getattr(env, "falai_key", None)
        return key.get_secret_value() if key is not None else None


class NewsConfig(BaseModel):
    ticker_min_materiality: Literal[
        "none", "mild", "moderate", "material", "critical"
    ] = "mild"
    max_items_per_feed_poll: int = 50
    #: How many stories the ``news_relevance`` job may classify in one run.
    #:
    #: Relevance is settled at ingest for anything new, so this only ever drains a
    #: backlog -- items stored before the classifier was configured, or before the
    #: rule existed. Bounded for the same reason every other paid job is: a large
    #: backlog should cost several ordinary runs, not one month's budget.
    relevance_backfill_per_run: int = 200

    #: Output budget for one headline classification, in tokens.
    #:
    #: **This has to cover reasoning the API does not return.** Measured over 2,474
    #: classification calls: the mean output was 235 tokens while the *content* was
    #: about 120, and 165 calls (6.7%) burned the whole 500-token budget and
    #: returned an empty body -- 500 tokens spent, nothing to parse. The tokens went
    #: to reasoning, which ``message.content`` does not carry, so a budget sized to
    #: the answer alone is a budget sized to the wrong thing.
    #:
    #: Raising it costs almost nothing: ``max_tokens`` is a cap, not a reservation,
    #: and the ordinary call still generates what it always did. What disappears is
    #: the second request for the 6.7% that ran out of room.
    classify_max_tokens: int = 2_000
    prefilter: PrefilterConfig = Field(default_factory=PrefilterConfig)
    scepticism: ScepticismConfig = Field(default_factory=ScepticismConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)


class ReportsConfig(BaseModel):
    """How much of the shareholders'-report history to keep.

    Separate from the rest of the filing configuration because it is the one place
    where "how far back" is a deliberate cost decision rather than a correctness
    one: each year is a document per filer, and the SEC's rate limit is what bounds
    a run.
    """

    #: Fiscal years of annual reports to hold per instrument.
    #:
    #: **Two for now, and it is a limitation rather than a target.** The accounting
    #: markers worth the most are about persistence, and
    #: :data:`awltux.analysis.accounting.MIN_PERIODS_FOR_TREND` needs three periods
    #: before it will call something a trend. Two buys a year-on-year comparison and
    #: nothing more. The request was for six; raising this is a config change and the
    #: markers already say when they have too few periods to make a claim.
    years: int = 2
    #: Documents downloaded per run. A document can be several megabytes and the SEC
    #: asks for no more than ten requests a second, so a backlog drains over runs.
    per_run: int = 60


class ResearchConfig(BaseModel):
    """Deep-dive research: one report per explicit request, never on a schedule.

    **Nothing here runs unattended.** A report costs a full pipeline refresh plus one deep
    model call over the held annual reports, so it is triggered by a reader pressing a
    button and by nothing else. There is no interval, no coverage probe and no
    ``run_on_start``, and the defaults below are the bounds on a single run.
    """

    enabled: bool = True

    #: Skip the refresh phase when a successful refresh of the instrument finished this
    #: recently, recorded on the report so the reader knows.
    #:
    #: The refresh is the long half -- thirteen steps, minutes, provider and model spend --
    #: and pressing Research twice in a quarter of an hour would otherwise re-run the whole
    #: pipeline for data that has not changed. Zero re-runs it every time.
    refresh_within_minutes: int = 30

    #: The news window the digest is drawn from, how many stories it carries, and how far
    #: down the priority order to look before taking the top.
    #:
    #: ``window`` is a *scan* bound, not a display one: priority is computed in Python
    #: (materiality x credibility x recency), so the ranking has to score a bounded recent
    #: set and sort it -- the same reasoning `routes/news.py::_ranked` records for the
    #: ticker. Measured 2026-10-09, 10,739 stories arrive in 30 days, so 300 is a few days
    #: of corpus and the top dozen is always well inside it.
    news_digest_days: int = 30
    news_digest_limit: int = 12
    news_digest_window: int = 300

    #: Held annual reports fed to the model, bounded per document and in total.
    #:
    #: The per-document cap is larger than `llm.extractors`' 400,000 because a research
    #: read wants the whole report and truncation keeps the head and the tail -- which is
    #: where the primary statements are. The total is what bounds the bill: 400,000
    #: characters is about 118,000 input tokens.
    max_documents: int = 3
    max_document_chars: int = 200_000
    max_total_document_chars: int = 400_000

    #: The deep model's context window, and the tokens held back from it for the answer and
    #: the message wrapper.
    #:
    #: Nothing else in this application has to know a window size, because every other
    #: request is orders of magnitude smaller. A deep-dive is not: measured 2026-10-09, the
    #: evidence for MSFT -- two 10-Ks, the digest, the stored figures and the last decision
    #: -- came to 410,826 characters, about **120,800 tokens**, against a 128,000-token
    #: window and a 16,000-token answer. So the totals above are not the whole bound: the
    #: evidence is trimmed to fit this window and the report says what was dropped, rather
    #: than the request being refused *after* the refresh has been paid for.
    #:
    #: ``reserve_tokens`` covers the *editable* prompt as well as the message wrapper, and it
    #: is a fixed number for a text a reader can change: the template plus the scope and the
    #: news URLs measures about 2,700 tokens. The trimmer cannot see the reader's edits, so
    #: somebody who pastes a very long prompt can still exceed the window; that is stated
    #: rather than guarded, because refusing an edit is worse than a provider error that says
    #: what went wrong.
    context_tokens: int = 128_000
    reserve_tokens: int = 4_000

    #: Output budget for one report. Above `llm.max_output_tokens` because a research
    #: report is longer than any classification or extraction this system asks for.
    max_output_tokens: int = 16_000

    #: Reports listed on the page, and when a report still marked `running` is shown as
    #: stale rather than as work in progress.
    list_limit: int = 25
    stale_minutes: int = 180

    #: The model to use. ``None`` means `llm.model_deep`, which is the point of the
    #: feature: this is the one task that asks for the deep model deliberately.
    model: str | None = None

    @model_validator(mode="after")
    def _window_has_room_for_an_answer(self) -> ResearchConfig:
        """A window with no room for the answer is a config error, not a small prompt.

        The evidence is trimmed to ``context_tokens - max_output_tokens - reserve_tokens``, so
        an output budget larger than the window leaves a negative one -- and the trimmer, asked
        to fit nothing, would drop every input and send the model an empty question. That is a
        mistake in the YAML and it is refused where it is made rather than producing a report
        that says nothing for the price of a full run.
        """
        room = self.context_tokens - self.max_output_tokens - self.reserve_tokens
        if room <= 0:
            raise ValueError(
                f"research.context_tokens ({self.context_tokens}) must exceed "
                f"max_output_tokens ({self.max_output_tokens}) + reserve_tokens "
                f"({self.reserve_tokens}); the evidence would otherwise be trimmed to "
                f"{room} tokens"
            )
        return self


class RetentionConfig(BaseModel):
    quote_days: int = 30
    news_days: int = 730
    raw_payload_days: int = 180
    llm_call_days: int = 365
    #: How long a provider balance reading is kept. The spend estimate differences a
    #: 30-day window, so this is far longer than anything reads -- deliberately: the series
    #: is the only record of what an account held on a given day, it costs about 48 rows a
    #: day, and a year of it is a chart nobody has asked for yet. Shortening this would
    #: delete history that cannot be re-fetched, which is not true of the quote table.
    balance_days: int = 400


class YamlConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    budgets: dict[str, BudgetRule] = Field(default_factory=dict)
    horizons: HorizonsConfig = Field(default_factory=HorizonsConfig)
    valuation: ValuationConfig = Field(default_factory=ValuationConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    decision: DecisionConfig = Field(default_factory=DecisionConfig)
    composite: CompositeConfig = Field(default_factory=CompositeConfig)
    gate: GateConfig = Field(default_factory=GateConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)


# --------------------------------------------------------------------------- #
# aggregate
# --------------------------------------------------------------------------- #


class Settings(BaseModel):
    """The fully resolved configuration used throughout the application."""

    model_config = {"arbitrary_types_allowed": True}

    env: EnvSettings
    yaml: YamlConfig

    # ------------------------------------------------------------- passthroughs
    @property
    def app(self) -> AppConfig:
        return self.yaml.app

    @property
    def universe(self) -> UniverseConfig:
        return self.yaml.universe

    @property
    def schedule(self) -> ScheduleConfig:
        return self.yaml.schedule

    @property
    def budget(self) -> dict[str, BudgetRule]:
        return self.yaml.budgets

    @property
    def valuation(self) -> ValuationConfig:
        return self.yaml.valuation

    @property
    def horizons(self) -> HorizonsConfig:
        return self.yaml.horizons

    @property
    def llm(self) -> LLMConfig:
        return self.yaml.llm

    @property
    def decision(self) -> DecisionConfig:
        return self.yaml.decision

    @property
    def composite(self) -> CompositeConfig:
        return self.yaml.composite

    @property
    def gate(self) -> GateConfig:
        return self.yaml.gate

    @property
    def news(self) -> NewsConfig:
        return self.yaml.news

    @property
    def reports(self) -> ReportsConfig:
        return self.yaml.reports

    @property
    def research(self) -> ResearchConfig:
        return self.yaml.research

    @property
    def retention(self) -> RetentionConfig:
        return self.yaml.retention

    # ------------------------------------------------------------------- paths
    @property
    def data_dir(self) -> Path:
        return self.env.data_dir

    @property
    def db_path(self) -> Path:
        return self.data_dir / "awltux.db"

    @property
    def database_url(self) -> str:
        return f"sqlite+pysqlite:///{self.db_path.as_posix()}"

    @property
    def raw_dir(self) -> Path:
        """Archive of raw provider payloads, so evidence survives a re-parse."""
        return self.data_dir / "raw"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def research_dir(self) -> Path:
        """Where generated deep-dive reports are written.

        Not `raw/`: that directory is the archive of what *providers* said, and these are
        documents this system wrote. Kept inside the data volume, which is also what keeps
        them out of git -- `docs/research/` is a different thing and is asserted to be
        tracked (`tests/test_repo_hygiene.py`).
        """
        return self.data_dir / "research"

    @property
    def joblog_dir(self) -> Path:
        """Where the most recent progress log of each job is kept.

        One file per job, truncated at the start of every run, so this directory is
        bounded by the registry rather than by time and needs no pruning.
        """
        return self.data_dir / "joblogs"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.raw_dir, self.cache_dir, self.joblog_dir):
            path.mkdir(parents=True, exist_ok=True)
        # Created here as well as by the writer, so a fresh volume has somewhere for a
        # report to land rather than failing on the first run of the feature.
        self.research_dir.mkdir(parents=True, exist_ok=True)


def load_yaml_config(path: Path) -> YamlConfig:
    """Load the tunables file, tolerating a missing or partial file."""
    if not path.exists():
        return YamlConfig()
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return YamlConfig.model_validate(raw)


def build_settings(env: EnvSettings | None = None) -> Settings:
    env = env or EnvSettings()
    return Settings(env=env, yaml=load_yaml_config(env.config_file))


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Use :func:`reload_settings` in tests."""
    settings = build_settings()
    settings.ensure_dirs()
    return settings


def reload_settings() -> Settings:
    """Drop the cached settings and rebuild (used by tests and the CLI)."""
    get_settings.cache_clear()
    return get_settings()


def redacted_dump(settings: Settings) -> dict[str, Any]:
    """A log-safe view of the configuration: secrets become presence flags."""
    env = settings.env
    return {
        "data_dir": str(env.data_dir),
        "t212_env": env.t212_env,
        "t212_configured": env.t212_configured,
        "deepseek_configured": env.deepseek_configured,
        # A label, not a credential, so it is printed rather than redacted -- and it is
        # the one thing that says *which* DeepSeek key this installation is spending.
        # `null` means the key has not been named; the balance it reads is the account's
        # either way.
        "deepseek_key_name": env.deepseek_key_name or None,
        "jev_configured": env.jev_configured,
        "sec_user_agent_set": bool(env.sec_user_agent),
        "companies_house_configured": bool(env.companies_house_api_key),
        "finnhub_configured": bool(env.finnhub_api_key),
        "marketaux_configured": bool(env.marketaux_api_key),
        "falai_configured": bool(env.falai_key),
        "embeddings_configured": settings.news.embeddings.configured,
        "engine_priority": settings.decision.engine_priority,
        "universe_initial_size": settings.universe.size,
    }
