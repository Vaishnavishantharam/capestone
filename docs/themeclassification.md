# `themeclassification.md` — Weekly Pulse + Themes (Pillar B: M2)

This document defines the review → themes → weekly pulse workflow used to:

1) generate an internal **Weekly Product Pulse**, and  
2) brief the booking agent so it becomes **theme-aware**.

---

## Inputs

- **Reviews CSV** (last 8–12 weeks) stored in `data/reviews/`
- Optional: cached reviews JSON (same schema)

No PII is allowed in inputs or outputs. Any names/emails/phones must be masked to `[REDACTED]`.

---

## Outputs (Weekly Pulse Artifact)

Persist to `data/state/pulses/` as a structured artifact:

- `pulse_id`
- `generated_at` (ISO)
- `themes` (max 5, each with a short definition)
- `top_themes` (top 3)
- `quotes` (exactly 3; PII-redacted)
- `weekly_note` (≤250 words)
- `action_ideas` (exactly 3)

---

## Theme generation requirements

- **Max themes**: 5
- **Top themes**: 3
- Themes must be **human-readable** labels (e.g., “Login issues”, “Nominee updates”).
- Quotes must be **verbatim** snippets from reviews (with redactions).

---

## Weekly Pulse generation rubric (must pass)

- Word count: **≤ 250**
- Includes:
  - Top 3 themes
  - 3 quotes
  - Exactly 3 action ideas
- Neutral internal tone; no exaggeration; no PII.

---

## Integration: briefing the booking agent

The booking agent reads the latest pulse artifact:

- `top_theme = top_themes[0]`

Greeting rule:

- If a pulse exists: mention `top_theme` once in the greeting (one sentence).
- If no pulse exists: skip theme mention.

This behavior is verified in UX evals (see `docs/evals.md`).

---

## Edge cases

- **Too few reviews**: still produce pulse but mark confidence low and reduce themes.
- **Highly mixed themes**: still cap at 5 themes; keep definitions short.
- **PII in review text**: redact before any quoting.

Full edge cases list lives in `docs/edgecase.md`.

