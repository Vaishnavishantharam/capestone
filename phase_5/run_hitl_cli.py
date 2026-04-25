from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.mcp.hitl import (  # noqa: E402
    enqueue_actions,
    generate_actions_from_booking,
    list_queue,
    load_latest_booking,
    set_status,
)


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 5: local HITL approval center (mock MCP)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("create", help="Generate 3 pending actions from latest booking")

    p_list = sub.add_parser("list", help="List queue items")
    p_list.add_argument("--status", default="", choices=["", "pending", "approved", "rejected"])

    p_approve = sub.add_parser("approve", help="Approve an action (writes outbox record)")
    p_approve.add_argument("approval_id", type=str)

    p_reject = sub.add_parser("reject", help="Reject an action")
    p_reject.add_argument("approval_id", type=str)

    args = ap.parse_args()

    if args.cmd == "create":
        booking = load_latest_booking()
        if not booking:
            raise SystemExit("No booking found. Run Phase 4 first to create a booking artifact.")
        actions = generate_actions_from_booking(booking)
        paths = enqueue_actions(actions)
        print(f"Enqueued {len(paths)} actions:")
        for p in paths:
            print(f"- {p.name}")
        return

    if args.cmd == "list":
        status = args.status or None
        items = list_queue(status=status)
        if not items:
            print("(no items)")
            return
        for it in items:
            print(f"{it['id']}  {it['status']}  {it['action_type']}  booking={it['payload'].get('booking_code')}")
        return

    if args.cmd == "approve":
        set_status(args.approval_id, "approved")
        print("Approved.")
        return

    if args.cmd == "reject":
        set_status(args.approval_id, "rejected")
        print("Rejected.")
        return


if __name__ == "__main__":
    main()

