from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.rag.retrieve import load_schemes_json, retrieve_top_k
from core.llm.gemini import generate_text


ROOT = Path(__file__).resolve().parents[2]
FEE_EXPLAINERS_PATH = ROOT / "data" / "state" / "fee_explainers.json"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


_ADVICE_RE = re.compile(r"\b(best|returns?|20%|guarantee|should i|invest|buy|sell|predict)\b", re.IGNORECASE)
_PII_RE = re.compile(r"\b(pan|aadhaar|otp|folio|account number|phone|email)\b", re.IGNORECASE)


@dataclass(frozen=True)
class SmartSyncAnswer:
    text: str
    scheme_citation: str | None
    fee_citation: str | None


def _load_fee_explainers(path: Path = FEE_EXPLAINERS_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _get_scenario(db: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    for s in db.get("scenarios", []):
        if s.get("scenario_id") == scenario_id:
            return s
    raise KeyError(f"Missing scenario_id={scenario_id} in {FEE_EXPLAINERS_PATH}")


def _pick_scheme_for_question(question: str, schemes_db: dict[str, Any]) -> dict[str, Any] | None:
    q = question.lower()
    schemes = schemes_db.get("schemes", [])
    if not schemes:
        return None

    # Simple keyword mapping first (works well for our 3-scheme corpus).
    keyword_map = [
        ("large cap", "large-cap"),
        ("flexi", "flexi-cap"),
        ("small cap", "small-cap"),
    ]
    for needle, slug in keyword_map:
        if needle in q:
            for s in schemes:
                if slug in str(s.get("scheme_name", "")).lower():
                    return s

    # Fallback: use evidence retrieval to infer best matching scheme via evidence row source_url.
    evidence = retrieve_top_k(question, k=1)
    if evidence:
        best_url = evidence[0].source_url
        for s in schemes:
            if s.get("source_url") == best_url:
                return s

    return schemes[0]


def _find_exit_load_evidence_text(schemes_db: dict[str, Any], *, scheme_name: str) -> str | None:
    for ev in schemes_db.get("evidence", []):
        if ev.get("field_name") == "exit_load" and ev.get("scheme_name") == scheme_name:
            return str(ev.get("evidence_text") or "").strip() or None
    return None


def _format_fee_bullets(template_bullets: list[str], *, exit_load_rule: str) -> str:
    filled = []
    for b in template_bullets[:6]:
        filled.append(b.replace("{exit_load_rule}", exit_load_rule))
    return "\n".join([f"- {b}" for b in filled])


def answer_question(question: str) -> SmartSyncAnswer:
    """
    Phase 3 Smart‑Sync (exit load only):
    - If combined question (exit load + why charged): scheme fact + 6-bullet fee explainer.
    - If fact-only: return scheme exit load evidence only.
    - Advice/PII: refuse.
    """
    if _PII_RE.search(question):
        msg = (
            "I can’t help with personal information or account-specific details. "
            "Please don’t share PAN/Aadhaar/OTP/phone/email here. "
            "I can answer factual scheme details like exit load with a source link.\n\n"
            f"Last updated from sources: {iso_now()}"
        )
        return SmartSyncAnswer(text=msg, scheme_citation=None, fee_citation=None)

    if _ADVICE_RE.search(question):
        msg = (
            "I can’t provide investment advice or predict returns. "
            "I can share factual scheme details (exit load, expense ratio, minimum SIP) with source links.\n\n"
            f"Last updated from sources: {iso_now()}"
        )
        return SmartSyncAnswer(text=msg, scheme_citation=None, fee_citation=None)

    schemes_db = load_schemes_json()
    scheme = _pick_scheme_for_question(question, schemes_db)
    if not scheme:
        msg = f"I couldn’t find scheme data in the current sources.\n\nLast updated from sources: {iso_now()}"
        return SmartSyncAnswer(text=msg, scheme_citation=None, fee_citation=None)

    scheme_name = str(scheme.get("scheme_name"))
    scheme_url = str(scheme.get("source_url"))

    # Evidence-backed scheme fact snippet.
    exit_load_evidence = _find_exit_load_evidence_text(schemes_db, scheme_name=scheme_name)
    exit_load_value = str(scheme.get("exit_load") or "not found in sources")
    scheme_fact_line = exit_load_evidence or f"Exit Load | {exit_load_value}"

    wants_why = bool(re.search(r"\b(why|charged|charge|deducted)\b", question, re.IGNORECASE))
    wants_exit_load = "exit load" in question.lower() or "exitload" in question.lower()

    if wants_exit_load and wants_why:
        fee_db = _load_fee_explainers()
        scenario = _get_scenario(fee_db, "exit_load_charged")
        fee_url = str((scenario.get("source_links") or [None])[0])
        bullets = _format_fee_bullets(scenario.get("bullets", []), exit_load_rule=exit_load_value)

        text = (
            f"{scheme_fact_line}\n\n"
            f"{bullets}\n\n"
            f"Scheme source: {scheme_url}\n"
            f"Fee source: {fee_url}\n"
            f"Last updated from sources: {iso_now()}"
        )
        return SmartSyncAnswer(text=text, scheme_citation=scheme_url, fee_citation=fee_url)

    # Fact-only response (exit load).
    text = f"{scheme_fact_line}\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
    return SmartSyncAnswer(text=text, scheme_citation=scheme_url, fee_citation=None)


def answer_question_gemini(question: str) -> SmartSyncAnswer:
    """
    Gemini rewrite mode:
    - First compute the deterministic, grounded answer (with citations).
    - Then ask Gemini to rewrite ONLY the explanation content (no new facts),
      while we keep citations and timestamp from the deterministic output.
    """
    base = answer_question(question)
    # If refusal or missing citations, just return base.
    if "Scheme source:" not in base.text and "Source:" not in base.text:
        return base

    # Separate body from citation/timestamp footer.
    lines = base.text.splitlines()
    footer_idx = None
    for i, ln in enumerate(lines):
        if ln.startswith("Scheme source:") or ln.startswith("Source:"):
            footer_idx = i
            break
    if footer_idx is None:
        return base

    body = "\n".join(lines[:footer_idx]).strip()
    footer = "\n".join(lines[footer_idx:]).strip()

    prompt = f"""
You are rewriting a compliance-sensitive fintech support answer.

Rules:
- Do NOT add any new facts or numbers.
- Do NOT remove any of the existing bullet points; keep exactly the same count.
- Keep it facts-only, neutral tone.
- Return ONLY the rewritten body text (no citations, no timestamps).

Original body:
{body}
""".strip()

    rewritten = generate_text(prompt)
    if not rewritten:
        return base

    merged = f"{rewritten.strip()}\n\n{footer}"
    return SmartSyncAnswer(text=merged, scheme_citation=base.scheme_citation, fee_citation=base.fee_citation)

