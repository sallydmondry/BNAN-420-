"""Deterministic money math shared by the agents and ``/api/recalculate``.

Nothing here calls an LLM. Every figure carries a ``formula`` string and a ``source`` so the UI can show
exactly how it was produced.

Money left over (monthly) = take-home pay − rent − living costs − student loans − other fixed costs,
where take-home pay is already net of taxes, pre-tax 401(k) and the pre-tax health premium.
"""

from __future__ import annotations

from typing import Optional

from backend.core.models import (
    BudgetLine,
    CityBudget,
    Match401k,
    OfferFields,
    SourceRef,
    TaxLine,
    TaxResult,
    UserProfile,
)
from backend.data import lookups as L

DEFAULT_HOURS_PER_WEEK = 40.0
WEEKS_PER_YEAR = 52


# ---------------------------------------------------------------------------
# Compensation
# ---------------------------------------------------------------------------


def annual_salary(fields: OfferFields) -> Optional[float]:
    """Annual base pay: stated salary, or hourly rate × hours/week × 52."""
    if fields.base_salary.known:
        return float(fields.base_salary.value)  # type: ignore[arg-type]
    if fields.hourly_rate.known:
        hours = float(fields.hours_per_week.value) if fields.hours_per_week.known else DEFAULT_HOURS_PER_WEEK
        return float(fields.hourly_rate.value) * hours * WEEKS_PER_YEAR  # type: ignore[arg-type]
    return None


def expected_bonus(fields: OfferFields, salary: float, payout_pct: float) -> float:
    """Target bonus × the share the user expects to be paid (0 when no bonus is stated)."""
    if fields.bonus_target_amount.known:
        target = float(fields.bonus_target_amount.value)  # type: ignore[arg-type]
    elif fields.bonus_target_pct.known:
        target = salary * float(fields.bonus_target_pct.value) / 100.0  # type: ignore[arg-type]
    else:
        return 0.0
    return target * payout_pct / 100.0


def employer_match(match: Optional[Match401k], salary: float, contribution_pct: float) -> float:
    """Employer 401(k) dollars for a year, given the plan formula and the employee's contribution %.

    Tiers are applied in order: e.g. 100% of the first 3% then 50% of the next 2%.
    Non-elective (safe-harbor) contributions are paid regardless of the employee's contribution.
    """
    if match is None or salary <= 0:
        return 0.0
    remaining = max(0.0, contribution_pct)
    pct = 0.0
    for t in match.tiers:
        used = min(remaining, t.on_pct)
        pct += used * t.rate
        remaining -= used
        if remaining <= 0:
            break
    dollars = salary * (pct + match.nonelective_pct) / 100.0
    if match.annual_cap is not None:
        dollars = min(dollars, match.annual_cap)
    return dollars


def max_match_contribution_pct(match: Optional[Match401k]) -> float:
    """Smallest contribution % that captures the full employer match."""
    if match is None:
        return 0.0
    return sum(t.on_pct for t in match.tiers)


def compensation(fields: OfferFields, profile: UserProfile) -> dict:
    """Year-1 and 3-year total compensation with a labeled breakdown.

    Year 1 = base + signing + expected bonus + employer 401(k) + employer HSA + relocation + equity/vesting years.
    3-year = base grows by the user's raise assumption each year; bonus, match and HSA recur; signing and
    relocation are one-time; equity counts only the portion vested within 3 years.
    """
    salary = annual_salary(fields)
    if salary is None:
        return {"comp_1yr": None, "comp_3yr": None, "breakdown": {}, "match_annual": None, "salary": None}
    match = fields.match_401k.value if fields.match_401k.known else None
    signing = float(fields.signing_bonus.value) if fields.signing_bonus.known else 0.0
    reloc = float(fields.relocation.value) if fields.relocation.known else 0.0
    hsa = float(fields.hsa_employer_annual.value) if fields.hsa_employer_annual.known else 0.0
    eq_year = 0.0
    eq_3yr = 0.0
    if fields.equity.known and fields.equity.value and fields.equity.value.value_usd:
        eq = fields.equity.value
        years = eq.vesting_years or 4.0
        eq_year = eq.value_usd / years
        eq_3yr = eq.value_usd * min(3.0, years) / years
    raise_f = 1 + profile.annual_raise_pct / 100.0
    bonus1 = expected_bonus(fields, salary, profile.bonus_payout_pct)
    match1 = employer_match(match, salary, profile.contribution_401k_pct)
    breakdown = {
        "base": salary,
        "signing_bonus": signing,
        "expected_bonus": bonus1,
        "employer_401k": match1,
        "employer_hsa": hsa,
        "relocation": reloc,
        "equity_per_year": eq_year,
    }
    comp_1yr = sum(breakdown.values())
    comp_3yr = signing + reloc + eq_3yr
    for y in range(3):
        s = salary * raise_f**y
        comp_3yr += s + expected_bonus(fields, s, profile.bonus_payout_pct) + employer_match(
            match, s, profile.contribution_401k_pct) + hsa
    return {"comp_1yr": comp_1yr, "comp_3yr": comp_3yr, "breakdown": breakdown, "match_annual": match1,
            "salary": salary}


def health_premium_monthly(fields: OfferFields, profile: UserProfile) -> tuple[float, str]:
    """Pre-tax employee health premium: user value > offer value > KFF national average."""
    if profile.health_premium_monthly is not None:
        return float(profile.health_premium_monthly), "you entered"
    if fields.health_premium_monthly.known:
        return float(fields.health_premium_monthly.value), "stated in offer"  # type: ignore[arg-type]
    return L.health_premium_default_monthly(), "KFF 2025 national average (not stated in offer)"


# ---------------------------------------------------------------------------
# Taxes
# ---------------------------------------------------------------------------


def compute_tax(offer_id: str, salary: Optional[float], state: Optional[str], city: Optional[str],
                contribution_401k_pct: float, health_monthly: float) -> TaxResult:
    """Wrap ``lookups.tax_for`` into a ``TaxResult`` with per-line formulas and sources."""
    if salary is None or salary <= 0:
        return TaxResult(offer_id=offer_id, computed=False,  # type: ignore[arg-type]
                         assumptions=["Salary not stated in offer, so taxes could not be computed."])
    c = L.tax_for(state, city, salary, contribution_401k_pct, health_monthly * 12)
    lines = []
    for ln in c.lines:
        src = ln.get("source")
        lines.append(TaxLine(label=ln["label"], annual=round(ln["annual"], 2), formula=ln["formula"],
                             source=SourceRef(name=src["name"], data_year=str(src.get("data_year", "")),
                                              url=src.get("url")) if src else None))
    return TaxResult(
        offer_id=offer_id,  # type: ignore[arg-type]
        gross_salary=round(c.gross, 2), pretax_401k=round(c.pretax_401k, 2), pretax_health=round(c.pretax_health, 2),
        federal_taxable_income=round(c.federal_taxable, 2), federal_tax=round(c.federal_tax, 2),
        social_security_tax=round(c.ss_tax, 2), medicare_tax=round(c.medicare_tax, 2),
        state_tax=round(c.state_tax, 2), state_taxable_income=round(c.state_taxable, 2),
        local_tax=round(c.local_tax, 2), local_tax_name=c.local_name, total_tax=round(c.total_tax, 2),
        take_home_annual=round(c.take_home, 2), take_home_monthly=round(c.take_home / 12, 2),
        effective_rate=round(c.effective_rate, 4), marginal_rate=round(c.marginal_rate, 4),
        lines=lines, assumptions=c.assumptions + c.warnings,
    )


# ---------------------------------------------------------------------------
# Cost of living
# ---------------------------------------------------------------------------


def _ce_source() -> SourceRef:
    ce = L.consumer_expenditure()
    return SourceRef(name=f"BLS Consumer Expenditure Survey {ce['year']} × BEA Regional Price Parities",
                     data_year=str(ce["year"]), url="https://www.bls.gov/cex/tables.htm")


def compute_budget(offer_id: str, cbsa: Optional[str], metro_name: Optional[str], housing: str = "alone",
                   roommates: int = 1, rent_adjust_pct: float = 0.0) -> CityBudget:
    """Monthly city budget: market rent (your share) + living costs scaled by local prices.

    Living costs = BLS CE national mean annual spending for a one-person household × BEA Regional Price
    Parity for the matching category (goods, services, utilities, or all items) ÷ 100 ÷ 12.
    """
    if not cbsa:
        return CityBudget(offer_id=offer_id, computed=False, metro_name=metro_name)  # type: ignore[arg-type]
    rpp = L.rpp_for(cbsa)
    sharers = 1 if housing == "alone" else max(1, min(3, roommates)) + 1
    bedrooms = 1 if sharers == 1 else min(4, sharers)
    rent = L.rent_for(cbsa, bedrooms)
    if rpp is None or rent is None:
        return CityBudget(offer_id=offer_id, computed=False, cbsa=cbsa, metro_name=metro_name)  # type: ignore[arg-type]

    adj = 1 + rent_adjust_pct / 100.0
    my_rent = rent.unit_rent / sharers * adj
    rent_formula = rent.formula
    if sharers > 1:
        rent_formula += f"; ÷ {sharers} people sharing"
    if rent_adjust_pct:
        rent_formula += f"; adjusted {rent_adjust_pct:+g}% (your what-if)"
    rent_formula += f" = ${my_rent:,.0f}/mo"

    ce = L.consumer_expenditure()["annual"]
    ce_src = _ce_source()
    rpp_year = rpp["year"]
    util_key = f"utilities_{min(4, sharers)}p"
    cats = [
        ("groceries", "Groceries", ce["food_home"], "rpp_goods", "goods", 1),
        ("transportation", "Transportation", ce["transportation"], "rpp_all", "all items", 1),
        ("utilities", "Utilities & phone", ce[util_key], "rpp_utilities", "utilities", sharers),
        ("dining_fun", "Dining out & entertainment", ce["food_away"] + ce["entertainment"], "rpp_other", "services", 1),
        ("personal", "Clothing & personal care", ce["apparel"] + ce["personal_care"], "rpp_goods", "goods", 1),
    ]
    lines = [BudgetLine(key="rent", label="Rent (your share)" if sharers > 1 else "Rent (1-bedroom)",
                        monthly=round(my_rent, 2), formula=rent_formula, source=rent.sources[0])]
    living = 0.0
    for key, label, annual, rkey, rname, divisor in cats:
        idx = rpp[rkey]
        monthly = annual * idx / 100.0 / 12.0 / divisor
        living += monthly
        hh = f"{sharers}-person household ÷ {sharers}" if divisor > 1 else "one-person household"
        formula = (f"BLS CE ${annual:,.0f}/yr ({hh}) × BEA RPP {rname} {idx:.1f} ÷ 100 ÷ 12 = ${monthly:,.0f}/mo")
        lines.append(BudgetLine(key=key, label=label, monthly=round(monthly, 2), formula=formula,
                                source=SourceRef(name=f"{ce_src.name} ({rpp_year} RPP)", data_year=ce_src.data_year,
                                                 url=ce_src.url)))
    return CityBudget(
        offer_id=offer_id, cbsa=cbsa, metro_name=metro_name, bedrooms=bedrooms, share_divisor=sharers,  # type: ignore[arg-type]
        rent_monthly=round(my_rent, 2), living_costs_monthly=round(living, 2), total_monthly=round(my_rent + living, 2),
        lines=lines, rpp_all=rpp["rpp_all"], rpp_housing=rpp["rpp_housing"],
        zori_typical_rent=round(rent.zori_latest, 2), zori_yoy_pct=round(rent.zori_yoy_pct, 2),
    )


# ---------------------------------------------------------------------------
# Money left over
# ---------------------------------------------------------------------------


def money_left_over(tax: TaxResult, budget: CityBudget, profile: UserProfile) -> Optional[float]:
    """Monthly take-home − rent − living costs − loans − other fixed costs (None if inputs missing)."""
    if not tax.computed or not budget.computed:
        return None
    return round(tax.take_home_monthly - budget.rent_monthly - budget.living_costs_monthly
                 - profile.student_loan_monthly - profile.extras_monthly, 2)
