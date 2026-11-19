"""Guards on generated text: no new dollar figures, no advice-sounding claims.

Any text an agent shows (Claude or local templates) must only mention dollar amounts that were
computed by the deterministic engine. ``check_dollars`` extracts every ``$`` figure from the text and
verifies each one is within rounding distance of an allowed number.
"""

from __future__ import annotations

import re
from typing import Iterable

_DOLLAR = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s*([kKmM])?(?![\w])")


def dollar_figures(text: str) -> list[float]:
    """All dollar amounts in ``text`` ('$1,234', '$85K', '$1.2M' -> floats)."""
    out: list[float] = []
    for m in _DOLLAR.finditer(text or ""):
        whole = float(m.group(1).replace(",", ""))
        frac = float("0." + m.group(2)) if m.group(2) else 0.0
        v = whole + frac
        suf = (m.group(3) or "").lower()
        if suf == "k":
            v *= 1_000
        elif suf == "m":
            v *= 1_000_000
        out.append(v)
    return out


def _close(v: float, allowed: Iterable[float]) -> bool:
    for a in allowed:
        a = abs(float(a))
        tol = max(1.0, 0.005 * a)
        if abs(v - a) <= tol:
            return True
        # Rounded forms: "$85K" for 85,000 / "$1,380" for 1,382 / "$1.2M"
        for step in (10, 100, 1_000, 10_000, 100_000):
            if a >= step and abs(round(a / step) * step - v) < 0.5:
                return True
    return False


def check_dollars(text: str, allowed: Iterable[float]) -> list[float]:
    """Return the dollar figures in ``text`` that are NOT traceable to ``allowed`` (empty list = pass)."""
    allowed = [abs(float(a)) for a in allowed if a is not None]
    return [v for v in dollar_figures(text) if not _close(v, allowed)]


def safe_text(candidate: str | None, fallback: str, allowed: Iterable[float]) -> tuple[str, bool]:
    """Use ``candidate`` only if it introduces no new dollar figures; otherwise ``fallback``.

    Returns ``(text, used_candidate)``.
    """
    allowed = list(allowed)
    if candidate and not check_dollars(candidate, allowed):
        return candidate.strip(), True
    return fallback, False


def collect_numbers(obj: object) -> list[float]:
    """Every numeric leaf in a nested dict/list/pydantic dump (used to build ``allowed`` sets)."""
    out: list[float] = []
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()  # type: ignore[union-attr]
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(collect_numbers(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(collect_numbers(v))
    return out
