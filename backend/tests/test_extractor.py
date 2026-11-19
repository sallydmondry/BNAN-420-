"""Offer Parser: every sample against ground truth, plus letters it has never seen."""

import asyncio
import json

import pytest

from backend.agents import offer_parser
from backend.core.config import SAMPLES_DIR
from backend.core.models import ManualOfferForm, OfferParserInput
from backend.services.rules_extractor import extract_fields
from backend.services.text_extract import UnsupportedFile, extract_text
from backend.tests.run_pipeline_eval import _eq, _got

GT = json.loads((SAMPLES_DIR / "ground_truth.json").read_text())["offers"]


@pytest.mark.parametrize("key", sorted(GT))
def test_sample_fields(key):
    o = GT[key]
    p = SAMPLES_DIR / "offers" / o["file"]
    fields, _ = extract_fields(extract_text(p.read_bytes(), p.name).text)
    got = _got(fields)
    bad = {k: (v, got[k]) for k, v in o["fields"].items() if not _eq(got[k], v)}
    assert not bad, bad


def test_not_stated_is_not_guessed():
    f, _ = extract_fields("Hi Sam, we're excited to offer you the Analyst role in Denver, CO. Base salary: $70,000 per year.")
    assert f.base_salary.value == 70_000
    for name in ("signing_bonus", "bonus_target_pct", "match_401k", "pto_days", "relocation", "equity", "start_date"):
        assert getattr(f, name).status == "not_stated", name


def test_hourly_letter():
    f, _ = extract_fields("Northwind Labs is happy to offer you the position of Lab Technician in our Columbus, Ohio office. "
                          "Your pay rate will be $24.50 per hour for 40 hours per week. We offer a 401(k) with a 3% employer match.")
    assert f.company.value == "Northwind Labs"
    assert f.pay_basis == "hourly" and f.base_salary.status == "derived"
    assert f.base_salary.value == pytest.approx(24.5 * 40 * 52)
    assert f.match_401k.value.tiers[0].on_pct == 3


def test_monthly_remote_no_bonus():
    f, _ = extract_fields("Hello Jamie! We'd like to offer you the role of Customer Success Associate at Brightwave. This is a fully "
                          "remote position. Compensation: $5,000 per month. There is no signing bonus for this role, and the role is "
                          "not eligible for an annual bonus. Unlimited PTO. Start: 1/5/2027.")
    assert f.base_salary.value == 60_000 and f.pay_basis == "monthly"
    assert f.work_arrangement.value == "remote" and f.pto_unlimited
    assert f.signing_bonus.value == 0 and f.signing_bonus.status == "stated"
    assert f.start_date.value == "2027-01-05"


def test_reimbursements_are_not_comp():
    f, _ = extract_fields("Starting salary: $81,500 annually. We will reimburse up to $5,250 per year in tuition. "
                          "Relocation assistance: $4,000.")
    assert f.base_salary.value == 81_500 and f.relocation.value == 4_000
    assert f.signing_bonus.status == "not_stated"


def test_remote_offer_uses_profile_city():
    out = asyncio.run(offer_parser.run(OfferParserInput(
        offer_id="A", source="text", remote_city_hint="Denver, CO",
        text="We're excited to offer you the Data Analyst role at Brightwave. This is a fully remote position. "
             "Base salary: $75,000 per year. Start date: June 1, 2026.")))
    assert out.location.matched and out.location.basis == "remote_residence"
    assert out.location.metro_name.startswith("Denver")


def test_manual_form():
    out = asyncio.run(offer_parser.run(OfferParserInput(offer_id="B", source="form", form=ManualOfferForm(
        company="Beta", job_title="Developer", office_city="Kansas City", office_state="MO", base_salary=88000,
        match_rate_pct=50, match_up_to_pct=6))))
    assert out.location.matched and out.fields.base_salary.status == "user_entered"
    assert out.fields.match_401k.value.tiers[0].rate == 0.5


def test_non_offer_flagged():
    out = asyncio.run(offer_parser.run(OfferParserInput(offer_id="A", source="text",
                                                        text="Grocery list: apples, bread, milk, eggs, coffee, rice, beans and cheese.")))
    assert not out.is_offer_letter and out.warnings


def test_rejects_binary_garbage():
    with pytest.raises(UnsupportedFile):
        extract_text(b"\x00\x01\x02\xff\xfe" * 100, "x.bin")
