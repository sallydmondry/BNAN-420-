"""API end to end, degraded mode, and privacy rules."""

import io
import json
import logging
import time

import pytest
from fastapi.testclient import TestClient

from backend.agents import market_agent
from backend.core.config import SAMPLES_DIR
from backend.main import app

LETTER = ("Hi Morgan! We are pleased to offer you the position of Financial Analyst at Zephyr Capital in our Boston, MA office. "
          "Base salary: $91,000 per year. Signing bonus: $6,000. 401(k): we match 100% of the first 4%. 18 days PTO. "
          "Start date: July 6, 2026. Hybrid. Our secret project codename is BLUE-PELICAN-7.")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _wait(client, run_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/api/compare/{run_id}/result")
        if r.status_code != 202:
            return r
        time.sleep(0.2)
    raise AssertionError("run did not finish")


def test_health_and_metadata(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["engine"] == "local" and h["oews"]
    assert len(client.get("/api/metros").json()) == 52
    samples = client.get("/api/samples").json()
    assert len(samples) == 6 and all(s["simulated"] for s in samples)
    assert client.get("/api/samples/file/../../main.py").status_code == 404


def test_sample_run_and_sse(client):
    rid = client.post("/api/compare", files={"payload": (None, json.dumps({"sample_id": "data-3way"}))}).json()["run_id"]
    res = _wait(client, rid).json()
    assert res["decision"]["winner"] in ("A", "B", "C") and len(res["decision"]["scorecard"]) == 3
    assert not res["degraded"]
    with client.stream("GET", f"/api/compare/{rid}/events") as s:
        body = "".join(s.iter_text())
    assert "agent_finished" in body and "event: result" in body


def test_upload_text_and_form_with_privacy(client, caplog):
    payload = {"profile": {"student_loan_monthly": 250},
               "offers": [{"offer_id": "A", "source": "file", "label": "Boston"},
                          {"offer_id": "B", "source": "form", "form": {"company": "Beta", "job_title": "Financial Analyst",
                                                                        "office_city": "Charlotte", "office_state": "NC",
                                                                        "base_salary": 84000}}]}
    with caplog.at_level(logging.INFO, logger="trueoffer"):
        rid = client.post("/api/compare", files={"payload": (None, json.dumps(payload)),
                                                 "file_A": ("offer.txt", io.BytesIO(LETTER.encode()), "text/plain")}).json()["run_id"]
        res = _wait(client, rid)
    blob = res.text
    assert res.status_code == 200
    a = res.json()["parsed"]["A"]["fields"]
    assert a["company"]["value"] == "Zephyr Capital" and a["base_salary"]["value"] == 91000
    # Privacy: the full letter is never echoed back; only short evidence quotes for extracted fields.
    assert "BLUE-PELICAN-7" not in blob
    # Logs carry ids/status/timing only — no salaries, names or letter text.
    logs = " ".join(r.getMessage() for r in caplog.records)
    assert "91,000" not in logs and "91000" not in logs and "Zephyr" not in logs and "BLUE-PELICAN" not in logs


def test_validation_errors(client):
    one = {"offers": [{"offer_id": "A", "source": "text", "text": LETTER}]}
    assert client.post("/api/compare", files={"payload": (None, json.dumps(one))}).status_code == 422
    missing_file = {"offers": [{"offer_id": "A", "source": "file"}, {"offer_id": "B", "source": "text", "text": LETTER}]}
    assert client.post("/api/compare", files={"payload": (None, json.dumps(missing_file))}).status_code == 422


def test_bad_file_degrades_gracefully(client):
    payload = {"offers": [{"offer_id": "A", "source": "file"}, {"offer_id": "B", "source": "text", "text": LETTER}]}
    rid = client.post("/api/compare", files={"payload": (None, json.dumps(payload)),
                                             "file_A": ("x.bin", io.BytesIO(b"\x00\xff" * 500), "application/octet-stream")}).json()["run_id"]
    res = _wait(client, rid).json()
    assert res["parsed"]["A"]["is_offer_letter"] is False
    assert res["decision"] is not None


def test_agent_failure_marks_degraded(client, monkeypatch):
    async def boom(_inp):
        raise RuntimeError("simulated outage")
    monkeypatch.setattr(market_agent, "run", boom)
    rid = client.post("/api/compare", files={"payload": (None, json.dumps({"sample_id": "tech-aus-sf"}))}).json()["run_id"]
    res = _wait(client, rid).json()
    assert res["degraded"] and "market" in res["degraded_agents"]
    assert res["decision"]["scorecard"], "pipeline still produces a scorecard without the market agent"


def test_recalculate_endpoint(client):
    rid = client.post("/api/compare", files={"payload": (None, json.dumps({"sample_id": "consulting-phx-den"}))}).json()["run_id"]
    ctx = _wait(client, rid).json()["recalc_context"]
    r = client.post("/api/recalculate", json={"context": ctx, "overrides": {"student_loan_monthly": 900}})
    assert r.status_code == 200 and all(row["loans_monthly"] == 900 for row in r.json()["scorecard"])
    bad = client.post("/api/recalculate", json={"context": ctx, "overrides": {"contribution_401k_pct": 500}})
    assert bad.status_code == 422


def test_sample_files_are_marked_simulated():
    for p in (SAMPLES_DIR / "offers").glob("*.txt"):
        assert "SIMULATED" in p.read_text()
