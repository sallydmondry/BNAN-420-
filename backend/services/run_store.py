"""In-memory run store with a TTL (default 30 minutes). Nothing is ever written to disk.

Each run keeps its progress events (status/timing only) and the final result, so the browser can
reconnect to the SSE stream and replay what it missed.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.core.config import get_settings
from backend.core.models import ProgressEvent


@dataclass
class RunRecord:
    run_id: str
    created: float = field(default_factory=time.time)
    events: list[ProgressEvent] = field(default_factory=list)
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    done: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    def push(self, ev: ProgressEvent) -> None:
        """Append an event and wake any listeners."""
        self.events.append(ev)
        self.changed.set()
        self.changed = asyncio.Event()

    def finish(self, result: Optional[dict[str, Any]], error: Optional[str] = None) -> None:
        """Mark the run complete."""
        self.result, self.error, self.done = result, error, True
        self.changed.set()


class RunStore:
    """Process-local store. Expired runs are purged on every access."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}

    def _purge(self) -> None:
        ttl = get_settings().run_ttl_seconds
        now = time.time()
        for k in [k for k, r in self._runs.items() if now - r.created > ttl]:
            del self._runs[k]

    def create(self) -> RunRecord:
        """Start a new run with a random id."""
        self._purge()
        rec = RunRecord(run_id=uuid.uuid4().hex)
        self._runs[rec.run_id] = rec
        return rec

    def get(self, run_id: str) -> Optional[RunRecord]:
        """Look up a live run."""
        self._purge()
        return self._runs.get(run_id)

    def active_count(self) -> int:
        """Runs still in progress."""
        return sum(1 for r in self._runs.values() if not r.done)


STORE = RunStore()
