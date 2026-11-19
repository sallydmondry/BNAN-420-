"""Agent 2 — Tax & Take-Home.

Computes 2026 federal, FICA, state and local income tax and monthly take-home pay for each offer
(``core.finance.compute_tax`` over ``data.lookups.tax_for``), then explains the result in plain English.
"""

from __future__ import annotations

import asyncio
import json
import time

from backend.core import finance, llm
from backend.core.guards import collect_numbers, safe_text
from backend.core.models import TaxInput, TaxOutput, TaxResult


def _money(x: float) -> str:
    return f"${x:,.0f}"


def explain_local(r: TaxResult, state: str | None, city: str | None) -> str:
    """Template explanation using only numbers already in ``r``."""
    if not r.computed:
        return "Taxes could not be computed because the salary is not stated in the offer."
    where = f"{city}, {state}" if city and state else (state or "this location")
    fica = r.social_security_tax + r.medicare_tax
    parts = [f"{_money(r.federal_tax)} federal income tax", f"{_money(fica)} Social Security and Medicare"]
    if r.state_tax > 0:
        parts.append(f"{_money(r.state_tax)} {state} state income tax")
    if r.local_tax > 0:
        parts.append(f"{_money(r.local_tax)} {r.local_tax_name or 'local income tax'}")
    s = (f"Of your {_money(r.gross_salary)} salary in {where}, about {_money(r.total_tax)} a year "
         f"({r.effective_rate * 100:.1f}%) goes to taxes: " + ", ".join(parts[:-1]) + f" and {parts[-1]}. ")
    pre = r.pretax_401k + r.pretax_health
    s += (f"After taxes and {_money(pre)} of pre-tax 401(k) and health premiums, you take home about "
          f"{_money(r.take_home_monthly)} a month.")
    if r.state_tax == 0 and state:
        s += f" {state} has no state income tax on wages, which helps."
    return s


async def run(inp: TaxInput) -> TaxOutput:
    """Compute taxes and take-home for every offer."""
    t0 = time.perf_counter()
    results: list[TaxResult] = []
    log: list[str] = []
    warnings: list[str] = []
    engine = "local"
    for o in inp.offers:
        r = finance.compute_tax(o.offer_id, o.gross_salary, o.state, o.city, o.contribution_401k_pct,
                                o.health_premium_monthly)
        fallback = explain_local(r, o.state, o.city)
        text = None
        if r.computed and llm.claude_enabled():
            facts = r.model_dump(include={"gross_salary", "federal_tax", "social_security_tax", "medicare_tax", "state_tax",
                                          "local_tax", "local_tax_name", "total_tax", "take_home_monthly", "effective_rate",
                                          "pretax_401k", "pretax_health"})
            text = await llm.generate("tax", json.dumps({"state": o.state, "city": o.city, **facts}), max_tokens=600)
        r.explanation, used = safe_text(text, fallback, collect_numbers(r) + [r.pretax_401k + r.pretax_health,
                                                                               r.social_security_tax + r.medicare_tax])
        if used:
            engine = "claude"
        results.append(r)
        if r.computed:
            log.append(f"Offer {o.offer_id}: {o.state or 'state unknown'} taxes computed; take-home "
                       f"{_money(r.take_home_monthly)}/mo.")
        else:
            warnings.append(f"Offer {o.offer_id}: salary not stated, so taxes were skipped.")
        await asyncio.sleep(0)
    computed = [r for r in results if r.computed]
    conf = 0.95 * len(computed) / max(1, len(results))
    if any(not o.state for o in inp.offers):
        conf *= 0.8
    log.append("Used IRS 2026 brackets, the 2026 Social Security wage base, Tax Foundation 2026 state brackets, and "
               "curated city income taxes.")
    return TaxOutput(results=results, log=log, warnings=warnings, confidence=round(conf, 2), engine=engine,  # type: ignore[arg-type]
                     elapsed_ms=int((time.perf_counter() - t0) * 1000))
