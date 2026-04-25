# Phase 5 — HITL Approval Center (Mock MCP)

No Google auth or real external actions. Phase 5 generates **mock** artifacts and stores them locally with approval gating.

## What it does

From the latest booking in `data/state/bookings/booking_*.json`, it generates 3 pending actions:

1. `calendar_hold` (mock payload)
2. `append_notes` (mock doc line, includes booking code)
3. `email_draft` (mock email, includes Weekly Pulse market/sentiment context snippet)

Each action must be **approved** or **rejected**.

## Run

```bash
source .venv/bin/activate
python phase_5/run_hitl_cli.py create
python phase_5/run_hitl_cli.py list --status pending
python phase_5/run_hitl_cli.py approve <approval_id>
```

## Data locations

- Queue: `data/state/approvals/approval_*.json`
- Mock execution log: `data/state/outbox/*.json`

