"""Runtime helpers: run an ADK agent once and extract its JSON/text output."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, Optional

from google.adk.agents import BaseAgent
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

logger = logging.getLogger(__name__)


def user_message(text: str) -> types.Content:
    """Wrap a string as a user message for the Runner."""
    return types.Content(role="user", parts=[types.Part(text=text)])


async def run_agent_text_async(
    agent: BaseAgent,
    prompt: str,
    *,
    user_id: str = "testmind",
    max_retries: int = 3,
    retry_delay: float = 45.0,
) -> str:
    """Run a single agent once (async) and return its final text response.

    Retries on transient LLM errors (rate limits / model overload) so the
    pipeline survives free-tier 429 throttling.
    """
    last_error: Optional[BaseException] = None
    for attempt in range(1, max_retries + 1):
        try:
            return await _run_agent_once(agent, prompt, user_id=user_id)
        except Exception as exc:  # noqa: BLE001 - retry any transient failure
            last_error = exc
            if attempt == max_retries:
                break
            if isinstance(exc, asyncio.CancelledError):
                raise
            logger.warning(
                "agent call failed (attempt %d/%d): %s; retrying in %.0fs",
                attempt,
                max_retries,
                type(exc).__name__,
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
    raise last_error


async def _run_agent_once(
    agent: BaseAgent,
    prompt: str,
    *,
    user_id: str,
) -> str:
    """Run a single agent once (no retries) and return its final text."""
    started = time.perf_counter()
    sid = f"session-{uuid.uuid4().hex[:8]}"
    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="testmind",
        session_service=session_service,
    )
    await session_service.create_session(
        app_name="testmind", user_id=user_id, session_id=sid
    )

    final_text: list[str] = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=sid,
        new_message=user_message(prompt),
    ):
        if event.author == agent.name and event.content is not None:
            for part in (event.content.parts or []):
                if getattr(part, "text", None):
                    final_text.append(part.text)

    logger.info("agent %s completed in %.1fs", agent.name, time.perf_counter() - started)
    return "\n".join(final_text)


def run_agent_text(
    agent: BaseAgent,
    prompt: str,
    *,
    user_id: str = "testmind",
    max_retries: int = 3,
    retry_delay: float = 45.0,
) -> str:
    """Sync wrapper: run a single agent once and return its final text."""
    return asyncio.run(
        run_agent_text_async(
            agent, prompt, user_id=user_id, max_retries=max_retries, retry_delay=retry_delay
        )
    )


def extract_json(text: str) -> Optional[Any]:
    """Best-effort JSON extraction from an LLM response (handles fences)."""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    cleaned = cleaned.strip()
    for candidate in (cleaned, text.strip()):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    # Last resort: pull the first {...} or [...] block.
    match = re.search(r"[\[{].*[\]}]", cleaned, flags=re.S)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None