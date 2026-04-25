from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.rag.smartsync import answer_question  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 3: Smart-Sync (exit load + fee logic)")
    ap.add_argument("question", type=str, help="User question")
    args = ap.parse_args()

    ans = answer_question(args.question)
    print(ans.text)


if __name__ == "__main__":
    main()

