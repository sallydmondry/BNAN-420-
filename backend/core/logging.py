"""Privacy-safe logging.

Only run ids, agent names, statuses and timings are ever logged. There is deliberately
no helper that accepts free-form offer data. Do not print() user content anywhere.
"""

from __future__ import annotations

import logging
import sys

_logger = logging.getLogger("trueoffer")
if not _logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s trueoffer %(message)s"))
    _logger.addHandler(_h)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False

_ALLOWED_STATUS = {"started", "finished", "failed", "timeout", "skipped", "rejected", "ok"}


def log_event(run_id: str, agent: str, status: str, elapsed_ms: int | None = None, code: str | None = None) -> None:
    """Log a status line. ``code`` must be a short machine code (e.g. 'rate_limited'), never user data."""
    status = status if status in _ALLOWED_STATUS else "ok"
    parts = [f"run={run_id[:8]}", f"agent={agent}", f"status={status}"]
    if elapsed_ms is not None:
        parts.append(f"ms={elapsed_ms}")
    if code:
        parts.append(f"code={code[:40]}")
    _logger.info(" ".join(parts))
