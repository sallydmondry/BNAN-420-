"""Scorecard, sensitivity and text guards."""

import asyncio

from backend.core import scoring
from backend.core.guards import check_dollars, dollar_figures
from backend.core.models import UserProfile
from backend.services.orchestrator import run_pipeline
from backend.tests.run_pipeline_eval import load_samples, sample_inputs


def _state(sample_id):
    s = next(x for x in load_samples()["samples"] if x["id"] == sample_id)
    return asyncio.run(run_pipeline("t-" + sample_id, UserProfile(**s["profile"]), sample_inputs(s), {}, lambda _e: None))


def test_dollar_parsing_and_guard():
    assert dollar_figures("costs $1,234.50 and $85K or $1.2M") == [1234.5, 85_000, 1_200_000]
    assert check_dollars("You keep $1,380 a month.", [1382.4]) == []
    assert check_dollars("You keep $9,999 a month.", [1382.4]) == [9999]


def test_bigger_salary_can_lose():
    st = _state("finance-nyc-clt")
    d = st.decision
    nyc = next(r for r in d.scorecard if r.metro_name.startswith("New York"))
    clt = next(r for r in d.scorecard if r.metro_name.startswith("Charlotte"))
    assert nyc.base_salary > clt.base_salary
    assert d.winner == clt.offer_id and clt.left_over_monthly > nyc.left_over_monthly
    assert "even though" in d.headline


def test_recalculate_matches_pipeline_and_is_stateless():
    st = _state("tech-aus-sf")
    r = scoring.recalculate(st.recalc_context)
    for a, b in zip(sorted(r.scorecard, key=lambda x: x.offer_id), sorted(st.decision.scorecard, key=lambda x: x.offer_id)):
        assert a.left_over_monthly == b.left_over_monthly and a.total_score == b.total_score
    r2 = scoring.recalculate(st.recalc_context, {"housing": "alone"})
    assert all(x.rent_monthly > y.rent_monthly for x, y in zip(sorted(r2.scorecard, key=lambda x: x.offer_id),
                                                               sorted(r.scorecard, key=lambda x: x.offer_id)))


def test_weights_change_winner_or_not_consistently():
    st = _state("data-3way")
    money_only = scoring.recalculate(st.recalc_context, {"weights": {"money_left_over": 100, "total_comp": 0, "lifestyle": 0,
                                                                     "market_position": 0, "culture": 0}})
    best_money = max(money_only.scorecard, key=lambda r: r.left_over_monthly)
    assert money_only.winner == best_money.offer_id


def test_sensitivity_and_generated_text_have_no_new_dollars():
    st = _state("accounting-chi-dal")
    d = st.decision
    assert {s.lever for s in d.sensitivity} >= {"housing", "rent", "bonus_payout", "contribution_401k", "loans", "weights"}
    from backend.core.guards import collect_numbers
    allowed = collect_numbers(st.model_dump()) + scoring.derived_numbers(d.scorecard)
    for t in st.tax.results:  # sums the tax agent itself allows (FICA total, pre-tax total)
        allowed += [t.social_security_tax + t.medicare_tax, t.pretax_401k + t.pretax_health]
    for text in [d.headline, d.recommendation, *d.reasoning, d.negotiation.body] + [r.explanation for r in st.tax.results] + \
            [b.explanation for b in st.col.budgets]:
        assert check_dollars(text, allowed) == [], text
