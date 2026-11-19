# TrueOffer: project context

BNAN 420 final project. TrueOffer is a web-based multi-agent product that helps college seniors and new grads compare 2–3 job offers in different cities. It shows what each offer is **really** worth after taxes, rent, cost of living, benefits and lifestyle. The core message: **the bigger salary isn't always the better offer.**

## Operating mode: works with NO external API

- The product must run end to end **with no API keys and no network calls at request time**.
- Decision (2026-11-19): the user does NOT want to use a Claude API key. Ship and demo in local mode (`LLM_MODE=off` in `.env.example`, `render.yaml`). The optional Claude path in `core/llm.py` stays but is never required.
- `LLM_MODE=auto` (default): if `ANTHROPIC_API_KEY` is set, agents use Claude for language tasks (extraction, explanations, the email). Otherwise each agent uses its **local engine**:
  - a rules/regex extractor
  - offline OCR (RapidOCR/ONNX)
  - data-driven text generation from computed facts
- `LLM_MODE=off` forces local mode, and every LLM call has a local fallback.
- Every agent reports which engine it used (`engine: "claude" | "local"`).
- Public data is downloaded **once at build time** by `backend/data/download_data.py`. The processed files are committed under `backend/data/processed/` because they are small. Runtime never fetches data.

## Architecture

```
Browser (React/Vite/TS/Tailwind) ──POST /api/compare──► FastAPI ──► Orchestrator
     ▲                                                     │
     └──────────── SSE /api/compare/{id}/events ◄──────────┤ progress events + final result
                                                           ▼
 Stage 1 (parallel, one per offer):  [1] Offer Parser
 Stage 2 (parallel, asyncio.gather): [2] Tax & Take-Home  [3] Cost of Living & Housing
                                     [4] Market & Company [5] Lifestyle Fit
 Stage 3:                            [6] Decision Strategist  (computes money-left-over, scorecard, sensitivity, email)
```

- The shared typed `PipelineState` (`backend/core/models.py`) is passed between stages.
- Per-agent timeouts apply. If an agent fails, the pipeline continues with degraded output, sets `state.degraded=True` and flags it in the report.
- Agents 2–5 are truly independent, so they run in parallel. Agent 3 outputs the city **budget**. The Strategist combines take-home (Agent 2) and budget (Agent 3) using `core/finance.py`, which is the same code `/api/recalculate` uses.

### Agents (one file each in `backend/agents/`)

| # | File | Role | Deterministic core | Language task (Claude or local) |
|---|------|------|--------------------|---------------------------------|
| 1 | `offer_parser.py` | Extract structured offer fields; "not stated in offer" instead of guessing | PDF text, OCR, metro resolution | field extraction |
| 2 | `tax_agent.py` | Federal + FICA + state + local tax, take-home | `data/lookups.tax_for` | plain-English explanation |
| 3 | `cost_of_living_agent.py` | Rent (Zillow ZORI × Census ACS bedroom mix) + living costs (BLS CE × BEA RPP) budget | pandas lookups | budget explanation |
| 4 | `market_agent.py` | BLS OEWS percentile benchmark, culture signals (simulated reviews), leverage | percentile interpolation | SOC choice, culture summary |
| 5 | `lifestyle_agent.py` | City fit vs. user priorities (NOAA, ACS, BEA, distance) | scoring formulas | fit narrative |
| 6 | `decision_agent.py` | Weighted scorecard, ranking/tie, sensitivity, negotiation email, recruiter questions | `core/scoring.py` | recommendation + email |

Every agent:
- exposes `async def run(inp: XInput) -> XOutput`
- has pydantic I/O models in `core/models.py`
- has its own system prompt in `backend/prompts/<agent>.md`
- returns `confidence` (0–1), `log` (what I did), `warnings`, `engine`, `elapsed_ms`

## Conventions

- Python 3.11+, full type hints, docstrings on every public function, pydantic v2.
- Shared models live **only** in `backend/core/models.py`. Prompts live **only** in `backend/prompts/`.
- **Never hardcoded or fake outputs.** Every number is computed from user input plus real data. Simulated data (reviews, sample offers) is clearly labeled `SIMULATED`.
- **All money math is deterministic Python, never LLM arithmetic.** LLMs only extract fields or explain numbers they are given. Generated text is checked so it introduces no new dollar figures (`core/guards.py`).
- **Every number shows its source and assumption** (`source`, `data_year` and `formula` fields on budget lines, tax lines and lifestyle inputs).
- All outputs are ESTIMATES for comparison, not tax, legal or financial advice. Taxes assume a single filer, the standard deduction, no other income and residence in the office city.
- Frontend: brand tokens in `frontend/tailwind.config.ts` / `src/index.css`. The only hues allowed are the brand palette plus the cool-gray neutrals (no green/yellow/orange/purple). Offer series colors: A=Arizona Blue #0C234B, B=Arizona Red #AB0520, C=Arroyo Blue #106AB1. Status is always icon + label + color.

## Privacy rules (enforced in code)

- Uploaded offer files and text are processed **in memory only**. They are never written to disk, never logged and never stored. File bytes are `exclude=True` in models.
- Logs (`core/logging.py`) record only run id, agent, status and timing, never offer contents or salaries. Use `log_event()`; do not `print()` user data.
- The run store is in-memory with a 30-minute TTL. `/api/recalculate` is stateless: the browser sends back the structured context.

## Commands

```bash
# backend (from repo root)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m backend.data.download_data      # rebuild processed data (needs network, one time)
.venv/bin/uvicorn backend.main:app --reload --port 8000
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m backend.tests.run_pipeline_eval  # full pipeline on all 6 samples

# frontend
cd frontend && npm install && npm run dev            # Vite on :5173, proxies /api to :8000
npm run build                                         # output served by FastAPI from frontend/dist
```

- Local Node lives at `~/.local/node/bin` (portable install). Add it to PATH before running npm.
- Git: the user manages GitHub themselves. Do not add remotes, push, or use `gh`.

## Data (see backend/data/SOURCES.md)

- REAL:
  - IRS Rev. Proc. 2025-32 (TY2026 brackets and standard deduction)
  - IRS Pub 15 (Social Security wage base)
  - Tax Foundation 2026 state brackets
  - curated local income taxes with official source URLs
  - BEA RPP (metro)
  - Zillow ZORI
  - BLS OEWS May 2025 (metro)
  - BLS Consumer Expenditure Survey
  - Census ACS 2024 1-year
  - Census Gazetteer
  - NOAA 1991–2020 Normals
- SIMULATED: `data/simulated/reviews.json` (fictional companies) and `data/samples/*` (fictional offer letters plus ground truth).

## Phase status

Track progress here. Update this section at the end of each phase.

- [x] Phase 0 scaffold & models
- [x] Phase 1 data layer — all sources built, incl. BLS OEWS May 2025 metro (oews.parquet, 33,304 rows, all 52 metros; national file oesm25nat.zip not added, so benchmarks are metro-only). Rent uses ACS B25031 × ZORI (HUD FMR dropped: huduser.gov blocks automated clients). Samples + simulated reviews built.
- [x] Phase 2 agents — all 6 agents + core/finance.py, core/scoring.py, core/guards.py, core/llm.py, services/rules_extractor.py, services/text_extract.py, prompts/*.md. Rules extractor: 195/195 sample fields correct; take-home matches the independent worksheet to the cent on all 13 offers.
- [x] Phase 3 orchestrator & API — services/orchestrator.py (3 stages, timeouts, degraded mode), services/run_store.py (in-memory, 30-min TTL), api/routes.py (compare, SSE events, result, recalculate, samples, metros, sources, health), main.py (serves frontend/dist, security headers).
- [x] Phase 4 frontend — React/Vite/TS/Tailwind: input (upload/paste/form, profile, priorities, 6 samples), live agent progress, results (headline, paycheck chart, offer cards, scorecard, what-if sliders via /api/recalculate, sensitivity, per-offer detail tabs with sources, negotiation email, recruiter questions, under-the-hood, sources). Deep link `/?sample=<id>`.
- [x] Phase 5 QA — `pytest backend/tests` = 54 passing (finance, extractor incl. unseen letters, scoring/guards, API, privacy of logs/responses, degraded mode); `run_pipeline_eval` = 195/195 fields, 0 take-home mismatches. UI checked by headless Chrome screenshots at desktop and 500 px.
- [x] Phase 6 deployment — Dockerfile (multi-stage, OCR models preloaded at build), render.yaml (free tier, LLM_MODE=off), run.sh + "Start TrueOffer.command" one-click local launch. Docker image NOT build-tested locally (Docker not installed on this Mac).
- [x] Phase 7 docs — README.md, docs/ARCHITECTURE.md, docs/DEMO_GUIDE.md, docs/screenshots/.
- [x] Post-launch fix (2026-11-19): a user's PDF letter lost job title + city. Rewrote parse_title/parse_location (labels, many sentence forms, role-noun validation, signature guard, city w/o state for supported metros), added PDFium spacing fallback, and an "Add or correct details" override in the UI (form sent with file/text sources). Tests: 102 passing (backend/tests/test_phrasings.py = 22 phrasings × text/PDF).
- [ ] Remaining (user): create GitHub repo + push; optionally deploy on Render from GitHub; course write-up / slides / demo video.
