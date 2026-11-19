"""Generate the SIMULATED employee-review dataset (fictional companies only).

    python -m backend.data.build_simulated

Why simulated: real review sites (e.g. Glassdoor) forbid scraping in their terms. Every company
below is FICTIONAL, every review is machine-generated from phrase banks with a fixed random seed,
and every record carries ``"simulated": true``. Ratings follow the J-shaped distribution typical of
public review sites (many 4s and 5s, a long tail of 1s and 2s), driven by each company's profile.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta

from backend.core.config import SIMULATED_DIR

SEED = 420  # BNAN 420
THEMES = ["work_life", "compensation", "culture", "management", "growth"]

# name, industry, HQ city, profile means per theme (1-5)
COMPANIES = [
    # Consulting
    ("Meridian Strategy Partners", "consulting", "Phoenix, AZ", dict(work_life=3.4, compensation=3.7, culture=4.1, management=3.8, growth=4.2)),
    ("Halcyon Advisory Group", "consulting", "Denver, CO", dict(work_life=2.9, compensation=4.0, culture=3.6, management=3.3, growth=4.3)),
    ("Brightpath Consulting", "consulting", "Chicago, IL", dict(work_life=3.1, compensation=3.5, culture=3.9, management=3.5, growth=3.9)),
    ("Keystone & Vale Advisors", "consulting", "Philadelphia, PA", dict(work_life=2.6, compensation=4.2, culture=3.2, management=3.0, growth=4.4)),
    ("Summit Ridge Consulting", "consulting", "Salt Lake City, UT", dict(work_life=3.9, compensation=3.3, culture=4.2, management=4.0, growth=3.6)),
    ("Copperline Partners", "consulting", "Tucson, AZ", dict(work_life=3.7, compensation=3.2, culture=3.8, management=3.6, growth=3.4)),
    ("Northgate Operations Group", "consulting", "Minneapolis, MN", dict(work_life=3.3, compensation=3.4, culture=3.1, management=2.8, growth=3.5)),
    ("Ironwood Strategy", "consulting", "Atlanta, GA", dict(work_life=2.4, compensation=4.4, culture=3.4, management=3.1, growth=4.5)),
    # Finance
    ("Granite Harbor Capital", "finance", "New York, NY", dict(work_life=2.3, compensation=4.5, culture=3.3, management=3.2, growth=4.1)),
    ("Piedmont Ridge Bank", "finance", "Charlotte, NC", dict(work_life=3.8, compensation=3.7, culture=3.9, management=3.6, growth=3.7)),
    ("Bluewater Securities", "finance", "Miami, FL", dict(work_life=2.8, compensation=4.1, culture=3.0, management=2.9, growth=3.8)),
    ("Lantern Peak Asset Management", "finance", "Boston, MA", dict(work_life=3.5, compensation=4.2, culture=3.8, management=3.7, growth=3.6)),
    ("Redfern Financial", "finance", "Dallas, TX", dict(work_life=3.6, compensation=3.4, culture=3.5, management=3.2, growth=3.3)),
    ("Harborview Trust", "finance", "Seattle, WA", dict(work_life=4.0, compensation=3.5, culture=4.0, management=3.8, growth=3.2)),
    ("Cobalt Street Partners", "finance", "Chicago, IL", dict(work_life=2.5, compensation=4.3, culture=2.9, management=2.7, growth=4.0)),
    ("Sterling Mesa Bank", "finance", "Phoenix, AZ", dict(work_life=3.9, compensation=3.2, culture=3.7, management=3.4, growth=3.1)),
    # Tech
    ("Bluegate Software", "tech", "Austin, TX", dict(work_life=3.9, compensation=3.8, culture=4.0, management=3.6, growth=3.9)),
    ("Quillfeather Analytics", "tech", "San Francisco, CA", dict(work_life=3.2, compensation=4.4, culture=3.7, management=3.3, growth=4.2)),
    ("Saguaro Data Works", "tech", "Tucson, AZ", dict(work_life=4.1, compensation=3.3, culture=4.2, management=3.9, growth=3.5)),
    ("Oak City Insights", "tech", "Raleigh, NC", dict(work_life=3.8, compensation=3.6, culture=3.9, management=3.7, growth=3.8)),
    ("Allegheny Analytics", "tech", "Pittsburgh, PA", dict(work_life=3.6, compensation=3.5, culture=3.4, management=3.1, growth=3.6)),
    ("Pinecrest Cloud", "tech", "Portland, OR", dict(work_life=3.4, compensation=4.0, culture=3.3, management=2.9, growth=3.7)),
    ("Lumen Forge", "tech", "San Jose, CA", dict(work_life=2.9, compensation=4.5, culture=3.5, management=3.2, growth=4.3)),
    ("Driftwood Systems", "tech", "San Diego, CA", dict(work_life=4.2, compensation=3.7, culture=4.3, management=4.0, growth=3.4)),
    # Accounting
    ("Lakeshore & Whitby LLP", "accounting", "Chicago, IL", dict(work_life=2.7, compensation=3.4, culture=3.7, management=3.4, growth=4.3)),
    ("Trinity Ledger Partners", "accounting", "Dallas, TX", dict(work_life=3.5, compensation=3.3, culture=3.9, management=3.6, growth=3.7)),
    ("Calloway Brandt CPAs", "accounting", "Columbus, OH", dict(work_life=3.8, compensation=3.0, culture=4.0, management=3.7, growth=3.3)),
    ("Fairmont & Pike LLP", "accounting", "Washington, DC", dict(work_life=2.5, compensation=3.6, culture=3.3, management=3.1, growth=4.4)),
    ("Ridgeway Assurance Group", "accounting", "Houston, TX", dict(work_life=3.0, compensation=3.5, culture=3.2, management=2.9, growth=3.8)),
    ("Hollis Mercer LLP", "accounting", "Nashville, TN", dict(work_life=3.6, compensation=3.2, culture=4.1, management=3.8, growth=3.6)),
    # Marketing
    ("Cascade Brightline", "marketing", "Seattle, WA", dict(work_life=3.7, compensation=3.4, culture=4.0, management=3.5, growth=3.6)),
    ("Cumberland Creative Co.", "marketing", "Nashville, TN", dict(work_life=4.0, compensation=3.0, culture=4.3, management=3.8, growth=3.4)),
]

PROS = {
    "work_life": ["Reasonable hours most weeks", "Flexible hybrid schedule", "Managers respect PTO", "Rarely work weekends",
                  "Good balance outside busy season", "Summer Fridays are real"],
    "compensation": ["Pay is above what peers get", "Solid annual bonus", "Generous 401(k) match", "Raises keep up with the market",
                     "Signing bonus was a nice touch", "Benefits are strong for a first job"],
    "culture": ["People genuinely help each other", "Smart, friendly analyst class", "Inclusive team environment",
                "Lots of social events for new hires", "Collaborative, low-ego culture", "Great onboarding cohort"],
    "management": ["My manager is a real mentor", "Leadership is transparent about goals", "Regular, useful feedback",
                   "Clear expectations from day one", "Senior people make time for juniors"],
    "growth": ["You learn a ton in year one", "Clear promotion path", "Exposure to senior clients early",
               "Strong formal training program", "Pays for certifications", "Big brand on your resume"],
}
CONS = {
    "work_life": ["Long hours during crunch", "Busy season is brutal", "Expect late nights before deadlines",
                  "Hard to fully disconnect", "Travel can be exhausting", "Weekend work is common"],
    "compensation": ["Base pay lags competitors", "Bonus is unpredictable", "Small raises after year one",
                     "401(k) match vests slowly", "Pay bands are rigid", "Cost of living outpaces salary"],
    "culture": ["Can feel cliquey", "Culture varies a lot by team", "Very competitive among analysts",
                "Return-to-office push hurt morale", "High turnover on some teams"],
    "management": ["Middle management is hit or miss", "Priorities change without explanation", "Feedback is rare",
                   "Leadership feels distant", "Micromanagement on some teams"],
    "growth": ["Promotions are slow", "Work gets repetitive after a year", "Training is mostly self-directed",
               "Hard to move between teams", "Limited mentorship in smaller offices"],
}
TITLES = {
    "consulting": ["Business Analyst", "Associate Consultant", "Consultant", "Senior Consultant"],
    "finance": ["Financial Analyst", "Investment Banking Analyst", "Credit Analyst", "Associate"],
    "tech": ["Data Analyst", "Software Engineer", "Product Analyst", "Analytics Engineer"],
    "accounting": ["Audit Associate", "Tax Associate", "Staff Accountant", "Senior Associate"],
    "marketing": ["Marketing Coordinator", "Marketing Specialist", "Brand Associate", "Content Strategist"],
}
HEADLINES_POS = ["Great place to start a career", "Learned more than I expected", "Would recommend to new grads",
                 "Supportive team, real growth", "Solid first job"]
HEADLINES_MIX = ["Good but demanding", "Depends heavily on your team", "Mixed experience", "Fine for a couple of years"]
HEADLINES_NEG = ["Burned out after a year", "Not what was promised", "Pay doesn't match the workload", "Leadership needs work"]


def _clip(x: float) -> int:
    return int(min(5, max(1, round(x))))


def build() -> dict:
    rng = random.Random(SEED)
    out = {
        "simulated": True,
        "disclaimer": "SIMULATED DATA. All companies are fictional and all reviews are machine-generated for this class "
                      "project. They do not describe any real employer.",
        "generator": "backend/data/build_simulated.py (seed 420)",
        "companies": [],
    }
    start = date(2024, 6, 1)
    for name, industry, hq, profile in COMPANIES:
        n = rng.randint(18, 42)
        reviews = []
        for i in range(n):
            mood = rng.gauss(0.1, 0.75)  # reviewer-level sentiment shared across themes
            if rng.random() < 0.08:  # the disgruntled tail seen on public review sites
                mood -= 2.0
            sub = {t: _clip(profile[t] + mood + rng.gauss(0, 0.6)) for t in THEMES}
            raw = sum(sub.values()) / len(sub) + rng.gauss(0.25, 0.45)  # J-shape: slight upward skew
            overall = _clip(raw)
            best = sorted(THEMES, key=lambda t: -sub[t])
            worst = sorted(THEMES, key=lambda t: sub[t])
            pros = rng.sample(PROS[best[0]], 1) + rng.sample(PROS[best[1]], 1)
            cons = rng.sample(CONS[worst[0]], 1) + (rng.sample(CONS[worst[1]], 1) if overall <= 3 else [])
            head = rng.choice(HEADLINES_POS if overall >= 4 else HEADLINES_MIX if overall == 3 else HEADLINES_NEG)
            reviews.append({
                "id": f"{name[:3].upper()}-{i:03d}",
                "simulated": True,
                "date": (start + timedelta(days=rng.randint(0, 880))).isoformat(),
                "job_title": rng.choice(TITLES[industry]),
                "employment": rng.choice(["Current employee", "Current employee", "Former employee"]),
                "rating": overall,
                "subratings": sub,
                "headline": head,
                "pros": "; ".join(pros),
                "cons": "; ".join(cons),
            })
        out["companies"].append({"name": name, "industry": industry, "hq": hq, "simulated": True,
                                 "n_reviews": n, "reviews": reviews})
    return out


def main() -> None:
    data = build()
    SIMULATED_DIR.mkdir(parents=True, exist_ok=True)
    path = SIMULATED_DIR / "reviews.json"
    path.write_text(json.dumps(data, indent=1))
    ratings = [r["rating"] for c in data["companies"] for r in c["reviews"]]
    dist = {k: ratings.count(k) for k in range(1, 6)}
    print(f"wrote {path} — {len(data['companies'])} fictional companies, {len(ratings)} simulated reviews")
    print("rating distribution:", {k: f"{v / len(ratings):.0%}" for k, v in dist.items()},
          f"mean {sum(ratings) / len(ratings):.2f}")


if __name__ == "__main__":
    main()
