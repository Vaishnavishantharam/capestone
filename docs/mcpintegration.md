# `mcpintegration.md` — HITL Approval Center + MCP Actions (Pillar C)

This document defines how we consolidate all external side-effects into a single **Human-in-the-Loop (HITL)** approval flow.

---

## Principles

- No side-effects without explicit **Approve**
- Every action is logged with status (`pending/approved/rejected`)
- Payloads must include the **booking code** when triggered from booking
- Email drafts must include **Weekly Pulse market/sentiment context**

---

## Action types (minimum set)

1. **Calendar hold** (tentative)
   - Title format: `Advisor Q&A — {Topic} — {BookingCode}`
   - Includes slot time + IST

2. **Notes/Doc append**
   - Append one line/section to “Advisor Pre-Bookings”
   - Must include: date, topic, slot, booking code, pulse_id/top_theme

3. **Email draft (advisor)**
   - Subject: `Advisor Pre-Booking — {Topic} — {BookingCode}`
   - Body includes:
     - booking details
     - “Market/Customer sentiment context” snippet derived from latest pulse
   - No auto-send

---

## Approval Center behavior

- Shows a list of `pending` actions
- Each item displays:
  - action type
  - human-readable summary
  - payload preview
- Buttons:
  - Approve → executes and marks `approved`
  - Reject → marks `rejected` (no execution)

---

## State persistence requirements (proof of integration)

- Booking code must appear in:
  - calendar hold title
  - notes entry
  - email subject/body
  - approval queue logs

---

## Failure handling

- If an MCP action fails after approval:
  - mark status `failed` and surface error message
  - allow retry with a new approval

