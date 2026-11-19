"""Agent 1 — Offer Parser.

Turns one offer (uploaded file, pasted text, or the manual form) into structured ``OfferFields`` and
matches the office city to a supported metro. Fields the letter does not mention are marked
"not stated in offer" instead of being guessed.

Engines: local rules extractor (always available) or Claude (optional; only fills fields the rules
missed, and every value must be quoted from the letter).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Optional

from backend.core import llm
from backend.core.config import get_settings
from backend.core.models import (
    EquityGrant,
    Extracted,
    Match401k,
    MatchTier,
    OfferFields,
    OfferParserInput,
    OfferParserOutput,
    ResolvedLocation,
)
from backend.data import lookups as L
from backend.services.rules_extractor import extract_fields, offer_likelihood
from backend.services.text_extract import UnsupportedFile, extract_text

KEY_FIELDS = ["company", "job_title", "office_city", "base_salary", "signing_bonus", "bonus_target_pct",
              "match_401k", "pto_days", "start_date", "work_arrangement"]


def _user(v: Any, note: Optional[str] = None) -> Extracted:
    return Extracted(value=v, status="user_entered", note=note) if v is not None else Extracted()


def fields_from_form(form) -> OfferFields:
    """Manual form -> OfferFields (blank inputs stay not_stated)."""
    f = OfferFields(
        company=_user(form.company), job_title=_user(form.job_title), office_city=_user(form.office_city),
        office_state=_user(L.normalize_state(form.office_state) if form.office_state else None),
        signing_bonus=_user(form.signing_bonus), bonus_target_pct=_user(form.bonus_target_pct),
        hsa_employer_annual=_user(form.hsa_employer_annual), pto_days=_user(form.pto_days),
        relocation=_user(form.relocation), start_date=_user(form.start_date), work_arrangement=_user(form.work_arrangement),
    )
    if form.base_salary:
        f.base_salary, f.pay_basis = _user(form.base_salary), "annual"
    elif form.hourly_rate:
        hours = form.hours_per_week or 40
        f.hourly_rate = _user(form.hourly_rate)
        f.hours_per_week = _user(hours)
        f.base_salary = Extracted(value=form.hourly_rate * hours * 52, status="derived",
                                  note=f"${form.hourly_rate:,.2f}/hr × {hours:g} hrs/week × 52")
        f.pay_basis = "hourly"
    if form.match_rate_pct is not None and form.match_up_to_pct:
        m = Match401k(tiers=[MatchTier(rate=form.match_rate_pct / 100, on_pct=form.match_up_to_pct)],
                      description=f"{form.match_rate_pct:g}% of the first {form.match_up_to_pct:g}%")
        f.match_401k = _user(m)
    if form.equity_value_usd:
        f.equity = _user(EquityGrant(value_usd=form.equity_value_usd, vesting_years=form.equity_vesting_years,
                                     description="entered manually"))
    return f


def apply_corrections(fields: OfferFields, form) -> list[str]:
    """Fill or override extracted fields with anything the user typed in 'Add or correct details'."""
    typed = fields_from_form(form)
    changed = []
    for name in OfferFields.model_fields:
        v = getattr(typed, name)
        if isinstance(v, Extracted) and v.value is not None:
            setattr(fields, name, v)
            changed.append(name)
    if typed.pay_basis != "unknown" and "base_salary" in changed:
        fields.pay_basis = typed.pay_basis
    return changed


def _count_found(f: OfferFields) -> int:
    return sum(1 for k in KEY_FIELDS if getattr(f, k).known or (k == "pto_days" and f.pto_unlimited))


async def _claude_fill(text: str, fields: OfferFields, log: list[str]) -> bool:
    """Ask Claude for fields the rules missed. Only quoted, numerically consistent values are accepted."""
    raw = await llm.generate("offer_parser", f"<offer_letter>\n{text[:20000]}\n</offer_letter>", max_tokens=3000)
    if not raw:
        return False
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return False
    ev = data.get("evidence") or {}
    flat_text = re.sub(r"\s+", " ", text).lower()
    filled = 0

    def quoted(key: str) -> Optional[str]:
        q = ev.get(key)
        if isinstance(q, str) and re.sub(r"\s+", " ", q).lower().strip(" .…") in flat_text:
            return q[:160]
        return None

    simple = {"company": str, "job_title": str, "office_city": str, "office_state": str, "base_salary": float,
              "signing_bonus": float, "bonus_target_pct": float, "bonus_target_amount": float,
              "hsa_employer_annual": float, "pto_days": float, "relocation": float, "start_date": str,
              "work_arrangement": str}
    for key, typ in simple.items():
        cur: Extracted = getattr(fields, key)
        val = data.get(key)
        if cur.known or val in (None, "") or not quoted(key):
            continue
        try:
            val = typ(val)
        except (TypeError, ValueError):
            continue
        if key == "work_arrangement" and val not in ("onsite", "hybrid", "remote"):
            continue
        if key == "office_state":
            val = L.normalize_state(val)
            if not val:
                continue
        setattr(fields, key, Extracted(value=val, status="stated", evidence=quoted(key), note="read by Claude"))
        filled += 1
    if not fields.match_401k.known and data.get("match_tiers") and quoted("match_tiers"):
        try:
            tiers = [MatchTier(rate=float(t["rate"]), on_pct=float(t["on_pct"])) for t in data["match_tiers"]]
            fields.match_401k = Extracted(value=Match401k(tiers=tiers, nonelective_pct=float(data.get("nonelective_pct") or 0),
                                                          description="read by Claude"),
                                          status="stated", evidence=quoted("match_tiers"))
            filled += 1
        except (KeyError, TypeError, ValueError):
            pass
    if filled:
        log.append(f"Claude filled {filled} field(s) the rules missed (each backed by a quote).")
    return True


def resolve_location(fields: OfferFields, remote_hint: Optional[str]) -> tuple[ResolvedLocation, list[str]]:
    """Office city -> supported metro. Fully remote offers use the user's chosen home base."""
    warnings: list[str] = []
    if fields.work_arrangement.value == "remote" and remote_hint:
        c, s = L.split_city_state(remote_hint)
        loc = L.resolve_city(c, s, basis="remote_residence")
        loc.method = "remote_profile"
        if not loc.matched:
            warnings.append(f"Your remote home base '{remote_hint}' is not one of the 52 supported metros.")
        return loc, warnings
    city = fields.office_city.value if fields.office_city.known else None
    state = fields.office_state.value if fields.office_state.known else None
    loc = L.resolve_city(city, state, basis="office")
    if not city:
        warnings.append("Office city not found in the letter, so city costs and lifestyle can't be computed. Type it under "
                        "'Add or correct details' and compare again.")
    elif not loc.matched:
        warnings.append(f"'{city}' isn't in TrueOffer's 52-metro dataset, so city costs can't be estimated.")
    elif loc.state and not fields.office_state.known:
        fields.office_state = Extracted(value=loc.state, status="derived", note=f"from metro match ({loc.metro_name})")
    if fields.work_arrangement.value == "remote" and not remote_hint:
        warnings.append("This offer is remote. Add 'where you'd live' in your profile for accurate costs.")
    return loc, warnings


async def run(inp: OfferParserInput) -> OfferParserOutput:
    """Parse one offer into structured fields and a resolved metro."""
    t0 = time.perf_counter()
    log: list[str] = []
    warnings: list[str] = []
    engine = "local"
    text_source = "none"
    is_offer = True

    if inp.source == "form" and inp.form is not None:
        fields = fields_from_form(inp.form)
        text_source = "form"
        log.append("Used the values you typed into the manual form.")
    else:
        text = ""
        if inp.source == "file" and inp.content:
            try:
                ex = await asyncio.to_thread(extract_text, inp.content, inp.file_name, inp.media_type,
                                             get_settings().max_pdf_pages)
            except UnsupportedFile as e:
                return OfferParserOutput(offer_id=inp.offer_id, label=inp.label, is_offer_letter=False, confidence=0.0,
                                         warnings=[str(e)], log=["Could not read the file."], engine="local",
                                         elapsed_ms=int((time.perf_counter() - t0) * 1000))
            text, text_source = ex.text, ex.source
            warnings.extend(ex.warnings)
            log.append({"pdf_text": "Read the PDF's embedded text.", "ocr": "Read the document with offline OCR.",
                        "text": "Read the file as text."}[ex.source])
        elif inp.text:
            text, text_source = inp.text, "text"
            log.append("Read the pasted text.")
        if len(text.strip()) < 40:
            return OfferParserOutput(offer_id=inp.offer_id, label=inp.label, is_offer_letter=False, text_source=text_source,
                                     warnings=["No readable text found. Try pasting the text or using the manual form."],
                                     log=log, engine="local", elapsed_ms=int((time.perf_counter() - t0) * 1000))
        likelihood = offer_likelihood(text)
        if likelihood < 0.34:
            is_offer = False
            warnings.append("This doesn't look like a job offer letter. Check that you uploaded the right file.")
        fields, rlog = await asyncio.to_thread(extract_fields, text)
        log.extend(rlog)
        if inp.form is not None:
            changed = apply_corrections(fields, inp.form)
            if changed:
                log.append(f"Used {len(changed)} detail(s) you typed in: " + ", ".join(c.replace('_', ' ') for c in changed) + ".")
        if llm.claude_enabled() and _count_found(fields) < len(KEY_FIELDS):
            if await _claude_fill(text, fields, log):
                engine = "claude"
        del text  # privacy: drop the letter text as soon as fields are extracted

    loc, lw = resolve_location(fields, inp.remote_city_hint)
    warnings.extend(lw)
    if loc.matched:
        log.append(f"Matched the office to the {loc.metro_name} metro ({loc.method.replace('_', ' ')}).")
    if not fields.job_title.known:
        warnings.append("Job title not found in the letter, so the pay benchmark is skipped. Type it under "
                        "'Add or correct details' and compare again.")
    if not fields.base_salary.known:
        warnings.append("Base salary not found in the letter, so pay-based numbers are missing. Type it under "
                        "'Add or correct details' and compare again.")

    found = _count_found(fields)
    confidence = round(min(1.0, 0.75 * found / len(KEY_FIELDS) + (0.25 if loc.matched else 0.0)) * (1.0 if is_offer else 0.5), 2)
    if text_source == "ocr":
        confidence = round(confidence * 0.9, 2)
    log.append(f"Found {found} of {len(KEY_FIELDS)} key fields; the rest are marked 'not stated in offer'.")
    return OfferParserOutput(
        offer_id=inp.offer_id, label=inp.label, fields=fields, location=loc, is_offer_letter=is_offer,
        text_source=text_source, fields_found=found, fields_total=len(KEY_FIELDS), confidence=confidence,
        log=log, warnings=warnings, engine=engine, elapsed_ms=int((time.perf_counter() - t0) * 1000),  # type: ignore[arg-type]
    )
