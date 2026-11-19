"""Real-world phrasings of job title and office city (added after a user's PDF letter went unread).

Each case is checked as plain text and as a generated PDF, so the PDF text path is covered too.
"""

import asyncio

import pytest
from fpdf import FPDF

from backend.agents.offer_parser import run
from backend.core.models import ManualOfferForm, OfferParserInput
from backend.services.rules_extractor import extract_fields
from backend.services.text_extract import _poorly_spaced, extract_text

PHRASINGS = {
    'job_title_label': ('Job Title: Staff Accountant\nWork Location: Chicago, Illinois\nAnnual Salary: $68,000', 'Staff Accountant', 'Chicago'),
    'position_title_label': ('Position Title: Associate Consultant\nLocation: Atlanta, GA\nStarting Salary: $75,000', 'Associate Consultant', 'Atlanta'),
    'employment_with_as': ('We are pleased to offer you employment with Orion Health as a Business Analyst. Your base salary will be $70,000.', 'Business Analyst', None),
    'join_team_as': ("We're thrilled to invite you to join our team as a Marketing Coordinator at our Denver location. Salary: $55,000 per year.", 'Marketing Coordinator', 'Denver'),
    'title_will_be': ('Your title will be Financial Analyst I and you will report to the Controller. Your salary will be $72,000 annually.', 'Financial Analyst I', None),
    'role_of': ('This letter confirms our offer for the role of Software Engineer. Salary $110,000.', 'Software Engineer', None),
    'location_will_be': ('Your primary work location will be Dallas, Texas. Base salary of $80,000 per year.', None, 'Dallas'),
    'based_out_of': ('You will be based out of our Phoenix office. Salary: $65,000.', None, 'Phoenix'),
    'located_in_nostate': ('This position is located in Seattle and is hybrid. Base pay: $90,000 per year.', None, 'Seattle'),
    'for_position_of': ('We are delighted to offer you the position of Audit Assistant at Crestline CPAs in Houston, TX.', 'Audit Assistant', 'Houston'),
    'offer_for_position': ('Congratulations! We are excited to extend an offer for the Data Analyst position at Northbeam in Minneapolis, Minnesota. Salary: $74,000.', 'Data Analyst', 'Minneapolis'),
    'caps_location': ('POSITION: TAX ASSOCIATE\nLOCATION: NEW YORK, NY\nSALARY: $90,000', 'Tax Associate', 'New York'),
    'table_no_colon': ('Position Junior Data Analyst\nLocation Boston, MA\nBase Salary $72,000', 'Junior Data Analyst', 'Boston'),
    'worksite': ('Worksite: 500 Market St, San Francisco, CA 94105. Position: Product Analyst. Compensation: $105,000 annually.', 'Product Analyst', 'San Francisco'),
    'offer_you_a': ('We would like to offer you a full-time position as an Investment Banking Analyst in our Charlotte office.', 'Investment Banking Analyst', 'Charlotte'),
    'hr_system': ('ACME CORPORATION\n100 Corporate Pkwy, Hartford, CT 06103\n\nDear Jordan,\nWe are pleased to confirm our offer of employment. The details are below.\nTitle: Supply Chain Analyst\nDepartment: Operations\nReports To: Director of Logistics\nWork Location: Columbus, OH\nBase Salary: $66,000 per year\nStart Date: June 15, 2026', 'Supply Chain Analyst', 'Columbus'),
    'narrative': ('Dear Priya, On behalf of Lumen Bank, I am delighted to offer you a position on our Treasury team. You will join us as a Treasury Analyst, working out of our Miami, Florida office. Your starting salary is $71,500.', 'Treasury Analyst', 'Miami'),
    'email_short': ('hi alex - official offer: product designer @ Kite, based in Portland OR (hybrid). base 98k. start 7/1/2026', 'Product Designer', 'Portland'),
    'lowercase_role': ('We are excited to offer you the position of software engineer II at Vantage. This role is located in San Diego, California.', 'Software Engineer II', 'San Diego'),
    'remote_hub': ('Congratulations on your offer for the Customer Success Manager role! This position is remote, attached to our Austin hub. Salary $78,000.', 'Customer Success Manager', 'Austin'),
    'nyc_alias': ('Your position will be Investment Associate, located at our NYC headquarters. Base compensation of $115,000.', 'Investment Associate', 'New York'),
    'signature_trap': ("We'd like to offer you the Marketing Analyst role in Detroit, MI. Salary: $60,000.\nBest,\nDana Lee\nSenior Recruiter, HR", 'Marketing Analyst', 'Detroit'),
}


def _pdf(text: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in text.split("\n"):
        pdf.multi_cell(0, 7, line.encode("latin-1", "replace").decode("latin-1"), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


@pytest.mark.parametrize("mode", ["text", "pdf"])
@pytest.mark.parametrize("key", sorted(PHRASINGS))
def test_title_and_city(key, mode):
    text, title, city = PHRASINGS[key]
    src = text if mode == "text" else extract_text(_pdf(text), "offer.pdf").text
    f, _ = extract_fields(src)
    if title:
        assert (f.job_title.value or "").lower() == title.lower()
    if city:
        assert (f.office_city.value or "").lower() == city.lower()
        assert f.office_state.value is not None


def test_signature_titles_are_not_the_job():
    f, _ = extract_fields("Congratulations again!\nSincerely,\nDana Lee\nSenior Recruiter")
    assert f.job_title.value is None


def test_user_corrections_override_and_fill():
    out = asyncio.run(run(OfferParserInput(
        offer_id="A", source="text",
        text="Congratulations! Your base salary will be $64,000 per year. We look forward to having you start on June 1, 2026.",
        form=ManualOfferForm(office_city="Denver", office_state="CO", job_title="Operations Analyst"))))
    assert out.fields.job_title.value == "Operations Analyst" and out.fields.job_title.status == "user_entered"
    assert out.location.matched and out.location.metro_name.startswith("Denver")
    assert out.fields.base_salary.value == 64_000  # still read from the letter


def test_missing_title_and_city_are_flagged():
    out = asyncio.run(run(OfferParserInput(offer_id="A", source="text",
                                           text="Congratulations on your offer! Your base salary will be $64,000 per year.")))
    joined = " ".join(out.warnings)
    assert "Job title not found" in joined and "Office city not found" in joined


def test_glued_pdf_text_is_detected():
    assert _poorly_spaced("WearepleasedtoofferyouthepositionofAnalystinourChicagooffice Salary $70,000")
    assert not _poorly_spaced("We are pleased to offer you the position of Analyst in our Chicago office.")
