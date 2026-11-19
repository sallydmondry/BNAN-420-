"""Agent 5 — Lifestyle Fit.

Scores each offer's metro 0–100 on six dimensions, then averages them using the user's 0–5 priorities.
Most dimensions are the metro's percentile rank among TrueOffer's 52 supported metros (so 100 = best of
the 52, 50 = middle), which keeps scores comparable across any set of offers:

* outdoors     — national parks within 300 miles and distance to the nearest one (Wikipedia/NPS list)
* nightlife    — share of residents aged 22–34 and metro population (Census ACS 2024)
* weather      — "comfortable" days per year (NOAA 1991–2020 Normals)
* commute      — mean one-way commute time, shorter is better (Census ACS 2024)
* cost_of_fun  — BEA price parity for services (dining, entertainment), cheaper is better
* family       — distance from the metro to your home city: 100 within 50 miles, falling linearly to 0 at 2,000
"""

from __future__ import annotations

import json
import time
from functools import lru_cache
from typing import Any, Optional

import pandas as pd

from backend.core import llm
from backend.core.guards import collect_numbers, safe_text
from backend.core.models import DimensionScore, LifestyleInput, LifestyleOutput, LifestyleResult
from backend.data import lookups as L

LABELS = {"outdoors": "Outdoors & nature", "nightlife": "Nightlife & young professionals", "weather": "Weather",
          "commute": "Commute", "family": "Close to family", "cost_of_fun": "Cost of fun"}


@lru_cache(maxsize=1)
def _metro_table() -> pd.DataFrame:
    rows = []
    for c in L.metros()["cbsa"]:
        p = L.city_profile(c)
        if p:
            rows.append({k: p.get(k) for k in ("cbsa", "short_name", "lat", "lon", "parks_300mi", "parks_150mi",
                                                "nearest_park", "nearest_park_mi", "share_22_34", "pop2024",
                                                "comfortable_days", "days_over_90", "days_below_32", "mean_commute_min",
                                                "rpp_other", "summer_tmax_f", "winter_tavg_f", "snow_in")})
    df = pd.DataFrame(rows).set_index("cbsa")
    return df


def _rank(col: str, higher_better: bool = True) -> pd.Series:
    s = pd.to_numeric(_metro_table()[col], errors="coerce")
    r = s.rank(method="average", ascending=higher_better)
    n = s.notna().sum()
    return (r - 1) / max(1, n - 1) * 100


@lru_cache(maxsize=1)
def _ranks() -> dict[str, pd.Series]:
    return {
        "parks": _rank("parks_300mi"), "park_dist": _rank("nearest_park_mi", higher_better=False),
        "young": _rank("share_22_34"), "pop": _rank("pop2024"),
        "comfortable": _rank("comfortable_days"), "commute": _rank("mean_commute_min", higher_better=False),
        "fun": _rank("rpp_other", higher_better=False),
    }


def _avg(*vals: Optional[float]) -> Optional[float]:
    v = [x for x in vals if x is not None and not pd.isna(x)]
    return round(sum(v) / len(v), 1) if v else None


def _py(v: Any) -> Any:
    """numpy/pandas scalars -> plain Python (None for NaN) so results serialize to JSON."""
    if v is None:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and pd.isna(v):
        return None
    if isinstance(v, float):
        return round(v, 2)
    return v


def _get(series: pd.Series, cbsa: str) -> Optional[float]:
    v = series.get(cbsa)
    return None if v is None or pd.isna(v) else float(v)


def score_metro(cbsa: str, priorities: dict[str, int], home: Optional[tuple[float, float, str]]) -> list[DimensionScore]:
    """Six dimension scores for one metro."""
    t = _metro_table()
    if cbsa not in t.index:
        return []
    row = t.loc[cbsa]
    rk = _ranks()
    n = len(t)
    dims: list[DimensionScore] = []

    def add(key: str, score: Optional[float], inputs: dict[str, Any], source: str, formula: str) -> None:
        dims.append(DimensionScore(dimension=key, label=LABELS[key], score=None if score is None else round(score, 1),  # type: ignore[arg-type]
                                   weight=int(priorities.get(key, 0)), inputs={k: _py(v) for k, v in inputs.items()},
                                   source=source, formula=formula))

    add("outdoors", _avg(_get(rk["parks"], cbsa), _get(rk["park_dist"], cbsa)),
        {"national_parks_within_300_mi": row["parks_300mi"], "nearest_national_park": row["nearest_park"],
         "nearest_park_miles": row["nearest_park_mi"]},
        "National parks list (Wikipedia, citing NPS), distances from the principal city",
        f"average of percentile ranks among {n} metros: parks within 300 mi, and nearness of the closest park")
    add("nightlife", _avg(_get(rk["young"], cbsa), _get(rk["pop"], cbsa)),
        {"share_age_22_34_pct": None if pd.isna(row["share_22_34"]) else round(float(row["share_22_34"]) * 100, 1),
         "metro_population": row["pop2024"]},
        "Census ACS 2024 1-year (B01001) and Vintage 2024 population estimates",
        f"average of percentile ranks among {n} metros: share of residents 22–34, and population")
    add("weather", _get(rk["comfortable"], cbsa),
        {"comfortable_days_per_year": row["comfortable_days"], "days_over_90F": row["days_over_90"],
         "days_below_32F": row["days_below_32"], "snow_inches": row["snow_in"]},
        "NOAA NCEI U.S. Climate Normals 1991–2020",
        f"percentile rank among {n} metros of comfortable days (daily high between 50°F and 90°F)")
    add("commute", _get(rk["commute"], cbsa),
        {"mean_commute_minutes": None if pd.isna(row["mean_commute_min"]) else round(float(row["mean_commute_min"]), 1)},
        "Census ACS 2024 1-year (B08013 / B08303)",
        f"percentile rank among {n} metros, shorter mean commute scores higher")
    add("cost_of_fun", _get(rk["fun"], cbsa),
        {"services_price_index_us_100": None if pd.isna(row["rpp_other"]) else round(float(row["rpp_other"]), 1)},
        "BEA Regional Price Parities 2024 (services)",
        f"percentile rank among {n} metros, lower services prices score higher")
    if home:
        d = L.haversine_mi(home[0], home[1], float(row["lat"]), float(row["lon"]))
        s = 100.0 if d <= 50 else max(0.0, 100.0 * (1 - (d - 50) / 1950))
        add("family", s, {"home": home[2], "miles_from_home": round(d)},
            "U.S. Census Gazetteer coordinates (great-circle distance)",
            "100 within 50 miles of home, falling linearly to 0 at 2,000 miles")
    else:
        add("family", None, {"home": None}, "", "Add your home city to score distance to family")
    return dims


def fit(dims: list[DimensionScore]) -> Optional[float]:
    """Priority-weighted average of the available dimension scores."""
    usable = [d for d in dims if d.score is not None and d.weight > 0]
    w = sum(d.weight for d in usable)
    return round(sum(d.score * d.weight for d in usable) / w, 1) if w else None  # type: ignore[operator]


def highlights(dims: list[DimensionScore]) -> list[str]:
    """Short, data-backed bullets about the strongest and weakest dimensions the user cares about."""
    cared = sorted([d for d in dims if d.score is not None and d.weight >= 3], key=lambda d: -(d.score or 0))
    out = []
    if cared:
        out.append(f"Best for you: {cared[0].label.lower()} ({cared[0].score:.0f}/100).")
        if len(cared) > 1:
            out.append(f"Weakest for you: {cared[-1].label.lower()} ({cared[-1].score:.0f}/100).")
    for d in dims:
        if d.dimension == "family" and d.inputs.get("miles_from_home") is not None:
            out.append(f"About {d.inputs['miles_from_home']:,} miles from {d.inputs['home']}.")
    return out


async def run(inp: LifestyleInput) -> LifestyleOutput:
    """Score lifestyle fit for every offer's metro."""
    t0 = time.perf_counter()
    pri = inp.priorities.model_dump()
    home = L.geocode(inp.home_city) if inp.home_city else None
    warnings, log, results = [], [], []
    engine = "local"
    if inp.home_city and not home:
        warnings.append(f"Couldn't find '{inp.home_city}', so distance to family isn't scored.")
    for o in inp.offers:
        if not o.cbsa:
            results.append(LifestyleResult(offer_id=o.offer_id, computed=False, metro_name=o.metro_name))
            warnings.append(f"Offer {o.offer_id}: city not in dataset, so lifestyle isn't scored.")
            continue
        dims = score_metro(o.cbsa, pri, home)
        r = LifestyleResult(offer_id=o.offer_id, metro_name=o.metro_name, dimensions=dims, fit_score=fit(dims),
                            highlights=highlights(dims))
        if llm.claude_enabled():
            txt = await llm.generate("lifestyle", json.dumps({"metro": o.metro_name, "fit_score": r.fit_score,
                                                              "dimensions": [d.model_dump() for d in dims]}, default=str),
                                     max_tokens=400)
            narrative, used = safe_text(txt, "", collect_numbers(r))
            if used and narrative:
                r.highlights.insert(0, narrative)
                engine = "claude"
        results.append(r)
        log.append(f"Offer {o.offer_id}: {o.metro_name} lifestyle fit {r.fit_score if r.fit_score is not None else 'n/a'}/100.")
    log.append("Scores are percentile ranks among TrueOffer's 52 metros, weighted by your 0–5 priorities.")
    computed = [r for r in results if r.computed]
    conf = 0.8 * len(computed) / max(1, len(results)) + (0.1 if home else 0.0)
    return LifestyleOutput(results=results, log=log, warnings=warnings, confidence=round(min(conf, 1.0), 2),  # type: ignore[arg-type]
                           engine=engine, elapsed_ms=int((time.perf_counter() - t0) * 1000))
