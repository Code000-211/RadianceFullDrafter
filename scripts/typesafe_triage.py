#!/usr/bin/env python3
"""
typesafe_triage.py — minimal client for TypeSafe's System One API (model jev-latest).

Used where a fuzzy text judgment feeds deterministic code: upstream PR triage
(watch_upstream.py) and lever claim / duplicate checks (lever_review.py). Gate
verdicts never depend on it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


def get_api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "")
    if not key:
        key_file = Path.home() / ".config" / "typesafe" / "api_key"
        if key_file.is_file():
            key = key_file.read_text(encoding="utf-8").strip()
    return key


def query_jev(state: str, questions: dict[str, Any]) -> dict[str, Any]:
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError(
            "TYPESAFE_API_KEY not found. Set it via env or in ~/.config/typesafe/api_key."
        )

    payload = {
        "state": state,
        "model": "jev-latest",
        "questions": questions,
    }

    req = urllib.request.Request(
        TYPESAFE_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("answers", {})
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TypeSafe API Error HTTP {e.code}: {err_body}") from e
    except Exception as e:
        raise RuntimeError(f"Network error contacting TypeSafe API: {e}") from e
