"""Shared pydantic v2 models for TrueOffer.

Every agent's input/output contract lives here, plus the PipelineState that the
orchestrator passes between stages and the progress events streamed to the browser.

Privacy: raw offer content (file bytes / pasted text) is marked ``exclude=True`` and
``repr=False`` so it can never be serialized into a response, an event, or a log line.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

NOT_STATED = "not stated in offer"

OfferId = Literal["A", "B", "C"]
Engine = Literal["claude", "local", "deterministic"]
T = TypeVar("T")


# ---------------------------------------------------------------------------
# Generic building blocks
# ---------------------------------------------------------------------------


class Extracted(BaseModel, Generic[T]):
    """A single field pulled from an offer letter.

    ``status`` is ``"stated"`` when the letter says it explicitly, ``"not_stated"``
    when it doesn't (value is None and the UI shows "not stated in offer"),
    ``"derived"`` when computed from stated facts (e.g. hourly x 2,080), and
    ``"user_entered"`` when it came from the manual form or a user override.
    """

    value: Optional[T] = None
    status: Literal["stated", "not_stated", "derived", "user_entered"] = "not_stated"
    evidence: Optional[str] = Field(
        default=None, description="Short quote (<=120 chars) from the letter supporting the value."
    )
    note: Optional[str] = None

    @property
    def known(self) -> bool:
        """True when the value can be used in calculations."""
        return self.value is not None and self.status != "not_stated"

    def display(self) -> str:
        """Human-readable value or the canonical not-stated label."""
        return NOT_STATED if not self.known else str(self.value)


class SourceRef(BaseModel):
    """Citation for a number: which dataset, which year, and how it was used."""

    name: str
    data_year: str
    url: Optional[str] = None
    real: bool = True  # False => SIMULATED data


class AgentOutputBase(BaseModel):
    """Fields every agent returns so the UI can show 'under the hood' details."""

    agent: str
    engine: Engine = "deterministic"
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    log: list[str] = Field(default_factory=list, description="Short 'what I did' steps.")
    warnings: list[str] = Field(default_factory=list)
    elapsed_ms: int = 0


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------


class LifestylePriorities(BaseModel):
    """Importance 0 (don't care) to 5 (very important) for each lifestyle dimension."""

    outdoors: int = Field(3, ge=0, le=5)
    nightlife: int = Field(3, ge=0, le=5)
    weather: int = Field(3, ge=0, le=5)
    commute: int = Field(3, ge=0, le=5)
    family: int = Field(3, ge=0, le=5)
    cost_of_fun: int = Field(3, ge=0, le=5)


class DecisionWeights(BaseModel):
    """Relative weight of each scorecard component (normalized at scoring time)."""

    money_left_over: float = Field(40, ge=0)
    total_comp: float = Field(20, ge=0)
    lifestyle: float = Field(25, ge=0)
    market_position: float = Field(10, ge=0)
    culture: float = Field(5, ge=0)


class UserProfile(BaseModel):
    """Personal inputs. Every field is an assumption the user can change."""

    student_loan_monthly: float = Field(0, ge=0, le=20000)
    housing: Literal["alone", "roommates"] = "alone"
    roommates: int = Field(1, ge=1, le=3, description="Number of roommates when housing='roommates'.")
    contribution_401k_pct: float = Field(6, ge=0, le=75)
    home_city: Optional[str] = Field(None, max_length=80, description="'City, ST' for distance to family.")
    remote_city: Optional[str] = Field(
        None, max_length=80, description="Where you'd live for a fully-remote offer ('City, ST')."
    )
    extras_monthly: float = Field(0, ge=0, le=20000, description="Other fixed monthly costs (car note, pet...).")
    health_premium_monthly: Optional[float] = Field(
        None, ge=0, le=3000, description="Pre-tax employee health premium; None = national average."
    )
    bonus_payout_pct: float = Field(100, ge=0, le=200, description="Expected % of target bonus actually paid.")
    annual_raise_pct: float = Field(3, ge=0, le=25)
    rent_adjust_pct: float = Field(0, ge=-50, le=100, description="Sensitivity: shift all rents by this %.")
    filing_status: Literal["single"] = "single"
    priorities: LifestylePriorities = Field(default_factory=LifestylePriorities)
    weights: DecisionWeights = Field(default_factory=DecisionWeights)


# ---------------------------------------------------------------------------
# Agent 1: Offer Parser
# ---------------------------------------------------------------------------


class MatchTier(BaseModel):
    """Employer matches ``rate`` (1.0 = 100%) of the next ``on_pct`` % of salary you contribute."""

    rate: float = Field(ge=0, le=5)
    on_pct: float = Field(ge=0, le=100)


class Match401k(BaseModel):
    """Employer 401(k) formula: tiered match plus optional non-elective contribution."""

    tiers: list[MatchTier] = Field(default_factory=list)
    nonelective_pct: float = Field(0, ge=0, le=25, description="Employer % of pay regardless of your contribution.")
    annual_cap: Optional[float] = None
    description: str = ""


class EquityGrant(BaseModel):
    """Equity as stated in the offer. ``value_usd`` is the total grant value if stated."""

    value_usd: Optional[float] = None
    vesting_years: Optional[float] = None
    description: str = ""


class OfferFields(BaseModel):
    """Structured fields extracted from one offer letter."""

    company: Extracted[str] = Field(default_factory=Extracted[str])
    job_title: Extracted[str] = Field(default_factory=Extracted[str])
    office_city: Extracted[str] = Field(default_factory=Extracted[str])
    office_state: Extracted[str] = Field(default_factory=Extracted[str])
    base_salary: Extracted[float] = Field(default_factory=Extracted[float], description="Annualized USD.")
    pay_basis: Literal["annual", "hourly", "monthly", "biweekly", "weekly", "unknown"] = "unknown"
    hourly_rate: Extracted[float] = Field(default_factory=Extracted[float])
    hours_per_week: Extracted[float] = Field(default_factory=Extracted[float])
    signing_bonus: Extracted[float] = Field(default_factory=Extracted[float])
    bonus_target_pct: Extracted[float] = Field(default_factory=Extracted[float], description="% of base.")
    bonus_target_amount: Extracted[float] = Field(default_factory=Extracted[float], description="USD/year.")
    match_401k: Extracted[Match401k] = Field(default_factory=Extracted[Match401k])
    hsa_employer_annual: Extracted[float] = Field(default_factory=Extracted[float])
    health_premium_monthly: Extracted[float] = Field(default_factory=Extracted[float])
    pto_days: Extracted[float] = Field(default_factory=Extracted[float])
    pto_unlimited: bool = False
    relocation: Extracted[float] = Field(default_factory=Extracted[float])
    equity: Extracted[EquityGrant] = Field(default_factory=Extracted[EquityGrant])
    start_date: Extracted[str] = Field(default_factory=Extracted[str])
    work_arrangement: Extracted[Literal["onsite", "hybrid", "remote"]] = Field(
        default_factory=Extracted[Literal["onsite", "hybrid", "remote"]]
    )


class ManualOfferForm(BaseModel):
    """'Fill in manually' form. Blank fields become not_stated."""

    company: Optional[str] = Field(None, max_length=120)
    job_title: Optional[str] = Field(None, max_length=120)
    office_city: Optional[str] = Field(None, max_length=80)
    office_state: Optional[str] = Field(None, max_length=2)
    base_salary: Optional[float] = Field(None, ge=0, le=5_000_000)
    hourly_rate: Optional[float] = Field(None, ge=0, le=2000)
    hours_per_week: Optional[float] = Field(None, ge=1, le=80)
    signing_bonus: Optional[float] = Field(None, ge=0, le=1_000_000)
    bonus_target_pct: Optional[float] = Field(None, ge=0, le=200)
    match_rate_pct: Optional[float] = Field(None, ge=0, le=500, description="e.g. 100 for dollar-for-dollar")
    match_up_to_pct: Optional[float] = Field(None, ge=0, le=100)
    hsa_employer_annual: Optional[float] = Field(None, ge=0, le=20000)
    pto_days: Optional[float] = Field(None, ge=0, le=100)
    relocation: Optional[float] = Field(None, ge=0, le=500_000)
    equity_value_usd: Optional[float] = Field(None, ge=0, le=10_000_000)
    equity_vesting_years: Optional[float] = Field(None, ge=0.25, le=10)
    work_arrangement: Optional[Literal["onsite", "hybrid", "remote"]] = None
    start_date: Optional[str] = Field(None, max_length=40)


class OfferParserInput(BaseModel):
    """One offer to parse. Exactly one of file/text/form is used."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    offer_id: OfferId
    label: str = ""
    source: Literal["file", "text", "form"]
    file_name: Optional[str] = Field(None, max_length=200)
    media_type: Optional[str] = None
    # PRIVACY: never serialized, never repr'd, never logged.
    content: Optional[bytes] = Field(default=None, exclude=True, repr=False)
    text: Optional[str] = Field(default=None, exclude=True, repr=False)
    form: Optional[ManualOfferForm] = None
    remote_city_hint: Optional[str] = Field(None, description="From profile; used when the offer is fully remote.")


class ResolvedLocation(BaseModel):
    """Office (or remote residence) location matched to a supported metro."""

    city: Optional[str] = None
    state: Optional[str] = None
    cbsa: Optional[str] = None
    metro_name: Optional[str] = None
    matched: bool = False
    method: str = "none"  # exact_city | principal_city | alias | remote_profile | none
    basis: Literal["office", "remote_residence", "unknown"] = "unknown"


class OfferParserOutput(AgentOutputBase):
    """Structured offer plus how it was read."""

    agent: str = "offer_parser"
    offer_id: OfferId
    label: str = ""
    fields: OfferFields = Field(default_factory=OfferFields)
    location: ResolvedLocation = Field(default_factory=ResolvedLocation)
    is_offer_letter: bool = True
    text_source: Literal["text", "pdf_text", "ocr", "vision", "form", "none"] = "none"
    fields_found: int = 0
    fields_total: int = 0


# ---------------------------------------------------------------------------
# Agent 2: Tax & Take-Home
# ---------------------------------------------------------------------------


class TaxOfferInput(BaseModel):
    """What the tax agent needs per offer (no names, no letter text)."""

    offer_id: OfferId
    gross_salary: Optional[float] = None
    state: Optional[str] = None
    city: Optional[str] = None
    contribution_401k_pct: float = 6
    health_premium_monthly: float = 0


class TaxInput(BaseModel):
    offers: list[TaxOfferInput]
    filing_status: Literal["single"] = "single"


class TaxLine(BaseModel):
    """One line of the tax breakdown with its formula and source."""

    label: str
    annual: float
    formula: str
    source: Optional[SourceRef] = None


class TaxResult(BaseModel):
    offer_id: OfferId
    computed: bool = True
    gross_salary: float = 0
    pretax_401k: float = 0
    pretax_health: float = 0
    federal_taxable_income: float = 0
    federal_tax: float = 0
    social_security_tax: float = 0
    medicare_tax: float = 0
    state_tax: float = 0
    state_taxable_income: float = 0
    local_tax: float = 0
    local_tax_name: Optional[str] = None
    total_tax: float = 0
    take_home_annual: float = 0
    take_home_monthly: float = 0
    effective_rate: float = 0
    marginal_rate: float = 0
    lines: list[TaxLine] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    explanation: str = ""


class TaxOutput(AgentOutputBase):
    agent: str = "tax"
    tax_year: int = 2026
    results: list[TaxResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent 3: Cost of Living & Housing
# ---------------------------------------------------------------------------


class COLOfferInput(BaseModel):
    offer_id: OfferId
    cbsa: Optional[str] = None
    metro_name: Optional[str] = None


class CostOfLivingInput(BaseModel):
    offers: list[COLOfferInput]
    housing: Literal["alone", "roommates"] = "alone"
    roommates: int = 1
    rent_adjust_pct: float = 0


class BudgetLine(BaseModel):
    key: str  # rent | groceries | transportation | utilities | dining_fun | personal
    label: str
    monthly: float
    formula: str
    source: Optional[SourceRef] = None


class CityBudget(BaseModel):
    offer_id: OfferId
    computed: bool = True
    cbsa: Optional[str] = None
    metro_name: Optional[str] = None
    bedrooms: int = 1
    share_divisor: int = 1
    rent_monthly: float = 0
    living_costs_monthly: float = 0  # everything except rent
    total_monthly: float = 0
    lines: list[BudgetLine] = Field(default_factory=list)
    rpp_all: Optional[float] = None
    rpp_housing: Optional[float] = None
    zori_typical_rent: Optional[float] = None
    zori_yoy_pct: Optional[float] = None
    explanation: str = ""


class CostOfLivingOutput(AgentOutputBase):
    agent: str = "cost_of_living"
    budgets: list[CityBudget] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent 4: Market & Company
# ---------------------------------------------------------------------------


class MarketOfferInput(BaseModel):
    offer_id: OfferId
    company: Optional[str] = None
    job_title: Optional[str] = None
    cbsa: Optional[str] = None
    metro_name: Optional[str] = None
    base_salary: Optional[float] = None
    pasted_reviews: Optional[str] = Field(default=None, exclude=True, repr=False)


class MarketInput(BaseModel):
    offers: list[MarketOfferInput]


class WagePercentiles(BaseModel):
    p10: Optional[float] = None
    p25: Optional[float] = None
    p50: Optional[float] = None
    p75: Optional[float] = None
    p90: Optional[float] = None
    mean: Optional[float] = None
    employment: Optional[float] = None
    area_name: str = ""
    area_level: Literal["metro", "national", "none"] = "none"


class CultureSummary(BaseModel):
    source: Literal["simulated", "user_pasted", "none"] = "none"
    company_found: bool = False
    rating: Optional[float] = None  # 1-5
    n_reviews: int = 0
    themes: dict[str, float] = Field(default_factory=dict, description="theme -> -1..1 sentiment")
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    summary: str = ""


class MarketResult(BaseModel):
    offer_id: OfferId
    soc_code: Optional[str] = None
    soc_title: Optional[str] = None
    soc_match_confidence: float = 0
    soc_match_reason: str = ""
    wages: WagePercentiles = Field(default_factory=WagePercentiles)
    salary_percentile: Optional[float] = None
    label: Literal["below", "near", "above", "unknown"] = "unknown"
    leverage_points: list[str] = Field(default_factory=list)
    culture: CultureSummary = Field(default_factory=CultureSummary)
    sources: list[SourceRef] = Field(default_factory=list)


class MarketOutput(AgentOutputBase):
    agent: str = "market"
    results: list[MarketResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent 5: Lifestyle Fit
# ---------------------------------------------------------------------------


class LifestyleOfferInput(BaseModel):
    offer_id: OfferId
    cbsa: Optional[str] = None
    metro_name: Optional[str] = None


class LifestyleInput(BaseModel):
    offers: list[LifestyleOfferInput]
    priorities: LifestylePriorities = Field(default_factory=LifestylePriorities)
    home_city: Optional[str] = None


class DimensionScore(BaseModel):
    dimension: Literal["outdoors", "nightlife", "weather", "commute", "family", "cost_of_fun"]
    label: str
    score: Optional[float] = None  # 0-100; None = data unavailable
    weight: int = 0
    inputs: dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    formula: str = ""


class LifestyleResult(BaseModel):
    offer_id: OfferId
    computed: bool = True
    metro_name: Optional[str] = None
    dimensions: list[DimensionScore] = Field(default_factory=list)
    fit_score: Optional[float] = None
    highlights: list[str] = Field(default_factory=list)


class LifestyleOutput(AgentOutputBase):
    agent: str = "lifestyle"
    results: list[LifestyleResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent 6: Decision Strategist
# ---------------------------------------------------------------------------


class ComponentScore(BaseModel):
    key: str
    label: str
    score: float  # 0-100
    weight: float  # normalized 0-1
    basis: str


class ScorecardRow(BaseModel):
    offer_id: OfferId
    label: str
    company: str
    job_title: str
    metro_name: str
    base_salary: Optional[float] = None
    take_home_monthly: Optional[float] = None
    taxes_monthly: Optional[float] = None
    pretax_savings_monthly: Optional[float] = None
    rent_monthly: Optional[float] = None
    living_costs_monthly: Optional[float] = None
    loans_monthly: float = 0
    extras_monthly: float = 0
    left_over_monthly: Optional[float] = None
    comp_1yr: Optional[float] = None
    comp_3yr: Optional[float] = None
    comp_breakdown: dict[str, float] = Field(default_factory=dict)
    employer_401k_match_annual: Optional[float] = None
    market_percentile: Optional[float] = None
    market_label: Literal["below", "near", "above", "unknown"] = "unknown"
    lifestyle_score: Optional[float] = None
    culture_rating: Optional[float] = None
    components: list[ComponentScore] = Field(default_factory=list)
    total_score: Optional[float] = None
    rank: Optional[int] = None
    missing: list[str] = Field(default_factory=list)


class SensitivityFinding(BaseModel):
    """'What would flip the decision' — computed by re-running the deterministic scorecard."""

    lever: Literal["housing", "bonus_payout", "rent", "contribution_401k", "loans", "weights"]
    statement: str
    flips: bool
    new_winner: Optional[OfferId] = None
    threshold: Optional[float] = None


class NegotiationEmail(BaseModel):
    offer_id: Optional[OfferId] = None
    subject: str = ""
    body: str = ""
    evidence: list[str] = Field(default_factory=list)


class DecisionInput(BaseModel):
    profile: UserProfile
    parsed: list[OfferParserOutput]
    tax: Optional[TaxOutput] = None
    col: Optional[CostOfLivingOutput] = None
    market: Optional[MarketOutput] = None
    lifestyle: Optional[LifestyleOutput] = None
    degraded_agents: list[str] = Field(default_factory=list)


class DecisionOutput(AgentOutputBase):
    agent: str = "decision"
    scorecard: list[ScorecardRow] = Field(default_factory=list)
    winner: Optional[OfferId] = None
    is_tie: bool = False
    headline: str = ""
    monthly_advantage: Optional[float] = None
    recommendation: str = ""
    reasoning: list[str] = Field(default_factory=list)
    sensitivity: list[SensitivityFinding] = Field(default_factory=list)
    negotiation: NegotiationEmail = Field(default_factory=NegotiationEmail)
    recruiter_questions: dict[str, list[str]] = Field(default_factory=dict)
    confidence_note: str = ""


# ---------------------------------------------------------------------------
# Recalculation (stateless, deterministic, no LLM)
# ---------------------------------------------------------------------------


class RecalcOffer(BaseModel):
    """Everything needed to recompute money, comp and score for one offer."""

    offer_id: OfferId
    label: str
    company: str
    job_title: str
    metro_name: str
    cbsa: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    fields: OfferFields
    market_percentile: Optional[float] = None
    market_label: Literal["below", "near", "above", "unknown"] = "unknown"
    lifestyle_score: Optional[float] = None
    culture_rating: Optional[float] = None


class RecalcContext(BaseModel):
    offers: list[RecalcOffer]
    profile: UserProfile


class RecalcRequest(BaseModel):
    context: RecalcContext
    overrides: dict[str, Any] = Field(default_factory=dict, description="Profile fields to change.")


class RecalcResponse(BaseModel):
    scorecard: list[ScorecardRow]
    winner: Optional[OfferId]
    is_tie: bool
    headline: str
    monthly_advantage: Optional[float] = None
    budgets: list[CityBudget] = Field(default_factory=list)
    taxes: list[TaxResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

AgentKey = Literal["orchestrator", "offer_parser", "tax", "cost_of_living", "market", "lifestyle", "decision"]
AgentState = Literal["waiting", "running", "done", "failed", "skipped"]


class AgentStatus(BaseModel):
    agent: AgentKey
    state: AgentState = "waiting"
    started_at: Optional[float] = None
    elapsed_ms: Optional[int] = None
    summary: str = ""
    error: Optional[str] = None


class ProgressEvent(BaseModel):
    """Streamed to the browser over SSE. Contains timings/status only — never offer contents."""

    type: Literal["pipeline_started", "agent_started", "agent_finished", "agent_failed", "pipeline_finished", "result", "error"]
    run_id: str
    agent: Optional[AgentKey] = None
    offer_id: Optional[OfferId] = None
    elapsed_ms: Optional[int] = None
    summary: str = ""
    ts: float = Field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    data: Optional[dict[str, Any]] = None


class PipelineState(BaseModel):
    """Shared, typed state handed from stage to stage by the orchestrator."""

    run_id: str
    created_at: float = Field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    profile: UserProfile
    offer_ids: list[OfferId] = Field(default_factory=list)
    parsed: dict[str, OfferParserOutput] = Field(default_factory=dict)
    tax: Optional[TaxOutput] = None
    col: Optional[CostOfLivingOutput] = None
    market: Optional[MarketOutput] = None
    lifestyle: Optional[LifestyleOutput] = None
    decision: Optional[DecisionOutput] = None
    status: dict[str, AgentStatus] = Field(default_factory=dict)
    degraded: bool = False
    degraded_agents: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    recalc_context: Optional[RecalcContext] = None
    total_elapsed_ms: int = 0
    llm_mode: str = "local"
