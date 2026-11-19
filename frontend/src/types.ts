// TypeScript mirrors of backend/core/models.py (only what the UI reads).
export type OfferId = "A" | "B" | "C";
export type Engine = "claude" | "local" | "deterministic";

export interface Extracted<T> { value: T | null; status: "stated" | "not_stated" | "derived" | "user_entered"; evidence?: string | null; note?: string | null }
export interface SourceRef { name: string; data_year: string; url?: string | null; real: boolean }
export interface AgentBase { agent: string; engine: Engine; confidence: number; log: string[]; warnings: string[]; elapsed_ms: number }

export interface Priorities { outdoors: number; nightlife: number; weather: number; commute: number; family: number; cost_of_fun: number }
export interface Weights { money_left_over: number; total_comp: number; lifestyle: number; market_position: number; culture: number }
export interface Profile {
  student_loan_monthly: number; housing: "alone" | "roommates"; roommates: number; contribution_401k_pct: number;
  home_city: string | null; remote_city: string | null; extras_monthly: number; health_premium_monthly: number | null;
  bonus_payout_pct: number; annual_raise_pct: number; rent_adjust_pct: number; filing_status: "single";
  priorities: Priorities; weights: Weights;
}

export interface MatchTier { rate: number; on_pct: number }
export interface Match401k { tiers: MatchTier[]; nonelective_pct: number; annual_cap: number | null; description: string }
export interface EquityGrant { value_usd: number | null; vesting_years: number | null; description: string }
export interface OfferFields {
  company: Extracted<string>; job_title: Extracted<string>; office_city: Extracted<string>; office_state: Extracted<string>;
  base_salary: Extracted<number>; pay_basis: string; hourly_rate: Extracted<number>; hours_per_week: Extracted<number>;
  signing_bonus: Extracted<number>; bonus_target_pct: Extracted<number>; bonus_target_amount: Extracted<number>;
  match_401k: Extracted<Match401k>; hsa_employer_annual: Extracted<number>; health_premium_monthly: Extracted<number>;
  pto_days: Extracted<number>; pto_unlimited: boolean; relocation: Extracted<number>; equity: Extracted<EquityGrant>;
  start_date: Extracted<string>; work_arrangement: Extracted<string>;
}
export interface ResolvedLocation { city: string | null; state: string | null; cbsa: string | null; metro_name: string | null; matched: boolean; method: string; basis: string }
export interface ParserOut extends AgentBase { offer_id: OfferId; label: string; fields: OfferFields; location: ResolvedLocation; is_offer_letter: boolean; text_source: string; fields_found: number; fields_total: number }

export interface TaxLine { label: string; annual: number; formula: string; source: SourceRef | null }
export interface TaxResult {
  offer_id: OfferId; computed: boolean; gross_salary: number; pretax_401k: number; pretax_health: number; federal_tax: number;
  social_security_tax: number; medicare_tax: number; state_tax: number; local_tax: number; local_tax_name: string | null;
  total_tax: number; take_home_annual: number; take_home_monthly: number; effective_rate: number; marginal_rate: number;
  lines: TaxLine[]; assumptions: string[]; explanation: string;
}
export interface BudgetLine { key: string; label: string; monthly: number; formula: string; source: SourceRef | null }
export interface CityBudget {
  offer_id: OfferId; computed: boolean; cbsa: string | null; metro_name: string | null; bedrooms: number; share_divisor: number;
  rent_monthly: number; living_costs_monthly: number; total_monthly: number; lines: BudgetLine[]; rpp_all: number | null;
  rpp_housing: number | null; zori_typical_rent: number | null; zori_yoy_pct: number | null; explanation: string;
}
export interface Wages { p10: number | null; p25: number | null; p50: number | null; p75: number | null; p90: number | null; mean: number | null; employment: number | null; area_name: string; area_level: string }
export interface Culture { source: "simulated" | "user_pasted" | "none"; company_found: boolean; rating: number | null; n_reviews: number; themes: Record<string, number>; pros: string[]; cons: string[]; summary: string }
export interface MarketResult { offer_id: OfferId; soc_code: string | null; soc_title: string | null; soc_match_confidence: number; soc_match_reason: string; wages: Wages; salary_percentile: number | null; label: string; leverage_points: string[]; culture: Culture; sources: SourceRef[] }
export interface Dimension { dimension: string; label: string; score: number | null; weight: number; inputs: Record<string, unknown>; source: string; formula: string }
export interface LifestyleResult { offer_id: OfferId; computed: boolean; metro_name: string | null; dimensions: Dimension[]; fit_score: number | null; highlights: string[] }

export interface Component { key: string; label: string; score: number; weight: number; basis: string }
export interface Row {
  offer_id: OfferId; label: string; company: string; job_title: string; metro_name: string; base_salary: number | null;
  take_home_monthly: number | null; taxes_monthly: number | null; pretax_savings_monthly: number | null; rent_monthly: number | null;
  living_costs_monthly: number | null; loans_monthly: number; extras_monthly: number; left_over_monthly: number | null;
  comp_1yr: number | null; comp_3yr: number | null; comp_breakdown: Record<string, number>; employer_401k_match_annual: number | null;
  market_percentile: number | null; market_label: string; lifestyle_score: number | null; culture_rating: number | null;
  components: Component[]; total_score: number | null; rank: number | null; missing: string[];
}
export interface Sensitivity { lever: string; statement: string; flips: boolean; new_winner: OfferId | null; threshold: number | null }
export interface Email { offer_id: OfferId | null; subject: string; body: string; evidence: string[] }
export interface DecisionOut extends AgentBase {
  scorecard: Row[]; winner: OfferId | null; is_tie: boolean; headline: string; monthly_advantage: number | null; recommendation: string;
  reasoning: string[]; sensitivity: Sensitivity[]; negotiation: Email; recruiter_questions: Record<string, string[]>; confidence_note: string;
}
export interface RecalcContext { offers: unknown[]; profile: Profile }
export interface RecalcResponse { scorecard: Row[]; winner: OfferId | null; is_tie: boolean; headline: string; monthly_advantage: number | null; budgets: CityBudget[]; taxes: TaxResult[] }

export interface AgentStatus { agent: string; state: string; elapsed_ms: number | null; summary: string; error: string | null }
export interface PipelineResult {
  run_id: string; profile: Profile; offer_ids: OfferId[]; parsed: Record<string, ParserOut>;
  tax: (AgentBase & { results: TaxResult[] }) | null; col: (AgentBase & { budgets: CityBudget[] }) | null;
  market: (AgentBase & { results: MarketResult[] }) | null; lifestyle: (AgentBase & { results: LifestyleResult[] }) | null;
  decision: DecisionOut | null; status: Record<string, AgentStatus>; degraded: boolean; degraded_agents: string[]; errors: string[];
  recalc_context: RecalcContext | null; total_elapsed_ms: number; llm_mode: string;
}
export interface ProgressEvent { type: string; run_id: string; agent: string | null; offer_id: OfferId | null; elapsed_ms: number | null; summary: string; data?: Record<string, unknown> | null }

export interface Sample { id: string; title: string; description: string; offers: { offer_id: OfferId; file: string; format: string; label: string }[]; profile: Partial<Profile> }

export interface ManualForm {
  company?: string; job_title?: string; office_city?: string; office_state?: string; base_salary?: number; hourly_rate?: number;
  hours_per_week?: number; signing_bonus?: number; bonus_target_pct?: number; match_rate_pct?: number; match_up_to_pct?: number;
  hsa_employer_annual?: number; pto_days?: number; relocation?: number; equity_value_usd?: number; equity_vesting_years?: number;
  work_arrangement?: "onsite" | "hybrid" | "remote"; start_date?: string;
}
export interface OfferDraft { offer_id: OfferId; label: string; source: "file" | "text" | "form"; file: File | null; text: string; form: ManualForm; reviews: string }

export const OFFER_COLORS: Record<OfferId, string> = { A: "#0C234B", B: "#AB0520", C: "#106AB1" };

export const DEFAULT_PROFILE: Profile = {
  student_loan_monthly: 0, housing: "alone", roommates: 1, contribution_401k_pct: 6, home_city: null, remote_city: null,
  extras_monthly: 0, health_premium_monthly: null, bonus_payout_pct: 100, annual_raise_pct: 3, rent_adjust_pct: 0, filing_status: "single",
  priorities: { outdoors: 3, nightlife: 3, weather: 3, commute: 3, family: 3, cost_of_fun: 3 },
  weights: { money_left_over: 40, total_comp: 20, lifestyle: 25, market_position: 10, culture: 5 },
};
