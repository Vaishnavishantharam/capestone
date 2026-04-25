from __future__ import annotations

import json
from pathlib import Path

import core.rag.smartsync as smartsync
from core.rag.retrieve import load_schemes_json


def test_smartsync_combined_includes_6_bullets_and_citations(tmp_path: Path, monkeypatch) -> None:
    schemes_fixture = Path(__file__).resolve().parent / "fixtures" / "schemes_min.json"
    fee_fixture = Path(__file__).resolve().parent / "fixtures" / "fee_explainers_min.json"

    # Patch the fee explainers path to fixture.
    monkeypatch.setattr(smartsync, "FEE_EXPLAINERS_PATH", fee_fixture)

    # Patch schemes loader to use fixture by monkeypatching load_schemes_json default path.
    def _load_fixture():
        with schemes_fixture.open("r", encoding="utf-8") as f:
            return json.load(f)

    monkeypatch.setattr(smartsync, "load_schemes_json", lambda: _load_fixture())

    ans = smartsync.answer_question("Why was I charged exit load for large cap?")
    # 6 bullets
    assert ans.text.count("\n- ") == 6
    assert "Scheme source:" in ans.text
    assert "Fee source:" in ans.text
    assert "Last updated from sources:" in ans.text


def test_smartsync_refuses_advice_and_pii() -> None:
    a1 = smartsync.answer_question("Which fund is best for 20% returns?")
    assert "can’t provide investment advice" in a1.text.lower()

    a2 = smartsync.answer_question("My PAN is ABCDE1234F, help me")
    assert "personal information" in a2.text.lower()

