"""Build the 6 SIMULATED sample comparisons (fictional companies) + ground_truth.json.

    python -m backend.data.build_samples

Offer letters are written by hand below in deliberately varied, messy formats and rendered to
plain text, PDF (fpdf2) or a photo-like PNG (Pillow). GROUND_TRUTH lists the correct field values
for each letter, typed by hand from the letter text — NOT produced by the parser. Expected take-home
pay comes from the independent worksheet in backend/tests/ground_truth_worksheet.py.
"""

from __future__ import annotations

import json
import random
import re
import textwrap
from pathlib import Path

from backend.core.config import SAMPLES_DIR
from backend.tests.ground_truth_worksheet import worksheet

OFFERS_DIR = SAMPLES_DIR / "offers"
SIM_NOTE = "SIMULATED SAMPLE - fictional company, for demonstration only."

# ---------------------------------------------------------------------------
# Letters
# ---------------------------------------------------------------------------

LETTERS: dict[str, str] = {}

LETTERS["s1_A"] = """\
From: Dana Whitfield <recruiting@meridianstrategy.example>
Subject: Your offer from Meridian Strategy Partners!!
Date: Mon, Mar 2, 2026

Hi Jordan,

Congrats again - the whole team loved meeting you. Pasting the official details below so you have
them in writing (PDF to follow from HR):

  Position ......... Business Analyst, Phoenix office (2 N Central Ave, Phoenix, AZ 85004)
  Start date ....... July 13, 2026
  Base salary ...... $72,000 per year, paid semi-monthly
  Sign-on bonus .... $5,000 (paid in first paycheck; repayable if you leave within 12 months)
  Annual bonus ..... target of 10% of base, based on firm + individual performance
  Relocation ....... up to $3,000 lump sum

Benefits highlights: medical/dental/vision day one; 401(k) with a 100% company match on the first 4% you
contribute; the firm also puts $500/yr into your HSA if you pick the HDHP plan. 15 days PTO + 10 paid holidays.

We're hybrid - 3 days a week in the office (Tue-Thu).

Please let me know by March 16 if you can! Happy to set up a call w/ the hiring manager.

Dana
Campus Recruiting | Meridian Strategy Partners
"""

LETTERS["s1_B"] = """\
HALCYON ADVISORY GROUP
1700 Lincoln Street, Suite 2400, Denver, CO 80203

March 4, 2026

Dear Jordan Lee,

On behalf of Halcyon Advisory Group ("Halcyon"), I am pleased to offer you the position of Associate
Consultant in our Denver office, reporting to the Operations Excellence practice lead. Your anticipated
start date is August 3, 2026.

Compensation. Your starting annual base salary will be $78,000.00, less applicable withholdings, paid
bi-weekly. You will also receive a one-time signing bonus of $8,000, payable within 30 days of your start
date. You will be eligible for an annual performance bonus with a target of 8% of your base salary.

Benefits. You will be eligible to participate in the Halcyon 401(k) Plan. Halcyon matches 50% of your
contributions up to 6% of eligible pay. You will accrue 20 days of paid time off per year in addition to
company holidays.

Work location. This is an in-office role; consultants are expected on-site at the Denver office or at
client sites five days per week.

This offer is contingent upon a satisfactory background check. Please sign and return by March 18, 2026.

Sincerely,
Marcus Okafor
Director, Talent Acquisition
"""

LETTERS["s2_A"] = """\
BLUEGATE SOFTWARE, INC.
500 W 2nd St, Austin, TX 78701

OFFER OF EMPLOYMENT

February 20, 2026

Dear Sam,

We are excited to offer you the role of Data Analyst on our Revenue Analytics team, based in Austin, Texas.

Base Salary: $85,000 annually.
Signing Bonus: $5,000, paid with your first regular paycheck.
Annual Bonus: You are eligible for a target bonus of 5% of base salary.
Equity: A grant of restricted stock units with an approximate value of $12,000, vesting over 4 years.
401(k): Bluegate matches dollar-for-dollar up to 5% of your salary.
Time Off: 18 days of PTO per year plus 9 company holidays.
Work Arrangement: Hybrid - in office Monday, Tuesday and Thursday.
Start Date: June 8, 2026.

We look forward to having you on the team.

Priya Raman
VP, People
"""

LETTERS["s2_B"] = """\
Quillfeather Analytics -- offer summary (please read carefully)

hey Sam! here's everything in one place:

* title: Product Analyst, Growth
* office: 350 Mission St, San Francisco, CA 94105 (in office 4 days/wk, Fridays WFH)
* base: $112K/yr
* sign-on: $15,000 cash, paid in two installments (half at start, half at 6 months)
* equity: $40,000 in RSUs over four years, 1-year cliff then quarterly
* 401k: we match 100% of the first 3% and 50% of the next 2% you put in
* time off: flexible / unlimited PTO
* relocation: $7,500 relocation stipend
* start: 6/22/2026

(bonus: not part of this role's comp plan)

let me know if you have q's!! - Theo @ Quillfeather recruiting
"""

LETTERS["s3_A"] = """\
GRANITE HARBOR CAPITAL LLC
One Liberty Plaza, New York, NY 10006

March 9, 2026

Dear Alex Moreno:

We are pleased to extend an offer of employment for the position of Financial Analyst in the Corporate
Finance group at our New York headquarters, commencing on July 6, 2026.

Your base salary will be at the annual rate of ninety-five thousand dollars ($95,000), payable in accordance
with the Firm's regular payroll practices. You will receive a sign-on bonus of $10,000 payable within your
first month of employment. You will be eligible to participate in the Firm's discretionary annual incentive
program, with a target award of 15% of base salary.

You will be eligible for the Firm's benefit programs, including the Granite Harbor 401(k) Savings Plan, under
which the Firm matches 50% of employee deferrals up to 6% of base salary. Analysts receive 15 vacation days
per year.

This position is based in our office five days per week.

Very truly yours,
Human Capital Management
Granite Harbor Capital LLC
"""

LETTERS["s3_B"] = """\
PIEDMONT RIDGE BANK
Corporate Banking - Analyst Program
301 S Tryon St, Charlotte, NC 28202

March 11, 2026

Dear Alex,

Congratulations! We are delighted to offer you a position as a Corporate
Banking Analyst in Charlotte, North Carolina, starting July 20, 2026.

- Annual base salary: $87,000
- Signing bonus: $7,500
- Annual incentive target: 12% of base salary
- 401(k): the Bank matches 100% of your contributions
  up to 6% of eligible pay
- HSA: the Bank contributes $1,000 per year to your
  Health Savings Account
- Paid time off: 20 days per year
- Relocation assistance: $5,000
- Hybrid schedule: in office 3 days per week

Please return your signed offer by March 25, 2026.

Warm regards,
Renee Castillo, Campus Recruiting
"""

LETTERS["s4_A"] = """\
LAKESHORE & WHITBY LLP
Certified Public Accountants
233 S Wacker Drive, Chicago, IL 60606

February 27, 2026

Dear Taylor Nguyen,

Lakeshore & Whitby LLP (the "Firm") is pleased to offer you employment as an Audit Associate in our Chicago
office. Your first day will be September 8, 2026.

Your starting salary will be $70,000 per year. You will receive a $3,000 signing bonus upon your start date.
Associates are eligible for a discretionary year-end bonus based on performance.

The Firm makes a safe harbor contribution equal to 3% of your eligible compensation to the Firm's 401(k)
plan each year, whether or not you contribute. You will receive 18 days of paid time off per year. In
addition, the Firm will reimburse CPA exam fees and review course costs up to $3,000.

This is an in-person role based in our Chicago office and at client locations.

Sincerely,
Elena Brooks, Partner - Human Resources
"""

LETTERS["s4_B"] = """\
Subject: Trinity Ledger Partners - Staff Accountant (Tax) offer

Taylor,

Thanks for your patience! Here are the terms we discussed:

Role: Staff Accountant - Tax
Location: Dallas, TX (2100 McKinney Ave). Hybrid: 2 days remote per week outside of busy season.
Salary: $66,500 annually
Signing bonus: $2,500
Bonus: target 5% of base, paid each July
401(k): 100% match on contributions up to 4% of salary, vests immediately
HSA: firm contributes $600 annually
PTO: 15 days
Start: 9/14/2026

-- Ryan Delgado, Talent Team, Trinity Ledger Partners
"""

LETTERS["s5_A"] = """\
Cascade Brightline | offer details

Hi Morgan - so excited to make this official! :)

Role: Associate Marketing Manager, Lifecycle & CRM
Where: Seattle, WA (Pioneer Square office) - hybrid, 3 days in office
Start: August 17, 2026
Base: $68,000/year
401(k): Cascade Brightline matches 50% of what you contribute, up to 8% of pay
Time off: unlimited PTO (most folks take ~4 weeks)

No signing bonus for this level, sorry! Benefits start the first of the month after you join.

Cheers,
Jess, People Ops
"""

LETTERS["s5_B"] = """\
CUMBERLAND CREATIVE CO.
900 Division Street, Nashville, TN 37203

March 3, 2026

Dear Morgan Patel,

It is our pleasure to offer you the position of Marketing Specialist with Cumberland Creative Co. in
Nashville, Tennessee. Your expected start date is August 10, 2026.

Your annual base salary will be $58,000, paid bi-weekly. You will receive a $2,000 signing bonus and will be
eligible for an annual bonus with a target of 5% of your base salary. We will also provide $2,500 toward
relocation expenses.

Cumberland Creative Co. matches 100% of your 401(k) contributions up to 3% of salary. You will receive 15 days
of paid time off each year. This position is on-site at our Nashville studio.

Best regards,
Caroline Webb, Studio Director
"""

LETTERS["s6_A"] = """\
Saguaro Data Works - Offer Letter

Dear Riley,

We'd love for you to join Saguaro Data Works as a Junior Data Analyst in our Tucson, Arizona office!

Here's a quick summary:
Salary: $62,000 annually
401(k): we match 100% of the first 4% you contribute
PTO: 15 days a year, plus your birthday off
Start date: June 29, 2026
Work style: hybrid (2 days in office)

Excited to have you!
Luis Ortega, Founder & CEO
"""

LETTERS["s6_B"] = """\
ALLEGHENY ANALYTICS
Two PPG Place, Pittsburgh, PA 15222

March 6, 2026

Dear Riley Johnson,

We are pleased to offer you the position of Data Analyst I in our Pittsburgh, Pennsylvania office, beginning
July 6, 2026.

Annual base salary: $68,000
Signing bonus: $4,000
Annual bonus target: 5% of base salary
401(k): the Company matches 50% of employee contributions up to 6% of salary
Paid time off: 20 days per year

This is an on-site position.

Sincerely,
Gwen Hartley, HR Business Partner
"""

LETTERS["s6_C"] = """\
Oak City Insights // Offer

Riley -

Pleased to offer you the Analytics Associate role on our client analytics team in Raleigh, NC.

   Base salary: $70,000/yr
   Signing bonus: $3,000
   Annual bonus target: 7.5% of base
   401(k): 100% of the first 4% (immediate vesting)
   HSA: $750 employer contribution each year
   PTO: 18 days
   Hybrid - Mon/Wed/Thu in office (Raleigh, 421 Fayetteville St)
   Start date: July 13, 2026

Best,
Hannah Cho - Recruiting, Oak City Insights
"""

# ---------------------------------------------------------------------------
# Ground truth (typed by hand from the letters above)
# ---------------------------------------------------------------------------


def M(*tiers: tuple[float, float], nonelective: float = 0.0) -> dict:
    return {"tiers": [{"rate": r, "on_pct": p} for r, p in tiers], "nonelective_pct": nonelective}


GROUND_TRUTH: dict[str, dict] = {
    "s1_A": dict(company="Meridian Strategy Partners", job_title="Business Analyst", office_city="Phoenix", office_state="AZ",
                 base_salary=72000, signing_bonus=5000, bonus_target_pct=10, match_401k=M((1.0, 4)), hsa_employer_annual=500,
                 pto_days=15, pto_unlimited=False, relocation=3000, equity_value_usd=None, start_date="2026-07-13", work_arrangement="hybrid"),
    "s1_B": dict(company="Halcyon Advisory Group", job_title="Associate Consultant", office_city="Denver", office_state="CO",
                 base_salary=78000, signing_bonus=8000, bonus_target_pct=8, match_401k=M((0.5, 6)), hsa_employer_annual=None,
                 pto_days=20, pto_unlimited=False, relocation=None, equity_value_usd=None, start_date="2026-08-03", work_arrangement="onsite"),
    "s2_A": dict(company="Bluegate Software", job_title="Data Analyst", office_city="Austin", office_state="TX",
                 base_salary=85000, signing_bonus=5000, bonus_target_pct=5, match_401k=M((1.0, 5)), hsa_employer_annual=None,
                 pto_days=18, pto_unlimited=False, relocation=None, equity_value_usd=12000, start_date="2026-06-08", work_arrangement="hybrid"),
    "s2_B": dict(company="Quillfeather Analytics", job_title="Product Analyst", office_city="San Francisco", office_state="CA",
                 base_salary=112000, signing_bonus=15000, bonus_target_pct=None, match_401k=M((1.0, 3), (0.5, 2)), hsa_employer_annual=None,
                 pto_days=None, pto_unlimited=True, relocation=7500, equity_value_usd=40000, start_date="2026-06-22", work_arrangement="hybrid"),
    "s3_A": dict(company="Granite Harbor Capital", job_title="Financial Analyst", office_city="New York", office_state="NY",
                 base_salary=95000, signing_bonus=10000, bonus_target_pct=15, match_401k=M((0.5, 6)), hsa_employer_annual=None,
                 pto_days=15, pto_unlimited=False, relocation=None, equity_value_usd=None, start_date="2026-07-06", work_arrangement="onsite"),
    "s3_B": dict(company="Piedmont Ridge Bank", job_title="Corporate Banking Analyst", office_city="Charlotte", office_state="NC",
                 base_salary=87000, signing_bonus=7500, bonus_target_pct=12, match_401k=M((1.0, 6)), hsa_employer_annual=1000,
                 pto_days=20, pto_unlimited=False, relocation=5000, equity_value_usd=None, start_date="2026-07-20", work_arrangement="hybrid"),
    "s4_A": dict(company="Lakeshore & Whitby LLP", job_title="Audit Associate", office_city="Chicago", office_state="IL",
                 base_salary=70000, signing_bonus=3000, bonus_target_pct=None, match_401k=M(nonelective=3), hsa_employer_annual=None,
                 pto_days=18, pto_unlimited=False, relocation=None, equity_value_usd=None, start_date="2026-09-08", work_arrangement="onsite"),
    "s4_B": dict(company="Trinity Ledger Partners", job_title="Staff Accountant - Tax", office_city="Dallas", office_state="TX",
                 base_salary=66500, signing_bonus=2500, bonus_target_pct=5, match_401k=M((1.0, 4)), hsa_employer_annual=600,
                 pto_days=15, pto_unlimited=False, relocation=None, equity_value_usd=None, start_date="2026-09-14", work_arrangement="hybrid"),
    "s5_A": dict(company="Cascade Brightline", job_title="Associate Marketing Manager", office_city="Seattle", office_state="WA",
                 base_salary=68000, signing_bonus=None, bonus_target_pct=None, match_401k=M((0.5, 8)), hsa_employer_annual=None,
                 pto_days=None, pto_unlimited=True, relocation=None, equity_value_usd=None, start_date="2026-08-17", work_arrangement="hybrid"),
    "s5_B": dict(company="Cumberland Creative Co.", job_title="Marketing Specialist", office_city="Nashville", office_state="TN",
                 base_salary=58000, signing_bonus=2000, bonus_target_pct=5, match_401k=M((1.0, 3)), hsa_employer_annual=None,
                 pto_days=15, pto_unlimited=False, relocation=2500, equity_value_usd=None, start_date="2026-08-10", work_arrangement="onsite"),
    "s6_A": dict(company="Saguaro Data Works", job_title="Junior Data Analyst", office_city="Tucson", office_state="AZ",
                 base_salary=62000, signing_bonus=None, bonus_target_pct=None, match_401k=M((1.0, 4)), hsa_employer_annual=None,
                 pto_days=15, pto_unlimited=False, relocation=None, equity_value_usd=None, start_date="2026-06-29", work_arrangement="hybrid"),
    "s6_B": dict(company="Allegheny Analytics", job_title="Data Analyst I", office_city="Pittsburgh", office_state="PA",
                 base_salary=68000, signing_bonus=4000, bonus_target_pct=5, match_401k=M((0.5, 6)), hsa_employer_annual=None,
                 pto_days=20, pto_unlimited=False, relocation=None, equity_value_usd=None, start_date="2026-07-06", work_arrangement="onsite"),
    "s6_C": dict(company="Oak City Insights", job_title="Analytics Associate", office_city="Raleigh", office_state="NC",
                 base_salary=70000, signing_bonus=3000, bonus_target_pct=7.5, match_401k=M((1.0, 4)), hsa_employer_annual=750,
                 pto_days=18, pto_unlimited=False, relocation=None, equity_value_usd=None, start_date="2026-07-13", work_arrangement="hybrid"),
}

# (sample_id, title, description, [(offer_key, format)], profile)
SAMPLES = [
    ("consulting-phx-den", "Consulting: Phoenix vs. Denver", "Business Analyst in Phoenix vs. Associate Consultant in Denver",
     [("s1_A", "txt"), ("s1_B", "pdf")], {"student_loan_monthly": 350, "housing": "alone", "home_city": "Tucson, AZ"}),
    ("tech-aus-sf", "Tech analyst: Austin vs. San Francisco", "A $27K higher SF salary vs. no state income tax in Austin",
     [("s2_A", "pdf"), ("s2_B", "txt")], {"student_loan_monthly": 300, "housing": "roommates", "roommates": 1, "home_city": "Dallas, TX"}),
    ("finance-nyc-clt", "Finance: New York vs. Charlotte", "NYC pays $8K more. Is it actually worth more?",
     [("s3_A", "txt"), ("s3_B", "png")], {"student_loan_monthly": 400, "housing": "alone", "home_city": "Richmond, VA"}),
    ("accounting-chi-dal", "Accounting: Chicago vs. Dallas", "Big-firm audit in Chicago vs. tax in Dallas",
     [("s4_A", "pdf"), ("s4_B", "txt")], {"student_loan_monthly": 250, "housing": "roommates", "roommates": 1, "home_city": "Milwaukee, WI"}),
    ("marketing-sea-bna", "Marketing: Seattle vs. Nashville", "Higher Seattle pay vs. lower Nashville costs",
     [("s5_A", "txt"), ("s5_B", "pdf")], {"student_loan_monthly": 200, "housing": "alone", "home_city": "Portland, OR"}),
    ("data-3way", "Data analyst: Tucson vs. Pittsburgh vs. Raleigh", "Three offers, three tax systems (incl. a city tax)",
     [("s6_A", "txt"), ("s6_B", "pdf"), ("s6_C", "txt")], {"student_loan_monthly": 300, "housing": "alone", "home_city": "Phoenix, AZ"}),
]

SLUGS = {"s1_A": "meridian", "s1_B": "halcyon", "s2_A": "bluegate", "s2_B": "quillfeather", "s3_A": "granite-harbor",
         "s3_B": "piedmont-ridge", "s4_A": "lakeshore-whitby", "s4_B": "trinity-ledger", "s5_A": "cascade-brightline",
         "s5_B": "cumberland-creative", "s6_A": "saguaro", "s6_B": "allegheny", "s6_C": "oak-city"}

# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_pdf(text: str, path: Path) -> None:
    """Formal letter PDF with a letterhead line and a simulated-data footer."""
    from fpdf import FPDF

    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(True, margin=20)
    pdf.add_page()
    pdf.set_margins(22, 20, 22)
    lines = text.splitlines()
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 8, lines[0], new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(12, 35, 75)
    pdf.line(22, pdf.get_y() + 1, 194, pdf.get_y() + 1)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 10.5)
    for para in "\n".join(lines[1:]).split("\n\n"):
        plines = para.split("\n")
        is_list = all(re.match(r"^\s*(-|\*|[A-Z][\w() ]{1,30}:)", ln) for ln in plines if ln.strip())
        pdf.multi_cell(0, 5.4, para if (is_list or len(plines) <= 3 and len(para) < 160) else " ".join(plines))
        pdf.ln(2.5)
    pdf.set_y(-18)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 6, SIM_NOTE, align="C")
    pdf.output(str(path))


def render_photo(text: str, path: Path, seed: int = 7) -> None:
    """Render the letter as a slightly rotated, unevenly lit 'phone photo' of a printed page."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    rng = random.Random(seed)
    W, H = 1275, 1650
    page = Image.new("RGB", (W, H), (252, 251, 247))
    d = ImageDraw.Draw(page)
    font_paths = ["/System/Library/Fonts/Supplemental/Times New Roman.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]
    fp = next((p for p in font_paths if Path(p).exists()), None)
    font = ImageFont.truetype(fp, 30) if fp else ImageFont.load_default()
    bold = ImageFont.truetype(fp, 40) if fp else font
    y = 110
    for i, line in enumerate(text.splitlines()):
        for chunk in (textwrap.wrap(line, 62) or [""]):
            d.text((100, y), chunk, fill=(25, 25, 30), font=bold if i == 0 else font)
            y += 52 if i == 0 else 41
    d.text((100, H - 90), SIM_NOTE, fill=(120, 120, 120), font=ImageFont.truetype(fp, 22) if fp else font)
    page = page.rotate(rng.uniform(-2.2, -1.2), expand=True, fillcolor=(70, 66, 60), resample=Image.BICUBIC)
    bg = Image.new("RGB", (page.width + 120, page.height + 120), (64, 60, 55))
    bg.paste(page, (60, 60))
    # uneven lighting: darken toward one corner
    shade = Image.linear_gradient("L").resize(bg.size).rotate(35, expand=False)
    bg = Image.composite(bg, Image.new("RGB", bg.size, (150, 145, 135)), shade.point(lambda v: 170 + v * 85 // 255))
    bg = bg.filter(ImageFilter.GaussianBlur(0.8))
    px = bg.load()
    for _ in range(9000):
        x, yy = rng.randrange(bg.width), rng.randrange(bg.height)
        r, g, b = px[x, yy]
        n = rng.randint(-18, 18)
        px[x, yy] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    bg = bg.resize((bg.width * 3 // 4, bg.height * 3 // 4))
    bg.save(path, quality=88)


def main() -> None:
    OFFERS_DIR.mkdir(parents=True, exist_ok=True)
    catalog, truth = [], {"simulated": True, "disclaimer": SIM_NOTE, "assumptions": {
        "contribution_401k_pct": 6, "health_premium_annual": 1440, "filing_status": "single", "tax_year": 2026,
        "method": "independent worksheet (backend/tests/ground_truth_worksheet.py) with constants typed from primary sources"},
        "offers": {}}
    for sid, title, desc, offers, profile in SAMPLES:
        entries = []
        for i, (key, fmt) in enumerate(offers):
            letter = "A" if i == 0 else "B" if i == 1 else "C"
            fname = f"{key}_{SLUGS[key]}.{ 'txt' if fmt == 'txt' else fmt}"
            path = OFFERS_DIR / fname
            body = LETTERS[key]
            if fmt == "txt":
                path.write_text(body + "\n[" + SIM_NOTE + "]\n")
            elif fmt == "pdf":
                render_pdf(body, path)
            else:
                render_photo(body, path)
            gt = GROUND_TRUTH[key]
            ws = worksheet(gt["base_salary"], gt["office_state"], gt["office_city"], 6.0, 1440.0)
            truth["offers"][key] = {"sample_id": sid, "file": fname, "format": fmt, "fields": gt, "take_home": ws}
            entries.append({"offer_id": letter, "key": key, "file": fname, "format": fmt, "label": f"Offer {letter}"})
        catalog.append({"id": sid, "title": title, "description": desc, "simulated": True, "offers": entries,
                        "profile": profile})
    (SAMPLES_DIR / "samples.json").write_text(json.dumps({"simulated": True, "disclaimer": SIM_NOTE, "samples": catalog}, indent=1))
    (SAMPLES_DIR / "ground_truth.json").write_text(json.dumps(truth, indent=1))
    for k, v in truth["offers"].items():
        print(f"{k:5s} {v['format']:3s} {v['fields']['company']:28s} ${v['fields']['base_salary']:>9,.0f} -> take-home ${v['take_home']['take_home_monthly']:,.2f}/mo")


if __name__ == "__main__":
    main()
