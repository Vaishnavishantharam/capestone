# Phase 4 — Booking Agent (Theme-aware) (M3)

Phase 4 adds a booking agent (text-first, voice optional later) that:

- reads the latest Weekly Pulse (`data/state/pulses/pulse_*.json`)
- mentions the **top theme** in the greeting (theme-aware requirement)
- collects topic + time preference (no PII)
- offers **two slots** (mock calendar)
- confirms and generates a booking code like `IN-A742`
- persists a booking artifact to `data/state/bookings/`

## Run (text booking demo)

```bash
source .venv/bin/activate
python phase_4/run_booking_cli.py --topic "Nominee update" --slot 1
```

