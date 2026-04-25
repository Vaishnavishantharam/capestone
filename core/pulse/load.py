from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PULSES_DIR = ROOT / "data" / "state" / "pulses"


def latest_pulse_path(pulses_dir: Path = PULSES_DIR) -> Path | None:
    candidates = sorted(pulses_dir.glob("pulse_*.json"))
    return candidates[-1] if candidates else None


def load_latest_pulse(pulses_dir: Path = PULSES_DIR) -> dict[str, Any] | None:
    p = latest_pulse_path(pulses_dir)
    if not p:
        return None
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

