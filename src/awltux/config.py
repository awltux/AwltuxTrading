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
from pydantic import BaseModel, Field, SecretStr
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

    # Trading 212
    t212_api_key: SecretStr | None = None
    t212_api_secret: SecretStr | None = None
    t212_env: Literal["demo", "live"] = "demo"
    allow_live_orders: bool = False

    # DeepSeek
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"

    # JEV / TypeSafe
    typesafe_api_key: SecretStr | None = None

    # SEC EDGAR -- the SEC rejects requests without a declared contact.
    sec_user_agent: str = "AwltuxTrading/0.1 (personal research)"

    # Companies House
    companies_house_api_key: SecretStr | None = None

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


class UniverseConfig(BaseModel):
    size: int = 500
    exchanges: list[str] = Field(default_factory=lambda: ["LSE", "NASDAQ", "NYSE"])
    min_daily_turnover_gbp: float = 250_000
    instrument_types: list[str] = Field(default_factory=lambda: ["STOCK"])


class ScheduleConfig(BaseModel):
    t212_instruments: int = 86_400
    t212_account: int = 300
    prices_intraday: int = 900
    prices_eod: int = 86_400
    quotes_held: int = 300
    fundamentals_rotation_per_day: int = 70
    edgar_submissions: int = 3_600
    edgar_atom_events: int = 45
    companies_house: int = 900
    news_rss: int = 300
    news_finnhub: int = 1_200
    news_marketaux: int = 1_800
    news_gdelt: int = 900
    news_analysis: int = 1_800
    sentiment_aggregate: int = 3_600
    valuation: int = 86_400
    decision: int = 86_400
    calibration: int = 86_400
    retention: int = 604_800


class BudgetRule(BaseModel):
    requests: int
    window_seconds: float


class ValuationConfig(BaseModel):
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
    monthly_budget_usd: float = 25.0
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


class NewsConfig(BaseModel):
    ticker_min_materiality: Literal[
        "none", "mild", "moderate", "material", "critical"
    ] = "mild"
    dedupe_window_hours: int = 72
    max_items_per_feed_poll: int = 50
    prefilter: PrefilterConfig = Field(default_factory=PrefilterConfig)
    scepticism: ScepticismConfig = Field(default_factory=ScepticismConfig)


class RetentionConfig(BaseModel):
    quote_days: int = 30
    news_days: int = 730
    raw_payload_days: int = 180
    llm_call_days: int = 365


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

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.raw_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)


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
        "jev_configured": env.jev_configured,
        "sec_user_agent_set": bool(env.sec_user_agent),
        "companies_house_configured": bool(env.companies_house_api_key),
        "finnhub_configured": bool(env.finnhub_api_key),
        "marketaux_configured": bool(env.marketaux_api_key),
        "engine_priority": settings.decision.engine_priority,
        "universe_size": settings.universe.size,
    }
