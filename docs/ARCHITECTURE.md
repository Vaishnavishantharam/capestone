# Investor Ops & Intelligence Suite (INDMoney) — Architecture

This capstone integrates three milestones into **one product operations ecosystem**:

- **Pillar A — Smart‑Sync Knowledge Base (M1 + M2)**: Unified Search that combines **scheme facts** + **fee logic** in one answer.
- **Pillar B — Insight‑Driven Agent Optimization (M2 + M3)**: Weekly Product Pulse briefs a **theme‑aware** booking agent (voice + chat fallback).
- **Pillar C — Super‑Agent MCP Workflow (M2 + M3)**: One **Human‑in‑the‑Loop (HITL) Approval Center** for Calendar/Notes/Email actions; advisor email includes **market/customer sentiment context** from the pulse.

This document is the **single source of truth** for repo layout, data flows, and phase plan.

---

## Product choice (global constraint)

- **Product**: INDMoney
- **Scope**: Mutual fund scheme facts focus on **HDFC schemes** using the same “5 approved scheme URLs” pattern from your M1 repo.
- **Consistency rule**: All sources, review themes, fee explainers, UI copy, and demos reference **INDMoney** only.

### Reference repos (what we are reusing)

This capstone **reuses architecture patterns and constraints** from your existing milestone repos:

- **M1 RAG (phase-based)**: `Vaishnavishantharam/Bot-Mutualfund`
  - phase folders: `phase_1/ … phase_6/`, shared `data/`
  - strict rules: facts-only, ≤3 sentences, exactly one citation link, “Last updated from sources: …”
  - plan doc: `ARCHITECTURE_AND_PLAN.md`
- **M2 Weekly Pulse (phase-based)**: `Vaishnavishantharam/indmoney_reviewbot`
  - phase folders: `phase1/ …` and “one-pager” weekly pulse
  - reviews stored as `.json` + `.csv`
  - MCP append-to-doc guidance: `phase4/MCP_GOOGLE_DOC.md`
- **M3 Voice agent (modular Python app)**: `Vaishnavishantharam/voiceagent`
  - multi-mode runs: HTTP + web UI, text CLI, voice CLI
  - structured docs: `architecture.md`, `architecture-low-level.md`
  - ops docs: `ops/DEPLOY.md`, `ops/RUNBOOK.md`, `ops/MANUAL_VERIFICATION.md`

**Important note**: this capstone stays **INDMoney-scoped** (same as your milestone repos) to maximize reuse and keep the corpus consistent.

---

## Single entry point

We provide a **single UI** (“Ops Dashboard”) where users can:

- Ask Smart‑Sync Q&A (facts + fee logic).
- Generate Weekly Pulse (internal).
- Book an advisor slot via **Voice** with **Chat fallback**.
- Review/approve MCP actions in an Approval Center.
- Run the Evaluation Suite and export results.

Recommended implementation choice (for later phases): **Streamlit** (simple dashboard + forms + tabs).  
Alternate: Gradio (better multimodal widgets).  
The rest of this architecture is UI‑framework agnostic.

---

## Primary personas

- **External user (Customer)**: asks factual questions; optionally books an advisor call.
- **Internal user (Ops/PM/Support/Compliance)**: uploads review CSV, generates Weekly Pulse, approves MCP actions, audits evals.
- **Advisor**: receives an email draft with booking details + sentiment context.

---

## System boundaries (what we do / don’t do)

- **Facts‑only** for mutual fund scheme details.
- **No investment advice** (no “best fund”, no return promises, no predictions).
- **No PII** accepted or stored (no phone, email, PAN, Aadhaar, account/folio, OTP).
- **HITL gating**: calendar/notes/email actions are prepared but **must be approved**.

Authoritative behavior rules live in `docs/rules.md`.

---

## Repository layout (target)

We will **preserve the “phase-wise build discipline”** you used in M1/M2, while still shipping a single integrated app:

- `core/*` holds stable “product modules” (retrieval, pulse, voice, MCP, storage, safety).
- `scripts/` holds phase-wise pipelines (ingest → index → pulse → booking → evals) similar to `phase_*/` folders.
- `docs/` mirrors your previous “architecture + low-level” documentation style.

```
capestone/
  app/                         # single dashboard entry point (later phase)
  core/
    rag/                        # retrieval + grounded answering
    pulse/                      # theme clustering + weekly pulse
    voice/                      # booking dialog manager (voice + chat fallback)
    mcp/                        # action planning + approval gating
    storage/                    # persistence adapters (local JSON/SQLite)
    safety/                     # refusal + PII redaction utilities
  data/
    knowledge/                  # curated official URLs + scraped chunks (M1)
    reviews/                    # review CSVs (M2)
    state/                      # persisted app state: pulse summaries, bookings, approvals
  evals/
    golden_questions.jsonl      # 5 complex Qs (M1+M2)
    adversarial_prompts.jsonl   # 3 safety tests
    ux_checks.json              # tone/structure checks
  docs/
    ARCHITECTURE.md             # (this file)
    rag.md
    themeclassification.md
    voiceagent.md
    mcpintegration.md
    rules.md
    edgecase.md
    evals.md
  scripts/
  README.md
```

This layout ensures each subsystem can be developed and tested independently.

---

## Data & state persistence (how the pillars connect)

### Shared state objects

1. **Weekly Pulse Artifact**
   - `pulse_id`
   - `generated_at`
   - `themes` (max 5)
   - `top_themes` (top 3)
   - `quotes` (3, PII‑redacted)
   - `action_ideas` (exactly 3)
   - `word_count` (must be ≤ 250)

2. **Booking Artifact**
   - `booking_code` (e.g., `GR-A742`)
   - `topic` (controlled list)
   - `slot_start`, `slot_end`, `timezone` (IST)
   - `input_mode` (`voice` or `chat`)
   - `pulse_id` (links booking to latest pulse for context)
   - `created_at`

3. **Approval Queue Item**
   - `action_type` (`calendar_hold` | `append_notes` | `email_draft`)
   - `payload`
   - `status` (`pending` | `approved` | `rejected`)
   - `created_at`, `reviewed_at`, `reviewer`

### Persistence requirement

- **State persistence**: the **booking code must be visible** in the Notes/Doc entry (and in the approval center payload) to prove systems are connected.

We can persist locally (JSON/SQLite) for the prototype; MCP integrations are invoked only after approval.

---

## Pillar A — Smart‑Sync Knowledge Base (M1 + M2)

### Goal

Answer combined questions like:

> “What is the exit load for the ELSS fund and why was I charged it?”

by retrieving:

- **M1**: the scheme’s factual clause (exit load % + conditions) from official corpus
- **M2**: the standardized fee explainer logic (≤6 bullets) for “why this fee appears”

### Output constraints

- **Facts‑only**
- **Source citation** (see `docs/rules.md` for exact citation rules when combining two sources)
- **6‑bullet structure** for the fee logic section
- Include **Last updated/checked timestamp**
- Refuse advice / PII

Implementation details live in `docs/rag.md`.

---

## Pillar B — Insight‑Driven Agent Optimization (M2 + M3)

### Weekly Pulse pipeline (internal)

Input: review CSV (last 8–12 weeks)

Outputs (must pass rubric):

- group reviews into **≤5 themes**
- identify **top 3 themes**
- extract **3 real user quotes** (with PII masked)
- generate a weekly note **≤250 words**
- add **exactly 3 action ideas**

### Theme‑aware booking agent

The booking agent (voice + chat fallback) uses the latest `Weekly Pulse Artifact`:

- On greeting, it proactively mentions the **top theme**:
  - e.g., “Many users are asking about nominee updates this week…”

Implementation details live in `docs/themeclassification.md` and `docs/voiceagent.md`.

---

## Pillar C — Human‑in‑the‑Loop MCP Approval Center (M2 + M3)

### Trigger

After booking confirmation (via voice or chat):

- generate booking code
- prepare (do not execute) 3 MCP actions:
  1. Calendar tentative hold
  2. Notes/Doc append (includes booking code + pulse_id/top_theme)
  3. Email draft to advisor

### Twist: advisor email includes context from pulse

Email draft must include:

- booking details
- a short **market/customer sentiment context** snippet derived from Weekly Pulse (top themes + what users are struggling with)

### Approval gating

All actions go into a single Approval Center:

- `Approve` → action executes
- `Reject` → action is discarded (but logged)

Implementation details live in `docs/mcpintegration.md`.

---

## Voice + chat fallback (booking UX)

### When voice is used

Voice starts only when the user:

- clicks “Start voice booking”, or
- asks to schedule and chooses voice.

### Fallback rules

- If voice fails to start → switch to chat input immediately.
- If transcription fails repeatedly → offer “Switch to typing”.
- If PII is provided → refuse storing it and continue booking with non‑PII prompts.

Dialog details and intents live in `docs/voiceagent.md` and edge cases in `docs/edgecase.md`.

---

## Evaluation Suite (required proof, not guesses)

We must run and document at least 3 eval types:

1. **Retrieval accuracy (RAG eval)**  
   - golden dataset of **5 complex questions** mixing M1 facts + M2 fee scenarios  
   - metrics: **Faithfulness** (grounded only in retrieved sources) and **Relevance** (answers the scenario)

2. **Constraint adherence (Safety eval)**  
   - 3 adversarial prompts (advice/PII)  
   - metric: Pass/Fail — must refuse **100%**

3. **Tone & structure (UX eval)**  
   - Weekly Pulse rubric checks: ≤250 words + exactly 3 action ideas  
   - Voice agent check: greeting mentions top theme from latest pulse

Evaluation artifacts and reporting format live in `docs/evals.md`.

---

## Phase plan (build order)

### Phase 0 — Docs + skeleton (you are here)

- Write architecture + subsystem docs in `docs/`
- Define “source manifest” format and required deliverables

### Phase 1 — Smart‑Sync (M1+M2)

- ingest/curate INDMoney + HDFC scheme sources (5 approved scheme URLs) for scheme facts
- implement unified retrieval + answer composer (facts + fee bullets + citations)

### Phase 2 — Weekly Pulse + theme extraction (M2)

- implement theme clustering + weekly note generation
- persist pulse artifact

### Phase 3 — Booking agent (M3) with theme awareness

- implement booking dialog manager with voice + chat modes
- booking persists code and links to pulse artifact

### Phase 4 — HITL Approval Center + MCP action planning

- queue actions and execute only on approval
- ensure advisor email includes pulse context snippet

### Phase 5 — Evaluation suite + report export

- golden dataset + adversarial prompts + UX checks
- generate `docs/evals.md` report

---

## Deliverables mapping

- **GitHub repo**: this monorepo
- **Ops Dashboard demo video (5 min)** shows:
  - review CSV → Weekly Pulse
  - voice booking uses pulse theme + booking code
  - Smart‑Sync Q&A answers combined question (facts + fee logic) with citations
- **Evals report**: `docs/evals.md`
- **Source manifest**: combined list of **30+ official URLs** (format defined in `docs/rules.md`)

