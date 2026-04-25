from __future__ import annotations

from pathlib import Path

from core.rag.retrieve import retrieve_top_k


def test_retrieve_top_k_returns_citation_url() -> None:
    schemes_path = Path(__file__).resolve().parent / "fixtures" / "schemes_min.json"
    out = retrieve_top_k("exit load", k=1, schemes_path=schemes_path)
    assert len(out) == 1
    assert out[0].source_url.startswith("https://")
    assert "exit load" in out[0].text.lower()

