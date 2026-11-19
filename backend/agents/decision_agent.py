"""Agent 6 — Decision Strategist.

Combines every other agent's output into the final comparison:
* money left over each month (take-home from Agent 2 − budget from Agent 3 − loans − extras)
* weighted scorecard, ranking and tie detection (``core.scoring``)
* "what would flip the decision" sensitivity checks (re-running the same deterministic scorecard)
* a negotiation email and recruiter questions built only from computed facts

All numbers come from ``core.finance``/``core.scoring``; text is checked by ``core.guards``.
"""

from __future__ import annotations

import json
import time
from typing import Optional

from backend.core import llm, scoring
from backend.core.guards import collect_numbers, safe_text
from backend.core.models import (
    DecisionInput,
    DecisionOutput,
    MarketResult,
    NegotiationEmail,
    OfferParserOutput,
    RecalcContext,
    RecalcOffer,
    ScorecardRow,
)


def _m(x: float) -> str:
    return f"${abs(x):,.0f}"


def build_context(inp: DecisionInput) -> RecalcContext:
    """Everything ``/api/recalculate`` needs, so the browser can re-run what-ifs statelessly."""
    mk = {r.offer_id: r for r in (inp.market.results if inp.market else [])}
    ls = {r.offer_id: r for r in (inp.lifestyle.results if inp.lifestyle else [])}
    offers = []
    for p in inp.parsed:
        f = p.fields
        m, life = mk.get(p.offer_id), ls.get(p.offer_id)
        offers.append(RecalcOffer(
            offer_id=p.offer_id, label=p.label or f"Offer {p.offer_id}",
            company=f.company.value if f.company.known else "Company not stated",
            job_title=f.job_title.value if f.job_title.known else "Title not stated",
            metro_name=p.location.metro_name or (f.office_city.value if f.office_city.known else "City not stated"),
            cbsa=p.location.cbsa, state=p.location.state or (f.office_state.value if f.office_state.known else None),
            city=p.location.city, fields=f,
            market_percentile=m.salary_percentile if m else None, market_label=m.label if m else "unknown",
            lifestyle_score=life.fit_score if life else None,
            culture_rating=m.culture.rating if m else None,
        ))
    return RecalcContext(offers=offers, profile=inp.profile)


def reasoning(rows: list[ScorecardRow]) -> list[str]:
    """Data-backed bullets explaining what drives the result."""
    out: list[str] = []
    ok = [r for r in rows if r.left_over_monthly is not None]
    for r in sorted(ok, key=lambda r: r.rank or 99):
        out.append(f"{r.label} ({r.metro_name}): {_m(r.take_home_monthly or 0)} take-home − {_m(r.rent_monthly or 0)} rent − "
                   f"{_m(r.living_costs_monthly or 0)} living costs − {_m(r.loans_monthly + r.extras_monthly)} loans & other "
                   f"= {_m(r.left_over_monthly or 0)} {'left over' if (r.left_over_monthly or 0) >= 0 else 'short'} each month.")
    if len(ok) >= 2:
        hi = max(ok, key=lambda r: r.rent_monthly or 0)
        lo = min(ok, key=lambda r: r.rent_monthly or 0)
        rent_gap = (hi.rent_monthly or 0) - (lo.rent_monthly or 0)
        tx_hi = max(ok, key=lambda r: r.taxes_monthly or 0)
        tx_lo = min(ok, key=lambda r: r.taxes_monthly or 0)
        tax_gap = (tx_hi.taxes_monthly or 0) - (tx_lo.taxes_monthly or 0)
        if rent_gap >= 50:
            out.append(f"Rent is {_m(rent_gap)}/month higher in {hi.metro_name} than in {lo.metro_name}.")
        if tax_gap >= 50:
            out.append(f"Taxes take {_m(tax_gap)}/month more in {tx_hi.metro_name} than in {tx_lo.metro_name}.")
        pay = sorted([r for r in ok if r.base_salary], key=lambda r: -(r.base_salary or 0))
        money = sorted(ok, key=lambda r: -(r.left_over_monthly or 0))
        if pay and money and pay[0].offer_id != money[0].offer_id:
            out.append(f"The bigger salary isn't the better deal here: {pay[0].label} pays the most, but {money[0].label} "
                       "leaves the most money each month.")
    for r in rows:
        if r.comp_1yr and r.comp_breakdown.get("employer_401k"):
            out.append(f"{r.label}'s employer 401(k) contribution is worth {_m(r.comp_breakdown['employer_401k'])}/year at "
                       "your contribution rate.")
    return out


def recommendation_local(rows: list[ScorecardRow], winner: Optional[str], tie: bool, headline: str,
                         flips: list[str]) -> str:
    """Template recommendation; leads with money left over."""
    if winner is None:
        return headline
    top = next(r for r in rows if r.offer_id == winner)
    s = headline + " "
    best_comp = [c for c in top.components if c.weight > 0]
    if best_comp:
        strongest = max(best_comp, key=lambda c: c.score * c.weight)
        s += f"Its biggest edge on your scorecard is {strongest.label.lower()} ({strongest.basis}). "
    if flips:
        s += "One thing could change the answer: " + flips[0][0].lower() + flips[0][1:] + " "
    else:
        s += "None of the what-if checks we ran flips the result, so it's a fairly robust choice. "
    s += "These are estimates for comparison, not financial advice."
    return s.strip()


def negotiation_email(rows: list[ScorecardRow], winner: Optional[str], market: dict[str, MarketResult],
                      parsed: dict[str, OfferParserOutput]) -> NegotiationEmail:
    """Polite, specific email to the winning offer's recruiter using only computed evidence."""
    if winner is None:
        return NegotiationEmail()
    top = next(r for r in rows if r.offer_id == winner)
    mr = market.get(winner)
    f = parsed[winner].fields
    evidence: list[str] = []
    asks: list[str] = []
    body_mid = ""
    if mr and mr.salary_percentile is not None and mr.wages.p50 and top.base_salary:
        evidence.append(f"BLS OEWS May 2025: {mr.soc_title} in {mr.wages.area_name} — 25th percentile "
                        f"{_m(mr.wages.p25 or 0)}, median {_m(mr.wages.p50)}; this offer ≈ {mr.salary_percentile:.0f}th percentile.")
        if mr.salary_percentile < 50:
            occ = f"the closest matching occupation ({mr.soc_title})" if mr.soc_title else "this role"
            bench = (f"below the 25th percentile of {_m(mr.wages.p25)}" if mr.salary_percentile < 25 and mr.wages.p25
                     else f"below the local median of {_m(mr.wages.p50)}")
            body_mid = (f"I looked at Bureau of Labor Statistics wage data for {occ} in {mr.wages.area_name}: a base "
                        f"salary of {_m(top.base_salary)} is {bench}. ")
            asks.append("the base salary")
    others = [r for r in rows if r.offer_id != winner and r.base_salary and top.base_salary and r.base_salary > top.base_salary]
    if others:
        o = max(others, key=lambda r: r.base_salary or 0)
        evidence.append(f"Competing offer: {o.label} base {_m(o.base_salary or 0)}.")
        body_mid += f"I also have another offer with a base salary of {_m(o.base_salary or 0)}. "
    if not f.signing_bonus.known or not f.signing_bonus.value:
        asks.append("a signing bonus")
    if not f.relocation.known:
        asks.append("relocation support")
    if not asks:
        asks.append("any flexibility in the overall package")
    ask_txt = asks[0] if len(asks) == 1 else ", ".join(asks[:-1]) + f" or {asks[-1]}"
    title = top.job_title if top.job_title != "Title not stated" else "the role"
    company = top.company if top.company != "Company not stated" else "your team"
    body = (f"Hi,\n\nThank you again for the offer to join {company} as {title}. I'm excited about the role and the team, "
            f"and I'd love to make this work.\n\n{body_mid}Would there be any flexibility on {ask_txt}?\n\n"
            "I'm hoping to make a decision soon and appreciate you considering this. Happy to talk by phone if that's "
            "easier.\n\nBest regards,\n[Your name]")
    return NegotiationEmail(offer_id=winner, subject=f"Question about my {title} offer", body=body, evidence=evidence)  # type: ignore[arg-type]


def recruiter_questions(p: OfferParserOutput) -> list[str]:
    """Questions for each recruiter, driven by what the letter did NOT state."""
    f = p.fields
    q: list[str] = []
    if not f.base_salary.known:
        q.append("What is the base salary for this role, and how often is it paid?")
    if not f.bonus_target_pct.known and not f.bonus_target_amount.known:
        if f.bonus_target_pct.note and "Discretionary" in f.bonus_target_pct.note:
            q.append("What has the discretionary bonus typically paid out for first-year hires?")
        else:
            q.append("Is this role eligible for an annual bonus? If so, what's the target and how is it decided?")
    if not f.match_401k.known:
        q.append("Does the 401(k) include an employer match? What's the formula and vesting schedule?")
    if not f.health_premium_monthly.known:
        q.append("What would my monthly health insurance premium be for single coverage?")
    if f.pto_unlimited:
        q.append("With unlimited PTO, how many days do people on the team typically take?")
    elif not f.pto_days.known:
        q.append("How many paid time off days and holidays does the role include?")
    if not f.work_arrangement.known:
        q.append("Is the role on-site, hybrid, or remote?")
    if f.equity.known:
        q.append("How was the equity grant valued, and what is the vesting schedule?")
    if not f.relocation.known:
        q.append("Is relocation assistance available?")
    if not f.start_date.known:
        q.append("What start dates are possible?")
    q.append("When are salary reviews, and what's a typical first-year raise?")
    return q[:6]


async def run(inp: DecisionInput) -> DecisionOutput:
    """Build the final scorecard, recommendation, sensitivity, email and recruiter questions."""
    t0 = time.perf_counter()
    ctx = build_context(inp)
    taxes = {r.offer_id: r for r in (inp.tax.results if inp.tax else []) if r.computed}
    budgets = {b.offer_id: b for b in (inp.col.budgets if inp.col else []) if b.computed}
    res = scoring.recalculate(ctx, taxes_in=taxes, budgets_in=budgets)
    sens = scoring.sensitivity(ctx)
    flips = [s.statement for s in sens if s.flips]
    rows = res.scorecard
    market = {r.offer_id: r for r in (inp.market.results if inp.market else [])}
    parsed = {p.offer_id: p for p in inp.parsed}
    warnings: list[str] = []
    log = ["Combined take-home (Agent 2) and city budgets (Agent 3) into money left over each month.",
           f"Scored {len(rows)} offers on {len(rows[0].components) if rows else 0} weighted components.",
           f"Ran {len(sens)} what-if checks; {len(flips)} would change the winner."]
    if inp.degraded_agents:
        warnings.append("Some agents didn't finish (" + ", ".join(inp.degraded_agents) + "), so parts of this "
                        "comparison are missing.")

    rec_local = recommendation_local(rows, res.winner, res.is_tie, res.headline, flips)
    engine = "local"
    allowed = collect_numbers(res) + collect_numbers(sens) + scoring.derived_numbers(rows)
    rec = rec_local
    if llm.claude_enabled() and res.winner:
        facts = {"headline": res.headline, "scorecard": [r.model_dump(exclude={"comp_breakdown"}) for r in rows],
                 "what_would_flip": flips}
        txt = await llm.generate("decision", "Task A.\n" + json.dumps(facts, default=str), max_tokens=900)
        rec, used = safe_text(txt, rec_local, allowed)
        engine = "claude" if used else engine

    email = negotiation_email(rows, res.winner, market, parsed)
    questions = {p.offer_id: recruiter_questions(p) for p in inp.parsed}
    confs = [x.confidence for x in (inp.tax, inp.col, inp.market, inp.lifestyle) if x is not None]
    parse_conf = sum(p.confidence for p in inp.parsed) / max(1, len(inp.parsed))
    conf = round((sum(confs) + parse_conf) / (len(confs) + 1) * (0.7 if inp.degraded_agents else 1.0), 2)
    missing = sorted({m for r in rows for m in r.missing})
    note = ("High confidence: every input was found or computed." if conf >= 0.8 and not missing else
            "Medium confidence: " + ("missing " + ", ".join(missing) + ". " if missing else "") +
            "Check the 'not stated in offer' fields and fill them in to sharpen the comparison.")
    return DecisionOutput(
        scorecard=rows, winner=res.winner, is_tie=res.is_tie, headline=res.headline,
        monthly_advantage=res.monthly_advantage, recommendation=rec, reasoning=reasoning(rows), sensitivity=sens,
        negotiation=email, recruiter_questions=questions, confidence_note=note, confidence=conf,
        log=log, warnings=warnings, engine=engine, elapsed_ms=int((time.perf_counter() - t0) * 1000),  # type: ignore[arg-type]
    )
