"""Agent 3 — Cost of Living & Housing.

Builds a monthly city budget for each offer: market rent (Zillow ZORI × Census ACS bedroom mix) and
everyday living costs (BLS Consumer Expenditure Survey × BEA Regional Price Parities). The Strategist
combines this budget with take-home pay using ``core.finance``.
"""

from __future__ import annotations

import json
import time

from backend.core import finance, llm
from backend.core.guards import collect_numbers, safe_text
from backend.core.models import CityBudget, CostOfLivingInput, CostOfLivingOutput


def _money(x: float) -> str:
    return f"${x:,.0f}"


def explain_local(b: CityBudget) -> str:
    """Template explanation using only numbers already in ``b``."""
    if not b.computed:
        return "City costs could not be estimated because the office city isn't in TrueOffer's dataset."
    share = f"your share of a {b.bedrooms}-bedroom split {b.share_divisor} ways" if b.share_divisor > 1 else "a 1-bedroom on your own"
    s = (f"In {b.metro_name}, rent for {share} runs about {_money(b.rent_monthly)} a month, and everyday costs "
         f"(food, transportation, utilities, fun and personal care) add about {_money(b.living_costs_monthly)}, "
         f"for {_money(b.total_monthly)} total. ")
    if b.rpp_all is not None:
        diff = b.rpp_all - 100
        if abs(diff) < 1.5:
            s += "Overall prices here are close to the U.S. average"
        else:
            s += f"Overall prices are {abs(diff):.0f}% {'above' if diff > 0 else 'below'} the U.S. average"
        if b.rpp_housing is not None:
            hd = b.rpp_housing - 100
            s += f", and housing is {abs(hd):.0f}% {'above' if hd > 0 else 'below'} average."
        else:
            s += "."
    if b.zori_yoy_pct is not None:
        s += f" Typical asking rents changed {b.zori_yoy_pct:+.1f}% over the past year."
    return s


async def run(inp: CostOfLivingInput) -> CostOfLivingOutput:
    """Compute a monthly budget for each offer's city."""
    t0 = time.perf_counter()
    budgets: list[CityBudget] = []
    log: list[str] = []
    warnings: list[str] = []
    engine = "local"
    for o in inp.offers:
        b = finance.compute_budget(o.offer_id, o.cbsa, o.metro_name, inp.housing, inp.roommates, inp.rent_adjust_pct)
        fallback = explain_local(b)
        text = None
        if b.computed and llm.claude_enabled():
            text = await llm.generate("cost_of_living", json.dumps(b.model_dump(exclude={"explanation"}), default=str),
                                      max_tokens=600)
        allowed = collect_numbers(b)
        if b.rpp_all is not None:
            allowed += [abs(b.rpp_all - 100), abs((b.rpp_housing or 100) - 100)]
        b.explanation, used = safe_text(text, fallback, allowed)
        engine = "claude" if used else engine
        budgets.append(b)
        if b.computed:
            log.append(f"Offer {o.offer_id}: {b.metro_name} rent {_money(b.rent_monthly)}/mo + living "
                       f"{_money(b.living_costs_monthly)}/mo.")
        else:
            warnings.append(f"Offer {o.offer_id}: city not in dataset, so no budget.")
    log.append("Rent = Zillow ZORI (latest month) scaled by Census ACS 2024 bedroom medians; living costs = BLS CE "
               "2025 spending × BEA 2024 Regional Price Parities.")
    conf = 0.85 * sum(b.computed for b in budgets) / max(1, len(budgets))
    return CostOfLivingOutput(budgets=budgets, log=log, warnings=warnings, confidence=round(conf, 2), engine=engine,  # type: ignore[arg-type]
                              elapsed_ms=int((time.perf_counter() - t0) * 1000))
