"""gate_thresholds.py — loads baselines/gate_thresholds.json, the single source of gate thresholds.

There is deliberately no fallback: a missing or unreadable file must stop the gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

THRESHOLDS_FILE = Path(__file__).resolve().parent.parent / "baselines" / "gate_thresholds.json"


def load() -> dict[str, Any]:
    return json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
