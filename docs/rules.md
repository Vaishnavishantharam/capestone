# `rules.md` — Safety, Structure, Citations (Global)

This document defines non-negotiable system rules across all pillars.

---

## Safety rules (must refuse 100% of the time)

- **Investment advice**: refuse questions like:
  - “Which fund is best?”
  - “Can I get 20% returns?”
  - “Should I buy/sell now?”
- **PII**: refuse and do not store:
  - phone, email, PAN, Aadhaar, account/folio, OTP, addresses, names of real users

Use `[REDACTED]` for any simulated personal fields.

---

## Response length rules

- Smart‑Sync Q&A: concise; avoid long essays (target: ≤3 short paragraphs or equivalent bullets)
- Weekly Pulse: **≤250 words**
- Fee Explainer: **≤6 bullets**

---

## Citation rules

### Smart‑Sync (combined M1+M2)

We allow **two citations only when the answer truly combines two evidence sources**:

- **1 scheme source** (M1) for the scheme fact(s)
- **1 fee/charges source** (M2) for the fee logic

If the question is scheme-facts-only, show **exactly one** scheme citation.  
If the question is fee-logic-only, show **exactly one** fee/charges citation.

### Weekly Pulse

- Internal artifact; citations optional unless you quote an official policy page.

### Voice booking

- No citations required; this is scheduling. Any educational link offered must be official.

---

## Timestamps

- Smart‑Sync answers must include: `Last updated from sources: <ISO timestamp>`
- Fee Explainer must include: `Last checked: <ISO timestamp>`
- Weekly Pulse artifact must include: `generated_at: <ISO timestamp>`

---

## Booking code format

- Pattern: `IN-[A-Z0-9]{4}` (example: `IN-A742`)
- Must be displayed to the user and persisted in state and HITL payloads.

