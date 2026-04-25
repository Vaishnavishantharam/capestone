from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMES_PATH = ROOT / "data" / "schemes.json"


@dataclass(frozen=True)
class RetrievedEvidence:
    chunk_id: str
    source_url: str
    text: str
    score: float


def load_schemes_json(path: Path = SCHEMES_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

_WORD_RE = re.compile(r"[A-Za-z0-9%]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text)]


def _build_idf(docs: list[list[str]]) -> dict[str, float]:
    n = len(docs)
    df: dict[str, int] = {}
    for toks in docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    # Smooth IDF.
    return {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}


def _tf_idf_dot(q: list[str], d: list[str], idf: dict[str, float]) -> float:
    if not q or not d:
        return 0.0
    q_tf: dict[str, int] = {}
    for t in q:
        q_tf[t] = q_tf.get(t, 0) + 1
    d_tf: dict[str, int] = {}
    for t in d:
        d_tf[t] = d_tf.get(t, 0) + 1

    score = 0.0
    for t, q_count in q_tf.items():
        if t in d_tf:
            w = idf.get(t, 1.0)
            score += (q_count * w) * (d_tf[t] * w)
    return score


def retrieve_top_k(question: str, *, k: int = 4, schemes_path: Path = SCHEMES_PATH) -> list[RetrievedEvidence]:
    db = load_schemes_json(schemes_path)
    chunks = db.get("evidence_chunks", [])
    if not chunks:
        return []

    tokenized_docs = [_tokenize(c["text"]) for c in chunks]
    idf = _build_idf(tokenized_docs)
    q_toks = _tokenize(question)

    scored = [(idx, _tf_idf_dot(q_toks, d_toks, idf)) for idx, d_toks in enumerate(tokenized_docs)]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:k]

    out: list[RetrievedEvidence] = []
    for idx, score in top:
        c = chunks[int(idx)]
        out.append(
            RetrievedEvidence(
                chunk_id=c["chunk_id"],
                source_url=c["source_url"],
                text=c["text"],
                score=float(score),
            )
        )
    return out

