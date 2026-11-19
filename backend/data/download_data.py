"""Download and process the REAL public datasets TrueOffer uses.

Run once (needs network):  python -m backend.data.download_data
Re-process without downloading:  python -m backend.data.download_data --offline

Raw files land in backend/data/raw/<source>/ (gitignored). Clean, small, indexed tables
are written to backend/data/processed/ and committed, so the deployed app never needs
the network. Every table records its source URL and data year in processed/manifest.json.

Nothing here is fabricated. Where a value is curated by hand (local income taxes), each
row carries its official source URL and how it was verified. If a required source cannot
be downloaded automatically, the script stops and prints manual download instructions.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from backend.core.config import PROCESSED_DIR, RAW_DIR

UA = "TrueOffer-data-builder/1.0 (student project)"
TODAY = date.today().isoformat()

N_METROS = 52  # 52 largest MSAs by 2024 population: top 50 + Buffalo + Tucson (and Phoenix, #10)

URLS = {
    "irs_rp": "https://www.irs.gov/pub/irs-drop/rp-25-32.pdf",
    "irs_p15": "https://www.irs.gov/pub/irs-pdf/p15.pdf",
    "taxfoundation": "https://taxfoundation.org/wp-content/uploads/2026/02/2026-State-Individual-Income-Tax-Rates-Brackets.xlsx",
    "nyc_it201i": "https://www.tax.ny.gov/pdf/2025/inc/it201i_2025.pdf",
    "bea_rpp": "https://apps.bea.gov/regional/zip/MARPP.zip",
    "zillow_zori": "https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_uc_sfrcondomfr_sm_month.csv",
    "census_pop": "https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/metro/totals/cbsa-est2024-alldata.csv",
    "gaz_cbsa": "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_cbsa_national.zip",
    "gaz_place": "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip",
    "acs_base": "https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/1YRData/",
    "noaa_stations": "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt",
    "noaa_normals": "https://www.ncei.noaa.gov/data/normals-annualseasonal/1991-2020/access/",
    "nps_list": "https://en.wikipedia.org/wiki/List_of_national_parks_of_the_United_States",
    "bls_api": "https://api.bls.gov/publicAPI/v1/timeseries/data/",
    "oews_tables": "https://www.bls.gov/oes/tables.htm",
}

ACS_TABLES = ["b01001", "b08013", "b08303", "b25031", "b25064"]

STATE_ABBR = {
    "Ala.": "AL", "Alaska": "AK", "Ariz.": "AZ", "Ark.": "AR", "Calif.": "CA", "Colo.": "CO", "Conn.": "CT",
    "Del.": "DE", "Fla.": "FL", "Ga.": "GA", "Hawaii": "HI", "Idaho": "ID", "Ill.": "IL", "Ind.": "IN",
    "Iowa": "IA", "Kans.": "KS", "Ky.": "KY", "La.": "LA", "Maine": "ME", "Md.": "MD", "Mass.": "MA",
    "Mich.": "MI", "Minn.": "MN", "Miss.": "MS", "Mo.": "MO", "Mont.": "MT", "Nebr.": "NE", "Nev.": "NV",
    "N.H.": "NH", "N.J.": "NJ", "N.M.": "NM", "N.Y.": "NY", "N.C.": "NC", "N.D.": "ND", "Ohio": "OH",
    "Okla.": "OK", "Ore.": "OR", "Pa.": "PA", "R.I.": "RI", "S.C.": "SC", "S.D.": "SD", "Tenn.": "TN",
    "Tex.": "TX", "Utah": "UT", "Vt.": "VT", "Va.": "VA", "Wash.": "WA", "W.Va.": "WV", "Wis.": "WI",
    "Wyo.": "WY", "D.C.": "DC",
}


class ManualDownloadRequired(RuntimeError):
    """Raised when an official file blocks automated download and must be fetched by hand."""


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------


def fetch(url: str, dest: Path, offline: bool = False, force: bool = False) -> Path:
    """Download ``url`` to ``dest`` (idempotent). Raises if the server returns nothing usable."""
    import httpx

    if dest.exists() and dest.stat().st_size > 0 and not force:
        return dest
    if offline:
        raise FileNotFoundError(f"{dest} missing and --offline was given")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=120) as c:
        r = c.get(url)
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"download failed ({r.status_code}, {len(r.content)} bytes): {url}")
    dest.write_bytes(r.content)
    return dest


def bls_api(series: list[str], start: int, end: int) -> dict[str, dict[str, float]]:
    """Query the official BLS public API v1 (no key, <=25 series). Returns {series: {year: value}}."""
    import httpx

    r = httpx.post(
        URLS["bls_api"],
        json={"seriesid": series, "startyear": str(start), "endyear": str(end)},
        headers={"User-Agent": UA},
        timeout=60,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API error: {d.get('message')}")
    out: dict[str, dict[str, float]] = {}
    for s in d["Results"]["series"]:
        out[s["seriesID"]] = {x["year"]: float(x["value"]) for x in s["data"] if x["period"] == "A01"}
    return out


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles."""
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Metros + places (Census population estimates + Gazetteer)
# ---------------------------------------------------------------------------


def _first_city(cbsa_name: str) -> tuple[str, str, list[str]]:
    """'Nashville-Davidson--Murfreesboro--Franklin, TN' -> ('Nashville', 'TN', ['Nashville','Murfreesboro','Franklin'])."""
    cities_part, states_part = cbsa_name.rsplit(",", 1)
    states = states_part.strip().split()[0].split("-")
    cities = [c.strip() for c in re.split(r"--|-|/", cities_part) if c.strip()]
    first = cities[0]
    if first == "Nashville":
        cities = ["Nashville", "Murfreesboro", "Franklin"]
    if first == "Louisville":
        cities = ["Louisville"]
    return first, states[0], cities


def build_places(offline: bool) -> pd.DataFrame:
    """All Census places (name, state, lat, lon) for city geocoding."""
    z = fetch(URLS["gaz_place"], RAW_DIR / "census" / "2024_Gaz_place_national.zip", offline)
    with zipfile.ZipFile(z) as zf:
        name = [n for n in zf.namelist() if n.endswith(".txt")][0]
        df = pd.read_csv(zf.open(name), sep="\t", dtype=str, encoding="latin-1")
    df.columns = [c.strip() for c in df.columns]
    lsad_words = (
        r"\s+(city and borough|consolidated government \(balance\)|metropolitan government \(balance\)|"
        r"metro government \(balance\)|unified government \(balance\)|city \(balance\)|urban county|"
        r"municipality|city|town|village|borough|CDP|township)$"
    )
    out = pd.DataFrame(
        {
            "full_name": df["NAME"].str.strip(),
            "name": df["NAME"].str.strip().str.replace(lsad_words, "", regex=True).str.replace(
                r"^Nashville-Davidson$", "Nashville", regex=True
            ).str.replace(r"^Louisville/Jefferson County$", "Louisville", regex=True)
            .str.replace(r"^Indianapolis city$", "Indianapolis", regex=True),
            "state": df["USPS"].str.strip(),
            "lat": df["INTPTLAT"].astype(float),
            "lon": df["INTPTLONG"].str.strip().astype(float),
            "aland_sqmi": df["ALAND_SQMI"].astype(float),
            "is_cdp": df["NAME"].str.strip().str.endswith("CDP"),
        }
    )
    # Prefer incorporated places over CDPs, larger land area first, for duplicate names.
    out = out.sort_values(["state", "name", "is_cdp", "aland_sqmi"], ascending=[True, True, True, False])
    out = out.drop_duplicates(["state", "name"], keep="first").reset_index(drop=True)
    out["key"] = (out["name"].str.lower() + "|" + out["state"].str.lower())
    return out


def build_metros(offline: bool, places: pd.DataFrame) -> pd.DataFrame:
    """Top-N MSAs by 2024 population with principal-city coordinates."""
    pop = pd.read_csv(fetch(URLS["census_pop"], RAW_DIR / "census" / "cbsa-est2024-alldata.csv", offline),
                      encoding="latin-1", dtype={"CBSA": str})
    msa = pop[pop["LSAD"] == "Metropolitan Statistical Area"].sort_values("POPESTIMATE2024", ascending=False)
    msa = msa.head(N_METROS).reset_index(drop=True)
    z = fetch(URLS["gaz_cbsa"], RAW_DIR / "census" / "2024_Gaz_cbsa_national.zip", offline)
    with zipfile.ZipFile(z) as zf:
        g = pd.read_csv(zf.open([n for n in zf.namelist() if n.endswith(".txt")][0]), sep="\t", dtype=str,
                        encoding="latin-1")
    g.columns = [c.strip() for c in g.columns]
    g = g.set_index("GEOID")
    rows = []
    for i, r in msa.iterrows():
        first, st, cities = _first_city(r["NAME"])
        p = places[(places["state"] == st) & (places["name"] == first)]
        if p.empty:
            raise RuntimeError(f"principal city not found in gazetteer: {first}, {st}")
        p = p.iloc[0].copy()
        if first == "San Francisco" and st == "CA":
            # The Census internal point for San Francisco city lies offshore (the city includes the
            # Farallon Islands). Use NOAA station USW00023272 "SAN FRANCISCO DWTN" as the city location.
            p["lat"], p["lon"] = 37.7706, -122.4269
        gc = g.loc[r["CBSA"]]
        rows.append(
            {
                "cbsa": r["CBSA"],
                "name": r["NAME"],
                "short_name": f"{first}, {st}",
                "principal_city": first,
                "state": st,
                "states": r["NAME"].rsplit(",", 1)[1].strip(),
                "title_cities": "|".join(cities),
                "pop2024": int(r["POPESTIMATE2024"]),
                "rank": i + 1,
                "lat": float(p["lat"]),
                "lon": float(p["lon"]),
                "cbsa_lat": float(gc["INTPTLAT"]),
                "cbsa_lon": float(str(gc["INTPTLONG"]).strip()),
                "land_sqmi": float(gc["ALAND_SQMI"]),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# BEA Regional Price Parities
# ---------------------------------------------------------------------------


def build_rpp(offline: bool, metros: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """BEA RPPs (all items, goods, housing, utilities, other services) for the latest year."""
    z = fetch(URLS["bea_rpp"], RAW_DIR / "bea" / "MARPP.zip", offline)
    with zipfile.ZipFile(z) as zf:
        name = [n for n in zf.namelist() if n.startswith("MARPP_MSA") and n.endswith(".csv")][0]
        df = pd.read_csv(zf.open(name), dtype={"GeoFIPS": str}, encoding="latin-1")
    df["GeoFIPS"] = df["GeoFIPS"].str.strip().str.strip('"')
    year = [c for c in df.columns if c.isdigit()][-1]
    keymap = {1: "rpp_all", 2: "rpp_goods", 3: "rpp_housing", 4: "rpp_utilities", 5: "rpp_other"}
    df = df[df["LineCode"].isin(keymap.keys())]
    wide = df.pivot_table(index="GeoFIPS", columns="LineCode", values=year, aggfunc="first").rename(columns=keymap)
    wide = wide.apply(pd.to_numeric, errors="coerce")
    out = metros[["cbsa"]].merge(wide, left_on="cbsa", right_index=True, how="left")
    missing = out[out["rpp_all"].isna()]["cbsa"].tolist()
    if missing:
        print(f"  ! RPP missing for {missing}")
    out["rpp_year"] = int(year)
    return out, year


# ---------------------------------------------------------------------------
# Census ACS 2024 1-year (summary file, table based)
# ---------------------------------------------------------------------------


def _acs(table: str, offline: bool) -> pd.DataFrame:
    p = fetch(URLS["acs_base"] + f"acsdt1y2024-{table}.dat", RAW_DIR / "census_acs" / f"acsdt1y2024-{table}.dat", offline)
    df = pd.read_csv(p, sep="|", dtype=str)
    df = df[df["GEO_ID"].str.startswith("310M")].copy()
    df["cbsa"] = df["GEO_ID"].str[-5:]
    return df.set_index("cbsa")


def build_acs(offline: bool, metros: pd.DataFrame) -> pd.DataFrame:
    """Mean commute, share aged 22-34, and median gross rent by bedrooms."""
    age, agg, workers = _acs("b01001", offline), _acs("b08013", offline), _acs("b08303", offline)
    rent, rent_all = _acs("b25031", offline), _acs("b25064", offline)

    def num(df: pd.DataFrame, cbsa: str, col: str) -> float | None:
        try:
            v = df.loc[cbsa, col]
            return float(v) if v not in (None, "", "null", "-") else None
        except (KeyError, ValueError):
            return None

    rows = []
    for c in metros["cbsa"]:
        total = num(age, c, "B01001_E001")
        young = sum(num(age, c, f"B01001_E{k:03d}") or 0 for k in (10, 11, 12, 34, 35, 36))
        aggt, w = num(agg, c, "B08013_E001"), num(workers, c, "B08303_E001")
        rows.append(
            {
                "cbsa": c,
                "population_acs": total,
                "share_22_34": (young / total) if total else None,
                "mean_commute_min": (aggt / w) if aggt and w else None,
                "acs_rent_all": num(rent_all, c, "B25064_E001"),
                "acs_rent_0br": num(rent, c, "B25031_E002"),
                "acs_rent_1br": num(rent, c, "B25031_E003"),
                "acs_rent_2br": num(rent, c, "B25031_E004"),
                "acs_rent_3br": num(rent, c, "B25031_E005"),
                "acs_rent_4br": num(rent, c, "B25031_E006"),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Zillow Observed Rent Index
# ---------------------------------------------------------------------------


def build_zori(offline: bool, metros: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Latest ZORI, its YoY change, and the 2024 average (to age ACS 2024 rents to today)."""
    z = pd.read_csv(fetch(URLS["zillow_zori"], RAW_DIR / "zillow" / "Metro_zori_uc_sfrcondomfr_sm_month.csv", offline))
    z = z[z["RegionType"] == "msa"]
    months = [c for c in z.columns if re.match(r"\d{4}-\d{2}-\d{2}", c)]
    latest = months[-1]
    prior = months[-13]
    y2024 = [m for m in months if m.startswith("2024-")]
    rows = []
    for _, m in metros.iterrows():
        cand = z[z["RegionName"] == m["short_name"]]
        if cand.empty:
            cand = z[(z["StateName"] == m["state"]) & z["RegionName"].str.startswith(m["principal_city"])]
        if cand.empty:
            print(f"  ! ZORI: no match for {m['short_name']}")
            rows.append({"cbsa": m["cbsa"]})
            continue
        r = cand.iloc[0]
        rows.append(
            {
                "cbsa": m["cbsa"],
                "zori_region": r["RegionName"],
                "zori_latest": float(r[latest]),
                "zori_latest_month": latest[:7],
                "zori_yoy_pct": float((r[latest] / r[prior] - 1) * 100),
                "zori_2024_avg": float(r[y2024].mean()),
            }
        )
    return pd.DataFrame(rows), latest[:7]


# ---------------------------------------------------------------------------
# NOAA 1991-2020 Climate Normals
# ---------------------------------------------------------------------------

NORMAL_FIELDS = {
    "ANN-TAVG-NORMAL": "tavg_f",
    "ANN-TMAX-AVGNDS-GRTH090": "days_over_90",
    "ANN-TMIN-AVGNDS-LSTH032": "days_below_32",
    "ANN-TMAX-AVGNDS-GRTH050": "days_max_over_50",
    "ANN-PRCP-NORMAL": "precip_in",
    "ANN-PRCP-AVGNDS-GE001HI": "precip_days",
    "ANN-SNOW-NORMAL": "snow_in",
    "DJF-TAVG-NORMAL": "winter_tavg_f",
    "JJA-TMAX-NORMAL": "summer_tmax_f",
}


def build_climate(offline: bool, metros: pd.DataFrame) -> pd.DataFrame:
    """Pick the best first-order (USW) station near each principal city and read its annual normals."""
    st_path = fetch(URLS["noaa_stations"], RAW_DIR / "noaa" / "ghcnd-stations.txt", offline)
    stations = []
    for line in st_path.read_text(errors="ignore").splitlines():
        if line.startswith("USW"):
            stations.append((line[0:11], float(line[12:20]), float(line[21:30]), line[38:40], line[41:71].strip(),
                             bool(line[80:85].strip())))
    rows = []
    for _, m in metros.iterrows():
        cands = []
        for sid, lat, lon, st, name, wmo in stations:
            d = haversine_mi(m["lat"], m["lon"], lat, lon)
            if d <= 45:
                # Prefer the city's primary first-order station: name contains the city and it has a WMO id
                # (major airports do), then any station named for the city, then any airport, then distance.
                city_hit = m["principal_city"].upper()[:5] in name
                airport = bool(re.search(r"\b(AP|INTL|AIRPORT|ARPT)\b", name))
                cands.append((not city_hit, not wmo, not airport, d, sid, name))
        cands.sort()
        chosen = None
        for *_, d, sid, name in cands[:8]:
            try:
                p = fetch(URLS["noaa_normals"] + f"{sid}.csv", RAW_DIR / "noaa" / "normals" / f"{sid}.csv", offline)
            except Exception:
                continue
            rec = pd.read_csv(p, dtype=str).iloc[0]
            vals = {}
            for k, out in NORMAL_FIELDS.items():
                v = str(rec.get(k, "")).strip()
                try:
                    vals[out] = float(v) if v not in ("", "nan") and float(v) > -7000 else None
                except ValueError:
                    vals[out] = None
            if vals["tavg_f"] is not None and vals["precip_days"] is not None and vals["days_over_90"] is not None:
                chosen = {"cbsa": m["cbsa"], "station_id": sid, "station_name": str(rec.get("NAME", name)).strip(),
                          "station_dist_mi": round(d, 1), **vals}
                break
        if not chosen:
            print(f"  ! climate: no station for {m['short_name']}")
            chosen = {"cbsa": m["cbsa"]}
        rows.append(chosen)
    df = pd.DataFrame(rows)
    df["comfortable_days"] = (df["days_max_over_50"] - df["days_over_90"]).clip(lower=0)
    df["dry_days"] = 365 - df["precip_days"]
    return df


# ---------------------------------------------------------------------------
# National parks (outdoors access)
# ---------------------------------------------------------------------------


def build_parks(offline: bool) -> pd.DataFrame:
    """The 63 U.S. national parks with coordinates (from Wikipedia's list, which cites NPS)."""
    p = fetch(URLS["nps_list"], RAW_DIR / "nps" / "national_parks.html", offline)
    doc = p.read_text(errors="ignore")
    table = doc[doc.find('<table class="wikitable'):]
    table = table[: table.find("</table>")]
    rows = []
    for tr in table.split("<tr")[1:]:
        geo = re.search(r'class="geo">\s*(-?\d+\.\d+);\s*(-?\d+\.\d+)', tr)
        name = re.search(r'<th[^>]*scope="row"[^>]*>.*?<a [^>]*title="([^"]+)"', tr, re.S)
        if geo and name:
            rows.append({"park": html.unescape(name.group(1)), "lat": float(geo.group(1)), "lon": float(geo.group(2))})
    df = pd.DataFrame(rows).drop_duplicates("park")
    # Gateway Arch NP is a 91-acre urban memorial, not outdoor-recreation access; excluded from outdoors scoring.
    df = df[~df["park"].str.startswith("Gateway Arch")]
    if not 59 <= len(df) <= 66:
        raise RuntimeError(f"expected ~62 national parks, parsed {len(df)}")
    return df


def build_outdoors(metros: pd.DataFrame, parks: pd.DataFrame) -> pd.DataFrame:
    """National parks within 150/300 miles and distance to the nearest one."""
    rows = []
    for _, m in metros.iterrows():
        d = parks.apply(lambda r: haversine_mi(m["lat"], m["lon"], r["lat"], r["lon"]), axis=1)
        rows.append({"cbsa": m["cbsa"], "parks_150mi": int((d <= 150).sum()), "parks_300mi": int((d <= 300).sum()),
                     "nearest_park": parks.loc[d.idxmin(), "park"], "nearest_park_mi": round(float(d.min()), 0)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# BLS Consumer Expenditure Survey (national, by consumer-unit size)
# ---------------------------------------------------------------------------

CE_SERIES = {
    "food_home": "CXUFOODHOMELB0502M",
    "food_away": "CXUFOODAWAYLB0502M",
    "transportation": "CXUTRANSLB0502M",
    "entertainment": "CXUENTRTAINLB0502M",
    "apparel": "CXUAPPARELLB0502M",
    "personal_care": "CXUPERSCARELB0502M",
    "utilities_1p": "CXUUTILSLB0502M",
    "utilities_2p": "CXUUTILSLB0504M",
    "utilities_3p": "CXUUTILSLB0505M",
    "utilities_4p": "CXUUTILSLB0506M",
}


def build_ce(offline: bool) -> dict[str, Any]:
    """Annual spending of one-person households (utilities also for 2-4 person households)."""
    cache = RAW_DIR / "bls_ce" / "ce_processed_source.json"
    if offline or cache.exists():
        data = json.loads(cache.read_text())
    else:
        data = bls_api(list(CE_SERIES.values()), date.today().year - 2, date.today().year)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, indent=1))
    year = max(max(v.keys()) for v in data.values() if v)
    vals = {k: data[s].get(year) for k, s in CE_SERIES.items()}
    if any(v is None for v in vals.values()):
        raise RuntimeError(f"CE series missing for {year}: {vals}")
    return {"year": int(year), "annual": vals, "series": CE_SERIES,
            "note": "Consumer Expenditure Survey, annual mean expenditure; LB0502 = one-person consumer units, "
                    "LB0504/5/6 = two/three/four-person consumer units."}


# ---------------------------------------------------------------------------
# Federal + FICA (IRS Rev. Proc. 2025-32, IRS Publication 15 (2026))
# ---------------------------------------------------------------------------


def _pdf_text(p: Path) -> str:
    import pdfplumber

    with pdfplumber.open(p) as pdf:
        return "\n".join((pg.extract_text() or "") for pg in pdf.pages)


def build_federal(offline: bool) -> dict[str, Any]:
    """Parse TY2026 single-filer brackets + standard deduction and the 2026 SS wage base."""
    txt = _pdf_text(fetch(URLS["irs_rp"], RAW_DIR / "irs" / "rp-25-32.pdf", offline))
    sec = txt[txt.find("SECTION 4. 2026 ADJUSTED ITEMS"):]
    t3 = sec[sec.find("TABLE 3"): sec.find("TABLE 4")]
    rates = [float(x) / 100 for x in re.findall(r"(\d+)% of", t3)]
    over = [float(x.replace(",", "")) for x in re.findall(r"Over \$([\d,]+)", t3)]
    thresholds = [0.0] + sorted(set(over))
    if len(rates) != 7 or len(thresholds) != 7 or rates != sorted(rates):
        raise RuntimeError(f"unexpected federal table parse: rates={rates} thresholds={thresholds}")
    sd_block = sec[sec.find("Standard Deduction.") :][:900]
    m = re.search(r"Unmarried Individuals.*?\$([\d,]+)", sd_block, re.S)
    std = float(m.group(1).replace(",", ""))

    p15 = _pdf_text(fetch(URLS["irs_p15"], RAW_DIR / "irs" / "p15.pdf", offline))
    if "Publication 15 (2026)" not in p15:
        raise RuntimeError("IRS Pub 15 is not the 2026 edition")
    wb = re.search(r"social security wage base limit is \$([\d,]+)", p15.replace("\n", " "))
    ss_base = float(wb.group(1).replace(",", ""))
    flat = p15.replace("\n", " ")
    for needle in ("6.2%", "1.45%", "0.9%", "$200,000"):
        if needle not in flat:
            raise RuntimeError(f"expected FICA term {needle} not found in Pub 15")
    return {
        "tax_year": 2026,
        "filing_status": "single",
        "standard_deduction": std,
        "brackets": [{"over": t, "rate": r} for t, r in zip(thresholds, rates)],
        "fica": {"ss_rate": 0.062, "ss_wage_base": ss_base, "medicare_rate": 0.0145,
                 "addl_medicare_rate": 0.009, "addl_medicare_threshold": 200000.0},
        "k401_elective_limit": 24500.0,
        "sources": [
            {"name": "IRS Rev. Proc. 2025-32, Sec. 4.01 Table 3 and Sec. 4.15", "url": URLS["irs_rp"], "data_year": "TY2026"},
            {"name": "IRS Publication 15 (2026), Social security and Medicare tax", "url": URLS["irs_p15"], "data_year": "2026"},
            {"name": "IRS Notice 2025-67 (2026 401(k) elective deferral limit $24,500)", "url": "https://www.irs.gov/pub/irs-drop/n-25-67.pdf", "data_year": "2026"},
        ],
    }


# ---------------------------------------------------------------------------
# State income tax (Tax Foundation 2026 table)
# ---------------------------------------------------------------------------

# Footnote-driven rules implemented in tax math (backend/data/lookups.py). Keys are state codes.
STATE_RULES: dict[str, dict[str, Any]] = {
    "AL": {"std_phaseout": {"base": 3000, "floor": 2500, "start": 25499, "per": 500, "step": 25}, "note": "TF footnote (c)"},
    "CT": {"exemption_phaseout": {"start": 30000, "per": 1000, "step": 1000},
           "two_pct_recapture": {"start": 56500, "per": 5000, "step": 1000}, "note": "TF footnotes (p), (r); personal tax credits (q) not modeled"},
    "OH": {"exemption_tiers": [[40000, 2400], [80000, 2150], [500000, 1900], [1e12, 0]], "note": "TF footnote (dd)"},
    "UT": {"credit_phaseout": {"start": 18213, "rate": 0.013}, "note": "TF footnote (gg) (2025 threshold)"},
    "WI": {"std_phaseout_linear": {"start": 20119, "end": 136453}, "note": "TF footnote (ii)"},
    "IL": {"exemption_cutoff": 250000, "note": "TF footnote (v)"},
    "MD": {"exemption_phaseout_linear": {"start": 100000, "end": 150000}, "note": "TF footnote (aa)"},
    "OR": {"credit_cutoff": 100000, "note": "TF footnote (ee); federal-tax subtraction (b) not modeled"},
    "PA": {"taxes_401k": True, "note": "Pennsylvania does not exclude employee 401(k) deferrals from compensation"},
}


def _cell_num(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    if s in ("", "n.a.", "n.a", "none"):
        return None
    try:
        return float(s.replace(",", "").replace("$", ""))
    except ValueError:
        return None


def build_states(offline: bool) -> dict[str, Any]:
    """Parse single-filer brackets, standard deduction and personal exemption/credit for every state + DC."""
    p = fetch(URLS["taxfoundation"], RAW_DIR / "taxfoundation" / "2026-State-Individual-Income-Tax-Rates-Brackets.xlsx", offline)
    df = pd.read_excel(p, "2026", header=None)
    states: dict[str, dict[str, Any]] = {}
    current: str | None = None
    for _, r in df.iloc[2:].iterrows():
        c0 = "" if pd.isna(r[0]) else str(r[0]).strip()
        if re.match(r"^\([a-z]+\) ", c0) and len(c0) > 40:
            break  # footnotes start
        label = re.sub(r"\s*\(.*$", "", c0).strip()
        if label in STATE_ABBR:
            current = STATE_ABBR[label]
            sd_raw, ex_raw = r[7], r[9]
            states[current] = {"brackets": [], "std_deduction": 0.0, "exemption": 0.0, "credit": 0.0,
                               "std_raw": None if pd.isna(sd_raw) else str(sd_raw).strip(),
                               "exemption_raw": None if pd.isna(ex_raw) else str(ex_raw).strip(),
                               "no_wage_tax": False}
            for raw, field in ((sd_raw, "std_deduction"), (ex_raw, "exemption")):
                s = "" if pd.isna(raw) else str(raw).strip()
                m = re.match(r"\$([\d,]+) credit", s)
                if m:
                    states[current]["credit"] += float(m.group(1).replace(",", ""))
                else:
                    states[current][field] = _cell_num(raw) or 0.0
        if current is None:
            continue
        rate_raw = r[1]
        rs = "" if pd.isna(rate_raw) else str(rate_raw).strip()
        if rs == "none" or rs.startswith("Capital gains"):
            states[current]["no_wage_tax"] = True
            continue
        rate, thr = _cell_num(rate_raw), _cell_num(r[3])
        if rate is not None and thr is not None and not states[current]["no_wage_tax"]:
            states[current]["brackets"].append({"over": thr, "rate": rate})
    for st, s in states.items():
        b = s["brackets"]
        if b and b[0]["over"] > 0:
            b.insert(0, {"over": 0.0, "rate": 0.0})  # e.g. Ohio's 0% band below $26,050
        if s["no_wage_tax"]:
            s["brackets"] = []
        s["rules"] = STATE_RULES.get(st, {})
    if len(states) != 51:
        raise RuntimeError(f"expected 51 jurisdictions, parsed {len(states)}")
    return {
        "tax_year": 2026,
        "states": states,
        "source": {"name": "Tax Foundation, State Individual Income Tax Rates and Brackets, 2026 (single filer columns)",
                   "url": URLS["taxfoundation"], "data_year": "TY2026"},
    }


# ---------------------------------------------------------------------------
# Local income taxes (curated, cited)
# ---------------------------------------------------------------------------

# base: "state_taxable" (state taxable income), "gross_wages" (Medicare-style wages: includes 401(k)
# deferrals, excludes Sec. 125 health premiums), or "head_tax" (fixed $/year).
LOCAL_TAXES: list[dict[str, Any]] = [
    {"state": "NY", "cities": ["New York", "New York City", "NYC", "Manhattan", "Brooklyn", "Bronx", "Queens", "Staten Island", "Long Island City"],
     "name": "New York City resident income tax", "base": "state_taxable",
     "brackets": [{"over": 0, "rate": 0.03078}, {"over": 12000, "rate": 0.03762}, {"over": 25000, "rate": 0.03819}, {"over": 50000, "rate": 0.03876}],
     "url": URLS["nyc_it201i"], "verified": "parsed from official NYS DTF IT-201-I (p.40); NYC rates unchanged for 2026", "verify_pattern": r"12,000 25,000 \$ 369 plus 3\.762%"},
    {"state": "PA", "cities": ["Philadelphia"], "name": "Philadelphia Wage Tax (resident)", "base": "gross_wages",
     "rate": 0.037375, "url": "https://www.phila.gov/services/payments-assistance-taxes/business-taxes/wage-tax-employers/",
     "verified": "phila.gov: 3.74% Jul 2025-Jun 2026, 3.735% from Jul 1 2026 -> 2026 blended 3.7375%"},
    {"state": "PA", "cities": ["Pittsburgh"], "name": "Pittsburgh Earned Income Tax (1% city + 2% school) + $52 LST", "base": "gross_wages",
     "rate": 0.03, "head_tax": 52, "url": "https://www.pittsburghpa.gov/City-Government/Finances/Taxes",
     "verified": "pittsburghpa.gov tax page: resident 3% total; LST $52"},
    {"state": "OH", "cities": ["Columbus"], "name": "Columbus municipal income tax", "base": "gross_wages", "rate": 0.025,
     "url": "https://www.columbus.gov/Government/City-Auditor/Income-Tax-Division/General-Income-Tax-Information", "verified": "columbus.gov: 2.5%"},
    {"state": "OH", "cities": ["Cleveland"], "name": "Cleveland municipal income tax", "base": "gross_wages", "rate": 0.025,
     "url": "https://www.ccatax.ci.cleveland.oh.us/", "verified": "secondary sources (Central Collection Agency administers): 2.5%"},
    {"state": "OH", "cities": ["Cincinnati"], "name": "Cincinnati municipal income tax", "base": "gross_wages", "rate": 0.018,
     "url": "https://www.cincinnati-oh.gov/finance/income-taxes/", "verified": "cincinnati-oh.gov fetched: 1.8% effective 10/02/20",
     "verify_pattern": r"1\.8%"},
    {"state": "MI", "cities": ["Detroit"], "name": "Detroit city income tax (resident)", "base": "state_taxable", "rate": 0.024,
     "url": "https://detroitmi.gov/departments/office-chief-financial-officer/ocfo-divisions/office-treasury/income-tax",
     "verified": "MCL 141.503 statutory 2.4% resident cap; city levies at cap"},
    {"state": "MI", "cities": ["Grand Rapids"], "name": "Grand Rapids city income tax (resident)", "base": "state_taxable", "rate": 0.015,
     "url": "https://www.grandrapidsmi.gov/Government/Departments/Income-Tax", "verified": "1.5% resident (city forms + secondary)"},
    {"state": "KY", "cities": ["Louisville"], "name": "Louisville Metro occupational license tax (resident)", "base": "gross_wages", "rate": 0.022,
     "url": "https://louisvilleky.gov/government/revenue-commission", "verified": "UofL 2025 payroll form + 2026 guides: 2.20% resident"},
    {"state": "MO", "cities": ["Kansas City"], "name": "Kansas City earnings tax", "base": "gross_wages", "rate": 0.01,
     "url": "https://www.kcmo.gov/city-hall/departments/finance/earnings-tax", "verified": "1% (Show-Me Institute, secondary)"},
    {"state": "MO", "cities": ["St. Louis", "Saint Louis"], "name": "St. Louis City earnings tax", "base": "gross_wages", "rate": 0.01,
     "url": "https://www.stlouis-mo.gov/government/departments/collector-revenue/earnings-tax/", "verified": "1% (Show-Me Institute, secondary)"},
    {"state": "IN", "cities": ["Indianapolis"], "name": "Marion County local income tax", "base": "state_taxable", "rate": 0.0202,
     "url": "https://www.in.gov/dor/", "verified": "DOR Departmental Notice #1 (2026) via secondary sources: 2.02%"},
    {"state": "MD", "cities": ["Baltimore"], "name": "Baltimore City local income tax", "base": "state_taxable", "rate": 0.032,
     "url": "https://dls.maryland.gov/pubs/prod/NoPblTabPDF/2026CountyLocalTaxRates.pdf", "verified": "Maryland DLS 2026 county local tax rates: 3.20%"},
    {"state": "AL", "cities": ["Birmingham"], "name": "Birmingham occupational tax", "base": "gross_wages", "rate": 0.01,
     "url": "https://www.birminghamal.gov/", "verified": "1% on gross wages (League of Municipalities survey, secondary)"},
    {"state": "OR", "cities": ["Portland"], "name": "Metro SHS (1% > $128k) + Multnomah PFA (1.5% > $125k, 3% > $250k)",
     "base": "state_taxable", "brackets_sum": [
         {"name": "Metro SHS", "brackets": [{"over": 0, "rate": 0.0}, {"over": 128000, "rate": 0.01}]},
         {"name": "Multnomah PFA", "brackets": [{"over": 0, "rate": 0.0}, {"over": 125000, "rate": 0.015}, {"over": 250000, "rate": 0.03}]}],
     "url": "https://www.portland.gov/revenue/personal-tax", "verified": "portland.gov SHS 2026 single threshold $128,000; PFA tiers from county (verify)"},
    {"state": "CO", "cities": ["Denver"], "name": "Denver Occupational Privilege Tax (employee)", "base": "head_tax", "head_tax": 69,
     "url": "https://denvergov.org/Government/Agencies-Departments-Offices/Agencies-Departments-Offices-Directory/Department-of-Finance/Our-Divisions/Treasury/Business-Tax-Information/Business-Tax-FAQ",
     "verified": "Denver Business Tax FAQ: $5.75/month employee"},
    {"state": "CO", "cities": ["Aurora"], "name": "Aurora Occupational Privilege Tax (employee)", "base": "head_tax", "head_tax": 24,
     "url": "https://www.auroragov.org/", "verified": "$2/month employee (secondary)"},
    {"state": "DE", "cities": ["Wilmington"], "name": "Wilmington earned income tax", "base": "gross_wages", "rate": 0.0125,
     "url": "https://www.wilmingtonde.gov/", "verified": "1.25% (secondary)"},
]


def build_local(offline: bool) -> dict[str, Any]:
    """Curated local income taxes; where an official document was downloaded, re-verify the rate text."""
    nyc_txt = _pdf_text(fetch(URLS["nyc_it201i"], RAW_DIR / "localtax" / "it201i_2025.pdf", offline)).replace("\n", " ")
    out = []
    for row in LOCAL_TAXES:
        row = dict(row)
        pat = row.pop("verify_pattern", None)
        if pat and "it201i" in row["url"]:
            if not re.search(pat, nyc_txt):
                raise RuntimeError("NYC schedule text not found in IT-201-I; re-check rates")
            row["auto_verified"] = True
        out.append(row)
    return {"tax_year": 2026, "localities": out,
            "assumption": "You live in the office city (resident rates). Commuter/nonresident rates are not modeled."}


# ---------------------------------------------------------------------------
# BLS OEWS (manual download: bls.gov blocks automated clients)
# ---------------------------------------------------------------------------

OEWS_HELP = """
BLS OEWS wage data must be downloaded by hand (bls.gov blocks automated downloads).

  1. Open https://www.bls.gov/oes/tables.htm in your browser.
  2. Under the most recent year (May 2025), click "Metropolitan and nonmetropolitan area" -> XLSX (zip).
     The file is named like  oesm25ma.zip  (~70 MB).
  3. (Optional, national fallback) also download "National" XLSX:  oesm25nat.zip
  4. Put the zip file(s) in:  backend/data/raw/bls_oews/
  5. Re-run:  .venv/bin/python -m backend.data.download_data --offline
"""


def _read_oews_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        xl = [n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls")) and "field" not in n.lower()]
        if not xl:
            raise RuntimeError(f"no xlsx in {path}")
        with zf.open(sorted(xl, key=lambda n: -zf.getinfo(n).file_size)[0]) as fh:
            return pd.read_excel(fh, dtype=str)


def build_oews(metros: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Annual wage percentiles for every detailed occupation in each supported metro (+ national if provided)."""
    d = RAW_DIR / "bls_oews"
    ma = sorted(d.glob("oesm*ma*.zip")) + sorted(d.glob("MSA_M*_dl.xlsx"))
    if not ma:
        raise ManualDownloadRequired(OEWS_HELP)
    f = ma[-1]
    raw = _read_oews_zip(f) if f.suffix == ".zip" else pd.read_excel(f, dtype=str)
    raw.columns = [c.strip().upper() for c in raw.columns]
    year_m = re.search(r"oesm(\d\d)", f.name.lower()) or re.search(r"M(20\d\d)", f.name)
    year = ("20" + year_m.group(1)) if year_m and len(year_m.group(1)) == 2 else (year_m.group(1) if year_m else "unknown")
    frames = [raw[raw["AREA"].isin(set(metros["cbsa"]))].assign(area_level="metro")]
    nat = sorted(d.glob("oesm*nat*.zip"))
    if nat:
        n = _read_oews_zip(nat[-1])
        n.columns = [c.strip().upper() for c in n.columns]
        if "O_GROUP" in n.columns:
            n = n[n["O_GROUP"].str.lower() == "detailed"]
        if "NAICS" in n.columns:
            n = n[n["NAICS"].astype(str).isin(["000000", "0"])] if (n["NAICS"].astype(str) == "000000").any() else n
        n["AREA"] = "99999"
        n["AREA_TITLE"] = "U.S. (national)"
        frames.append(n.assign(area_level="national"))
    df = pd.concat(frames, ignore_index=True)
    if "O_GROUP" in df.columns:
        df = df[df["O_GROUP"].str.lower() == "detailed"]
    keep = {"AREA": "area", "AREA_TITLE": "area_title", "OCC_CODE": "soc", "OCC_TITLE": "occ_title", "TOT_EMP": "employment",
            "A_MEAN": "mean", "A_PCT10": "p10", "A_PCT25": "p25", "A_MEDIAN": "p50", "A_PCT75": "p75", "A_PCT90": "p90"}
    df = df[list(keep) + ["area_level"]].rename(columns=keep)
    for c in ["employment", "mean", "p10", "p25", "p50", "p75", "p90"]:
        # '*' = not available, '#' = >= top-coded value, '**' = employment not available
        df[c + "_flag"] = df[c].astype(str).str.contains(r"[#*]")
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
    df = df.drop(columns=[c for c in df.columns if c.endswith("_flag") and not c.startswith("p90")])
    missing = sorted(set(metros["cbsa"]) - set(df[df.area_level == "metro"]["area"]))
    if missing:
        print(f"  ! OEWS: no rows for metros {missing}")
    return df.reset_index(drop=True), year


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true", help="use files already in backend/data/raw")
    args = ap.parse_args()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"built": TODAY, "tables": {}}

    def save(df: pd.DataFrame, name: str, meta: dict[str, Any]) -> None:
        df.to_parquet(PROCESSED_DIR / f"{name}.parquet", index=False)
        manifest["tables"][name] = {"rows": len(df), **meta}
        print(f"  ✓ {name}.parquet  ({len(df)} rows)")

    print("Census places + metros…")
    places = build_places(args.offline)
    save(places[["name", "state", "lat", "lon", "key"]], "places",
         {"source": "U.S. Census Bureau 2024 Gazetteer (places)", "url": URLS["gaz_place"], "data_year": "2024", "real": True})
    metros = build_metros(args.offline, places)
    save(metros, "metros", {"source": "Census Bureau Vintage 2024 CBSA population estimates + 2024 Gazetteer",
                            "url": URLS["census_pop"], "data_year": "2024", "real": True})

    print("BEA Regional Price Parities…")
    rpp, rpp_year = build_rpp(args.offline, metros)
    save(rpp, "rpp", {"source": "BEA Regional Price Parities by MSA (MARPP)", "url": URLS["bea_rpp"], "data_year": rpp_year, "real": True})

    print("Census ACS 2024 1-year…")
    acs = build_acs(args.offline, metros)
    print("Zillow ZORI…")
    zori, zmonth = build_zori(args.offline, metros)
    rent = acs.merge(zori, on="cbsa", how="left")
    save(rent, "metro_stats", {"source": "Census ACS 2024 1-year (B01001, B08013, B08303, B25031, B25064) + Zillow ZORI",
                               "url": URLS["acs_base"], "data_year": f"ACS 2024; ZORI {zmonth}", "real": True,
                               "zori_url": URLS["zillow_zori"]})

    print("NOAA climate normals…")
    climate = build_climate(args.offline, metros)
    save(climate, "climate", {"source": "NOAA NCEI U.S. Climate Normals 1991-2020 (annual/seasonal)",
                              "url": URLS["noaa_normals"], "data_year": "1991-2020", "real": True})

    print("National parks…")
    parks = build_parks(args.offline)
    save(parks, "parks", {"source": "List of U.S. national parks (Wikipedia, citing NPS)", "url": URLS["nps_list"], "data_year": "2025", "real": True})
    save(build_outdoors(metros, parks), "outdoors", {"source": "Derived: national parks within 150/300 mi of principal city",
                                                     "url": URLS["nps_list"], "data_year": "2025", "real": True})

    print("BLS Consumer Expenditure Survey…")
    ce = build_ce(args.offline)
    print("IRS federal + FICA…")
    fed = build_federal(args.offline)
    print("Tax Foundation state taxes…")
    states = build_states(args.offline)
    print("Local income taxes…")
    local = build_local(args.offline)
    tax_tables = {"federal": fed, "state": states, "local": local,
                  "health_premium_default": {"monthly": 120.0, "annual": 1440.0,
                                             "source": "KFF 2025 Employer Health Benefits Survey: average worker contribution, single coverage",
                                             "url": "https://www.kff.org/health-costs/report/2025-employer-health-benefits-survey/", "data_year": "2025"}}
    (PROCESSED_DIR / "tax_tables.json").write_text(json.dumps(tax_tables, indent=1))
    (PROCESSED_DIR / "consumer_expenditure.json").write_text(json.dumps(ce, indent=1))
    manifest["tables"]["tax_tables"] = {"source": "IRS Rev. Proc. 2025-32; IRS Pub 15 (2026); Tax Foundation 2026; curated local taxes",
                                        "data_year": "TY2026", "real": True}
    manifest["tables"]["consumer_expenditure"] = {"source": "BLS Consumer Expenditure Survey via BLS Public API v1",
                                                  "url": URLS["bls_api"], "data_year": str(ce["year"]), "real": True}
    print("  ✓ tax_tables.json, consumer_expenditure.json")

    print("BLS OEWS wages…")
    try:
        oews, oyear = build_oews(metros)
        save(oews, "oews", {"source": "BLS Occupational Employment and Wage Statistics (metro + national)",
                            "url": URLS["oews_tables"], "data_year": f"May {oyear}", "real": True})
    except ManualDownloadRequired as e:
        manifest["tables"]["oews"] = {"status": "MISSING - manual download required"}
        (PROCESSED_DIR / "manifest.json").write_text(json.dumps(manifest, indent=1))
        print(e)
        sys.exit(2)

    (PROCESSED_DIR / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print("Done.")


if __name__ == "__main__":
    main()
