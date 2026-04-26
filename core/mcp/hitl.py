from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from core.pulse.load import load_latest_pulse


ROOT = Path(__file__).resolve().parents[2]
BOOKINGS_DIR = ROOT / "data" / "state" / "bookings"
APPROVALS_DIR = ROOT / "data" / "state" / "approvals"
OUTBOX_DIR = ROOT / "data" / "state" / "outbox"

ActionType = Literal["calendar_hold", "append_notes", "email_draft"]
ActionStatus = Literal["pending", "approved", "rejected"]


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def latest_booking_path(bookings_dir: Path = BOOKINGS_DIR) -> Path | None:
    candidates = sorted(bookings_dir.glob("booking_*.json"))
    return candidates[-1] if candidates else None


def load_latest_booking(bookings_dir: Path = BOOKINGS_DIR) -> dict[str, Any] | None:
    p = latest_booking_path(bookings_dir)
    if not p:
        return None
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _market_context_snippet(pulse: dict[str, Any] | None) -> str:
    if not pulse:
        return "Market/Customer sentiment context: (no weekly pulse available yet)."
    top = pulse.get("top_themes") or []
    themes = ", ".join([str(t) for t in top[:3]]) if top else "(no themes)"
    note = str(pulse.get("weekly_note") or "").strip()
    if note:
        return "\n".join(
            [
                "Market Context (from Weekly Pulse):",
                note,
                "",
                f"Customer Sentiment this week: {themes}",
            ]
        )
    return f"Market/Customer sentiment context (from Weekly Pulse): top themes this week are {themes}."


def generate_actions_from_booking(
    booking: dict[str, Any],
    *,
    pulse: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Generate (but do not execute) 3 mock actions for HITL:
      1) calendar hold
      2) notes/doc append
      3) email draft (includes pulse context snippet)
    """
    pulse = pulse or load_latest_pulse()

    booking_code = booking["booking_code"]
    topic = booking["topic"]
    slot_ist = booking["slot_ist"]
    pulse_id = booking.get("pulse_id")
    top_theme = booking.get("top_theme")
    # Voice-tab booking schema can include these:
    pulse_theme = booking.get("pulse_theme") or top_theme
    market_context = booking.get("market_context")

    is_voice_style = str(booking_code).startswith("BOOK-2024-")

    calendar_payload = {
        "title": (f"Advisor Call - {topic}" if is_voice_style else f"Advisor Q&A — {topic} — {booking_code}"),
        "slot_ist": slot_ist,
        "timezone": "IST",
        "booking_code": booking_code,
    }

    notes_payload = {
        "doc_name": "Advisor Pre-Bookings (mock)",
        "line": (
            f"Booking {booking_code} | Topic: {topic} | Pulse Theme: {pulse_theme} | Slot: {slot_ist}"
            if is_voice_style
            else f"{slot_ist} | {topic} | {booking_code} | pulse_id={pulse_id} | top_theme={top_theme}"
        ),
        "booking_code": booking_code,
    }

    email_payload = {
        "to": "advisor@company.test",
        "subject": (f"Upcoming call - {topic}" if is_voice_style else f"Advisor Pre-Booking — {topic} — {booking_code}"),
        "body": "\n".join(
            [
                "Dear Advisor,",
                "You have a call booked.",
                f"Topic: {topic}",
                f"Slot: {slot_ist}",
                f"Booking Code: {booking_code}",
                "",
                "Market Context (from Weekly Pulse):",
                (market_context.strip() if isinstance(market_context, str) and market_context.strip() else _market_context_snippet(pulse)),
                "",
                f"Customer Sentiment this week: {pulse_theme}",
                "",
                "Note: This is a draft only (HITL approval required).",
            ]
        )
        if is_voice_style
        else "\n".join(
            [
                f"Booking code: {booking_code}",
                f"Topic: {topic}",
                f"Slot (IST): {slot_ist}",
                "",
                _market_context_snippet(pulse),
                "",
                "Note: This is a draft only (HITL approval required).",
            ]
        ),
        "booking_code": booking_code,
    }

    return [
        {"action_type": "calendar_hold", "payload": calendar_payload},
        {"action_type": "append_notes", "payload": notes_payload},
        {"action_type": "email_draft", "payload": email_payload},
    ]


def enqueue_actions(actions: list[dict[str, Any]], *, approvals_dir: Path = APPROVALS_DIR) -> list[Path]:
    approvals_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for a in actions:
        item_id = f"approval_{uuid.uuid4().hex[:10]}"
        item = {
            "id": item_id,
            "status": "pending",
            "created_at": iso_now(),
            "action_type": a["action_type"],
            "payload": a["payload"],
        }
        p = approvals_dir / f"{item_id}.json"
        p.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(p)
    return written


def list_queue(*, approvals_dir: Path = APPROVALS_DIR, status: ActionStatus | None = None) -> list[dict[str, Any]]:
    if not approvals_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for p in sorted(approvals_dir.glob("approval_*.json")):
        with p.open("r", encoding="utf-8") as f:
            item = json.load(f)
        if status and item.get("status") != status:
            continue
        items.append(item)
    return items


def _write_outbox(action: dict[str, Any], *, outbox_dir: Path = OUTBOX_DIR) -> Path:
    outbox_dir.mkdir(parents=True, exist_ok=True)
    action_type = action["action_type"]
    code = action.get("payload", {}).get("booking_code", "UNKNOWN")
    p = outbox_dir / f"{action_type}_{code}.json"
    p.write_text(json.dumps(action, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def set_status(approval_id: str, new_status: ActionStatus, *, approvals_dir: Path = APPROVALS_DIR) -> Path:
    p = approvals_dir / f"{approval_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"Approval item not found: {approval_id}")
    item = json.loads(p.read_text(encoding="utf-8"))
    item["status"] = new_status
    item["reviewed_at"] = iso_now()
    p.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # On approve, write a copy to outbox (mock execution log).
    if new_status == "approved":
        _write_outbox(item)
    return p

