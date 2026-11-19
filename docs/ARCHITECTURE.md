# TrueOffer architecture

## Design principles

1. **No external API needed.** Every language task has a local engine: a rules extractor, offline OCR
   (RapidOCR/ONNX models bundled with the package) and template text built from computed facts. Claude is an
   optional upgrade (`core/llm.py`) that returns `None` whenever it's disabled, fails or declines. Every caller
   treats `None` as "use local."
2. **All money math is deterministic Python.** `core/finance.py` and `core/scoring.py` produce every number. Any
   generated sentence goes through `core/guards.py`, which rejects text containing a dollar figure the engine
   didn't produce (rounded forms such as "$85K" are allowed).
3. **Every number carries its source.** Tax lines, budget lines and lifestyle dimensions each include `formula`,
   `source` and `data_year`, and the UI shows them all.
4. **Data is built once, never fetched at runtime.** `backend/data/download_data.py` builds the small files in
   `backend/data/processed/`, which are committed. `data/lookups.py` is the only reader.
5. **Privacy.** Upload bytes and letter text are `exclude=True` in the models. They're dropped as soon as parsing
   finishes, never written to disk and never logged. `core/logging.py` accepts only a run id, agent name, status,
   timing and a short machine code.

## Request flow

```
POST /api/compare (multipart: payload JSON + file_A/B/C)
  └─ api/routes.py validates (2–3 offers, ≤10 MB each, rate limit, concurrency cap)
       └─ creates RunRecord in services/run_store.py (in-memory, 30-min TTL)
       └─ asyncio task: services/orchestrator.run_pipeline(...)
              Stage 1  asyncio.gather(offer_parser.run × N)
              Stage 2  asyncio.gather(tax, cost_of_living, market, lifestyle)
              Stage 3  decision_agent.run
            each call wrapped by _timed(): timeout, status, ProgressEvent, log_event
GET /api/compare/{id}/events   SSE: replays + streams ProgressEvents, then `event: result`
GET /api/compare/{id}/result   polling fallback (202 while running)
POST /api/recalculate          stateless: RecalcContext from the browser + overrides → RecalcResponse
```

`PipelineState` (`core/models.py`) is the typed object passed between stages. If an agent fails or times out,
the orchestrator records `degraded=True` and the agent's name. Later stages then work with whatever is
available. For example, if the market agent fails, the scorecard drops that component and the UI flags the
partial result.

## Agents

Each agent lives in `backend/agents/<name>.py` and exposes `async def run(inp) -> Output`. Its pydantic I/O
models are in `core/models.py`, and its prompt is in `backend/prompts/<name>.md`. Every output includes
`engine`, `confidence`, `log`, `warnings` and `elapsed_ms`.

### 1. Offer Parser
- `services/text_extract.py` identifies the file type from its magic bytes, then reads it: PDF text (pdfplumber),
  OCR for scanned PDFs and images (pypdfium2 + RapidOCR), DOCX (python-docx) or plain text.
- `services/rules_extractor.py` splits the text into sentence, bullet and "Label: value" segments. Each dollar
  amount is classified by the nearest compensation keyword in its own segment (base, signing, relocation, HSA,
  equity, bonus; reimbursements are ignored). Dedicated patterns handle 401(k) formulas (tiered, dollar-for-dollar,
  safe harbor), bonus %, PTO (including unlimited), start date and work arrangement. Company, title and location
  come from phrase patterns plus the letterhead and signature.
- Fields that aren't found stay `not_stated` and display as "not stated in offer." Hourly and monthly pay are
  annualized with `status="derived"` and the formula shown.
- The office city resolves to a supported metro through an alias table, then the metro's title cities, then the
  nearest metro within 60 miles via Census Gazetteer coordinates. Fully remote offers use the profile's
  "where you'd live" city.

### 2. Tax & Take-Home
`data/lookups.tax_for` covers 2026 federal brackets and the standard deduction, Social Security (6.2% up to
$184,500), Medicare (+0.9% over $200k), Tax Foundation state brackets with per-state footnote rules, and curated
city taxes (NYC, Pittsburgh, Denver OPT, etc.). The 401(k) contribution (capped at the IRS limit) and Section 125
health premiums are deducted before tax in the correct order.

### 3. Cost of Living & Housing
- Rent = Zillow ZORI (latest month) × ACS median rent for the bedroom count ÷ ACS all-units median. Living alone
  means a 1-bedroom; with *n* roommates it's an (*n*+1)-bedroom split *n*+1 ways.
- Living costs = BLS Consumer Expenditure Survey spending for a one-person household × BEA Regional Price Parity
  for the matching category ÷ 100. Utilities use the CE figure for the actual household size, split per person.

### 4. Market & Company
- Job title → SOC code via ordered keyword rules. Each rule has a confidence, and its codes were checked against
  the OEWS file.
- Salary percentile is interpolated linearly between the OEWS 10/25/50/75/90 points and clamped to 1–99.
- Culture comes from SIMULATED reviews (fictional companies, `data/simulated/reviews.json`) or from reviews the user
  pastes, scored with a keyword lexicon by theme.

### 5. Lifestyle Fit
Each dimension is the metro's percentile rank among the 52 supported metros: national parks within 300 miles and
distance to the nearest one; share of residents aged 22–34 and population; days with a high between 50°F and
90°F; mean commute; services price parity. Distance to family scores 100 within 50 miles and falls to 0 at 2,000
miles. The overall fit is the average weighted by the user's 0–5 priorities.

### 6. Decision Strategist
`core/scoring.py`:
- **money_left_over:** 100 for the best offer, −10 points per $100/month behind it.
- **total_comp:** 100 × 3-year comp ÷ the best offer's (proportional, so salary isn't counted twice).
- **lifestyle**, **market_position** and **culture:** already on a 0–100 scale.
- The total is weighted by the user's weights, normalized. A top-two gap under 2 points is reported as a tie.
- **Sensitivity** re-runs the same `recalculate()` with: housing flipped, rents ±5–50%, bonus 0%/150%, 401(k)
  0%/15%, loans, and weights (money-only or lifestyle-heavy).
- The negotiation email and recruiter questions use only computed evidence and the fields the letter didn't state.

`/api/recalculate` calls the same `scoring.recalculate()`, so the what-if sliders always agree with the report.

## Frontend

React 18 + Vite + TypeScript + Tailwind + Recharts. The views are `InputView`, `ProgressView` (live SSE agent
states) and `ResultsView` (+ `Details`, `Extras`). The brand palette is defined only in `tailwind.config.ts` and
`index.css`: Arizona Blue / Arizona Red / Arroyo Blue for offers A/B/C, plus cool grays. Status always uses an
icon, a label and a color. The UI works down to phone widths and prints cleanly (Save as PDF).
`/?sample=<id>` deep-links straight to a sample comparison for demos.

## Security

- Upload limits: 10 MB per file, 10 PDF pages, file type checked from its bytes.
- Per-IP rate limit, a cap on concurrent runs, and an agent timeout.
- Strict CSP: the app loads nothing from third-party origins. `X-Frame-Options: DENY`, `nosniff`, `no-referrer`.
- The sample-file endpoint serves only files listed in `samples.json`, so path traversal is blocked.
- Text in the letter is treated as data. The optional Claude prompt says to ignore any instructions inside the
  letter, and Claude-extracted values are accepted only if their quote appears verbatim in the letter.
