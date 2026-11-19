"""Orchestrator: runs the six agents in three stages over a shared ``PipelineState``.

Stage 1 (parallel, one per offer):  Offer Parser
Stage 2 (parallel):                 Tax · Cost of Living · Market · Lifestyle
Stage 3:                            Decision Strategist

Every agent has a timeout. A failed or timed-out agent marks the run ``degraded`` and the pipeline
continues with whatever is available. Progress events carry status and timing only — never offer data.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional

from backend.agents import (
    cost_of_living_agent,
    decision_agent,
    lifestyle_agent,
    market_agent,
    offer_parser,
    tax_agent,
)
from backend.core import finance
from backend.core.config import get_settings
from backend.core.logging import log_event
from backend.core.models import (
    AgentStatus,
    COLOfferInput,
    CostOfLivingInput,
    DecisionInput,
    LifestyleInput,
    LifestyleOfferInput,
    MarketInput,
    MarketOfferInput,
    OfferParserInput,
    PipelineState,
    ProgressEvent,
    TaxInput,
    TaxOfferInput,
    UserProfile,
)

Emit = Callable[[ProgressEvent], None]

SUMMARIES = {
    "offer_parser": "Reading offer letters",
    "tax": "Calculating taxes & take-home",
    "cost_of_living": "Pricing rent & living costs",
    "market": "Benchmarking pay & culture",
    "lifestyle": "Scoring lifestyle fit",
    "decision": "Building your recommendation",
}


async def _timed(state: PipelineState, emit: Emit, agent: str, coro: Awaitable[Any], offer_id: Optional[str] = None,
                 summarize: Callable[[Any], str] = lambda _o: "done") -> Optional[Any]:
    """Run one agent with a timeout, recording status and emitting start/finish events."""
    key = f"{agent}:{offer_id}" if offer_id else agent
    st = AgentStatus(agent=agent, state="running", started_at=time.time(), summary=SUMMARIES.get(agent, ""))  # type: ignore[arg-type]
    state.status[key] = st
    emit(ProgressEvent(type="agent_started", run_id=state.run_id, agent=agent, offer_id=offer_id,  # type: ignore[arg-type]
                       summary=SUMMARIES.get(agent, "")))
    log_event(state.run_id, key, "started")
    t0 = time.perf_counter()
    try:
        out = await asyncio.wait_for(coro, timeout=get_settings().agent_timeout_seconds)
    except asyncio.TimeoutError:
        out, err = None, "timed out"
    except Exception as e:  # noqa: BLE001 — any agent failure degrades, never crashes the run
        out, err = None, type(e).__name__
    else:
        err = None
    ms = int((time.perf_counter() - t0) * 1000)
    st.elapsed_ms = ms
    if err:
        st.state, st.error = "failed", err
        state.degraded = True
        if agent not in state.degraded_agents:
            state.degraded_agents.append(agent)
        emit(ProgressEvent(type="agent_failed", run_id=state.run_id, agent=agent, offer_id=offer_id,  # type: ignore[arg-type]
                           elapsed_ms=ms, summary=f"{SUMMARIES.get(agent, agent)} — {err}"))
        log_event(state.run_id, key, "timeout" if err == "timed out" else "failed", ms, code=err)
        return None
    st.state, st.summary = "done", summarize(out)
    emit(ProgressEvent(type="agent_finished", run_id=state.run_id, agent=agent, offer_id=offer_id,  # type: ignore[arg-type]
                       elapsed_ms=ms, summary=st.summary,
                       data={"engine": getattr(out, "engine", None), "confidence": getattr(out, "confidence", None)}))
    log_event(state.run_id, key, "finished", ms)
    return out


async def run_pipeline(run_id: str, profile: UserProfile, inputs: list[OfferParserInput],
                       pasted_reviews: dict[str, str], emit: Emit) -> PipelineState:
    """Execute all three stages and return the populated state."""
    t_start = time.perf_counter()
    state = PipelineState(run_id=run_id, profile=profile, offer_ids=[i.offer_id for i in inputs],
                          llm_mode="claude" if get_settings().claude_enabled else "local")
    emit(ProgressEvent(type="pipeline_started", run_id=run_id, summary=f"Comparing {len(inputs)} offers",
                       data={"offers": state.offer_ids, "llm_mode": state.llm_mode}))

    # ---- Stage 1: parse every offer in parallel
    for i in inputs:
        i.remote_city_hint = i.remote_city_hint or profile.remote_city
    parsed = await asyncio.gather(*[
        _timed(state, emit, "offer_parser", offer_parser.run(i), offer_id=i.offer_id,
               summarize=lambda o: f"Found {o.fields_found}/{o.fields_total} key fields"
               + (f" · {o.location.metro_name}" if o.location.matched else ""))
        for i in inputs])
    for i, p in zip(inputs, parsed):
        i.content = None  # privacy: drop file bytes / text once parsed
        i.text = None
        if p is not None:
            state.parsed[p.offer_id] = p
    if not state.parsed:
        state.errors.append("None of the offers could be read.")
        state.total_elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        return state

    # ---- Stage 2: four independent agents in parallel
    offers = list(state.parsed.values())
    tax_in = TaxInput(offers=[
        TaxOfferInput(offer_id=p.offer_id, gross_salary=finance.annual_salary(p.fields),
                      state=p.location.state or (p.fields.office_state.value if p.fields.office_state.known else None),
                      city=p.location.city, contribution_401k_pct=profile.contribution_401k_pct,
                      health_premium_monthly=finance.health_premium_monthly(p.fields, profile)[0])
        for p in offers])
    col_in = CostOfLivingInput(offers=[COLOfferInput(offer_id=p.offer_id, cbsa=p.location.cbsa,
                                                     metro_name=p.location.metro_name) for p in offers],
                               housing=profile.housing, roommates=profile.roommates,
                               rent_adjust_pct=profile.rent_adjust_pct)
    mk_in = MarketInput(offers=[MarketOfferInput(
        offer_id=p.offer_id, company=p.fields.company.value if p.fields.company.known else None,
        job_title=p.fields.job_title.value if p.fields.job_title.known else None, cbsa=p.location.cbsa,
        metro_name=p.location.metro_name, base_salary=finance.annual_salary(p.fields),
        pasted_reviews=pasted_reviews.get(p.offer_id)) for p in offers])
    ls_in = LifestyleInput(offers=[LifestyleOfferInput(offer_id=p.offer_id, cbsa=p.location.cbsa,
                                                       metro_name=p.location.metro_name) for p in offers],
                           priorities=profile.priorities, home_city=profile.home_city)
    state.tax, state.col, state.market, state.lifestyle = await asyncio.gather(
        _timed(state, emit, "tax", tax_agent.run(tax_in),
               summarize=lambda o: "Take-home: " + ", ".join(f"{r.offer_id} ${r.take_home_monthly:,.0f}/mo"
                                                            for r in o.results if r.computed)),
        _timed(state, emit, "cost_of_living", cost_of_living_agent.run(col_in),
               summarize=lambda o: "Budgets: " + ", ".join(f"{b.offer_id} ${b.total_monthly:,.0f}/mo"
                                                           for b in o.budgets if b.computed)),
        _timed(state, emit, "market", market_agent.run(mk_in),
               summarize=lambda o: "Pay percentile: " + ", ".join(
                   f"{r.offer_id} ~{r.salary_percentile:.0f}th" for r in o.results if r.salary_percentile is not None)),
        _timed(state, emit, "lifestyle", lifestyle_agent.run(ls_in),
               summarize=lambda o: "Fit: " + ", ".join(f"{r.offer_id} {r.fit_score:.0f}/100" for r in o.results
                                                       if r.fit_score is not None)),
    )

    # ---- Stage 3: decision
    d_in = DecisionInput(profile=profile, parsed=offers, tax=state.tax, col=state.col, market=state.market,
                         lifestyle=state.lifestyle, degraded_agents=list(state.degraded_agents))
    state.recalc_context = decision_agent.build_context(d_in)
    state.decision = await _timed(state, emit, "decision", decision_agent.run(d_in),
                                  summarize=lambda o: ("Tie" if o.is_tie else f"Offer {o.winner} ranks first")
                                  if o.winner else "Not enough data")
    state.total_elapsed_ms = int((time.perf_counter() - t_start) * 1000)
    return state
