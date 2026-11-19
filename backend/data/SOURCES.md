# Data sources

All REAL data is downloaded and processed by `python -m backend.data.download_data`. The processed tables in `processed/` are small (< 3 MB total), so they are committed. The deployed app never calls the network at request time. Provenance is recorded in `processed/manifest.json`.

## REAL (public, official)

| Dataset | Used for | Data year | Source |
|---|---|---|---|
| IRS Rev. Proc. 2025-32 (Table 3, Sec. 4.15) | Federal single brackets; $16,100 standard deduction | TY2026 | https://www.irs.gov/pub/irs-drop/rp-25-32.pdf |
| IRS Publication 15 (2026) | Social Security 6.2% to $184,500; Medicare 1.45% (+0.9% over $200k) | 2026 | https://www.irs.gov/pub/irs-pdf/p15.pdf |
| IRS Notice 2025-67 | 401(k) elective deferral limit $24,500 | 2026 | https://www.irs.gov/pub/irs-drop/n-25-67.pdf |
| Tax Foundation, State Individual Income Tax Rates and Brackets 2026 | State brackets, standard deduction, exemptions/credits (single) | TY2026 | https://taxfoundation.org/data/all/state/state-income-tax-rates-2026/ |
| Local income taxes (curated, 18 cities) | NYC, Philadelphia, Pittsburgh, Columbus, Cleveland, Cincinnati, Detroit, Grand Rapids, Louisville, Kansas City, St. Louis, Indianapolis, Baltimore, Birmingham, Portland, Denver, Aurora, Wilmington | 2026 | Official URL and verification note on each row in `download_data.py::LOCAL_TAXES` |
| BEA Regional Price Parities by MSA | Price levels: all items, goods, housing, utilities, other services | 2024 | https://apps.bea.gov/regional/zip/MARPP.zip |
| Zillow Observed Rent Index (ZORI), metro, smoothed | Current market rent level and year-over-year change | Oct 2026 | https://www.zillow.com/research/data/ |
| Census ACS 2024 1-year, B25031 / B25064 | Median gross rent by bedroom count (bedroom mix) | 2024 | https://www2.census.gov/programs-surveys/acs/summary_file/2024/ |
| Census ACS 2024 1-year, B01001 / B08013 / B08303 | Share of residents aged 22–34; mean commute time | 2024 | same |
| Census Vintage 2024 CBSA population estimates | Picking the 52 largest metros | 2024 | https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/metro/totals/ |
| Census 2024 Gazetteer (CBSA, places) | City geocoding and distances | 2024 | https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/ |
| NOAA NCEI U.S. Climate Normals 1991–2020 | Average temperature, days over 90°F, freezing days, dry days, snow | 1991–2020 | https://www.ncei.noaa.gov/data/normals-annualseasonal/1991-2020/ |
| BLS Consumer Expenditure Survey (Public API v1) | Groceries, transportation, dining/entertainment, apparel/personal care, utilities by household size | 2025 | https://api.bls.gov/publicAPI/v1/ |
| BLS OEWS, metropolitan and national | Wage percentiles by occupation (SOC) and metro | May 2025 | https://www.bls.gov/oes/tables.htm (**manual download**) |
| KFF Employer Health Benefits Survey 2025 | Default employee health premium, $1,440/yr | 2025 | https://www.kff.org/health-costs/report/2025-employer-health-benefits-survey/ |
| List of U.S. national parks (Wikipedia, citing NPS) | Outdoors access: parks within 150/300 miles | 2025 | https://en.wikipedia.org/wiki/List_of_national_parks_of_the_United_States |

## SIMULATED (clearly labeled)

| Dataset | What it is |
|---|---|
| `simulated/reviews.json` | 1,026 machine-generated employee reviews for 32 **fictional** companies (seed 420). Used because review sites such as Glassdoor forbid scraping. |
| `samples/` | 6 sample comparisons (13 fictional offer letters in .txt, .pdf and photo .png) and `ground_truth.json`. |

## Method notes

- **Rent** = ZORI (latest month) × ACS median gross rent for N bedrooms ÷ ACS median gross rent for all units.
  - ZORI sets today's market level and ACS supplies the bedroom mix.
  - With roommates, a (roommates + 1)-bedroom unit is split evenly.
- **Living costs** = national one-person spending from the BLS Consumer Expenditure Survey × the metro's BEA price parity for that category ÷ 100.
- **Outdoors**: the Gateway Arch National Park, a 91-acre urban memorial, is excluded.
- **San Francisco location**: the Census internal point for San Francisco lies offshore because the city includes the Farallon Islands. NOAA's downtown SF station coordinates are used instead.
