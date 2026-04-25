from __future__ import annotations

import json
import re
from pathlib import Path

from core.voice.booking import BOOKINGS_DIR, run_text_booking_session, theme_aware_greeting


def test_greeting_mentions_top_theme_when_pulse_exists() -> None:
    greeting, pulse_id, top_theme = theme_aware_greeting()
    # In this repo we usually have at least one pulse from Phase 2; if not, allow skip.
    if pulse_id and top_theme:
        assert top_theme.lower() in greeting.lower()


def test_booking_persists_and_has_code_format(tmp_path: Path, monkeypatch) -> None:
    # Force bookings to temp dir
    monkeypatch.setattr("core.voice.booking.BOOKINGS_DIR", tmp_path)

    res = run_text_booking_session(user_topic="Nominee update", user_time_preference="tomorrow evening", user_slot_choice=1)
    assert re.match(r"^IN-[A-Z0-9]{4}$", res.booking_code)

    p = Path(res.persisted_path)
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["booking_code"] == res.booking_code
    assert data["timezone"] == "IST"
    assert data["input_mode"] == "chat"

