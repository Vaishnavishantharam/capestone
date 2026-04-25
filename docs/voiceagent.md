# `voiceagent.md` — Booking Agent (Voice + Chat fallback) (Pillars B/C: M3)

This document specifies the advisor pre‑booking agent that runs in **voice mode** with a **chat fallback**.

---

## Goals

- Collect **topic** + **time preference** (IST)
- Offer **two slots**
- Confirm the slot
- Generate a **booking code**
- Produce MCP action proposals (calendar hold + notes append + email draft) into the HITL Approval Center

---

## Non-goals / constraints

- No investment advice (refuse)
- No PII collection on the call/chat (refuse; ask user to use secure link later)
- Always repeat **date/time + timezone (IST)** on confirmation

---

## Supported intents (minimum 5)

- `book_new`
- `reschedule`
- `cancel`
- `what_to_prepare`
- `check_availability_windows`

---

## Topics (controlled list)

- KYC / Onboarding
- SIP / Mandates
- Statements / Tax Docs
- Withdrawals & Timelines
- Account Changes / Nominee

---

## Conversation flow (canonical)

1. **Greet + disclaimer** (informational only; no advice; no PII)
2. **Theme-aware mention** (if Weekly Pulse exists): mention the top theme once
3. **Confirm topic** (must map to controlled list)
4. **Collect day/time window** (IST)
5. **Offer two slots** (from mock availability)
6. **Confirm**: repeat topic + exact slot + IST
7. **Generate booking code** (e.g., `IN-A742`)
8. **Provide secure link** (placeholder) to finish contact details outside the agent
9. **Create HITL actions** (pending approval):
   - Calendar hold
   - Notes/Doc append
   - Advisor email draft (includes pulse context snippet)

---

## Voice ↔ Chat fallback rules

### Start conditions

- User chooses “Start voice booking”, OR asks to schedule and chooses voice.

### Fallback triggers

- Voice cannot start (device/permission/network) → auto switch to chat
- Repeated transcription failures → offer “Switch to typing”
- User preference → immediate switch

### Contract

- The booking state must be **shared** between voice and chat.
- Switching modes must not reset captured slots (topic/time).

---

## Output artifacts

On successful booking:

- `Booking Artifact` persisted in `data/state/bookings/`
- 3 approval items created in `data/state/approvals/` (pending)

See `docs/mcpintegration.md` for payload formats.

