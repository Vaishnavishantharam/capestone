from __future__ import annotations

import os
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str
    model: str = "gemini-1.5-flash"


def _load_config() -> GeminiConfig:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing GEMINI_API_KEY environment variable.")
    model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash").strip() or "gemini-1.5-flash"
    return GeminiConfig(api_key=key, model=model)


def generate_text(prompt: str) -> str:
    """
    Gemini text generation via REST API (no heavy client deps; works on older pip/Python).

    Env: GEMINI_API_KEY, optional GEMINI_MODEL
    """
    cfg = _load_config()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.model}:generateContent?key={cfg.api_key}"
    resp = requests.post(
        url,
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 800},
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return ""

