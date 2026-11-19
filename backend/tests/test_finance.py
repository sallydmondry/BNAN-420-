"""Deterministic money math: taxes vs. independent ground truth, match formulas, budgets."""

import json

import pytest

from backend.core import finance
from backend.core.config import SAMPLES_DIR
from backend.core.models import Extracted, Match401k, MatchTier, OfferFields, UserProfile
from backend.data import lookups as L

GT = json.loads((SAMPLES_DIR / "ground_truth.json").read_text())


@pytest.mark.parametrize("key", sorted(GT["offers"]))
def test_take_home_matches_independent_worksheet(key):
    o = GT["offers"][key]
    f, th = o["fields"], o["take_home"]
    c = L.tax_for(f["office_state"], f["office_city"], f["base_salary"], 6, 1440)
    assert c.take_home == pytest.approx(th["take_home_annual"], abs=0.02)
    assert c.federal_tax == pytest.approx(th["federal_tax"], abs=0.02)
    assert c.state_tax == pytest.approx(th["state_tax"], abs=0.02)
    assert c.local_tax == pytest.approx(th["local_tax"], abs=0.02)


def test_tiered_match():
    m = Match401k(tiers=[MatchTier(rate=1.0, on_pct=3), MatchTier(rate=0.5, on_pct=2)])
    assert finance.employer_match(m, 100_000, 6) == pytest.approx(4_000)  # 3% + 1%
    assert finance.employer_match(m, 100_000, 4) == pytest.approx(3_500)  # 3% + 0.5%
    assert finance.employer_match(m, 100_000, 0) == 0
    assert finance.max_match_contribution_pct(m) == 5


def test_safe_harbor_paid_without_contribution():
    m = Match401k(nonelective_pct=3)
    assert finance.employer_match(m, 70_000, 0) == pytest.approx(2_100)


def test_hourly_annualized():
    f = OfferFields(hourly_rate=Extracted(value=25.0, status="stated"), hours_per_week=Extracted(value=30.0, status="stated"))
    assert finance.annual_salary(f) == pytest.approx(25 * 30 * 52)
    f2 = OfferFields(hourly_rate=Extracted(value=25.0, status="stated"))
    assert finance.annual_salary(f2) == pytest.approx(25 * 40 * 52)


def test_budget_roommates_splits_rent():
    cbsa = L.resolve_city("Austin", "TX").cbsa
    alone = finance.compute_budget("A", cbsa, "Austin", "alone")
    shared = finance.compute_budget("A", cbsa, "Austin", "roommates", 1)
    assert alone.computed and shared.computed
    two_br = L.rent_for(cbsa, 2).unit_rent
    assert shared.rent_monthly == pytest.approx(two_br / 2, abs=0.01)
    assert shared.bedrooms == 2 and shared.share_divisor == 2
    assert all(l.source is not None and l.formula for l in alone.lines)


def test_rent_adjust_and_left_over():
    cbsa = L.resolve_city("Denver", "CO").cbsa
    b0 = finance.compute_budget("A", cbsa, "Denver")
    b1 = finance.compute_budget("A", cbsa, "Denver", rent_adjust_pct=10)
    assert b1.rent_monthly == pytest.approx(b0.rent_monthly * 1.1, abs=0.02)
    t = finance.compute_tax("A", 80_000, "CO", "Denver", 6, 120)
    p = UserProfile(student_loan_monthly=300, extras_monthly=50)
    left = finance.money_left_over(t, b0, p)
    assert left == pytest.approx(t.take_home_monthly - b0.rent_monthly - b0.living_costs_monthly - 350, abs=0.02)


def test_unknown_salary_not_computed():
    t = finance.compute_tax("A", None, "TX", "Austin", 6, 120)
    assert not t.computed
    assert finance.money_left_over(t, finance.compute_budget("A", None, None), UserProfile()) is None


def test_comp_includes_one_time_and_equity():
    f = OfferFields(base_salary=Extracted(value=100_000.0, status="stated"), signing_bonus=Extracted(value=10_000.0, status="stated"),
                    bonus_target_pct=Extracted(value=10.0, status="stated"))
    c = finance.compensation(f, UserProfile(bonus_payout_pct=50, contribution_401k_pct=0))
    assert c["comp_1yr"] == pytest.approx(100_000 + 10_000 + 5_000)
    assert c["comp_3yr"] > 3 * 100_000
