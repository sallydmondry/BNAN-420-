"""Deterministic scorecard, ranking, headline and sensitivity analysis.

Used by the Decision Strategist (Agent 6) and by the stateless ``/api/recalculate`` endpoint, so the
what-if sliders in the browser always agree with the original report.

Component scores (0–100):
  * money_left_over: 100 for the offer with the most money left each month, minus 10 points for every
    $100/month behind it (floor 0).
  * total_comp: 3-year total compensation as a share of the best offer's (100 × comp ÷ best comp).
    Proportional on purpose: salary already drives money left over, so comp shouldn't count it twice.
  * lifestyle: the Lifestyle Fit score (already 0–100).
  * market_position: the salary's percentile within BLS OEWS wages for the role and metro.
  * culture: simulated/pasted review rating mapped from 1–5 stars onto 0–100.
The total is the weighted average using the user's weights (normalized to sum to 1). When one offer is
missing a component the others have, it gets a neutral 50 for it and the gap is listed in ``missing``.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.core import finance
from backend.core.models import (
    CityBudget,
    ComponentScore,
    DecisionWeights,
    RecalcContext,
    RecalcOffer,
    RecalcResponse,
    ScorecardRow,
    SensitivityFinding,
    TaxResult,
    UserProfile,
)

TIE_POINTS = 2.0
MONEY_STEP = 100.0

COMPONENTS = [
    ("money_left_over", "Money left over"),
    ("total_comp", "Total compensation (3 yr)"),
    ("lifestyle", "Lifestyle fit"),
    ("market_position", "Market position"),
    ("culture", "Culture (simulated reviews)"),
]


def apply_overrides(profile: UserProfile, overrides: Optional[dict[str, Any]]) -> UserProfile:
    """Return a validated copy of ``profile`` with ``overrides`` merged in (nested dicts merge too)."""
    if not overrides:
        return profile
    data = profile.model_dump()
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            data[k] = {**data[k], **v}
        else:
            data[k] = v
    return UserProfile.model_validate(data)


def _fmt(x: float) -> str:
    return f"${abs(x):,.0f}"


def _compute_offer(o: RecalcOffer, p: UserProfile, tax: Optional[TaxResult] = None,
                   budget: Optional[CityBudget] = None) -> tuple[ScorecardRow, TaxResult, CityBudget]:
    """One scorecard row. ``tax``/``budget`` come from Agents 2 and 3 when available, else are computed here."""
    comp = finance.compensation(o.fields, p)
    salary = comp["salary"]
    if tax is None:
        health, _ = finance.health_premium_monthly(o.fields, p)
        tax = finance.compute_tax(o.offer_id, salary, o.state, o.city, p.contribution_401k_pct, health)
    if budget is None:
        budget = finance.compute_budget(o.offer_id, o.cbsa, o.metro_name, p.housing, p.roommates, p.rent_adjust_pct)
    left = finance.money_left_over(tax, budget, p)
    missing = []
    if salary is None:
        missing.append("salary")
    if not budget.computed:
        missing.append("city cost data")
    row = ScorecardRow(
        offer_id=o.offer_id, label=o.label, company=o.company, job_title=o.job_title, metro_name=o.metro_name,
        base_salary=salary,
        take_home_monthly=tax.take_home_monthly if tax.computed else None,
        taxes_monthly=round(tax.total_tax / 12, 2) if tax.computed else None,
        pretax_savings_monthly=round((tax.pretax_401k + tax.pretax_health) / 12, 2) if tax.computed else None,
        rent_monthly=budget.rent_monthly if budget.computed else None,
        living_costs_monthly=budget.living_costs_monthly if budget.computed else None,
        loans_monthly=p.student_loan_monthly, extras_monthly=p.extras_monthly,
        left_over_monthly=left,
        comp_1yr=None if comp["comp_1yr"] is None else round(comp["comp_1yr"], 2),
        comp_3yr=None if comp["comp_3yr"] is None else round(comp["comp_3yr"], 2),
        comp_breakdown={k: round(v, 2) for k, v in comp["breakdown"].items()},
        employer_401k_match_annual=None if comp["match_annual"] is None else round(comp["match_annual"], 2),
        market_percentile=o.market_percentile, market_label=o.market_label,
        lifestyle_score=o.lifestyle_score, culture_rating=o.culture_rating, missing=missing,
    )
    return row, tax, budget


def _relative(values: list[Optional[float]], step: float) -> list[Optional[float]]:
    known = [v for v in values if v is not None]
    if not known:
        return [None] * len(values)
    best = max(known)
    return [None if v is None else max(0.0, 100.0 - 10.0 * (best - v) / step) for v in values]


def _proportional(values: list[Optional[float]]) -> list[Optional[float]]:
    known = [v for v in values if v is not None and v > 0]
    if not known:
        return [None] * len(values)
    best = max(known)
    return [None if v is None else max(0.0, 100.0 * v / best) for v in values]


def score_rows(rows: list[ScorecardRow], weights: DecisionWeights) -> None:
    """Fill ``components``, ``total_score`` and ``rank`` on each row in place."""
    raw: dict[str, list[Optional[float]]] = {
        "money_left_over": _relative([r.left_over_monthly for r in rows], MONEY_STEP),
        "total_comp": _proportional([r.comp_3yr for r in rows]),
        "lifestyle": [r.lifestyle_score for r in rows],
        "market_position": [None if r.market_percentile is None else max(0.0, min(100.0, r.market_percentile))
                            for r in rows],
        "culture": [None if r.culture_rating is None else (r.culture_rating - 1) / 4 * 100 for r in rows],
    }
    wmap = weights.model_dump()
    active = [k for k, _ in COMPONENTS if any(v is not None for v in raw[k]) and wmap[k] > 0]
    wsum = sum(wmap[k] for k in active) or 1.0
    labels = dict(COMPONENTS)
    for i, r in enumerate(rows):
        comps = []
        for k in active:
            s = raw[k][i]
            basis = _basis(k, r)
            if s is None:
                s = 50.0
                basis = "not available for this offer — neutral 50"
                if labels[k] not in r.missing:
                    r.missing.append(labels[k])
            comps.append(ComponentScore(key=k, label=labels[k], score=round(s, 1), weight=round(wmap[k] / wsum, 4),
                                        basis=basis))
        r.components = comps
        r.total_score = round(sum(c.score * c.weight for c in comps), 1) if comps else None
    order = sorted(range(len(rows)), key=lambda i: -(rows[i].total_score or -1))
    for rank, i in enumerate(order, 1):
        rows[i].rank = rank


def _basis(key: str, r: ScorecardRow) -> str:
    if key == "money_left_over" and r.left_over_monthly is not None:
        return f"{_fmt(r.left_over_monthly)}/mo left over" if r.left_over_monthly >= 0 else \
            f"{_fmt(r.left_over_monthly)}/mo short"
    if key == "total_comp" and r.comp_3yr is not None:
        return f"{_fmt(r.comp_3yr)} over 3 years"
    if key == "lifestyle" and r.lifestyle_score is not None:
        return f"fit score {r.lifestyle_score:.0f}/100"
    if key == "market_position" and r.market_percentile is not None:
        return f"~{r.market_percentile:.0f}th percentile of local pay for the role"
    if key == "culture" and r.culture_rating is not None:
        return f"{r.culture_rating:.1f}/5 average (SIMULATED reviews)"
    return ""


def winner_of(rows: list[ScorecardRow]) -> tuple[Optional[str], bool]:
    """(winning offer id, is_tie). A tie is a top-two gap under TIE_POINTS."""
    ranked = sorted([r for r in rows if r.total_score is not None], key=lambda r: -r.total_score)  # type: ignore[operator]
    if not ranked:
        return None, False
    if len(ranked) > 1 and ranked[0].total_score - ranked[1].total_score < TIE_POINTS:  # type: ignore[operator]
        return ranked[0].offer_id, True
    return ranked[0].offer_id, False


def headline(rows: list[ScorecardRow], winner: Optional[str], tie: bool) -> tuple[str, Optional[float]]:
    """One-sentence verdict that leads with money left over (the product's core message)."""
    if winner is None:
        return "Not enough information to compare these offers yet.", None
    ranked = sorted(rows, key=lambda r: r.rank or 99)
    top, others = ranked[0], ranked[1:]
    if not others:
        return f"{top.label} is the only offer with enough data to score.", None
    second = others[0]
    adv = None
    if top.left_over_monthly is not None and second.left_over_monthly is not None:
        adv = round(top.left_over_monthly - second.left_over_monthly, 2)
    if tie:
        return (f"It's close: {top.label} ({top.company}) and {second.label} ({second.company}) score within "
                f"{TIE_POINTS:g} points of each other, so your priorities should decide."), adv
    pay = sorted([r for r in rows if r.base_salary is not None], key=lambda r: -(r.base_salary or 0))
    by_money = sorted([r for r in rows if r.left_over_monthly is not None], key=lambda r: -(r.left_over_monthly or 0))
    name = f"{top.label} ({top.company}, {top.metro_name})"
    if pay and by_money and by_money[0].offer_id == top.offer_id and pay[0].offer_id != top.offer_id and adv is not None:
        gap = (pay[0].base_salary or 0) - (top.base_salary or 0)
        return (f"{name} leaves you {_fmt(adv)} more per month after taxes, rent and living costs, even though "
                f"{pay[0].label} pays {_fmt(gap)} more in base salary."), adv
    if adv is not None and adv > 0:
        return f"{name} comes out ahead and leaves you {_fmt(adv)} more per month after taxes, rent and living costs.", adv
    if adv is not None and adv < 0:
        return (f"{name} ranks first on your priorities, even though {second.label} leaves {_fmt(adv)} more per "
                f"month after costs."), adv
    return f"{name} ranks first on your weighted scorecard.", adv


def derived_numbers(rows: list[ScorecardRow]) -> list[float]:
    """Pairwise gaps the engine computes (salary, take-home, rent, taxes, left over, comp) — allowed in text."""
    out: list[float] = []
    keys = ("base_salary", "take_home_monthly", "rent_monthly", "taxes_monthly", "left_over_monthly", "comp_1yr", "comp_3yr",
            "living_costs_monthly")
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            for k in keys:
                x, y = getattr(a, k), getattr(b, k)
                if x is not None and y is not None:
                    out.append(abs(x - y))
    return out


def recalculate(ctx: RecalcContext, overrides: Optional[dict[str, Any]] = None,
                taxes_in: Optional[dict[str, TaxResult]] = None,
                budgets_in: Optional[dict[str, CityBudget]] = None) -> RecalcResponse:
    """Recompute money left over, comp and scores for every offer. No LLM, no I/O.

    ``taxes_in``/``budgets_in`` (keyed by offer id) let the Strategist reuse Agent 2/3 results; any offer
    without one is computed here with the same ``core.finance`` functions.
    """
    p = apply_overrides(ctx.profile, overrides)
    rows, taxes, budgets = [], [], []
    for o in ctx.offers:
        r, t, b = _compute_offer(o, p, (taxes_in or {}).get(o.offer_id), (budgets_in or {}).get(o.offer_id))
        rows.append(r)
        taxes.append(t)
        budgets.append(b)
    score_rows(rows, p.weights)
    w, tie = winner_of(rows)
    head, adv = headline(rows, w, tie)
    return RecalcResponse(scorecard=rows, winner=w, is_tie=tie, headline=head,  # type: ignore[arg-type]
                          monthly_advantage=adv, budgets=budgets, taxes=taxes)


# ---------------------------------------------------------------------------
# Sensitivity: what would flip the decision?
# ---------------------------------------------------------------------------


def _label(ctx: RecalcContext, oid: Optional[str]) -> str:
    for o in ctx.offers:
        if o.offer_id == oid:
            return f"{o.label} ({o.metro_name})"
    return str(oid)


def sensitivity(ctx: RecalcContext) -> list[SensitivityFinding]:
    """Re-run the scorecard under alternative assumptions and report which ones change the winner."""
    base = recalculate(ctx)
    if base.winner is None or len(ctx.offers) < 2:
        return []
    w0 = base.winner
    out: list[SensitivityFinding] = []
    p = ctx.profile

    # Housing
    alt = "roommates" if p.housing == "alone" else "alone"
    r = recalculate(ctx, {"housing": alt})
    desc = "with a roommate" if alt == "roommates" else "alone"
    out.append(SensitivityFinding(
        lever="housing", flips=r.winner != w0, new_winner=r.winner if r.winner != w0 else None,  # type: ignore[arg-type]
        statement=(f"If you lived {desc}, {_label(ctx, r.winner)} would come out on top instead."
                   if r.winner != w0 else f"Living {desc} instead would not change the winner.")))

    # Rent level (all cities shifted together)
    flip_at = None
    for pct in [5, -5, 10, -10, 15, -15, 20, -20, 25, -25, 30, -30, 40, -40, 50]:
        rr = recalculate(ctx, {"rent_adjust_pct": max(-50, min(100, p.rent_adjust_pct + pct))})
        if rr.winner != w0:
            flip_at = (pct, rr.winner)
            break
    if flip_at:
        out.append(SensitivityFinding(
            lever="rent", flips=True, new_winner=flip_at[1], threshold=flip_at[0],  # type: ignore[arg-type]
            statement=f"If rents everywhere were {abs(flip_at[0])}% {'higher' if flip_at[0] > 0 else 'lower'} than "
                      f"today's market, {_label(ctx, flip_at[1])} would win."))
    else:
        out.append(SensitivityFinding(lever="rent", flips=False,
                                      statement="Rents 50% higher or lower everywhere would not change the winner."))

    # Bonus payout
    for payout in (0, 150):
        rb = recalculate(ctx, {"bonus_payout_pct": payout})
        if rb.winner != w0:
            out.append(SensitivityFinding(
                lever="bonus_payout", flips=True, new_winner=rb.winner, threshold=payout,  # type: ignore[arg-type]
                statement=f"If bonuses paid {payout}% of target, {_label(ctx, rb.winner)} would win."))
            break
    else:
        out.append(SensitivityFinding(lever="bonus_payout", flips=False,
                                      statement="Bonuses paying anywhere from 0% to 150% of target would not change the winner."))

    # 401(k) contribution
    for c in (0, 15):
        rc = recalculate(ctx, {"contribution_401k_pct": c})
        if rc.winner != w0:
            out.append(SensitivityFinding(
                lever="contribution_401k", flips=True, new_winner=rc.winner, threshold=c,  # type: ignore[arg-type]
                statement=f"Contributing {c}% to your 401(k) would make {_label(ctx, rc.winner)} the winner."))
            break
    else:
        out.append(SensitivityFinding(lever="contribution_401k", flips=False,
                                      statement="Contributing anywhere from 0% to 15% to your 401(k) would not change the winner."))

    # Loans: subtract equally from every city
    out.append(SensitivityFinding(lever="loans", flips=False,
                                  statement="Student loan payments are the same in every city, so they lower money left "
                                            "over equally and cannot flip the decision on their own."))

    # Weights
    money_only = {"weights": {"money_left_over": 100, "total_comp": 0, "lifestyle": 0, "market_position": 0, "culture": 0}}
    life_heavy = {"weights": {"money_left_over": 20, "total_comp": 10, "lifestyle": 60, "market_position": 5, "culture": 5}}
    rm, rl = recalculate(ctx, money_only), recalculate(ctx, life_heavy)
    parts = []
    if rm.winner != w0:
        parts.append(f"judged on money left over alone, {_label(ctx, rm.winner)} wins")
    if rl.winner != w0:
        parts.append(f"if lifestyle mattered most, {_label(ctx, rl.winner)} wins")
    flips = bool(parts)
    out.append(SensitivityFinding(
        lever="weights", flips=flips, new_winner=(rm.winner if rm.winner != w0 else rl.winner) if flips else None,  # type: ignore[arg-type]
        statement=("Your priorities matter here: " + "; ".join(parts) + ".") if flips else
        "The winner is the same whether you weigh money alone or lifestyle most."))
    return out
