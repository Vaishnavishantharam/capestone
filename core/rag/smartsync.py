from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.rag.retrieve import load_schemes_json, retrieve_top_k
from core.llm.gemini import generate_text
from core.pulse.load import load_latest_pulse


ROOT = Path(__file__).resolve().parents[2]
FEE_EXPLAINERS_PATH = ROOT / "data" / "state" / "fee_explainers.json"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


_ADVICE_RE = re.compile(r"\b(best|returns?|20%|guarantee|should i|invest|buy|sell|predict)\b", re.IGNORECASE)
_PII_RE = re.compile(r"\b(pan|aadhaar|otp|folio|account number|phone|email)\b", re.IGNORECASE)
_SIP_DEF_RE = re.compile(r"^\s*(what is|define|meaning of)\s+(a\s+)?sip\s*\??\s*$", re.IGNORECASE)
# "Why am I seeing this?" follow-up detector (typo-tolerant).
# Covers: seeing / seeng, "showing", "do I see", etc.
_WHY_SEE_RE = re.compile(
    r"\b("
    r"why\s+am\s+i\s+see(?:ing|ng)\s+this"
    r"|why\s+do\s+i\s+see\s+this"
    r"|why\s+is\s+this\s+show(?:ing|n)"
    r"|why\s+am\s+i\s+seeing"
    r")\b",
    re.IGNORECASE,
)
_WHY_GENERIC_RE = re.compile(r"^\s*why\s+am\s+i\s+see(?:ing|ng)\s+(it|this)\s*\??\s*$", re.IGNORECASE)

# Education / definitions: keep a single approved official link for concepts.
_AMFI_SIP_URL = "https://www.amfiindia.com/investor-corner/systematic-investment-plan"


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

    # Simple keyword mapping first (works well for our small curated corpus).
    # Prefer matching on category when present, otherwise scheme_name.
    keyword_map = [
        ("large cap", ["large cap"]),
        ("flexi", ["flexi cap", "flexi"]),
        ("small cap", ["small cap"]),
        ("mid cap", ["mid cap"]),
        ("nifty 100", ["nifty 100", "index"]),
        ("index", ["index"]),
    ]
    for needle, variants in keyword_map:
        if needle in q:
            for s in schemes:
                cat = str(s.get("category") or "").lower()
                name = str(s.get("scheme_name") or "").lower()
                if any(v in cat for v in variants) or any(v in name for v in variants):
                    return s

    # Fallback: use evidence retrieval to infer best matching scheme via evidence row source_url.
    evidence = retrieve_top_k(question, k=1)
    if evidence:
        best_url = evidence[0].source_url
        for s in schemes:
            if s.get("source_url") == best_url:
                return s

    return schemes[0]


def _find_evidence_text(schemes_db: dict[str, Any], *, scheme_name: str, field_name: str) -> str | None:
    for ev in schemes_db.get("evidence", []):
        if ev.get("field_name") == field_name and ev.get("scheme_name") == scheme_name:
            return str(ev.get("evidence_text") or "").strip() or None
    return None


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


def _format_generic_bullets(template_bullets: list[str], replacements: dict[str, str]) -> str:
    filled: list[str] = []
    for b in template_bullets[:6]:
        out = b
        for k, v in replacements.items():
            out = out.replace("{" + k + "}", v)
        filled.append(out)
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

    # Concept definition (not scheme-specific).
    if _SIP_DEF_RE.search(question.strip()):
        msg = (
            "SIP (Systematic Investment Plan) is a way to invest a fixed amount at regular intervals into a mutual fund scheme. "
            "It’s a contribution method; the scheme’s terms (like minimum SIP amount) depend on the specific scheme.\n\n"
            f"Source: {_AMFI_SIP_URL}\n"
            f"Last updated from sources: {iso_now()}"
        )
        return SmartSyncAnswer(text=msg, scheme_citation=_AMFI_SIP_URL, fee_citation=None)

    schemes_db = load_schemes_json()
    schemes = schemes_db.get("schemes", []) or []

    def _pulse_context_snippet() -> str:
        pulse = load_latest_pulse()
        if not pulse:
            return "Weekly Pulse context: (not available yet — run Phase 2 to generate a pulse artifact.)"
        top = pulse.get("top_themes") or pulse.get("topThemes") or []
        top_theme = top[0] if isinstance(top, list) and top else None
        pulse_id = pulse.get("pulse_id") or pulse.get("pulseId") or "latest"
        if top_theme:
            return f"Weekly Pulse context (internal): pulse_id={pulse_id}; top_theme={top_theme}"
        return f"Weekly Pulse context (internal): pulse_id={pulse_id}"

    # If the user asks a generic "why am I seeing it/this?" without a scheme fact,
    # give a safe clarification and keep scope tight (HDFC scheme facts only).
    if _WHY_GENERIC_RE.search(question):
        known = ", ".join([str(s.get("scheme_name")) for s in schemes[:6]]) if schemes else "HDFC schemes"
        msg = (
            "I can explain why you’re seeing a *specific* scheme detail (like exit load, minimum SIP, expense ratio, lock-in, benchmark, AUM, inception date, risk) — "
            "but I need the scheme + which detail you’re looking at.\n\n"
            "Try: “exit load for HDFC Small Cap — why am I seeing this?”\n"
            "Or: “minimum SIP for HDFC Large Cap — why am I seeing this?”\n\n"
            f"{_pulse_context_snippet()}\n\n"
            f"Available HDFC schemes in my current sources: {known}\n\n"
            f"Last updated from sources: {iso_now()}"
        )
        return SmartSyncAnswer(text=msg, scheme_citation=None, fee_citation=None)

    wants_why = bool(re.search(r"\b(why|charged|charge|deducted)\b", question, re.IGNORECASE))
    wants_exit_load = "exit load" in question.lower() or "exitload" in question.lower()
    wants_min_sip = bool(re.search(r"\b(min(imum)?\s+)?sip\b", question, re.IGNORECASE))
    wants_expense = bool(re.search(r"\bexpense\s+ratio\b", question, re.IGNORECASE))
    wants_lockin = bool(re.search(r"\block[- ]?in\b|\belss\b", question, re.IGNORECASE))
    wants_benchmark = bool(re.search(r"\bbenchmark\b", question, re.IGNORECASE))
    wants_aum = bool(re.search(r"\baum\b", question, re.IGNORECASE))
    wants_inception = bool(re.search(r"\binception\b|launch date|start date", question, re.IGNORECASE))
    wants_risk = bool(re.search(r"\brisk\b|riskometer|risk level", question, re.IGNORECASE))
    # "why am I seeing this?" or "why was I charged" should trigger the explanatory add-on
    # for scheme attributes (except exit load, which uses the dedicated 6-bullet scenario).
    wants_why_seeing = bool(_WHY_SEE_RE.search(question)) or (wants_why and not wants_exit_load)

    is_scheme_specific = (
        wants_exit_load
        or wants_min_sip
        or wants_expense
        or wants_lockin
        or wants_benchmark
        or wants_aum
        or wants_inception
        or wants_risk
    )
    scheme = _pick_scheme_for_question(question, schemes_db) if is_scheme_specific else None

    # If user asked a scheme-specific fact but we can't confidently infer a scheme, ask for scheme name.
    if is_scheme_specific and schemes and scheme is None:
        known = ", ".join([str(s.get("scheme_name")) for s in schemes[:5]])
        msg = (
            "Which HDFC scheme do you mean? I can answer facts like exit load / minimum SIP / expense ratio with a source link.\n\n"
            f"Available in my current sources: {known}\n\n"
            f"Last updated from sources: {iso_now()}"
        )
        return SmartSyncAnswer(text=msg, scheme_citation=None, fee_citation=None)
    if is_scheme_specific and not scheme:
        msg = f"I couldn’t find scheme data in the current sources.\n\nLast updated from sources: {iso_now()}"
        return SmartSyncAnswer(text=msg, scheme_citation=None, fee_citation=None)

    # If it's not a supported scheme fact question, keep scope tight and offer booking.
    if scheme is None:
        msg = (
            "I’m limited to facts-only questions about the configured HDFC mutual fund schemes "
            "(exit load, minimum SIP, expense ratio, lock-in, benchmark, AUM, inception date, risk) with source links.\n\n"
            f"{_pulse_context_snippet()}\n\n"
            "If you want help beyond facts, you can say: “book an advisor call”.\n\n"
            f"Last updated from sources: {iso_now()}"
        )
        return SmartSyncAnswer(text=msg, scheme_citation=None, fee_citation=None)

    scheme_name = str(scheme.get("scheme_name"))
    scheme_url = str(scheme.get("source_url"))

    # Evidence-backed scheme fact snippet for exit load.
    exit_load_value = str(scheme.get("exit_load") or "not found in sources")
    scheme_fact_line = (_find_evidence_text(schemes_db, scheme_name=scheme_name, field_name="exit_load")) or f"Exit Load | {exit_load_value}"

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

    if wants_exit_load:
        extra = ""
        if wants_why_seeing:
            extra = (
                "\n\nWhy you might see this in-app (general):\n"
                "- You’re viewing scheme terms (factsheet/KIM/SID summary) for this scheme.\n"
                "- Exit load applies only when redeeming within the scheme’s exit-load window; the exact window is scheme-defined.\n\n"
                + _pulse_context_snippet()
            )
        text = f"{scheme_fact_line}{extra}\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
        return SmartSyncAnswer(text=text, scheme_citation=scheme_url, fee_citation=None)

    if wants_min_sip:
        min_sip_raw = scheme.get("min_sip_raw") or scheme.get("min_sip")
        if not min_sip_raw:
            msg = f"I couldn’t find the minimum SIP for {scheme_name} in the current sources.\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
            return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)
        fact_line = f"Minimum SIP | {min_sip_raw}"

        # If user asks "why charged" about min SIP, answer with the required 6-bullet structure
        # (this is a constraint explainer, not a fee).
        if wants_why:
            fee_db = _load_fee_explainers()
            scenario = _get_scenario(fee_db, "min_sip_constraint")
            fee_url = str((scenario.get("source_links") or [None])[0])
            bullets = _format_generic_bullets(
                scenario.get("bullets", []),
                replacements={"min_sip": str(min_sip_raw)},
            )
            text = (
                f"{fact_line}\n\n"
                f"{bullets}\n\n"
                f"{_pulse_context_snippet()}\n\n"
                f"Scheme source: {scheme_url}\n"
                f"Fee/Explainer source: {fee_url}\n"
                f"Last updated from sources: {iso_now()}"
            )
            return SmartSyncAnswer(text=text, scheme_citation=scheme_url, fee_citation=fee_url)

        extra = ""
        if wants_why_seeing:
            extra = (
                "\n\nWhy you might see this in-app (general):\n"
                "- This is the scheme’s minimum allowed SIP installment amount.\n"
                "- If you tried to set up a SIP below this minimum, the app may show this value as a constraint.\n\n"
                + _pulse_context_snippet()
            )
        msg = f"{fact_line}{extra}\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
        return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)

    if wants_expense:
        v = scheme.get("expense_ratio")
        ev = _find_evidence_text(schemes_db, scheme_name=scheme_name, field_name="expense_ratio")
        if not (ev or v):
            msg = f"I couldn’t find the expense ratio for {scheme_name} in the current sources.\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
            return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)
        fact_line = ev or f"Expense ratio | {v}"

        # If user asks "why charged" about expense ratio, use the 6-bullet explainer template.
        if wants_why:
            fee_db = _load_fee_explainers()
            scenario = _get_scenario(fee_db, "expense_ratio_applied")
            fee_url = str((scenario.get("source_links") or [None])[0])
            bullets = _format_generic_bullets(
                scenario.get("bullets", []),
                replacements={"expense_ratio": str(v)},
            )
            text = (
                f"{fact_line}\n\n"
                f"{bullets}\n\n"
                f"{_pulse_context_snippet()}\n\n"
                f"Scheme source: {scheme_url}\n"
                f"Fee source: {fee_url}\n"
                f"Last updated from sources: {iso_now()}"
            )
            return SmartSyncAnswer(text=text, scheme_citation=scheme_url, fee_citation=fee_url)

        extra = ""
        if wants_why_seeing:
            extra = (
                "\n\nWhy you might see this in-app (general):\n"
                "- Expense ratio is a disclosed scheme attribute; it is typically reflected in NAV over time rather than charged as a separate bill.\n\n"
                + _pulse_context_snippet()
            )
        msg = f"{fact_line}{extra}\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
        return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)

    if wants_lockin:
        v = scheme.get("lock_in")
        ev = _find_evidence_text(schemes_db, scheme_name=scheme_name, field_name="lock_in")
        if not (ev or v):
            msg = f"I couldn’t find the lock-in for {scheme_name} in the current sources.\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
            return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)
        extra = ""
        if wants_why_seeing:
            extra = (
                "\n\nWhy you might see this in-app (general):\n"
                "- Lock-in is a scheme restriction (common for ELSS). Apps show it so users know redemption constraints.\n\n"
                + _pulse_context_snippet()
            )
        msg = f"{ev or f'Lock In | {v}'}{extra}\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
        return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)

    if wants_benchmark:
        v = scheme.get("benchmark")
        ev = _find_evidence_text(schemes_db, scheme_name=scheme_name, field_name="benchmark")
        if not (ev or v):
            msg = f"I couldn’t find the benchmark for {scheme_name} in the current sources.\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
            return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)
        extra = ""
        if wants_why_seeing:
            extra = (
                "\n\nWhy you might see this in-app (general):\n"
                "- Benchmark is the reference index disclosed for the scheme; apps show it as a factual comparison baseline.\n\n"
                + _pulse_context_snippet()
            )
        msg = f"{ev or f'Benchmark | {v}'}{extra}\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
        return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)

    if wants_aum:
        v = scheme.get("aum")
        ev = _find_evidence_text(schemes_db, scheme_name=scheme_name, field_name="aum")
        if not (ev or v):
            msg = f"I couldn’t find the AUM for {scheme_name} in the current sources.\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
            return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)
        extra = ""
        if wants_why_seeing:
            extra = (
                "\n\nWhy you might see this in-app (general):\n"
                "- AUM is the total assets managed by the scheme, typically shown as a scheme size metric.\n\n"
                + _pulse_context_snippet()
            )
        msg = f"{ev or f'AUM | {v}'}{extra}\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
        return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)

    if wants_inception:
        v = scheme.get("inception_date")
        ev = _find_evidence_text(schemes_db, scheme_name=scheme_name, field_name="inception_date")
        if not (ev or v):
            msg = f"I couldn’t find the inception date for {scheme_name} in the current sources.\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
            return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)
        extra = ""
        if wants_why_seeing:
            extra = (
                "\n\nWhy you might see this in-app (general):\n"
                "- Inception date is when the scheme started; apps show it as a factual scheme attribute.\n\n"
                + _pulse_context_snippet()
            )
        msg = f"{ev or f'Inception Date | {v}'}{extra}\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
        return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)

    if wants_risk:
        v = scheme.get("risk_level")
        ev = _find_evidence_text(schemes_db, scheme_name=scheme_name, field_name="risk_level")
        if not (ev or v):
            msg = f"I couldn’t find the risk level for {scheme_name} in the current sources.\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
            return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)
        extra = ""
        if wants_why_seeing:
            extra = (
                "\n\nWhy you might see this in-app (general):\n"
                "- Risk level/riskometer is disclosed for the scheme; apps show it as a factual risk label.\n\n"
                + _pulse_context_snippet()
            )
        msg = f"{ev or f'Risk | {v}'}{extra}\n\nSource: {scheme_url}\nLast updated from sources: {iso_now()}"
        return SmartSyncAnswer(text=msg, scheme_citation=scheme_url, fee_citation=None)

    # If it's not one of the supported scheme facts, refuse to hallucinate.
    msg = (
        "I can answer facts about the configured HDFC schemes (exit load, minimum SIP, expense ratio, lock-in, benchmark, AUM, inception date, risk) with source links. "
        "Ask one of those, and include the scheme name (e.g., “HDFC Flexi Cap”).\n\n"
        f"Last updated from sources: {iso_now()}"
    )
    return SmartSyncAnswer(text=msg, scheme_citation=None, fee_citation=None)


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

    try:
        rewritten = generate_text(prompt)
    except Exception:
        # If Gemini isn't configured (missing key) or request fails,
        # fall back to the deterministic grounded answer.
        return base
    if not rewritten:
        return base

    merged = f"{rewritten.strip()}\n\n{footer}"
    return SmartSyncAnswer(text=merged, scheme_citation=base.scheme_citation, fee_citation=base.fee_citation)

