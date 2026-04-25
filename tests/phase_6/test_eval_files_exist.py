from __future__ import annotations

from pathlib import Path


def test_eval_datasets_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "evals" / "golden_questions.jsonl").exists()
    assert (root / "evals" / "adversarial_prompts.jsonl").exists()
    assert (root / "evals" / "ux_checks.json").exists()

