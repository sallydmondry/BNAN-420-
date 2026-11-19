"""Run the full 6-agent pipeline on every sample and check it against ground truth.

    .venv/bin/python -m backend.tests.run_pipeline_eval

Checks per offer: every extracted field vs. ground truth, and take-home pay (annual, to the cent)
vs. the independent worksheet. Prints the headline and winner for each sample.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from backend.core.config import SAMPLES_DIR
from backend.core.models import OfferParserInput, UserProfile
from backend.services.orchestrator import run_pipeline

MEDIA = {"pdf": "application/pdf", "png": "image/png", "txt": "text/plain"}


def load_samples() -> dict[str, Any]:
    """samples.json + ground_truth.json."""
    return {"samples": json.loads((SAMPLES_DIR / "samples.json").read_text())["samples"],
            "truth": json.loads((SAMPLES_DIR / "ground_truth.json").read_text())}


def sample_inputs(sample: dict[str, Any]) -> list[OfferParserInput]:
    """Build parser inputs for one sample's offer files."""
    out = []
    for o in sample["offers"]:
        p = SAMPLES_DIR / "offers" / o["file"]
        out.append(OfferParserInput(offer_id=o["offer_id"], label=o["label"], source="file", file_name=p.name,
                                    media_type=MEDIA.get(o["format"]), content=p.read_bytes()))
    return out


def _got(f) -> dict[str, Any]:
    m = f.match_401k.value
    return {
        "company": f.company.value, "job_title": f.job_title.value, "office_city": f.office_city.value,
        "office_state": f.office_state.value, "base_salary": f.base_salary.value,
        "signing_bonus": f.signing_bonus.value or None, "bonus_target_pct": f.bonus_target_pct.value or None,
        "match_401k": None if m is None else {"tiers": [{"rate": t.rate, "on_pct": t.on_pct} for t in m.tiers],
                                              "nonelective_pct": m.nonelective_pct},
        "hsa_employer_annual": f.hsa_employer_annual.value, "pto_days": f.pto_days.value,
        "pto_unlimited": f.pto_unlimited, "relocation": f.relocation.value,
        "equity_value_usd": f.equity.value.value_usd if f.equity.value else None,
        "start_date": f.start_date.value, "work_arrangement": f.work_arrangement.value,
    }


def _eq(a: Any, b: Any) -> bool:
    if isinstance(b, dict) and isinstance(a, dict):
        return a.keys() == b.keys() and all(_eq(a[k], b[k]) for k in b)
    if isinstance(b, list) and isinstance(a, list):
        return len(a) == len(b) and all(_eq(x, y) for x, y in zip(a, b))
    if isinstance(b, (int, float)) and not isinstance(b, bool) and isinstance(a, (int, float)):
        return abs(float(a) - float(b)) < 0.01
    return a == b


async def evaluate(verbose: bool = True) -> dict[str, int]:
    """Run every sample; return counts of field and take-home mismatches."""
    data = load_samples()
    truth = data["truth"]["offers"]
    field_total = field_bad = th_bad = 0
    for s in data["samples"]:
        t0 = time.perf_counter()
        state = await run_pipeline("eval" + s["id"], UserProfile(**s["profile"]), sample_inputs(s), {}, lambda _e: None)
        ms = int((time.perf_counter() - t0) * 1000)
        for o in s["offers"]:
            gt = truth[o["key"]]
            p = state.parsed.get(o["offer_id"])
            if p is None:
                field_bad += len(gt["fields"])
                print(f"  ✗ {o['key']}: parser failed")
                continue
            got = _got(p.fields)
            for k, v in gt["fields"].items():
                field_total += 1
                if not _eq(got[k], v):
                    field_bad += 1
                    print(f"  ✗ {o['key']} {k}: expected {v!r}, got {got[k]!r}")
            tr = next((r for r in (state.tax.results if state.tax else []) if r.offer_id == o["offer_id"]), None)
            if tr is None or abs(tr.take_home_annual - gt["take_home"]["take_home_annual"]) > 0.02:
                th_bad += 1
                print(f"  ✗ {o['key']} take-home: expected {gt['take_home']['take_home_annual']}, "
                      f"got {tr.take_home_annual if tr else None}")
        d = state.decision
        if verbose:
            flag = " (DEGRADED: " + ", ".join(state.degraded_agents) + ")" if state.degraded else ""
            print(f"[{s['id']}] {ms} ms{flag}\n   {d.headline if d else 'no decision'}")
            if d:
                for r in sorted(d.scorecard, key=lambda r: r.rank or 9):
                    print(f"   #{r.rank} {r.label} {r.metro_name:18} left over ${r.left_over_monthly or 0:>8,.0f}/mo  "
                          f"score {r.total_score}")
    print(f"\nFields: {field_total - field_bad}/{field_total} correct · take-home mismatches: {th_bad}")
    return {"field_total": field_total, "field_bad": field_bad, "take_home_bad": th_bad}


def main() -> None:
    """CLI entry point; exits non-zero on any mismatch."""
    res = asyncio.run(evaluate())
    sys.exit(1 if res["field_bad"] or res["take_home_bad"] else 0)


if __name__ == "__main__":
    main()
