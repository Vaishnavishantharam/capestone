from __future__ import annotations

import json
import os
import random
import re
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.pulse.load import load_latest_pulse


ROOT = Path(__file__).resolve().parents[2]
BOOKINGS_DIR = ROOT / "data" / "state" / "bookings"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def generate_booking_code(prefix: str = "IN") -> str:
    suffix = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"{prefix}-{suffix}"


PII_RE = re.compile(r"\b(pan|aadhaar|otp|folio|account number|phone|email)\b", re.IGNORECASE)
ADVICE_RE = re.compile(r"\b(best|returns?|20%|guarantee|should i|invest|buy|sell|predict)\b", re.IGNORECASE)


TOPICS = [
    "KYC / Onboarding",
    "SIP / Mandates",
    "Statements / Tax Docs",
    "Withdrawals & Timelines",
    "Account Changes / Nominee",
]


@dataclass(frozen=True)
class BookingResult:
    booking_code: str
    topic: str
    slot_ist: str
    pulse_id: str | None
    top_theme: str | None
    persisted_path: str


def theme_aware_greeting() -> tuple[str, str | None, str | None]:
    pulse = load_latest_pulse()
    if not pulse:
        return (
            "Hi — I can help schedule a tentative advisor slot. This is informational only (not investment advice). "
            "Please don’t share personal details (phone/email/PAN/Aadhaar/OTP).",
            None,
            None,
        )
    top_theme = (pulse.get("top_themes") or [None])[0]
    pulse_id = pulse.get("pulse_id")
    msg = (
        "Hi — I can help schedule a tentative advisor slot. This is informational only (not investment advice). "
        "Please don’t share personal details (phone/email/PAN/Aadhaar/OTP). "
    )
    if top_theme:
        msg += f"Quick note: many users are asking about {top_theme} this week — I can help you book a call for that."
    return msg, pulse_id, top_theme


def offer_two_slots(now_utc: datetime | None = None) -> list[str]:
    """
    Mock calendar: offer two slots in IST.
    Keeps it deterministic enough for demos.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    # pretend IST = UTC+5:30
    ist = timezone(timedelta(hours=5, minutes=30))
    base = now_utc.astimezone(ist).replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
    slot1 = base.strftime("%Y-%m-%d %I:%M %p IST")
    slot2 = (base + timedelta(minutes=45)).strftime("%Y-%m-%d %I:%M %p IST")
    return [slot1, slot2]


def persist_booking(bundle: dict[str, Any], bookings_dir: Path = BOOKINGS_DIR) -> Path:
    bookings_dir.mkdir(parents=True, exist_ok=True)
    out = bookings_dir / f"booking_{bundle['booking_code']}.json"
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def run_text_booking_session(
    *,
    user_topic: str,
    user_slot_choice: int,
    user_time_preference: str = "",
) -> BookingResult:
    """
    Text-mode booking (chat fallback). Voice can be added later; state machine remains same.

    Inputs are already collected by a UI/CLI layer.
    """
    if PII_RE.search(user_topic) or PII_RE.search(user_time_preference):
        raise ValueError("PII detected in input. Do not collect/store personal information.")
    if ADVICE_RE.search(user_topic):
        raise ValueError("Investment advice is out of scope for booking.")

    greeting, pulse_id, top_theme = theme_aware_greeting()
    _ = greeting  # returned by UI layer; kept here to show dependency on pulse

    topic = next((t for t in TOPICS if t.lower() in user_topic.lower()), user_topic.strip() or TOPICS[-1])

    slots = offer_two_slots()
    idx = 0 if user_slot_choice == 1 else 1
    chosen = slots[idx]

    booking_code = generate_booking_code(prefix=os.environ.get("BOOKING_PREFIX", "IN"))
    bundle = {
        "booking_code": booking_code,
        "topic": topic,
        "slot_ist": chosen,
        "timezone": "IST",
        "input_mode": "chat",
        "pulse_id": pulse_id,
        "top_theme": top_theme,
        "created_at": iso_now(),
    }
    path = persist_booking(bundle)

    return BookingResult(
        booking_code=booking_code,
        topic=topic,
        slot_ist=chosen,
        pulse_id=pulse_id,
        top_theme=top_theme,
        persisted_path=str(path),
    )

