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


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: str
    source_url: str
    text: str


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
    # Best-effort: use <title> if present, otherwise fallback to URL path.
    m = re.search(r"<title[^>]*>(.*?)</title>", page_text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        return title[:120]
    return source_url.rstrip("/").split("/")[-1][:120]


def main() -> None:
    sources = load_sources()
    urls = sources.get("approved_scheme_urls", [])
    validate_urls(urls)

    ingested_at = iso_now()
    all_chunks: list[dict[str, Any]] = []
    schemes: list[dict[str, Any]] = []

    for i, url in enumerate(urls, start=1):
        print(f"[{i}/{len(urls)}] Fetching {url}")
        html = fetch_url(url)
        text = html_to_text(html)
        scheme_name = infer_scheme_name(url, html)

        chunks = chunk_text(text)
        scheme_chunks: list[EvidenceChunk] = []
        for j, c in enumerate(chunks):
            chunk_id = f"scheme_{i:02d}_chunk_{j:04d}"
            scheme_chunks.append(EvidenceChunk(chunk_id=chunk_id, source_url=url, text=c))

        schemes.append(
            {
                "scheme_id": f"scheme_{i:02d}",
                "scheme_name": scheme_name,
                "source_url": url,
                "evidence_chunk_ids": [c.chunk_id for c in scheme_chunks],
            }
        )
        all_chunks.extend([c.__dict__ for c in scheme_chunks])

        # polite delay
        time.sleep(0.5)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(
            {
                "product": sources.get("product"),
                "amc": sources.get("amc"),
                "ingested_at": ingested_at,
                "schemes": schemes,
                "evidence_chunks": all_chunks,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {OUT_PATH} with {len(schemes)} schemes and {len(all_chunks)} evidence chunks.")


if __name__ == "__main__":
    main()

