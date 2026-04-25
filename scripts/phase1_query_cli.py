from __future__ import annotations

import argparse
from datetime import datetime, timezone

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.rag.retrieve import retrieve_top_k  # noqa: E402


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 1: query schemes.json via local retrieval")
    ap.add_argument("question", type=str, help="User question")
    ap.add_argument("--k", type=int, default=4, help="Top-k evidence chunks")
    args = ap.parse_args()

    evidence = retrieve_top_k(args.question, k=args.k)
    if not evidence:
        raise SystemExit("No evidence found. Run scripts/phase1_ingest_schemes.py first.")

    # Minimal “facts-only” output: show the best evidence chunk and its source URL.
    best = evidence[0]
    print("Answer (evidence-backed snippet):")
    print(best.text[:900].strip())
    print()
    print(f"Source: {best.source_url}")
    print(f"Last updated from sources: {iso_now()}")


if __name__ == "__main__":
    main()

