from __future__ import annotations

import json
from pathlib import Path

from core.mcp.hitl import generate_actions_from_booking


def test_actions_include_booking_code_and_pulse_context() -> None:
    here = Path(__file__).resolve().parent
    booking = json.loads((here / "fixtures" / "booking_min.json").read_text(encoding="utf-8"))
    pulse = json.loads((here / "fixtures" / "pulse_min.json").read_text(encoding="utf-8"))

    actions = generate_actions_from_booking(booking, pulse=pulse)
    assert {a["action_type"] for a in actions} == {"calendar_hold", "append_notes", "email_draft"}

    # booking code must propagate everywhere
    for a in actions:
        assert booking["booking_code"] in json.dumps(a)

    email = next(a for a in actions if a["action_type"] == "email_draft")
    assert "Market/Customer sentiment context" in email["payload"]["body"]
    assert "Login issues" in email["payload"]["body"]

