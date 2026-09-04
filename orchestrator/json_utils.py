"""Tolerant JSON parsing helpers for LLM-produced strings."""
from __future__ import annotations

import ast
import json
import re
from typing import Any, Optional


def safe_loads(text: str) -> Optional[Any]:
    """Parse an LLM string as JSON, tolerating common slips.

    Tries (in order): strict JSON, JSON after stripping code fences, Python
    literal (handles single quotes / None / True), then a regex-extracted
    array/object block. Returns None if nothing parses.
    """
    if not text or not isinstance(text, str):
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    stripped = text.strip()

    for candidate in (stripped, text):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            pass

    try:
        return ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        pass

    match = re.search(r"[\[{].*[\]}]", stripped, flags=re.S)
    if match:
        block = match.group(0)
        for candidate in (block, block.replace("'", '"')):
            try:
                return json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def extract_list_json(text: str) -> list[dict]:
    """Return a list of dicts from an LLM string, or [] if not parseable."""
    parsed = safe_loads(text)
    if isinstance(parsed, list):
        return [p for p in parsed if isinstance(p, dict)]
    if isinstance(parsed, dict):
        for _, v in parsed.items():
            if isinstance(v, list):
                return [p for p in v if isinstance(p, dict)]
    return []