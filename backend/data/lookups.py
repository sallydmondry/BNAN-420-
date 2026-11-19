"""Deterministic lookups over the processed REAL datasets.

Public API (all pure functions, cached data):
    tax_for(state, city, income, ...)      -> TaxComputation (federal + FICA + state + local)
    rent_for(cbsa, bedrooms)               -> RentEstimate
    rpp_for(cbsa)                          -> dict of BEA Regional Price Parities
    wages_for(soc_code, cbsa)              -> dict of BLS OEWS percentiles (or None)
    city_profile(cbsa)                     -> merged metro profile (climate, ACS, outdoors, RPP, rent)
    resolve_city(city, state)              -> ResolvedLocation for a supported metro (or unmatched)
    geocode(city_state)                    -> (lat, lon, label) for any U.S. Census place

No LLM is involved anywhere in this module.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional

import pandas as pd

from backend.core.config import PROCESSED_DIR
from backend.core.models import ResolvedLocation, SourceRef

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _pq(name: str) -> pd.DataFrame:
    path = PROCESSED_DIR / f"{name}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


@lru_cache(maxsize=None)
def _json(name: str) -> dict[str, Any]:
    return json.loads((PROCESSED_DIR / f"{name}.json").read_text())


@lru_cache(maxsize=1)
def manifest() -> dict[str, Any]:
    """Data provenance written by download_data.py."""
    p = PROCESSED_DIR / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else {}


def tax_tables() -> dict[str, Any]:
    return _json("tax_tables")


def consumer_expenditure() -> dict[str, Any]:
    return _json("consumer_expenditure")


def metros() -> pd.DataFrame:
    return _pq("metros")


def oews_available() -> bool:
    return not _pq("oews").empty


def _src(table: str, name: Optional[str] = None) -> SourceRef:
    meta = manifest().get("tables", {}).get(table, {})
    return SourceRef(name=name or meta.get("source", table), data_year=str(meta.get("data_year", "")),
                     url=meta.get("url"), real=bool(meta.get("real", True)))


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles."""
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Location resolution
# ---------------------------------------------------------------------------

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
STATE_CODES = set(US_STATES.values())

CITY_ALIASES = {
    "nyc": ("New York", "NY"), "new york city": ("New York", "NY"), "manhattan": ("New York", "NY"),
    "brooklyn": ("New York", "NY"), "queens": ("New York", "NY"), "bronx": ("New York", "NY"),
    "the bronx": ("New York", "NY"), "staten island": ("New York", "NY"), "long island city": ("New York", "NY"),
    "sf": ("San Francisco", "CA"), "philly": ("Philadelphia", "PA"), "la": ("Los Angeles", "CA"),
    "dc": ("Washington", "DC"), "washington dc": ("Washington", "DC"), "washington d.c.": ("Washington", "DC"),
    "st louis": ("St. Louis", "MO"), "saint louis": ("St. Louis", "MO"), "vegas": ("Las Vegas", "NV"),
    "slc": ("Salt Lake City", "UT"), "nashville-davidson": ("Nashville", "TN"),
}


def normalize_state(s: Optional[str]) -> Optional[str]:
    """'Arizona' / 'az' / 'Ariz.' -> 'AZ'."""
    if not s:
        return None
    t = s.strip().rstrip(".").lower()
    if t.upper() in STATE_CODES:
        return t.upper()
    if t in US_STATES:
        return US_STATES[t]
    for name, code in US_STATES.items():
        if name.startswith(t) and len(t) >= 4:
            return code
    return None


def split_city_state(text: str) -> tuple[Optional[str], Optional[str]]:
    """'Tucson, AZ' -> ('Tucson', 'AZ'); 'Austin Texas' -> ('Austin', 'TX')."""
    if not text:
        return None, None
    t = re.sub(r"\s+", " ", text.strip())
    m = re.match(r"^(.*?)[,\s]+([A-Za-z .]{2,20})$", t)
    if m:
        st = normalize_state(m.group(2))
        if st:
            return m.group(1).strip(" ,"), st
    alias = CITY_ALIASES.get(t.lower())
    if alias:
        return alias
    return t, None


@lru_cache(maxsize=4096)
def geocode(city_state: str) -> Optional[tuple[float, float, str]]:
    """Locate any U.S. Census place. Returns (lat, lon, 'City, ST') or None."""
    city, st = split_city_state(city_state)
    if not city:
        return None
    alias = CITY_ALIASES.get(city.lower())
    if alias:
        city, st = alias
    places = _pq("places")
    m = metros()
    # Principal cities of supported metros first (exact & unambiguous).
    hit = m[(m["principal_city"].str.lower() == city.lower()) & ((m["state"] == st) if st else True)]
    if not hit.empty:
        r = hit.sort_values("pop2024", ascending=False).iloc[0]
        return float(r["lat"]), float(r["lon"]), f"{r['principal_city']}, {r['state']}"
    q = places[places["name"].str.lower() == city.lower().replace("saint ", "st. ")]
    if st:
        q = q[q["state"] == st]
    if q.empty:
        return None
    r = q.iloc[0]
    return float(r["lat"]), float(r["lon"]), f"{r['name']}, {r['state']}"


def resolve_city(city: Optional[str], state: Optional[str], basis: str = "office") -> ResolvedLocation:
    """Map an office city to a supported metro (CBSA).

    1. Alias table (NYC boroughs, 'SF', ...). 2. Principal/title city of a supported metro.
    3. Geocode with the Census place gazetteer and take the nearest supported metro within 60 miles.
    """
    if not city:
        return ResolvedLocation(city=city, state=state, matched=False, method="none", basis="unknown")
    st = normalize_state(state) if state else None
    c = city.strip()
    if not st:
        c2, st2 = split_city_state(c)
        c, st = (c2 or c), st2
    alias = CITY_ALIASES.get(c.lower())
    if alias:
        c, st = alias[0], alias[1]
    m = metros()
    b = basis if basis in ("office", "remote_residence") else "office"
    for _, r in m.iterrows():
        titles = [t.lower() for t in r["title_cities"].split("|")]
        if c.lower() in titles and (st is None or st in r["states"]):
            return ResolvedLocation(city=c, state=st or r["state"], cbsa=r["cbsa"], metro_name=r["short_name"],
                                    matched=True, method="principal_city", basis=b)
    g = geocode(f"{c}, {st}" if st else c)
    if g:
        lat, lon, label = g
        d = m.apply(lambda r: min(haversine_mi(lat, lon, r["lat"], r["lon"]),
                                  haversine_mi(lat, lon, r["cbsa_lat"], r["cbsa_lon"])), axis=1)
        i = d.idxmin()
        if d[i] <= 60:
            r = m.loc[i]
            return ResolvedLocation(city=c, state=st or label.split(", ")[-1], cbsa=r["cbsa"],
                                    metro_name=r["short_name"], matched=True,
                                    method=f"nearest_metro ({d[i]:.0f} mi)", basis=b)
    return ResolvedLocation(city=c, state=st, matched=False, method="not_in_dataset", basis=b)


def supported_metros() -> list[dict[str, Any]]:
    """List for the UI / GET /api/metros."""
    return [
        {"cbsa": r["cbsa"], "name": r["short_name"], "full_name": r["name"], "rank": int(r["rank"]),
         "population": int(r["pop2024"])}
        for _, r in metros().sort_values("rank").iterrows()
    ]


# ---------------------------------------------------------------------------
# Taxes
# ---------------------------------------------------------------------------


def _bracket_tax(income: float, brackets: list[dict[str, float]]) -> tuple[float, float]:
    """Progressive tax and marginal rate for ``income`` given [{'over': x, 'rate': r}, ...]."""
    if income <= 0 or not brackets:
        return 0.0, (brackets[0]["rate"] if brackets else 0.0)
    tax, marginal = 0.0, 0.0
    for i, b in enumerate(brackets):
        lo = b["over"]
        hi = brackets[i + 1]["over"] if i + 1 < len(brackets) else float("inf")
        if income > lo:
            tax += (min(income, hi) - lo) * b["rate"]
            marginal = b["rate"]
    return tax, marginal


@dataclass
class TaxComputation:
    """Full deterministic breakdown for one salary. Amounts are annual USD."""

    gross: float
    pretax_401k: float
    pretax_health: float
    federal_wages: float
    federal_taxable: float
    federal_tax: float
    federal_marginal: float
    ss_tax: float
    medicare_tax: float
    state: Optional[str]
    state_taxable: float
    state_tax: float
    state_marginal: float
    local_name: Optional[str]
    local_tax: float
    local_marginal: float
    total_tax: float
    take_home: float
    effective_rate: float
    marginal_rate: float
    lines: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _state_tax(state: str, wages_for_state: float, st: dict[str, Any]) -> tuple[float, float, float, str]:
    """Return (tax, taxable_income, marginal, formula) applying Tax Foundation table + footnote rules."""
    if st.get("no_wage_tax") or not st.get("brackets"):
        return 0.0, 0.0, 0.0, f"{state} has no state income tax on wages"
    rules = st.get("rules", {})
    agi = wages_for_state
    std = float(st.get("std_deduction") or 0)
    ex = float(st.get("exemption") or 0)
    credit = float(st.get("credit") or 0)
    notes = []
    if "std_phaseout" in rules:
        r = rules["std_phaseout"]
        steps = max(0, math.ceil((agi - r["start"]) / r["per"])) if agi > r["start"] else 0
        std = max(r["floor"], r["base"] - steps * r["step"])
        notes.append(f"std deduction phased to ${std:,.0f}")
    if "std_phaseout_linear" in rules:
        r = rules["std_phaseout_linear"]
        frac = min(1.0, max(0.0, (agi - r["start"]) / (r["end"] - r["start"])))
        std = std * (1 - frac)
        notes.append(f"std deduction phased to ${std:,.0f}")
    if "exemption_phaseout" in rules:
        r = rules["exemption_phaseout"]
        steps = max(0, math.ceil((agi - r["start"]) / r["per"])) if agi > r["start"] else 0
        ex = max(0.0, ex - steps * r["step"])
        notes.append(f"exemption phased to ${ex:,.0f}")
    if "exemption_phaseout_linear" in rules:
        r = rules["exemption_phaseout_linear"]
        frac = min(1.0, max(0.0, (agi - r["start"]) / (r["end"] - r["start"])))
        ex = ex * (1 - frac)
    if "exemption_tiers" in rules:
        for cap, amt in rules["exemption_tiers"]:
            if agi <= cap:
                ex = float(amt)
                break
        notes.append(f"exemption ${ex:,.0f} for this AGI")
    if "exemption_cutoff" in rules and agi > rules["exemption_cutoff"]:
        ex = 0.0
    if "credit_cutoff" in rules and agi > rules["credit_cutoff"]:
        credit = 0.0
        notes.append("personal credit not allowed at this AGI")
    if "credit_phaseout" in rules:
        r = rules["credit_phaseout"]
        credit = max(0.0, credit - max(0.0, agi - r["start"]) * r["rate"])
        notes.append(f"credit phased to ${credit:,.0f}")
    taxable = max(0.0, agi - std - ex)
    brackets = [dict(b) for b in st["brackets"]]
    if "two_pct_recapture" in rules and len(brackets) > 1 and agi > rules["two_pct_recapture"]["start"]:
        r = rules["two_pct_recapture"]
        steps = math.ceil((agi - r["start"]) / r["per"])
        new_top = max(0.0, brackets[1]["over"] - steps * r["step"])
        brackets[1]["over"] = new_top
        notes.append(f"2% band reduced to ${new_top:,.0f}")
    tax, marginal = _bracket_tax(taxable, brackets)
    tax = max(0.0, tax - credit)
    formula = (f"(${agi:,.0f} state wages − ${std:,.0f} std deduction − ${ex:,.0f} exemption) = ${taxable:,.0f} "
               f"taxed on {state} 2026 single brackets" + (f" − ${credit:,.0f} credit" if credit else ""))
    if notes:
        formula += f" [{'; '.join(notes)}]"
    return tax, taxable, marginal, formula


def find_local(state: Optional[str], city: Optional[str]) -> Optional[dict[str, Any]]:
    """Curated local income tax entry for the office city, if any."""
    if not state or not city:
        return None
    c = city.strip().lower()
    for loc in tax_tables()["local"]["localities"]:
        if loc["state"] == state and c in [x.lower() for x in loc["cities"]]:
            return loc
    return None


def tax_for(state: Optional[str], city: Optional[str], income: float, contribution_401k_pct: float = 0.0,
            health_premium_annual: float = 0.0) -> TaxComputation:
    """Estimate 2026 taxes for a single filer with only W-2 wages, standard deduction, living in the office city.

    Order of operations: pre-tax 401(k) (capped at the IRS limit) and Sec. 125 health premiums reduce federal and
    state wages; health premiums (not 401(k)) reduce FICA wages; local tax base depends on the locality.
    """
    tt = tax_tables()
    fed, fica = tt["federal"], tt["federal"]["fica"]
    gross = max(0.0, float(income))
    k401 = min(gross * max(0.0, contribution_401k_pct) / 100.0, fed["k401_elective_limit"])
    health = min(max(0.0, health_premium_annual), gross - k401)
    fed_wages = gross - k401 - health
    fed_taxable = max(0.0, fed_wages - fed["standard_deduction"])
    fed_tax, fed_marg = _bracket_tax(fed_taxable, fed["brackets"])
    fica_wages = gross - health
    ss = min(fica_wages, fica["ss_wage_base"]) * fica["ss_rate"]
    medicare = fica_wages * fica["medicare_rate"] + max(0.0, fica_wages - fica["addl_medicare_threshold"]) * fica["addl_medicare_rate"]
    fica_marg = (fica["ss_rate"] if fica_wages < fica["ss_wage_base"] else 0) + fica["medicare_rate"]

    warnings: list[str] = []
    st_code = normalize_state(state) if state else None
    st_tax = st_taxable = st_marg = 0.0
    st_formula = "state unknown — state tax not included"
    if st_code and st_code in tt["state"]["states"]:
        sdata = tt["state"]["states"][st_code]
        st_wages = (gross - health) if sdata.get("rules", {}).get("taxes_401k") else fed_wages
        st_tax, st_taxable, st_marg, st_formula = _state_tax(st_code, st_wages, sdata)
    else:
        warnings.append("Office state not identified, so state income tax is excluded.")

    loc = find_local(st_code, city)
    local_tax = local_marg = 0.0
    local_name = None
    local_formula = ""
    if loc:
        local_name = loc["name"]
        base_kind = loc["base"]
        base = st_taxable if base_kind == "state_taxable" else (gross - health)
        if "brackets" in loc:
            local_tax, local_marg = _bracket_tax(base, loc["brackets"])
        elif "brackets_sum" in loc:
            for part in loc["brackets_sum"]:
                t, mr = _bracket_tax(base, part["brackets"])
                local_tax += t
                local_marg += mr
        elif base_kind != "head_tax":
            local_tax, local_marg = base * loc["rate"], loc["rate"]
        local_tax += float(loc.get("head_tax", 0) or 0)
        base_label = "state taxable income" if base_kind == "state_taxable" else "gross wages (401(k) not excluded)"
        local_formula = (f"{local_name}: " + (f"${loc['head_tax']}/yr flat" if base_kind == "head_tax"
                         else f"{base_label} ${base:,.0f} × rate(s)" + (f" + ${loc['head_tax']} flat" if loc.get('head_tax') else "")))

    total = fed_tax + ss + medicare + st_tax + local_tax
    take_home = gross - k401 - health - total
    fed_src = fed["sources"]
    lines = [
        {"label": "Pre-tax 401(k)", "annual": k401, "formula": f"{contribution_401k_pct:g}% × ${gross:,.0f} (cap ${fed['k401_elective_limit']:,.0f})",
         "source": fed_src[2] if len(fed_src) > 2 else None},
        {"label": "Pre-tax health premium", "annual": health, "formula": "Section 125 premium you entered (or KFF 2025 average)",
         "source": {"name": tt["health_premium_default"]["source"], "url": tt["health_premium_default"]["url"], "data_year": "2025"}},
        {"label": "Federal income tax", "annual": fed_tax,
         "formula": f"(${fed_wages:,.0f} wages − ${fed['standard_deduction']:,.0f} standard deduction) = ${fed_taxable:,.0f} on 2026 single brackets",
         "source": fed_src[0]},
        {"label": "Social Security (6.2%)", "annual": ss, "formula": f"6.2% × ${min(fica_wages, fica['ss_wage_base']):,.0f} (wage base ${fica['ss_wage_base']:,.0f})", "source": fed_src[1]},
        {"label": "Medicare (1.45%)", "annual": medicare, "formula": f"1.45% × ${fica_wages:,.0f}" + (" + 0.9% over $200k" if fica_wages > 200000 else ""), "source": fed_src[1]},
        {"label": f"{st_code or 'State'} income tax", "annual": st_tax, "formula": st_formula, "source": tt["state"]["source"]},
    ]
    if loc:
        lines.append({"label": "Local income tax", "annual": local_tax, "formula": local_formula,
                      "source": {"name": f"{loc['name']} ({loc['verified']})", "url": loc["url"], "data_year": "2026"}})
    assumptions = [
        "Tax year 2026, single filer, standard deduction, no other income, no dependents.",
        "You live in the office city, so resident state/local rates apply.",
        "State disability / paid-leave payroll contributions (0–1.3% in some states) are not included.",
        "Estimates for comparison only — not tax advice.",
    ]
    return TaxComputation(
        gross=gross, pretax_401k=k401, pretax_health=health, federal_wages=fed_wages, federal_taxable=fed_taxable,
        federal_tax=fed_tax, federal_marginal=fed_marg, ss_tax=ss, medicare_tax=medicare, state=st_code,
        state_taxable=st_taxable, state_tax=st_tax, state_marginal=st_marg, local_name=local_name, local_tax=local_tax,
        local_marginal=local_marg, total_tax=total, take_home=take_home,
        effective_rate=(total / gross) if gross else 0.0,
        marginal_rate=fed_marg + fica_marg + st_marg + local_marg,
        lines=lines, assumptions=assumptions, warnings=warnings,
    )


def health_premium_default_monthly() -> float:
    return float(tax_tables()["health_premium_default"]["monthly"])


# ---------------------------------------------------------------------------
# Rent, prices, wages, profiles
# ---------------------------------------------------------------------------


@dataclass
class RentEstimate:
    cbsa: str
    bedrooms: int
    unit_rent: float  # whole unit, per month
    acs_bedroom_median: float
    acs_all_median: float
    zori_latest: float
    zori_month: str
    zori_yoy_pct: float
    formula: str
    sources: list[SourceRef]


def _row(table: str, cbsa: str) -> Optional[pd.Series]:
    df = _pq(table)
    if df.empty:
        return None
    r = df[df["cbsa"] == cbsa]
    return None if r.empty else r.iloc[0]


def rent_for(cbsa: str, bedrooms: int) -> Optional[RentEstimate]:
    """Current market rent for a whole unit with ``bedrooms`` bedrooms.

    rent = Zillow ZORI (latest month, typical asking rent) × ACS median gross rent for that bedroom count
    ÷ ACS median gross rent for all units. ZORI sets today's market level; ACS supplies the bedroom mix.
    """
    s = _row("metro_stats", cbsa)
    if s is None:
        return None
    b = int(min(max(bedrooms, 0), 4))
    col = f"acs_rent_{b}br"
    acs_b, acs_all, z = s.get(col), s.get("acs_rent_all"), s.get("zori_latest")
    if pd.isna(acs_b) or pd.isna(acs_all) or pd.isna(z) or not acs_all:
        return None
    unit = float(z) * float(acs_b) / float(acs_all)
    label = "studio" if b == 0 else f"{b}-bedroom"
    formula = (f"Zillow ZORI ${z:,.0f} ({s['zori_latest_month']}) × ACS {label} median ${acs_b:,.0f} "
               f"÷ ACS all-units median ${acs_all:,.0f} = ${unit:,.0f}/mo for the whole unit")
    meta = manifest().get("tables", {}).get("metro_stats", {})
    sources = [
        SourceRef(name="Zillow Observed Rent Index (ZORI), all homes, smoothed", data_year=str(s["zori_latest_month"]),
                  url=meta.get("zori_url")),
        SourceRef(name="Census ACS 2024 1-year B25031 / B25064 median gross rent", data_year="2024",
                  url="https://www.census.gov/programs-surveys/acs"),
    ]
    return RentEstimate(cbsa=cbsa, bedrooms=b, unit_rent=unit, acs_bedroom_median=float(acs_b),
                        acs_all_median=float(acs_all), zori_latest=float(z), zori_month=str(s["zori_latest_month"]),
                        zori_yoy_pct=float(s["zori_yoy_pct"]), formula=formula, sources=sources)


def rpp_for(cbsa: str) -> Optional[dict[str, Any]]:
    """BEA Regional Price Parities (U.S. = 100)."""
    r = _row("rpp", cbsa)
    if r is None or pd.isna(r.get("rpp_all")):
        return None
    return {k: float(r[k]) for k in ("rpp_all", "rpp_goods", "rpp_housing", "rpp_utilities", "rpp_other")} | {
        "year": int(r["rpp_year"]), "source": _src("rpp")}


def wages_for(soc_code: str, cbsa: Optional[str]) -> Optional[dict[str, Any]]:
    """BLS OEWS annual wage percentiles for an occupation in a metro, falling back to national."""
    df = _pq("oews")
    if df.empty:
        return None
    rows = df[df["soc"] == soc_code]
    for area, level in ((cbsa, "metro"), ("99999", "national")):
        if area is None:
            continue
        r = rows[rows["area"] == area]
        if not r.empty and not pd.isna(r.iloc[0]["p50"]):
            x = r.iloc[0]
            out = {k: (None if pd.isna(x[k]) else float(x[k])) for k in ("p10", "p25", "p50", "p75", "p90", "mean", "employment")}
            out |= {"area_name": x["area_title"], "area_level": level, "occ_title": x["occ_title"],
                    "p90_topcoded": bool(x.get("p90_flag", False)), "source": _src("oews")}
            return out
    return None


def city_profile(cbsa: str) -> Optional[dict[str, Any]]:
    """Everything known about a metro, merged from every processed table."""
    m = metros()
    mr = m[m["cbsa"] == cbsa]
    if mr.empty:
        return None
    out: dict[str, Any] = mr.iloc[0].to_dict()
    for t in ("metro_stats", "climate", "outdoors"):
        r = _row(t, cbsa)
        if r is not None:
            out.update({k: (None if (isinstance(v, float) and math.isnan(v)) else v) for k, v in r.to_dict().items() if k != "cbsa"})
    rpp = rpp_for(cbsa)
    if rpp:
        out.update({k: v for k, v in rpp.items() if k != "source"})
    out["sources"] = {t: _src(t).model_dump() for t in ("metros", "metro_stats", "climate", "outdoors", "rpp")}
    return out
