from __future__ import annotations

from pathlib import Path

from core.pulse.generate import build_weekly_pulse


def test_pulse_constraints_hold_on_sample() -> None:
    csv_path = Path(__file__).resolve().parents[2] / "data" / "reviews" / "sample_reviews.csv"
    bundle = build_weekly_pulse(product="INDMoney", reviews_csv_path=csv_path, weeks_back=10)

    assert len(bundle["themes"]) <= 5
    assert len(bundle["top_themes"]) == 3
    assert len(bundle["quotes"]) == 3
    assert bundle["word_count"] <= 250
    assert len(bundle["action_ideas"]) == 3

