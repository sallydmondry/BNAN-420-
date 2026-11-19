"""Shared fixtures. Tests always run in local mode (no network, no API key)."""

import os

os.environ["LLM_MODE"] = "off"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "1000")
