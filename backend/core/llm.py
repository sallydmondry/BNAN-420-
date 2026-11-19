"""Optional Claude access for language tasks. Off unless an API key is present.

TrueOffer runs fully offline. ``generate()`` returns ``None`` whenever Claude is not enabled
(``LLM_MODE=off`` or no ``ANTHROPIC_API_KEY``), when the call fails, or when the model declines.
Every caller treats ``None`` as "use the local engine", so the product never depends on the network.

Claude is only ever asked to extract fields or to *explain* numbers it is handed; all arithmetic stays
in Python, and generated text is checked by ``core.guards`` before it is shown.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Optional

from backend.core.config import PROMPTS_DIR, get_settings


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Read ``backend/prompts/<name>.md`` (prompts live only there)."""
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def claude_enabled() -> bool:
    """True only when LLM_MODE allows it and a key is configured."""
    return get_settings().claude_enabled


async def generate(prompt_name: str, user_content: str, max_tokens: int = 2000, timeout_s: float = 30.0) -> Optional[str]:
    """Ask Claude for text using the system prompt in ``backend/prompts/<prompt_name>.md``.

    Returns the response text, or ``None`` if Claude is disabled or anything goes wrong.
    """
    if not claude_enabled():
        return None
    try:
        import anthropic  # imported lazily so local mode never touches the SDK
    except ImportError:
        return None
    try:
        client = anthropic.AsyncAnthropic(timeout=timeout_s, max_retries=1)
        resp = await asyncio.wait_for(
            client.beta.messages.create(
                model=get_settings().anthropic_model,
                max_tokens=max_tokens,
                system=load_prompt(prompt_name),
                messages=[{"role": "user", "content": user_content}],
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ),
            timeout=timeout_s + 5,
        )
    except (anthropic.APIError, asyncio.TimeoutError, TypeError, ValueError):
        return None
    if getattr(resp, "stop_reason", None) == "refusal":
        return None
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text").strip()
    return text or None
