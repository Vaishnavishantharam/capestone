from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.pulse.generate import build_weekly_pulse, write_pulse_bundle


def _latest_reviews_csv(data_reviews_dir: Path) -> Path | None:
    candidates = sorted(data_reviews_dir.glob("reviews_*.csv"))
    return candidates[-1] if candidates else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 2: Generate Weekly Product Pulse from reviews CSV")
    ap.add_argument(
        "--csv",
        type=str,
        default="",
        help="Path to reviews CSV. If omitted, uses latest data/reviews/reviews_*.csv, else sample_reviews.csv",
    )
    ap.add_argument("--weeks-back", type=int, default=10, help="Weeks back (label only for local CSV)")
    ap.add_argument("--product", type=str, default="INDMoney", help="Product name")
    args = ap.parse_args()

    data_reviews_dir = (ROOT / "data" / "reviews").resolve()
    if args.csv:
        csv_path = Path(args.csv).resolve()
    else:
        csv_path = _latest_reviews_csv(data_reviews_dir) or (data_reviews_dir / "sample_reviews.csv")

    bundle = build_weekly_pulse(product=args.product, reviews_csv_path=csv_path, weeks_back=args.weeks_back)
    out_path = write_pulse_bundle(bundle, Path("data/state/pulses"))

    print(f"Wrote pulse bundle: {out_path}")
    print(f"Input reviews CSV: {csv_path}")
    print(f"Top themes: {bundle['top_themes']}")
    print(f"Word count: {bundle['word_count']} (must be <= 250)")
    print(f"Action ideas: {len(bundle['action_ideas'])} (must be exactly 3)")


if __name__ == "__main__":
    main()

