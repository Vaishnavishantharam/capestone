# `edgecase.md` — Edge Cases & Guardrails

This document enumerates high-priority edge cases across the unified system.

---

## Smart‑Sync Q&A edge cases

- **Advice-seeking**: “best fund / 20% returns / should I invest” → refuse (see `docs/rules.md`)
- **Account-specific fee dispute**: explain general logic only; refuse to ingest PII; suggest non-PII checks
- **No evidence found**: say not in sources; cite closest official page; do not guess
- **Conflicting sources**: prefer more authoritative/latest; note discrepancy; cite per `rules.md`

---

## Weekly Pulse edge cases

- **Too few reviews**: reduce themes; still output top themes + quotes if available
- **Duplicate/spam reviews**: de-duplicate before clustering
- **PII in review text**: redact before quoting; never leak
- **Word count overflow**: hard-trim to ≤250 words while preserving required elements

---

## Booking agent (voice + chat) edge cases

- **Voice unavailable**: immediate chat fallback with preserved state
- **Repeated ASR failures**: ask to switch to typing; do not loop endlessly
- **User gives PII**: refuse and proceed with topic/time only
- **No slots match**: create a waitlist item + draft email (approval-gated)
- **Timezone ambiguity**: always confirm IST and repeat final time

---

## HITL Approval edge cases

- **User rejects action**: mark rejected; do not execute; keep audit record
- **Execution failure after approval**: mark failed; allow retry with new approval
- **Partial approvals**: allow approving calendar but rejecting email, etc.

