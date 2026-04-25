# Phase 3 — Smart‑Sync (Exit Load + “Why charged?”)

Phase 3 composes a **combined** answer that merges:

- **Scheme fact** (from `data/schemes.json`) — e.g. `Exit Load | 1.0%`
- **Fee logic explainer** (6 bullets) from `data/state/fee_explainers.json`

It enforces facts-only + citations + timestamp rules from `docs/rules.md`.

## Run

```bash
source .venv/bin/activate
python phase_3/run_smartsync.py "What is the exit load for HDFC Flexi Cap and why was I charged it?"
```

