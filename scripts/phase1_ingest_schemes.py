from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "data" / "knowledge" / "source_urls.json"
OUT_PATH = ROOT / "data" / "schemes.json"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_sources() -> dict[str, Any]:
    with SOURCES_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_urls(urls: list[str]) -> None:
    bad = [u for u in urls if (not isinstance(u, str)) or ("REPLACE_WITH" in u) or (not u.startswith("http"))]
    if bad:
        raise SystemExit(
            "Phase 1 source URLs not set. Update data/knowledge/source_urls.json with the exact 5 approved URLs."
        )
    if len(urls) < 3:
        raise SystemExit("Need at least 3 scheme URLs to run ingestion (recommended: exactly 5).")
    if len(urls) > 5:
        raise SystemExit("Too many scheme URLs. Use at most 5 (recommended: exactly 5).")


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    # Remove noisy content.
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, *, max_chars: int = 900, overlap: int = 120) -> list[str]:
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


FIELD_ALIASES: dict[str, str] = {
    "Expense ratio": "expense_ratio",
    "Exit Load": "exit_load",
    "Min Lumpsum/SIP": "min_lumpsum_sip",
    "Lock In": "lock_in",
    "Risk": "risk_level",
    "Benchmark": "benchmark",
    "AUM": "aum",
    "Inception Date": "inception_date",
}


def _first_match(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _parse_money_int(raw: str) -> int | None:
    raw = raw.replace(",", "")
    m = re.search(r"(\d+)", raw)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def extract_structured_fields(page_text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Extract scheme fields and evidence objects in the same spirit as Bot-Mutualfund's schema.

    We primarily parse lines like:
      "Exit Load | 1.0%"
      "Min Lumpsum/SIP | ₹100/₹100"
    """
    scheme_fields: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []

    # Normalize and scan line-by-line for:
    # - "Label | value"
    # - "Label value" (including cases like "AUM₹35458 Cr")
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in page_text.splitlines()]
    for ln in lines:
        # Case A: "Label | value"
        if "|" in ln:
            left, right = [p.strip() for p in ln.split("|", 1)]
            if left and right and left in FIELD_ALIASES:
                field_key = FIELD_ALIASES[left]
                scheme_fields[field_key] = right
                evidence.append(
                    {
                        "field_name": field_key,
                        "field_value": right,
                        "evidence_text": f"{left} | {right}",
                    }
                )
            continue

        # Case B: "Label value"
        for label, field_key in FIELD_ALIASES.items():
            if not ln.lower().startswith(label.lower()):
                continue
            value = ln[len(label) :].strip()
            if not value:
                continue
            scheme_fields[field_key] = value
            evidence.append(
                {
                    "field_name": field_key,
                    "field_value": value,
                    "evidence_text": f"{label} | {value}",
                }
            )
            break

    # Special: split Min Lumpsum/SIP into both values.
    if "min_lumpsum_sip" in scheme_fields:
        raw = str(scheme_fields.pop("min_lumpsum_sip"))
        # common format: "₹100/₹100" or "₹100 / ₹100"
        parts = [p.strip() for p in re.split(r"/", raw)]
        if len(parts) >= 2:
            lumpsum_raw, sip_raw = parts[0], parts[1]
            scheme_fields["min_lumpsum_raw"] = lumpsum_raw
            scheme_fields["min_sip_raw"] = sip_raw
            scheme_fields["min_lumpsum"] = _parse_money_int(lumpsum_raw)
            scheme_fields["min_sip"] = _parse_money_int(sip_raw)

    # Fallbacks from free text (best-effort).
    scheme_fields.setdefault("expense_ratio", scheme_fields.get("expense_ratio"))
    scheme_fields.setdefault("exit_load", scheme_fields.get("exit_load"))

    return scheme_fields, evidence


def fetch_url(url: str, *, timeout_s: int = 30) -> str:
    headers = {
        # Try to look like a real browser; some sites block generic agents.
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://www.google.com/",
    }

    resp = requests.get(url, timeout=timeout_s, headers=headers)
    if resp.status_code == 403:
        # Fallback: fetch readable HTML through r.jina.ai proxy.
        # This avoids brittle anti-bot rules during local prototyping.
        proxied = f"https://r.jina.ai/{url}"
        resp = requests.get(proxied, timeout=timeout_s, headers=headers)

    resp.raise_for_status()
    return resp.text


def infer_scheme_name(source_url: str, page_text: str) -> str:
    # Best-effort:
    # - r.jina.ai pages include a "Title: ..." header line.
    # - otherwise use <title> if present, otherwise fallback to URL path.
    jina_title = _first_match(r"^\s*Title:\s*(.+)$", page_text)
    if jina_title:
        return jina_title[:120]

    m = re.search(r"<title[^>]*>(.*?)</title>", page_text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        return title[:120]
    return source_url.rstrip("/").split("/")[-1][:120]


def main() -> None:
    sources = load_sources()
    urls = sources.get("approved_scheme_urls", [])
    validate_urls(urls)

    scraped_at = iso_now()
    schemes: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []

    for i, url in enumerate(urls, start=1):
        print(f"[{i}/{len(urls)}] Fetching {url}")
        html = fetch_url(url)
        text = html_to_text(html)
        scheme_name = infer_scheme_name(url, html)

        # Extract structured scheme fields and evidence lines.
        extracted_fields, extracted_evidence = extract_structured_fields(text)

        # Parse basic plan/option/category from the scheme name if possible.
        plan_type = "Direct" if "direct" in scheme_name.lower() else "Unknown"
        option_type = "Growth" if "growth" in scheme_name.lower() else "Unknown"
        category = _first_match(r"\b(large cap|flexi cap|mid cap|small cap|index)\b", scheme_name)
        if category:
            category = category.title()

        scheme_obj: dict[str, Any] = {
            "scheme_name": scheme_name,
            "amc_name": sources.get("amc") or "HDFC",
            "category": category,
            "plan_type": plan_type,
            "option_type": option_type,
            "source_url": url,
            "scraped_at": scraped_at,
            # Filled below from extracted fields (may be null).
            "expense_ratio": extracted_fields.get("expense_ratio"),
            "exit_load": extracted_fields.get("exit_load"),
            "min_sip": extracted_fields.get("min_sip"),
            "min_sip_raw": extracted_fields.get("min_sip_raw"),
            "min_lumpsum": extracted_fields.get("min_lumpsum"),
            "min_lumpsum_raw": extracted_fields.get("min_lumpsum_raw"),
            "lock_in": extracted_fields.get("lock_in"),
            "risk_level": extracted_fields.get("risk_level"),
            "benchmark": extracted_fields.get("benchmark"),
            "aum": extracted_fields.get("aum"),
            "inception_date": extracted_fields.get("inception_date"),
            "fund_manager": extracted_fields.get("fund_manager"),
        }
        schemes.append(scheme_obj)

        for ev in extracted_evidence:
            ev["source_url"] = url
            ev["scheme_name"] = scheme_name
            evidence.append(ev)

        # polite delay
        time.sleep(0.5)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(
            {
                "meta": {
                    "last_scraped": scraped_at,
                    "source_urls": urls,
                },
                "schemes": schemes,
                "evidence": evidence,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {OUT_PATH} with {len(schemes)} schemes and {len(evidence)} evidence rows.")


if __name__ == "__main__":
    main()

