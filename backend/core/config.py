"""Runtime configuration read from environment variables (never from code or the repo)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DATA_DIR = BACKEND / "data"
PROCESSED_DIR = DATA_DIR / "processed"
RAW_DIR = DATA_DIR / "raw"
SIMULATED_DIR = DATA_DIR / "simulated"
SAMPLES_DIR = DATA_DIR / "samples"
PROMPTS_DIR = BACKEND / "prompts"
FRONTEND_DIST = ROOT / "frontend" / "dist"

load_dotenv(ROOT / ".env", override=False)


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Immutable settings snapshot."""

    llm_mode: str = field(default_factory=lambda: os.getenv("LLM_MODE", "auto").lower())
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5"))
    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 10))
    max_pdf_pages: int = field(default_factory=lambda: _int("MAX_PDF_PAGES", 10))
    rate_limit_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 12))
    max_concurrent_runs: int = field(default_factory=lambda: _int("MAX_CONCURRENT_RUNS", 4))
    run_ttl_seconds: int = field(default_factory=lambda: _int("RUN_TTL_SECONDS", 1800))
    agent_timeout_seconds: int = field(default_factory=lambda: _int("AGENT_TIMEOUT_SECONDS", 60))
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
        )
    )

    @property
    def claude_enabled(self) -> bool:
        """Claude is used only when allowed by LLM_MODE *and* a key exists in the environment."""
        return self.llm_mode != "off" and bool(os.getenv("ANTHROPIC_API_KEY"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor."""
    return Settings()
