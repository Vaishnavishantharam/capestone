from __future__ import annotations

import os
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class ElevenLabsSTTConfig:
    api_key: str
    model_id: str = "scribe_v2"


def _load_config() -> ElevenLabsSTTConfig:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing ELEVENLABS_API_KEY environment variable.")
    model_id = os.environ.get("ELEVENLABS_STT_MODEL_ID", "scribe_v2").strip() or "scribe_v2"
    return ElevenLabsSTTConfig(api_key=key, model_id=model_id)


def transcribe_audio_bytes(*, audio_bytes: bytes, filename: str = "audio.wav", language_code: str | None = "eng") -> str:
    """
    ElevenLabs Speech-to-Text (batch) via REST API.

    Env: ELEVENLABS_API_KEY, optional ELEVENLABS_STT_MODEL_ID
    Docs: POST https://api.elevenlabs.io/v1/speech-to-text (multipart form)
    """
    cfg = _load_config()
    url = "https://api.elevenlabs.io/v1/speech-to-text"

    data: dict[str, str] = {
        "model_id": cfg.model_id,
        "tag_audio_events": "false",
        "diarize": "false",
    }
    if language_code:
        data["language_code"] = language_code

    resp = requests.post(
        url,
        headers={"xi-api-key": cfg.api_key},
        data=data,
        files={"file": (filename, audio_bytes)},
        timeout=90,
    )
    resp.raise_for_status()
    payload = resp.json()

    # ElevenLabs responses can include either "text" or nested transcript structures.
    text = (payload.get("text") or payload.get("transcript") or "").strip()
    if text:
        return text
    # fallback: some variants return {"transcripts":[{"text":...}]}
    transcripts = payload.get("transcripts") or []
    if transcripts and isinstance(transcripts, list):
        t0 = transcripts[0] or {}
        if isinstance(t0, dict):
            return str(t0.get("text") or "").strip()
    return ""

