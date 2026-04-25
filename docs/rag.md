# `rag.md` — Smart‑Sync RAG (Pillar A: M1 + M2)

This document specifies how the unified system answers **combined** questions using:

- **M1 (scheme facts)**: grounded in official scheme sources (factsheets / scheme pages / product help pages).
- **M2 (fee explainer logic)**: a structured “why you were charged” explainer (≤6 bullets) grounded in official fee/charges sources.

---

## Inputs

- **User question** (text) from the dashboard.
- **Knowledge base**:
  - `data/schemes.json` (Bot‑Mutualfund schema: `meta`, `schemes`, `evidence`)
  - `data/state/fee_explainers.json` (approved explainer scenarios + official links)

---

## Output contract (must always hold)

- **Facts-only**. No recommendations, comparisons, or return predictions.
- **Combined answer** must contain:
  - **Scheme fact snippet(s)** (e.g., exit load %, lock-in)
  - **Fee logic explainer** in **≤6 bullets**
  - **Citations** (see `docs/rules.md` for exact formatting rules)
  - **Last updated from sources: `<ISO timestamp>`**
- **Refusals**:
  - advice prompts → refuse + offer factual alternatives
  - PII prompts → refuse + remind “don’t share”

---

## Retrieval plan

### Step 1 — Query intent classification (lightweight)

Classify the user question into one of:

- `scheme_fact_only`
- `fee_logic_only`
- `combined_fact_plus_fee` (Smart‑Sync)
- `out_of_scope` (advice/PII/returns)

### Step 2 — Retrieve M1 evidence (scheme facts)

- Retrieve top‑k **evidence rows** from `data/schemes.json` relevant to the asked attribute(s):
  - exit load, expense ratio, min SIP, lock-in (ELSS), riskometer, benchmark, etc.
- Choose the **best single source URL** when possible (per milestone constraints) OR apply the combined-citation rule defined in `docs/rules.md`.

### Step 3 — Retrieve M2 fee explainer evidence

- Select the matching fee scenario (e.g., **Exit load charged**).
- Retrieve:
  - explainer template (≤6 bullets)
  - its official fee/charges links

---

## Answer composition (Smart‑Sync)

When `combined_fact_plus_fee`:

1. Extract the scheme fact(s) (exact numeric values / conditions) from M1 evidence.
2. Fill the fee explainer bullets with the relevant context.
   - **Phase 3 implementation note**: we use a deterministic 6‑bullet template (no LLM) and inject the retrieved exit‑load rule (e.g. `1.0%`) into `{exit_load_rule}`.
3. Enforce:
   - bullet count ≤ 6
   - no advice language (“should”, “best”, “invest”)
   - refusal if user asks for returns or “best fund”
4. Attach citations + timestamp.

---

## Failure modes (and required behavior)

- **No matching scheme evidence**: say “not found in current sources” + cite closest official source.
- **Conflicting values**: prefer most recent/authoritative doc; mention discrepancy and cite both if allowed by `rules.md`.
- **User asks account-specific “why was I charged”**: explain general logic only; ask user *not* to share PII; suggest checking transaction date vs redemption date.

---

## Test cases (used in evals)

These map to `evals/golden_questions.jsonl`:

- Combined: “exit load for ELSS + why charged”
- Combined: “lock-in + fee/charge scenario”
- Combined: “minimum SIP + fee reasoning”

Evaluation format and metrics are defined in `docs/evals.md`.

