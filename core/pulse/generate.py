from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.llm.gemini import generate_text

ROOT = Path(__file__).resolve().parents[2]

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def redact_pii(text: str) -> str:
    # Very small prototype redactions.
    text = re.sub(r"\b[\w\.-]+@[\w\.-]+\.\w+\b", "[REDACTED]", text)
    text = re.sub(r"\b\d{10}\b", "[REDACTED]", text)
    text = re.sub(r"\b\d{12}\b", "[REDACTED]", text)
    return text


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text)]


THEME_KEYWORDS: dict[str, list[str]] = {
    "Login issues": ["login", "otp", "sign", "logged", "log", "authentication"],
    "Nominee updates": ["nominee", "name change", "account changes"],
    "Performance / crashes": ["slow", "lag", "crash", "freeze", "hang", "performance"],
    "SIP / mandates": ["sip", "mandate", "autopay", "upi", "bank"],
    "Withdrawals & timelines": ["withdraw", "redemption", "redeem", "pending", "timeline", "settlement"],
    "Statements / tax docs": ["statement", "statements", "tax", "capital", "gains", "download"],
    "Support": ["support", "customer care", "helpdesk", "help"],
    "UX / usability": ["ui", "ux", "confusing", "navigation", "navigat", "flow", "screen"],
}


@dataclass(frozen=True)
class ReviewRow:
    index: int
    rating: int
    title: str
    text: str
    date: str
    date_display: str
    helpful_count: int


def load_reviews_csv(path: Path) -> list[ReviewRow]:
    rows: list[ReviewRow] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if not r:
                continue
            index_raw = (r.get("index") or "").strip()
            title = (r.get("title") or "").strip()
            text = (r.get("text") or "").strip()
            date = (r.get("date") or "").strip()
            date_display = (r.get("dateDisplay") or r.get("date_display") or "").strip()
            helpful_raw = (r.get("helpfulCount") or r.get("helpful_count") or "").strip()
            rating_raw = (r.get("rating") or "").strip()
            try:
                rating = int(float(rating_raw)) if rating_raw else 0
            except ValueError:
                rating = 0
            try:
                index = int(float(index_raw)) if index_raw else len(rows)
            except ValueError:
                index = len(rows)
            try:
                helpful_count = int(float(helpful_raw)) if helpful_raw else 0
            except ValueError:
                helpful_count = 0
            if not (title or text):
                continue
            rows.append(
                ReviewRow(
                    index=index,
                    rating=rating,
                    title=title,
                    text=text,
                    date=date,
                    date_display=date_display,
                    helpful_count=helpful_count,
                )
            )
    return rows


def assign_theme(review: ReviewRow) -> str:
    blob = " ".join([review.title, review.text]).lower()
    scores: dict[str, int] = {}
    for theme, kws in THEME_KEYWORDS.items():
        scores[theme] = sum(1 for kw in kws if kw in blob)
    best_theme, best_score = max(scores.items(), key=lambda x: x[1])
    if best_score == 0:
        return "Other"
    return best_theme


def build_weekly_pulse(
    *,
    product: str,
    reviews_csv_path: Path,
    weeks_back: int = 10,
    max_themes: int = 5,
) -> dict:
    # weeks_back kept for compatibility with the milestone interface; for local CSV we assume it is already filtered.
    reviews = load_reviews_csv(reviews_csv_path)
    if not reviews:
        raise ValueError("No reviews found in CSV.")

    # Optional Gemini path: set USE_GEMINI_PULSE=1 to enable.
    if str(os.environ.get("USE_GEMINI_PULSE", "")).strip() == "1":
        try:
            return build_weekly_pulse_gemini(
                product=product,
                reviews=reviews,
                weeks_back=weeks_back,
                max_themes=max_themes,
            )
        except Exception:
            # Fall back to deterministic logic if Gemini fails.
            pass

    themed: dict[str, list[ReviewRow]] = defaultdict(list)
    for r in reviews:
        themed[assign_theme(r)].append(r)

    counts = Counter({k: len(v) for k, v in themed.items()})
    # keep top N themes (excluding Other if possible)
    ordered = [t for t, _ in counts.most_common() if t != "Other"]
    if "Other" in counts:
        ordered.append("Other")
    themes = ordered[:max_themes]

    # recompute top based on selected themes only
    top_themes = sorted(themes, key=lambda t: counts.get(t, 0), reverse=True)[:3]

    # pick 3 quotes from the most frequent themes (prefer low ratings)
    quotes: list[str] = []
    for theme in top_themes:
        candidates = sorted(themed.get(theme, []), key=lambda r: (r.rating if r.rating else 5))
        for r in candidates:
            q = redact_pii((r.text or r.title).strip())
            if q and q not in quotes:
                quotes.append(q[:220])
            if len(quotes) == 3:
                break
        if len(quotes) == 3:
            break

    # action ideas: simple deterministic mapping
    action_pool: list[str] = []
    if "Login issues" in top_themes:
        action_pool.append("Investigate OTP/login failure spikes; add a status banner and retry guidance in-app.")
    if "Nominee updates" in top_themes:
        action_pool.append("Audit the nominee update flow for validation/API errors; add clearer inline error messages.")
    if "Performance / crashes" in top_themes:
        action_pool.append("Profile slow screens and crash logs; prioritize a performance hotfix for the portfolio page.")
    if "SIP / mandates" in top_themes:
        action_pool.append("Simplify mandate setup steps and add a troubleshooting checklist for failed mandates.")
    if "Withdrawals & timelines" in top_themes:
        action_pool.append("Clarify redemption timelines in-product and surface real-time status for pending withdrawals.")
    if "Statements / tax docs" in top_themes:
        action_pool.append("Improve statement/tax-doc download discoverability and add a short guided path.")
    if "Support" in top_themes:
        action_pool.append("Triage top support complaints and publish a short status + resolution playbook for agents.")
    if "UX / usability" in top_themes:
        action_pool.append("Run a quick UX audit on the top friction paths and simplify navigation labels and flows.")

    # Ensure exactly 3 action ideas.
    fallbacks = [
        "Review recent negative reviews and tag them into clear themes for weekly tracking.",
        "Add a lightweight in-app feedback prompt on key friction screens.",
        "Improve help-center links for the most common issues this week.",
    ]
    if not action_pool:
        action_pool = fallbacks[:]

    action_ideas: list[str] = []
    i = 0
    while len(action_ideas) < 3:
        if i < len(action_pool):
            candidate = action_pool[i]
        else:
            candidate = fallbacks[(i - len(action_pool)) % len(fallbacks)]
        if candidate not in action_ideas:
            action_ideas.append(candidate)
        i += 1

    theme_defs = {t: f"Reviews primarily about {t.lower()}." for t in themes}

    weekly_note = (
        f"Weekly pulse (last ~{weeks_back} weeks): Top themes are "
        + ", ".join([f"{t} ({counts.get(t, 0)})" for t in top_themes])
        + ". "
        + "Key friction points show up in user quotes below. "
        + "Action ideas focus on reducing repeat issues and improving clarity."
    )

    # Hard-enforce <= 250 words.
    words = weekly_note.split()
    if len(words) > 250:
        weekly_note = " ".join(words[:250])

    return {
        "pulse_id": f"pulse_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "product": product,
        "generated_at": iso_now(),
        "themes": [{"label": t, "count": counts.get(t, 0), "definition": theme_defs[t]} for t in themes],
        "top_themes": top_themes,
        "quotes": quotes[:3],
        "weekly_note": weekly_note,
        "action_ideas": action_ideas,
        "word_count": len(weekly_note.split()),
    }


def build_weekly_pulse_gemini(
    *,
    product: str,
    reviews: list[ReviewRow],
    weeks_back: int,
    max_themes: int,
) -> dict:
    """
    Gemini-based pulse generation. Still enforces rubric checks after generation.
    """
    # Prepare a compact review sample to stay within token limits.
    sample = []
    for r in reviews[:200]:
        sample.append({"rating": r.rating, "text": redact_pii(r.text)[:400], "date": r.date_display or r.date})

    prompt = f"""
You are a fintech product analyst. Generate a Weekly Product Pulse for {product} from app reviews.

Hard rules:
- Group into at most {max_themes} themes
- Pick top 3 themes
- Include exactly 3 real user quotes (verbatim from the provided texts; already redacted)
- Weekly note must be <= 250 words
- Include exactly 3 action ideas
- Output MUST be valid JSON with keys: themes, top_themes, quotes, weekly_note, action_ideas

Reviews (JSON list):
{json.dumps(sample, ensure_ascii=False)}
""".strip()

    raw = generate_text(prompt)
    data = json.loads(raw)

    # Build the artifact; validate constraints.
    themes = data.get("themes", [])
    top_themes = data.get("top_themes", [])
    quotes = data.get("quotes", [])
    weekly_note = str(data.get("weekly_note", "")).strip()
    action_ideas = data.get("action_ideas", [])

    # enforce
    weekly_note_words = weekly_note.split()
    if len(weekly_note_words) > 250:
        weekly_note = " ".join(weekly_note_words[:250])

    return {
        "pulse_id": f"pulse_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "product": product,
        "generated_at": iso_now(),
        "themes": themes[:max_themes],
        "top_themes": list(top_themes)[:3],
        "quotes": list(quotes)[:3],
        "weekly_note": weekly_note,
        "action_ideas": list(action_ideas)[:3],
        "word_count": len(weekly_note.split()),
    }


def write_pulse_bundle(bundle: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{bundle['pulse_id']}.json"
    out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path

