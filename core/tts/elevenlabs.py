from __future__ import annotations

import os
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class ElevenLabsConfig:
    api_key: str
    voice_id: str
    model_id: str = "eleven_multilingual_v2"


def _load_config() -> ElevenLabsConfig:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing ELEVENLABS_API_KEY environment variable.")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM").strip()
    model_id = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip() or "eleven_multilingual_v2"
    return ElevenLabsConfig(api_key=key, voice_id=voice_id, model_id=model_id)


def tts_mp3_bytes(text: str) -> bytes:
    """
    Returns mp3 bytes for the provided text using ElevenLabs TTS.
    Env: ELEVENLABS_API_KEY, optional ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL_ID
    """
    cfg = _load_config()
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{cfg.voice_id}"
    resp = requests.post(
        url,
        headers={
            "xi-api-key": cfg.api_key,
            "accept": "audio/mpeg",
            "content-type": "application/json",
        },
        json={
            "text": text,
            "model_id": cfg.model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.7},
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.content

