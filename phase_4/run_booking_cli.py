from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.voice.booking import theme_aware_greeting, run_text_booking_session  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 4: booking agent (text mode)")
    ap.add_argument("--topic", required=True, type=str, help="Booking topic (no PII)")
    ap.add_argument("--time", default="", type=str, help="Optional time preference string (no PII)")
    ap.add_argument("--slot", default=1, type=int, choices=[1, 2], help="Choose slot 1 or 2")
    args = ap.parse_args()

    greeting, pulse_id, top_theme = theme_aware_greeting()
    print(greeting)
    if pulse_id:
        print(f"(Using pulse_id={pulse_id}, top_theme={top_theme})")
    print()

    res = run_text_booking_session(user_topic=args.topic, user_time_preference=args.time, user_slot_choice=args.slot)
    print("Confirmed booking:")
    print(f"- Booking code: {res.booking_code}")
    print(f"- Topic: {res.topic}")
    print(f"- Slot: {res.slot_ist}")
    print(f"- Saved: {res.persisted_path}")


if __name__ == "__main__":
    main()

