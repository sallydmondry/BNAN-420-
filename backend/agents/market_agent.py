"""Agent 4 — Market & Company.

* Maps the job title to a BLS SOC occupation (keyword rules; Claude optional for unusual titles).
* Places the base salary within BLS OEWS May 2025 wage percentiles for that occupation in the metro.
* Summarizes culture from SIMULATED reviews (fictional companies) or reviews the user pastes in.
* Lists negotiation leverage points derived from those numbers.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from functools import lru_cache
from typing import Optional

from backend.core import llm
from backend.core.config import SIMULATED_DIR
from backend.core.guards import collect_numbers, safe_text
from backend.core.models import (
    CultureSummary,
    MarketInput,
    MarketOfferInput,
    MarketOutput,
    MarketResult,
    SourceRef,
    WagePercentiles,
)
from backend.data import lookups as L

# (pattern, SOC code, confidence). Most specific first. Codes verified present in OEWS May 2025.
SOC_RULES: list[tuple[str, str, float]] = [
    (r"software (?:engineer|developer)|\bswe\b|full[- ]stack|back[- ]?end|front[- ]?end developer|mobile developer", "15-1252", 0.9),
    (r"\bqa\b|quality assurance|test engineer|sdet", "15-1253", 0.85),
    (r"web developer", "15-1254", 0.9),
    (r"ux|ui designer|product designer|interaction designer", "15-1255", 0.75),
    (r"security analyst|cyber ?security|information security", "15-1212", 0.9),
    (r"systems analyst|it analyst|business systems analyst", "15-1211", 0.85),
    (r"database administrator|\bdba\b", "15-1242", 0.85),
    (r"network (?:engineer|administrator)|systems administrator|sysadmin", "15-1244", 0.8),
    (r"help ?desk|it support|technical support|support specialist", "15-1232", 0.8),
    (r"data scientist|machine learning|\bml engineer|ai engineer", "15-2051", 0.9),
    (r"data (?:analyst|analytics)|analytics (?:associate|analyst)|business intelligence|\bbi analyst|product analyst|"
     r"insights analyst|reporting analyst", "15-2051", 0.7),
    (r"data engineer", "15-1252", 0.6),
    (r"statistician|biostatistic", "15-2041", 0.9),
    (r"actuar", "15-2011", 0.9),
    (r"operations research|quantitative analyst|\bquant\b", "15-2031", 0.75),
    (r"economist", "19-3011", 0.85),
    (r"audit|accountant|\bcpa\b|tax (?:associate|staff|analyst)|staff accountant", "13-2011", 0.9),
    (r"budget analyst", "13-2031", 0.9),
    (r"credit analyst", "13-2041", 0.9),
    (r"underwriter", "13-2053", 0.85),
    (r"risk analyst|risk specialist", "13-2054", 0.8),
    (r"financial advisor|wealth advisor|financial planner", "13-2052", 0.85),
    (r"loan officer", "13-2072", 0.9),
    (r"financial analyst|investment (?:banking )?analyst|banking analyst|equity research|fp&a|corporate finance|"
     r"investment analyst|portfolio analyst", "13-2051", 0.85),
    (r"marketing manager|brand manager|product marketing manager", "11-2021", 0.6),
    (r"marketing|market research|seo|social media|content strategist|growth marketer|crm", "13-1161", 0.8),
    (r"public relations|communications specialist|\bpr\b", "27-3031", 0.75),
    (r"sales (?:representative|development|associate)|account executive|\bsdr\b|\bbdr\b", "41-4012", 0.6),
    (r"human resources|\bhr\b (?:generalist|specialist|coordinator)|recruit|talent acquisition", "13-1071", 0.8),
    (r"project manager|program manager|project coordinator|scrum master", "13-1082", 0.8),
    (r"logistic|supply chain", "13-1081", 0.8),
    (r"buyer|purchasing|procurement", "13-1020", 0.8),
    (r"consultant|business analyst|management analyst|strategy analyst|operations analyst|associate consultant", "13-1111", 0.8),
    (r"civil engineer", "17-2051", 0.9),
    (r"mechanical engineer", "17-2141", 0.9),
    (r"electrical engineer", "17-2071", 0.9),
    (r"industrial engineer|manufacturing engineer|process engineer", "17-2112", 0.85),
    (r"chemical engineer", "17-2041", 0.9),
    (r"aerospace engineer", "17-2011", 0.9),
    (r"biomedical engineer|bioengineer", "17-2031", 0.9),
    (r"environmental engineer", "17-2081", 0.9),
    (r"registered nurse|\brn\b|nurse", "29-1141", 0.85),
    (r"paralegal|legal assistant", "23-2011", 0.9),
    (r"attorney|lawyer|associate attorney", "23-1011", 0.85),
    (r"teacher", "25-2031", 0.6),
    (r"graphic designer", "27-1024", 0.9),
    (r"chemist", "19-2031", 0.85),
    (r"biologist|research associate|lab technician", "19-4021", 0.5),
    (r"analyst", "13-1111", 0.45),
    (r"engineer", "17-2199", 0.35),
]

THEME_LABELS = {"work_life": "work-life balance", "compensation": "pay", "culture": "culture",
                "management": "management", "growth": "career growth"}
LEXICON = {
    "work_life": (r"balance|flexib|reasonable hours|remote|wfh|hours", r"burnout|long hours|weekend|overtime|exhaust|always on"),
    "compensation": (r"pay(?:s)? well|good pay|bonus|raise|competitive", r"underpaid|low pay|no raise|below market"),
    "culture": (r"collaborat|friendly|supportive|inclusive|fun|low-ego", r"toxic|cliqu|competitive|political|drama"),
    "management": (r"great manager|transparent|support(?:ive)? manag|leadership is", r"micromanag|poor manag|disorganiz|chaotic"),
    "growth": (r"learn|mentor|promot|growth|training", r"dead end|no growth|stagnant|slow promot"),
}


@lru_cache(maxsize=1)
def _reviews() -> dict:
    p = SIMULATED_DIR / "reviews.json"
    return json.loads(p.read_text()) if p.exists() else {"companies": []}


def _norm(name: str) -> str:
    n = re.sub(r"[^a-z0-9& ]", " ", (name or "").lower())
    n = re.sub(r"\b(llc|llp|inc|corp|corporation|co|company|ltd|the)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def map_soc(title: Optional[str]) -> tuple[Optional[str], Optional[str], float, str]:
    """Job title -> (SOC code, SOC title, confidence, reason)."""
    if not title:
        return None, None, 0.0, "Job title not stated in offer."
    t = title.lower()
    for pat, code, conf in SOC_RULES:
        m = re.search(pat, t)
        if m:
            df = L._pq("oews")
            hit = df[df["soc"] == code]
            occ = hit.iloc[0]["occ_title"] if not hit.empty else None
            if occ is None:
                continue
            return code, occ, conf, f"'{title}' matched the keyword '{m.group(0)}' → {occ} (SOC {code})."
    return None, None, 0.0, f"No BLS occupation rule matched '{title}'."


def percentile_of(salary: float, w: dict) -> Optional[float]:
    """Piecewise-linear percentile of ``salary`` between the OEWS 10/25/50/75/90 points (clamped 1–99)."""
    pts = [(p, w.get(k)) for p, k in ((10, "p10"), (25, "p25"), (50, "p50"), (75, "p75"), (90, "p90"))]
    pts = [(p, v) for p, v in pts if v is not None]
    if len(pts) < 2:
        return None
    if salary <= pts[0][1]:
        (p0, v0), (p1, v1) = pts[0], pts[1]
    elif salary >= pts[-1][1]:
        (p0, v0), (p1, v1) = pts[-2], pts[-1]
    else:
        for (p0, v0), (p1, v1) in zip(pts, pts[1:]):
            if v0 <= salary <= v1:
                break
    pct = p0 + (salary - v0) * (p1 - p0) / (v1 - v0) if v1 != v0 else p0
    return round(max(1.0, min(99.0, pct)), 1)


def culture_from_simulated(company: Optional[str]) -> CultureSummary:
    """Aggregate SIMULATED reviews for a fictional company, if it is in the dataset."""
    if not company:
        return CultureSummary(summary="Company not stated in offer, so no culture signal.")
    key = _norm(company)
    match = None
    for c in _reviews().get("companies", []):
        n = _norm(c["name"])
        if n == key or (len(key) > 5 and (key in n or n in key)):
            match = c
            break
    if not match:
        return CultureSummary(source="none", company_found=False,
                              summary=f"No reviews for {company} in TrueOffer's SIMULATED review set. "
                                      "Paste real reviews to get a culture read.")
    revs = match["reviews"]
    rating = sum(r["rating"] for r in revs) / len(revs)
    themes = {}
    for th in THEME_LABELS:
        vals = [r["subratings"][th] for r in revs if th in r.get("subratings", {})]
        if vals:
            themes[th] = round((sum(vals) / len(vals) - 3) / 2, 2)
    pros = Counter(p.strip() for r in revs for p in r.get("pros", "").split(";") if p.strip())
    cons = Counter(p.strip() for r in revs for p in r.get("cons", "").split(";") if p.strip())
    best = max(themes, key=themes.get) if themes else None
    worst = min(themes, key=themes.get) if themes else None
    summary = (f"SIMULATED reviews ({len(revs)}) average {rating:.1f}/5. "
               + (f"Strongest theme: {THEME_LABELS[best]}; weakest: {THEME_LABELS[worst]}." if best else ""))
    return CultureSummary(source="simulated", company_found=True, rating=round(rating, 2), n_reviews=len(revs),
                          themes=themes, pros=[p for p, _ in pros.most_common(3)], cons=[c for c, _ in cons.most_common(3)],
                          summary=summary)


def culture_from_pasted(text: str) -> CultureSummary:
    """Keyword sentiment over reviews the user pasted (kept in memory only)."""
    low = text.lower()
    themes = {}
    for th, (pos, neg) in LEXICON.items():
        p, n = len(re.findall(pos, low)), len(re.findall(neg, low))
        if p + n:
            themes[th] = round((p - n) / (p + n), 2)
    stars = [float(x) for x in re.findall(r"\b([1-5](?:\.\d)?)\s*(?:/\s*5|stars?)\b", low)]
    rating = round(sum(stars) / len(stars), 2) if stars else None
    best = max(themes, key=themes.get) if themes else None
    worst = min(themes, key=themes.get) if themes else None
    summary = "From the reviews you pasted: " + (
        f"most positive about {THEME_LABELS[best]}, most negative about {THEME_LABELS[worst]}." if best else
        "not enough recognizable themes to summarize.")
    return CultureSummary(source="user_pasted", company_found=True, rating=rating, n_reviews=max(1, low.count("\n\n") + 1),
                          themes=themes, summary=summary)


def leverage(base: Optional[float], w: Optional[dict], pct: Optional[float], occ: Optional[str], area: str) -> list[str]:
    """Negotiation talking points grounded in the wage percentiles."""
    pts: list[str] = []
    if base is None or w is None or pct is None:
        return pts
    if pct < 25 and w.get("p25"):
        pts.append(f"Your base is below the 25th percentile ({_m(w['p25'])}) for {occ} in {area}. That is a fair, "
                   "data-backed reason to ask for more.")
    elif pct < 50 and w.get("p50"):
        pts.append(f"Your base is between the 25th percentile and the median ({_m(w['p50'])}) for {occ} in {area}; "
                   "typical for entry level, with some room to ask.")
    else:
        pts.append(f"Your base is at or above the local median ({_m(w['p50'])}) for {occ}. It's a strong offer; "
                   "negotiate on signing bonus or start date rather than base.")
    return pts


def _m(x: float) -> str:
    return f"${x:,.0f}"


async def _analyze(o: MarketOfferInput) -> tuple[MarketResult, list[str], bool]:
    warnings: list[str] = []
    used_claude = False
    code, occ, conf, reason = map_soc(o.job_title)
    if code is None and o.job_title and llm.claude_enabled():
        raw = await llm.generate("market", f"Return ONLY a 7-character BLS SOC code (e.g. 13-2011) for the job title: "
                                           f"{o.job_title[:120]}", max_tokens=50)
        mm = re.search(r"\b\d{2}-\d{4}\b", raw or "")
        if mm and L.wages_for(mm.group(0), o.cbsa):
            code, conf, reason = mm.group(0), 0.6, f"Claude mapped '{o.job_title}' to SOC {mm.group(0)}."
            occ = L.wages_for(code, o.cbsa)["occ_title"]  # type: ignore[index]
            used_claude = True
    res = MarketResult(offer_id=o.offer_id, soc_code=code, soc_title=occ, soc_match_confidence=conf, soc_match_reason=reason)
    w = L.wages_for(code, o.cbsa) if code else None
    if w:
        res.wages = WagePercentiles(**{k: w.get(k) for k in ("p10", "p25", "p50", "p75", "p90", "mean", "employment")},
                                    area_name=w["area_name"], area_level=w["area_level"])
        res.sources.append(w["source"])
        if o.base_salary:
            res.salary_percentile = percentile_of(o.base_salary, w)
            p = res.salary_percentile
            res.label = "unknown" if p is None else "below" if p < 25 else "near" if p < 60 else "above"
        res.leverage_points = leverage(o.base_salary, w, res.salary_percentile, occ, o.metro_name or w["area_name"])
    elif code:
        warnings.append(f"Offer {o.offer_id}: no OEWS wages for {occ} in this metro.")
    if o.pasted_reviews and o.pasted_reviews.strip():
        res.culture = culture_from_pasted(o.pasted_reviews)
    else:
        res.culture = culture_from_simulated(o.company)
        if res.culture.source == "simulated":
            res.sources.append(SourceRef(name="SIMULATED employee reviews (fictional companies)", data_year="2026",
                                         real=False))
    base_text = res.culture.summary
    if llm.claude_enabled() and res.culture.source != "none":
        facts = {"wages": res.wages.model_dump(), "salary_percentile": res.salary_percentile,
                 "occupation": occ, "culture": res.culture.model_dump()}
        txt = await llm.generate("market", json.dumps(facts), max_tokens=500)
        res.culture.summary, used = safe_text(txt, base_text, collect_numbers(res))
        used_claude = used_claude or used
    return res, warnings, used_claude


async def run(inp: MarketInput) -> MarketOutput:
    """Benchmark each offer's salary and summarize company culture."""
    t0 = time.perf_counter()
    results, log, warnings = [], [], []
    engine = "local"
    for o in inp.offers:
        r, w, used = await _analyze(o)
        results.append(r)
        warnings.extend(w)
        engine = "claude" if used else engine
        if r.salary_percentile is not None:
            log.append(f"Offer {o.offer_id}: {r.soc_title} → salary at ~{r.salary_percentile:.0f}th percentile in "
                       f"{r.wages.area_name}.")
        else:
            log.append(f"Offer {o.offer_id}: {r.soc_match_reason}")
        if r.culture.source == "simulated":
            log.append(f"Offer {o.offer_id}: culture from {r.culture.n_reviews} SIMULATED reviews.")
    confs = [r.soc_match_confidence for r in results if r.salary_percentile is not None]
    conf = (sum(confs) / len(results)) if results else 0.0
    log.append("Wages: BLS OEWS May 2025 metro estimates (all experience levels, so entry-level offers usually land "
               "below the median).")
    return MarketOutput(results=results, log=log, warnings=warnings, confidence=round(conf, 2), engine=engine,  # type: ignore[arg-type]
                        elapsed_ms=int((time.perf_counter() - t0) * 1000))
