"""HTTP API.

POST /api/compare                  start a run (multipart: ``payload`` JSON + optional ``file_A``/``file_B``/``file_C``)
GET  /api/compare/{id}/events      Server-Sent Events: agent progress, then the final result
GET  /api/compare/{id}/result      final result JSON (polling fallback)
POST /api/recalculate              stateless what-if recompute (no LLM)
GET  /api/samples                  SIMULATED sample offer sets
GET  /api/samples/file/{name}      download a sample offer letter
GET  /api/metros                   supported metros
GET  /api/sources                  data provenance
GET  /api/health                   liveness + engine mode
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from backend.core import scoring
from backend.core.config import SAMPLES_DIR, get_settings
from backend.core.logging import log_event
from backend.core.models import (
    ManualOfferForm,
    OfferParserInput,
    ProgressEvent,
    RecalcRequest,
    RecalcResponse,
    UserProfile,
)
from backend.data import lookups as L
from backend.services.orchestrator import run_pipeline
from backend.services.run_store import STORE, RunRecord

router = APIRouter(prefix="/api")
_hits: dict[str, deque[float]] = defaultdict(deque)
_run_sem: Optional[asyncio.Semaphore] = None


class OfferSpec(BaseModel):
    """One offer in the compare payload (file bytes arrive as a separate multipart part)."""

    offer_id: str = Field(pattern="^[ABC]$")
    label: str = Field("", max_length=40)
    source: str = Field(pattern="^(file|text|form)$")
    text: Optional[str] = Field(None, max_length=60_000)
    form: Optional[ManualOfferForm] = None
    pasted_reviews: Optional[str] = Field(None, max_length=20_000)


class ComparePayload(BaseModel):
    profile: UserProfile = Field(default_factory=UserProfile)
    offers: list[OfferSpec] = Field(default_factory=list)
    sample_id: Optional[str] = Field(None, max_length=60)


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limit(request: Request) -> None:
    """Sliding one-minute window per client IP."""
    key = _client(request)
    now = time.time()
    q = _hits[key]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= get_settings().rate_limit_per_minute:
        log_event("-", "api", "rejected", code="rate_limited")
        raise HTTPException(429, "Too many comparisons in the last minute. Please wait a moment and try again.")
    q.append(now)


def _samples() -> list[dict[str, Any]]:
    return json.loads((SAMPLES_DIR / "samples.json").read_text())["samples"]


def _sample_inputs(sample_id: str) -> tuple[list[OfferParserInput], dict[str, Any]]:
    s = next((x for x in _samples() if x["id"] == sample_id), None)
    if s is None:
        raise HTTPException(404, "Unknown sample.")
    media = {"pdf": "application/pdf", "png": "image/png", "txt": "text/plain"}
    inputs = []
    for o in s["offers"]:
        p = SAMPLES_DIR / "offers" / o["file"]
        inputs.append(OfferParserInput(offer_id=o["offer_id"], label=o["label"], source="file", file_name=p.name,
                                       media_type=media.get(o["format"]), content=p.read_bytes()))
    return inputs, s["profile"]


async def _execute(rec: RunRecord, profile: UserProfile, inputs: list[OfferParserInput], reviews: dict[str, str]) -> None:
    global _run_sem
    if _run_sem is None:
        _run_sem = asyncio.Semaphore(get_settings().max_concurrent_runs)
    async with _run_sem:
        try:
            state = await run_pipeline(rec.run_id, profile, inputs, reviews, rec.push)
            result = state.model_dump(mode="json")
            rec.push(ProgressEvent(type="pipeline_finished", run_id=rec.run_id, elapsed_ms=state.total_elapsed_ms,
                                   summary="Degraded result" if state.degraded else "All agents finished"))
            rec.finish(result)
        except Exception as e:  # noqa: BLE001
            log_event(rec.run_id, "orchestrator", "failed", code=type(e).__name__)
            rec.push(ProgressEvent(type="error", run_id=rec.run_id, summary="Something went wrong comparing these offers."))
            rec.finish(None, "Something went wrong comparing these offers.")
        finally:
            for i in inputs:
                i.content = None
                i.text = None


@router.post("/compare")
async def compare(request: Request) -> JSONResponse:
    """Start a comparison run; returns ``{run_id}``. Progress streams from ``/events``."""
    _rate_limit(request)
    s = get_settings()
    if STORE.active_count() >= s.max_concurrent_runs * 3:
        raise HTTPException(503, "TrueOffer is busy right now. Please try again in a minute.")
    form = await request.form()
    try:
        payload = ComparePayload.model_validate_json(str(form.get("payload") or "{}"))
    except ValidationError as e:
        raise HTTPException(422, "Invalid request: " + "; ".join(x["msg"] for x in e.errors()[:3])) from None

    reviews: dict[str, str] = {}
    if payload.sample_id:
        inputs, sample_profile = _sample_inputs(payload.sample_id)
        profile = payload.profile if "profile" in payload.model_fields_set else UserProfile(**sample_profile)
    else:
        profile = payload.profile
        ids = [o.offer_id for o in payload.offers]
        if not 2 <= len(ids) <= 3 or len(set(ids)) != len(ids):
            raise HTTPException(422, "Add 2 or 3 offers (A, B and optionally C).")
        inputs = []
        max_bytes = s.max_upload_mb * 1024 * 1024
        for o in payload.offers:
            content = None
            fname = mtype = None
            if o.source == "file":
                up = form.get(f"file_{o.offer_id}")
                if up is None or not hasattr(up, "read"):
                    raise HTTPException(422, f"Offer {o.offer_id}: choose a file to upload.")
                content = await up.read(max_bytes + 1)  # type: ignore[union-attr]
                if len(content) > max_bytes:
                    raise HTTPException(413, f"Offer {o.offer_id}: file is larger than {s.max_upload_mb} MB.")
                if not content:
                    raise HTTPException(422, f"Offer {o.offer_id}: the file is empty.")
                fname, mtype = getattr(up, "filename", None), getattr(up, "content_type", None)
            elif o.source == "text" and not (o.text and o.text.strip()):
                raise HTTPException(422, f"Offer {o.offer_id}: paste the offer text.")
            elif o.source == "form" and o.form is None:
                raise HTTPException(422, f"Offer {o.offer_id}: fill in the form.")
            inputs.append(OfferParserInput(offer_id=o.offer_id, label=o.label or f"Offer {o.offer_id}",  # type: ignore[arg-type]
                                           source=o.source, file_name=(fname or "")[:200] or None, media_type=mtype,  # type: ignore[arg-type]
                                           content=content, text=o.text, form=o.form))
            if o.pasted_reviews:
                reviews[o.offer_id] = o.pasted_reviews
    rec = STORE.create()
    log_event(rec.run_id, "api", "started")
    asyncio.create_task(_execute(rec, profile, inputs, reviews))
    return JSONResponse({"run_id": rec.run_id})


@router.get("/compare/{run_id}/events")
async def events(run_id: str, request: Request) -> StreamingResponse:
    """SSE stream: replays past events, then streams new ones, ending with the result."""
    rec = STORE.get(run_id)
    if rec is None:
        raise HTTPException(404, "This comparison has expired. Please run it again.")

    async def gen():
        i = 0
        while True:
            while i < len(rec.events):
                yield f"event: progress\ndata: {rec.events[i].model_dump_json()}\n\n"
                i += 1
            if rec.done:
                if rec.result is not None:
                    yield f"event: result\ndata: {json.dumps(rec.result)}\n\n"
                else:
                    yield f"event: failed\ndata: {json.dumps({'error': rec.error})}\n\n"
                return
            if await request.is_disconnected():
                return
            waiter = rec.changed
            try:
                await asyncio.wait_for(waiter.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/compare/{run_id}/result")
async def result(run_id: str) -> JSONResponse:
    """Final result (202 while running)."""
    rec = STORE.get(run_id)
    if rec is None:
        raise HTTPException(404, "This comparison has expired. Please run it again.")
    if not rec.done:
        return JSONResponse({"status": "running", "events": [e.model_dump(mode="json") for e in rec.events]}, status_code=202)
    if rec.result is None:
        raise HTTPException(500, rec.error or "Run failed.")
    return JSONResponse(rec.result)


@router.post("/recalculate", response_model=RecalcResponse)
async def recalculate(req: RecalcRequest, request: Request) -> RecalcResponse:
    """Re-run the deterministic money math and scorecard with changed assumptions."""
    if len(req.context.offers) > 3:
        raise HTTPException(422, "At most 3 offers.")
    try:
        return scoring.recalculate(req.context, req.overrides)
    except ValidationError as e:
        raise HTTPException(422, "Invalid what-if value: " + "; ".join(x["msg"] for x in e.errors()[:3])) from None


@router.get("/samples")
async def samples() -> list[dict[str, Any]]:
    """SIMULATED sample offer sets for the demo."""
    return [{**s, "disclaimer": "SIMULATED SAMPLE - fictional companies, for demonstration only."} for s in _samples()]


@router.get("/samples/file/{name}")
async def sample_file(name: str) -> FileResponse:
    """Download one SIMULATED sample letter (only files listed in samples.json)."""
    allowed = {o["file"] for s in _samples() for o in s["offers"]}
    if name not in allowed:
        raise HTTPException(404, "Not found.")
    return FileResponse(SAMPLES_DIR / "offers" / name, filename=name)


@router.get("/metros")
async def metros() -> list[dict[str, Any]]:
    """The 52 supported metro areas."""
    return L.supported_metros()


@router.get("/sources")
async def sources() -> dict[str, Any]:
    """Provenance of every processed dataset."""
    return L.manifest()


@router.get("/health")
async def health() -> dict[str, Any]:
    """Liveness and engine mode."""
    s = get_settings()
    return {"ok": True, "engine": "claude" if s.claude_enabled else "local", "llm_mode": s.llm_mode,
            "oews": L.oews_available(), "data_built": L.manifest().get("built")}
