from __future__ import annotations

import sys
from pathlib import Path


def _find_repo_root() -> Path:
    """Directory that contains the `core` package (works regardless of cwd / Railway root)."""
    start = Path(__file__).resolve()
    for d in [start.parent, *start.parents]:
        if (d / "core" / "__init__.py").is_file():
            return d
    raise RuntimeError(
        "Could not find the `core/` package. Deploy the full repository from its root "
        "so `core/` is included (e.g. Railway: set Root Directory to `.` or leave blank, "
        "not `app`)."
    )


# Must run before any `from core...` imports (Railway, Docker, etc.).
ROOT = _find_repo_root().resolve()
sys.path.insert(0, str(ROOT))

import html
import json
import os
import base64
import tempfile

import streamlit as st
import streamlit.components.v1 as components

from core.mcp.hitl import enqueue_actions, generate_actions_from_booking, list_queue, load_latest_booking, set_status
from core.pulse.load import load_latest_pulse
from core.rag.smartsync import answer_question
from core.stt.elevenlabs import transcribe_audio_bytes
from core.tts.elevenlabs import tts_mp3_bytes
from core.voice.booking import create_voice_booking_artifact, theme_aware_greeting


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def _load_dotenv_fallback(path: Path) -> None:
    """
    Minimal .env loader (avoids extra dependency on python-dotenv).
    Only sets vars that are not already present in the process env.
    """
    for k, v in _read_env_file(path).items():
        os.environ[k] = v


ENV_PATH = ROOT / ".env"
_load_dotenv_fallback(ENV_PATH)

def _get_env(key: str) -> str:
    """
    Robust env lookup for Streamlit reruns:
    - prefer process env
    - if empty, re-read root .env and set it
    """
    v = str(os.environ.get(key, "")).strip()
    if v:
        return v
    file_vars = _read_env_file(ENV_PATH)
    v2 = str(file_vars.get(key, "")).strip()
    if v2:
        os.environ[key] = v2
    return v2


def _has_env(key: str) -> bool:
    return bool(_get_env(key))


def _inject_ops_dashboard_theme() -> None:
    """Dark navy + neon cyan glassmorphism (professional ops / AI-assistant style)."""
    st.markdown(
        """
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
          :root {
            --ops-bg0: #0a0c12;
            --ops-bg1: #0f1219;
            --ops-panel: rgba(22, 27, 38, 0.72);
            --ops-border: rgba(34, 211, 238, 0.18);
            --ops-cyan: #22d3ee;
            --ops-cyan-dim: rgba(34, 211, 238, 0.35);
            --ops-text: #f1f5f9;
            --ops-muted: #94a3b8;
          }
          html, body, .stApp {
            font-family: 'Inter', system-ui, sans-serif !important;
          }
          .stApp {
            background: linear-gradient(165deg, var(--ops-bg0) 0%, #12151f 42%, #0e1118 100%) !important;
            color: var(--ops-text) !important;
          }
          [data-testid="stAppViewContainer"] > .main {
            background: transparent !important;
          }
          section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0c0f16 0%, #151a24 100%) !important;
            border-right: 1px solid var(--ops-border) !important;
          }
          section[data-testid="stSidebar"] .stMarkdown, section[data-testid="stSidebar"] p,
          section[data-testid="stSidebar"] span, section[data-testid="stSidebar"] label {
            color: #cbd5e1 !important;
          }
          header[data-testid="stHeader"] {
            background: rgba(10, 12, 18, 0.92) !important;
            backdrop-filter: blur(14px);
            border-bottom: 1px solid var(--ops-border) !important;
          }
          div[data-testid="stDecoration"] { display: none; }
          #MainMenu { visibility: hidden; }
          footer { visibility: hidden; }
          .block-container {
            padding-top: 1.25rem !important;
            padding-bottom: 3rem !important;
            max-width: 1280px !important;
          }
          .stTabs [data-baseweb="tab-list"] {
            gap: 6px !important;
            background: rgba(15, 18, 26, 0.85) !important;
            border-radius: 14px !important;
            padding: 6px !important;
            border: 1px solid var(--ops-border) !important;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
          }
          .stTabs [data-baseweb="tab"] {
            border-radius: 10px !important;
            color: var(--ops-muted) !important;
            font-weight: 600 !important;
            letter-spacing: 0.02em;
          }
          .stTabs [aria-selected="true"] {
            background: linear-gradient(135deg, rgba(34, 211, 238, 0.18), rgba(34, 211, 238, 0.08)) !important;
            color: var(--ops-cyan) !important;
            box-shadow: 0 0 28px rgba(34, 211, 238, 0.12);
          }
          .stTabs [data-baseweb="tab-highlight"] {
            background: transparent !important;
          }
          .main .stMarkdown p, .main .stMarkdown li,
          .main .stCaption, .main label {
            color: #cbd5e1 !important;
          }
          .main h1, .main h2, .main h3 {
            color: var(--ops-cyan) !important;
            font-weight: 700 !important;
            letter-spacing: -0.02em;
          }
          .stButton > button {
            border-radius: 12px !important;
            font-weight: 600 !important;
            border: 1px solid var(--ops-border) !important;
            background: rgba(30, 41, 59, 0.5) !important;
            color: var(--ops-text) !important;
          }
          .stButton > button:hover {
            border-color: var(--ops-cyan) !important;
            box-shadow: 0 0 20px rgba(34, 211, 238, 0.15);
          }
          .stButton > button[kind="primary"], div[data-testid="column"] button[kind="primary"] {
            background: linear-gradient(135deg, #0891b2 0%, #22d3ee 100%) !important;
            color: #0a0c12 !important;
            border: none !important;
            box-shadow: 0 4px 24px rgba(34, 211, 238, 0.28) !important;
          }
          [data-testid="stChatMessage"] {
            background: var(--ops-panel) !important;
            backdrop-filter: blur(12px);
            border: 1px solid var(--ops-border) !important;
            border-radius: 16px !important;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.25) !important;
          }
          [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p,
          [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] li {
            color: #e2e8f0 !important;
          }
          .stChatInput > div {
            border-radius: 14px !important;
            border: 1px solid var(--ops-border) !important;
            background: rgba(15, 23, 42, 0.65) !important;
          }
          .stChatInput textarea {
            color: var(--ops-text) !important;
          }
          [data-testid="stExpander"] {
            background: rgba(17, 21, 31, 0.75) !important;
            border: 1px solid var(--ops-border) !important;
            border-radius: 12px !important;
          }
          div[data-testid="stAlert"] {
            background: rgba(15, 23, 42, 0.85) !important;
            border: 1px solid var(--ops-border) !important;
            border-radius: 12px !important;
            color: #e2e8f0 !important;
          }
          [data-testid="stSuccess"] {
            background: rgba(16, 185, 129, 0.1) !important;
            border: 1px solid rgba(16, 185, 129, 0.4) !important;
            color: #a7f3d0 !important;
          }
          [data-testid="stInfo"] {
            background: rgba(14, 165, 233, 0.1) !important;
            border: 1px solid rgba(34, 211, 238, 0.35) !important;
            color: #bae6fd !important;
          }
          [data-testid="stWarning"] {
            background: rgba(245, 158, 11, 0.12) !important;
            border: 1px solid rgba(245, 158, 11, 0.45) !important;
            color: #fde68a !important;
          }
          .va-ind {
            display: flex; justify-content: center; align-items: center; gap: 10px;
            margin: 6px 0 14px 0; font-weight: 700; color: #e2e8f0; font-size: 0.95rem; letter-spacing: 0.02em;
          }
          .va-dot {
            width: 10px; height: 10px; border-radius: 999px; background: #f43f5e;
            box-shadow: 0 0 12px rgba(244, 63, 94, 0.55);
            animation: va_pulse 1.2s infinite;
          }
          .va-dots span {
            display: inline-block; width: 6px; height: 6px; margin: 0 2px;
            background: #22d3ee; border-radius: 999px; animation: va_bounce 1.2s infinite; opacity: 0.65;
          }
          .va-dots span:nth-child(2) { animation-delay: 0.2s; }
          .va-dots span:nth-child(3) { animation-delay: 0.4s; }
          @keyframes va_pulse {
            0% { transform: scale(0.9); opacity: 0.5; } 50% { transform: scale(1.1); opacity: 1; } 100% { transform: scale(0.9); opacity: 0.5; }
          }
          @keyframes va_bounce {
            0%, 80%, 100% { transform: translateY(0); opacity: 0.4; } 40% { transform: translateY(-6px); opacity: 1; }
          }
          [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
            color: #e2e8f0 !important;
          }
          iframe[title="st.dataframe"] {
            border: 1px solid var(--ops-border) !important;
            border-radius: 12px !important;
          }
          .ops-hero-title {
            margin-bottom: 1.35rem;
            padding: 1.1rem 1.35rem;
            border-radius: 16px;
            background: linear-gradient(135deg, rgba(34, 211, 238, 0.12) 0%, rgba(99, 102, 241, 0.06) 100%);
            border: 1px solid var(--ops-border);
            box-shadow: 0 12px 48px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255,255,255,0.04);
          }
          .ops-hero-title h1 {
            margin: 0.35rem 0 0.25rem 0;
            font-size: 1.55rem;
            font-weight: 700;
            letter-spacing: -0.03em;
            background: linear-gradient(90deg, #e0f2fe 0%, var(--ops-cyan) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
          }
          [data-testid="stVerticalBlockBorderWrapper"] {
            background: rgba(17, 21, 31, 0.45) !important;
            border: 1px solid var(--ops-border) !important;
            border-radius: 16px !important;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2) !important;
          }
          hr {
            border: none !important;
            border-top: 1px solid var(--ops-border) !important;
            margin: 1.25rem 0 !important;
          }
          .ops-hero-title .ops-tagline {
            margin: 0;
            font-size: 0.88rem;
            color: var(--ops-muted);
            font-weight: 500;
          }
          .ops-product-chip {
            display: inline-block;
            font-size: 0.65rem;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: var(--ops-cyan);
            padding: 0.2rem 0.55rem;
            border-radius: 6px;
            border: 1px solid var(--ops-cyan-dim);
            background: rgba(34, 211, 238, 0.08);
          }
          .ops-workspace-caption {
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            color: var(--ops-muted);
            margin: 0 0 0.45rem 0;
          }
          div[data-testid="stRadio"] div[role="radiogroup"] {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            gap: 6px !important;
            width: 100% !important;
            padding: 5px !important;
            margin: 0 0 1.35rem 0 !important;
            background: rgba(12, 15, 22, 0.92) !important;
            border: 1px solid var(--ops-border) !important;
            border-radius: 14px !important;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.35);
          }
          div[data-testid="stRadio"] div[role="radiogroup"] label {
            flex: 1 1 0 !important;
            min-width: 0 !important;
            margin: 0 !important;
            padding: 0.65rem 0.45rem !important;
            text-align: center !important;
            border-radius: 10px !important;
            font-weight: 700 !important;
            font-size: 0.86rem !important;
            color: #e0f2fe !important;
            border: 1px solid rgba(34, 211, 238, 0.2) !important;
            cursor: pointer !important;
            transition: background 0.15s, color 0.15s, box-shadow 0.15s, border-color 0.15s;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.45);
          }
          div[data-testid="stRadio"] div[role="radiogroup"] label p,
          div[data-testid="stRadio"] div[role="radiogroup"] label span,
          div[data-testid="stRadio"] div[role="radiogroup"] label div,
          div[data-testid="stRadio"] [data-testid="stMarkdownContainer"] p {
            color: inherit !important;
            margin: 0 !important;
          }
          div[data-testid="stRadio"] div[role="radiogroup"] label input {
            accent-color: #22d3ee;
          }
          div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked),
          div[data-testid="stRadio"] div[role="radiogroup"] label[aria-checked="true"] {
            background: linear-gradient(135deg, rgba(34, 211, 238, 0.45), rgba(6, 182, 212, 0.25)) !important;
            color: #ffffff !important;
            border-color: rgba(103, 232, 249, 0.7) !important;
            box-shadow: 0 0 32px rgba(34, 211, 238, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.12);
            text-shadow: 0 0 18px rgba(34, 211, 238, 0.55);
          }
          div[data-testid="stRadio"] div[role="radiogroup"] label:hover {
            color: #ffffff !important;
            border-color: rgba(34, 211, 238, 0.4) !important;
          }
          .chat-intro-card {
            margin: 0 0 1rem 0;
            padding: 1rem 1.15rem 1.05rem;
            border-radius: 14px;
            border: 1px solid var(--ops-border);
            background: rgba(17, 21, 31, 0.65);
            backdrop-filter: blur(12px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.22);
          }
          .chat-intro-card .chat-intro-title {
            margin: 0 0 0.5rem 0;
            font-size: 0.95rem;
            font-weight: 600;
            color: #f1f5f9;
            line-height: 1.45;
          }
          .chat-intro-card .chat-intro-body {
            margin: 0;
            font-size: 0.88rem;
            color: #94a3b8;
            line-height: 1.55;
          }
          .chat-intro-card .chat-intro-kicker {
            margin: 0 0 0.35rem 0;
            font-size: 0.65rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: var(--ops-cyan);
          }
          .chat-thread-label {
            margin: 0 0 0.5rem 0;
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: var(--ops-muted);
          }
          .voice-panel-head {
            margin: 0 0 1.1rem 0;
            padding: 1rem 1.15rem;
            border-radius: 14px;
            border: 1px solid var(--ops-border);
            background: rgba(17, 21, 31, 0.55);
            backdrop-filter: blur(10px);
          }
          .voice-panel-kicker {
            display: block;
            font-size: 0.65rem;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: var(--ops-cyan);
            margin-bottom: 0.35rem;
          }
          .voice-panel-head h2.voice-panel-title {
            margin: 0 0 0.35rem 0;
            font-size: 1.2rem;
            font-weight: 700;
            color: #f1f5f9 !important;
            letter-spacing: -0.02em;
            -webkit-text-fill-color: #f1f5f9;
          }
          .voice-panel-desc {
            margin: 0;
            font-size: 0.86rem;
            color: #94a3b8;
            line-height: 1.45;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_workspace_selector() -> None:
    """Three-way workspace switch (session state key: ops_workspace → chat | pulse | voice)."""
    if "ops_workspace" not in st.session_state:
        st.session_state.ops_workspace = "chat"
    st.markdown('<p class="ops-workspace-caption">Choose workspace</p>', unsafe_allow_html=True)
    st.radio(
        "workspace_section",
        options=["chat", "pulse", "voice"],
        format_func=lambda k: {
            "chat": "💬  Chat / FAQ",
            "pulse": "📊  Weekly Pulse",
            "voice": "📞  Voice & Book",
        }[k],
        horizontal=True,
        key="ops_workspace",
        label_visibility="collapsed",
    )


st.set_page_config(page_title="Investor Ops & Intelligence Suite", layout="wide")
_inject_ops_dashboard_theme()

st.markdown(
    """
    <div class="ops-hero-title">
      <span class="ops-product-chip">INDMoney</span>
      <h1>Investor Ops & Intelligence Suite</h1>
      <p class="ops-tagline">Smart‑Sync Q&A · Weekly pulse · Voice booking · HITL approvals · Evals</p>
    </div>
    """,
    unsafe_allow_html=True,
)

_render_workspace_selector()


def _intent_is_booking(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in ["book", "booking", "schedule", "call", "advisor", "appointment"])


def _render_chat_faq() -> None:
    st.markdown(
        """
        <div class="chat-intro-card">
          <div class="chat-intro-kicker">Smart-Sync support</div>
          <p class="chat-intro-title">HDFC mutual fund facts on INDMoney</p>
          <p class="chat-intro-body">
            Ask about exit load, expense ratio, minimum SIP, lock-in, and more. Replies use your RAG sources and citations.
          </p>
          <p class="chat-intro-body" style="margin-top:0.65rem;">
            <strong style="color:#e2e8f0;">Try:</strong>
            <span style="color:#cbd5e1;"> “What is the minimum SIP for HDFC Small Cap?”</span>
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []

    st.markdown('<p class="chat-thread-label">Conversation</p>', unsafe_allow_html=True)
    if not st.session_state.messages:
        st.caption("No messages yet — type below to begin.")

    with st.container(border=True):
        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])

        user_text = st.chat_input("Message INDMoney support…")

    if user_text:
        q = (user_text or "").strip()
        if q:
            st.session_state.messages.append({"role": "user", "content": q})
            ans = answer_question(q)
            st.session_state.messages.append({"role": "assistant", "content": ans.text})
            st.rerun()


def _render_weekly_pulse_dashboard() -> None:
    st.markdown(
        """
        <style>
          .pulse-hero {
            background: linear-gradient(135deg, rgba(8, 145, 178, 0.35) 0%, rgba(34, 211, 238, 0.12) 48%, rgba(99, 102, 241, 0.08) 100%);
            color: #f1f5f9;
            padding: 1.35rem 1.6rem 1.45rem;
            border-radius: 16px;
            margin-bottom: 1.25rem;
            border: 1px solid rgba(34, 211, 238, 0.22);
            box-shadow: 0 12px 48px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.05);
          }
          .pulse-hero h1 {
            margin: 0 0 0.35rem 0;
            font-size: 1.35rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            line-height: 1.25;
            color: #e0f2fe;
          }
          .pulse-hero p {
            margin: 0;
            font-size: 0.9rem;
            opacity: 0.9;
            font-weight: 500;
            line-height: 1.5;
            color: #94a3b8;
          }
          .pulse-h3 {
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: #22d3ee;
            margin: 0 0 0.65rem 0;
            padding-bottom: 0.4rem;
            border-bottom: 2px solid rgba(34, 211, 238, 0.45);
            display: inline-block;
          }
          .pulse-note-body {
            font-size: 1.02rem;
            line-height: 1.65;
            color: #e2e8f0;
            margin: 0;
          }
          .pulse-quote-card {
            background: rgba(22, 27, 38, 0.75);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(34, 211, 238, 0.15);
            border-left: 4px solid #22d3ee;
            padding: 0.85rem 1rem;
            margin-bottom: 0.6rem;
            border-radius: 12px;
            font-size: 0.92rem;
            line-height: 1.55;
            color: #cbd5e1;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
          }
          .pulse-q-ldquo, .pulse-q-rdquo {
            color: #22d3ee;
            font-weight: 700;
            opacity: 0.9;
          }
          .pulse-action-row {
            display: flex;
            align-items: flex-start;
            gap: 0.65rem;
            margin-bottom: 0.5rem;
            font-size: 0.95rem;
            line-height: 1.5;
            color: #e2e8f0;
          }
          .pulse-action-num {
            flex-shrink: 0;
            width: 1.5rem;
            height: 1.5rem;
            border-radius: 999px;
            background: rgba(34, 211, 238, 0.18);
            color: #22d3ee;
            font-weight: 700;
            font-size: 0.75rem;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 1px solid rgba(34, 211, 238, 0.35);
          }
          .pulse-meta {
            font-size: 0.8rem;
            color: #94a3b8;
            margin-top: 0.35rem;
          }
          .pulse-theme-line {
            margin: 0 0 0.5rem 0;
            font-size: 0.95rem;
            color: #94a3b8;
            line-height: 1.5;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="pulse-hero">
          <h1>Weekly product pulse</h1>
          <p>Executive snapshot from the latest saved pulse in your workspace.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    pulse = load_latest_pulse()
    if not pulse:
        st.info(
            "No pulse JSON found yet. From the project root run "
            "`python phase_2/fetch_reviews.py` then `python scripts/phase2_generate_pulse.py` "
            "(or place a bundle under `data/state/pulses/`)."
        )
        return

    top = pulse.get("top_themes") or []
    quotes = pulse.get("quotes") or []
    ideas = pulse.get("action_ideas") or []
    note = str(pulse.get("weekly_note") or "")

    _ga = html.escape(str(pulse.get("generated_at", "—")))
    st.markdown(
        f'<p class="pulse-meta">Updated <code>{_ga}</code></p>',
        unsafe_allow_html=True,
    )

    row_a, row_b = st.columns([1.15, 1], gap="large")
    with row_a:
        st.markdown('<h3 class="pulse-h3">Executive summary</h3>', unsafe_allow_html=True)
        _note_html = html.escape(note) if note else "—"
        st.markdown(f'<p class="pulse-note-body">{_note_html}</p>', unsafe_allow_html=True)

    with row_b:
        st.markdown('<h3 class="pulse-h3">Theme mix</h3>', unsafe_allow_html=True)
        _top_line = " · ".join(html.escape(str(t)) for t in top) if top else "—"
        st.markdown(
            '<p class="pulse-theme-line">' + _top_line + "</p>",
            unsafe_allow_html=True,
        )
        th = pulse.get("themes") or []
        if th and isinstance(th, list) and isinstance(th[0] if th else None, dict):
            st.dataframe(
                [{"Theme": t.get("label", ""), "Count": t.get("count", ""), "Notes": t.get("definition", "")} for t in th],
                use_container_width=True,
                hide_index=True,
                height=min(320, 52 + len(th) * 36),
            )
        elif th:
            st.json(th)

    st.markdown('<h3 class="pulse-h3">Voice of the customer</h3>', unsafe_allow_html=True)
    if quotes:
        for q in quotes[:3]:
            q_esc = html.escape(str(q))
            st.markdown(
                f'<div class="pulse-quote-card"><span class="pulse-q-ldquo">&ldquo;</span>{q_esc}'
                f'<span class="pulse-q-rdquo">&rdquo;</span></div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("No quotes in this bundle.")

    st.markdown('<h3 class="pulse-h3">Recommended actions</h3>', unsafe_allow_html=True)
    for i, a in enumerate(ideas[:3], 1):
        a_esc = html.escape(str(a))
        st.markdown(
            f'<div class="pulse-action-row"><span class="pulse-action-num">{i}</span><span>{a_esc}</span></div>',
            unsafe_allow_html=True,
        )

    st.download_button(
        "Export JSON",
        data=json.dumps(pulse, ensure_ascii=False, indent=2),
        file_name=f"{pulse.get('pulse_id', 'pulse')}.json",
        mime="application/json",
        use_container_width=True,
    )


def _render_voice_book_tab() -> None:
    st.markdown(
        """
        <div class="voice-panel-head">
          <span class="voice-panel-kicker">Advisor booking</span>
          <h2 class="voice-panel-title">Voice assistant</h2>
          <p class="voice-panel-desc">Book a call by voice or on-screen buttons. Audio stays off until you start.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # -----------------------------
    # Voice assistant (mic + buttons fallback)
    # -----------------------------

    def autoplay_audio(audio_bytes):
        if audio_bytes is None:
            return
        b64 = base64.b64encode(audio_bytes).decode()
        audio_html = f"""
            <audio autoplay="true" style="display:none">
                <source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg">
            </audio>
            <script>
                // Force play on some browsers that block autoplay
                document.addEventListener('DOMContentLoaded', function() {{
                    var audio = document.querySelector('audio');
                    if(audio) {{
                        audio.play().catch(function(e) {{
                            console.log('Autoplay blocked:', e);
                        }});
                    }}
                }});
            </script>
        """
        components.html(audio_html, height=0)

    def _append_once(role: str, text: str) -> None:
        log = st.session_state["voice_transcript_log"]
        if log and log[-1].get("role") == role and log[-1].get("text") == text:
            return
        log.append({"role": role, "text": text})

    def bot_say(text: str) -> None:
        _append_once("bot", text)
        # Queue this message for TTS exactly once; playback is handled centrally
        # so we can avoid replaying on reruns.
        st.session_state["voice_tts_queue"].append(text)

    # Session state init
    if "voice_stage" not in st.session_state:
        st.session_state["voice_stage"] = "idle"
    if "voice_transcript_log" not in st.session_state:
        st.session_state["voice_transcript_log"] = []
    if "voice_confirmed_done" not in st.session_state:
        st.session_state["voice_confirmed_done"] = False
    if "voice_tts_queue" not in st.session_state:
        st.session_state["voice_tts_queue"] = []
    if "voice_spoken_upto" not in st.session_state:
        st.session_state["voice_spoken_upto"] = 0
    if "voice_audio_unlocked" not in st.session_state:
        # Browsers may block autoplay until a user gesture. We'll still attempt autoplay,
        # but after the first click/record, this will be reliably allowed.
        st.session_state["voice_audio_unlocked"] = False
    if "voice_processing" not in st.session_state:
        st.session_state["voice_processing"] = False
    if "voice_mic_locked" not in st.session_state:
        st.session_state["voice_mic_locked"] = False
    if "voice_mic_epoch" not in st.session_state:
        st.session_state["voice_mic_epoch"] = 0
    if "voice_stt_last_sig" not in st.session_state:
        st.session_state["voice_stt_last_sig"] = None

    # Load pulse data once
    if "pulse_top_theme" not in st.session_state:
        try:
            pulse = load_latest_pulse() or {}
            st.session_state["pulse_top_theme"] = str((pulse.get("top_themes") or ["General Queries"])[0])
            st.session_state["pulse_weekly_note"] = str(pulse.get("weekly_note") or "")
            st.session_state["pulse_id"] = str(pulse.get("pulse_id") or "")
            st.session_state["pulse_obj"] = pulse
        except Exception:
            st.session_state["pulse_top_theme"] = "General Queries"
            st.session_state["pulse_weekly_note"] = ""
            st.session_state["pulse_id"] = ""
            st.session_state["pulse_obj"] = None

    top_theme_label = st.session_state.get("pulse_top_theme", "General Queries")

    # UI: speaking/listening indicators (.va-* styled in global theme)
    _stage_ind = st.session_state.get("voice_stage")
    _mic_stages_ind = ("await_yes_no", "await_topic", "await_slot")
    _mic_eligible = _has_env("ELEVENLABS_API_KEY") and _stage_ind in _mic_stages_ind

    indicator = st.empty()
    if _stage_ind == "idle":
        indicator.markdown(
            '<div class="va-ind"><span class="va-dots"><span></span><span></span><span></span></span>'
            "<span>Inactive — start when you’re ready</span></div>",
            unsafe_allow_html=True,
        )
    elif st.session_state.voice_processing:
        indicator.markdown(
            '<div class="va-ind"><span class="va-dots"><span></span><span></span><span></span></span>'
            "<span>Transcribing your response…</span></div>",
            unsafe_allow_html=True,
        )
    elif st.session_state.get("voice_mic_locked") and _mic_eligible:
        indicator.markdown(
            '<div class="va-ind"><span class="va-dots"><span></span><span></span><span></span></span>'
            "<span>Assistant is speaking…</span></div>",
            unsafe_allow_html=True,
        )
    elif _mic_eligible and not st.session_state.get("voice_mic_locked"):
        indicator.markdown(
            '<div class="va-ind"><span class="va-dot"></span><span>🎤 Your turn — speak now</span></div>',
            unsafe_allow_html=True,
        )
    else:
        indicator.markdown(
            '<div class="va-ind"><span class="va-dots"><span></span><span></span><span></span></span><span>Ready</span></div>',
            unsafe_allow_html=True,
        )

    # Not started: show tab but no audio / no flow until user opts in
    if st.session_state.get("voice_stage") == "idle":
        st.markdown(
            "Book an advisor call using voice or the buttons below. "
            "**No audio plays until you start.**"
        )
        if st.button("Start Voice Chat", type="primary", use_container_width=True, key="btn_start_voice_chat"):
            st.session_state["voice_stage"] = "greeting"
            st.rerun()
        st.caption("Tip: starting the chat also helps your browser allow voice playback.")
        st.stop()

    # Stage: greeting (run once)
    if st.session_state["voice_stage"] == "greeting":
        greeting = (
            "Hi! I am your INDMoney assistant. "
            f"I can see that many users are asking about {top_theme_label} today. "
            "I can help you book a call with an advisor for that. Would you like to proceed?"
        )
        bot_say(greeting)
        st.session_state["voice_stage"] = "await_yes_no"
        st.rerun()

    # Transcript UI (above buttons)
    for msg in st.session_state.get("voice_transcript_log", []):
        if msg.get("role") == "bot":
            st.chat_message("assistant").write(msg.get("text", ""))
        else:
            st.chat_message("user").write(msg.get("text", ""))

    # TTS playback: speak only NEW bot messages (avoid replay on reruns)
    if _has_env("ELEVENLABS_API_KEY"):
        q = st.session_state["voice_tts_queue"]
        i = int(st.session_state["voice_spoken_upto"])
        if i < len(q):
            # Always attempt autoplay. If browser blocks until gesture, audio may be silent;
            # after the first user interaction (mic/button), it should work.
            try:
                audio_bytes = tts_mp3_bytes(q[i])
            except Exception as e:
                st.error(f"TTS failed: {e}")
                st.session_state["voice_spoken_upto"] = i + 1
            else:
                autoplay_audio(audio_bytes)
                st.session_state["voice_spoken_upto"] = i + 1

    # Mic: always call st.audio_input every render when eligible; transcribe when it returns audio.
    has_voice_key = _has_env("ELEVENLABS_API_KEY")
    st.markdown("---")
    st.markdown("### Speak")

    if has_voice_key and st.session_state.get("voice_mic_locked"):
        if int(st.session_state["voice_spoken_upto"]) >= len(st.session_state["voice_tts_queue"]):
            st.session_state["voice_mic_locked"] = False
            st.session_state["voice_stt_last_sig"] = None
            st.session_state["voice_mic_epoch"] = int(st.session_state.get("voice_mic_epoch", 0)) + 1

    stage_for_mic = st.session_state.get("voice_stage")
    mic_stages = ("await_yes_no", "await_topic", "await_slot")

    if not has_voice_key:
        st.caption("Voice disabled (missing ELEVENLABS_API_KEY). Using buttons.")
    elif stage_for_mic not in mic_stages:
        st.caption("Use buttons to continue this step.")
    elif st.session_state.get("voice_mic_locked"):
        st.info("Please wait — the assistant is responding. The mic will unlock when playback is done.")
    else:
        # Return value is read every run; when not None the user just finished a recording.
        _epoch = int(st.session_state.get("voice_mic_epoch", 0))
        audio_data = st.audio_input(
            "Tap to record, then tap again to stop",
            key=f"voice_mic_{stage_for_mic}_{_epoch}",
        )
        if audio_data is not None:
            blob = audio_data.getvalue()
            if not blob or len(blob) < 80:
                st.session_state["voice_mic_epoch"] = int(st.session_state.get("voice_mic_epoch", 0)) + 1
                st.warning("Could not understand. Please try again or use buttons below.")
                st.rerun()
            else:
                sig = hash(blob)
                if st.session_state.get("voice_stt_last_sig") != sig:
                    st.session_state["voice_stt_last_sig"] = sig
                    st.session_state["voice_mic_locked"] = True
                    st.session_state["voice_processing"] = True
                    tmp_path = None
                    transcript = ""
                    try:
                        with st.spinner("Transcribing your response..."):
                            sfx = ".wav" if blob[:4] == b"RIFF" else ".webm"
                            fname = f"recording{sfx}"
                            with tempfile.NamedTemporaryFile(delete=False, suffix=sfx) as tf:
                                tf.write(blob)
                                tmp_path = tf.name
                            with open(tmp_path, "rb") as f:
                                file_bytes = f.read()
                            transcript = transcribe_audio_bytes(
                                audio_bytes=file_bytes,
                                filename=fname,
                                language_code="eng",
                            )
                    except Exception as e:
                        st.session_state["voice_mic_locked"] = False
                        st.session_state["voice_stt_last_sig"] = None
                        st.session_state["voice_mic_epoch"] = int(st.session_state.get("voice_mic_epoch", 0)) + 1
                        st.error(f"Transcription failed: {e}")
                        st.warning("Could not understand. Please try again or use buttons below.")
                        st.session_state["voice_processing"] = False
                        st.rerun()
                    finally:
                        st.session_state["voice_processing"] = False
                        if tmp_path:
                            try:
                                os.unlink(tmp_path)
                            except OSError:
                                pass

                    transcript = (transcript or "").strip()
                    if transcript:
                        st.success(f"You said: {transcript}")
                        _append_once("user", transcript)
                        low = transcript.lower()
                        stage_now = st.session_state.get("voice_stage")

                        if stage_now == "await_yes_no":
                            if any(w in low for w in ["yes", "sure", "okay", "proceed", "yeah"]):
                                bot_say("Great! What would you like to discuss? Choose a topic:")
                                st.session_state["voice_stage"] = "await_topic"
                                st.rerun()
                            elif any(w in low for w in ["no", "different", "other"]):
                                st.session_state["voice_stage"] = "ended"
                                bot_say("No problem! You can type your question under Chat / FAQ. Have a great day!")
                                st.rerun()
                            else:
                                bot_say("Sorry, I didn't catch that. Please say Yes or No.")
                                st.rerun()

                        elif stage_now == "await_topic":
                            if any(tok in low for tok in str(top_theme_label).lower().split()[:2]):
                                st.session_state["selected_topic"] = top_theme_label
                            elif any(w in low for w in ["sip", "fund", "performance"]):
                                st.session_state["selected_topic"] = "Fund Performance / SIP"
                            elif "nominee" in low:
                                st.session_state["selected_topic"] = "Nominee Updates"
                            elif "login" in low:
                                st.session_state["selected_topic"] = "Login Issues"
                            else:
                                st.session_state["selected_topic"] = "General Query"
                            bot_say(
                                "Perfect. I have two slots available. "
                                "Option 1: Tomorrow at 10 AM. "
                                "Option 2: Tomorrow at 3 PM. "
                                "Which one works for you?"
                            )
                            st.session_state["voice_stage"] = "await_slot"
                            st.rerun()

                        elif stage_now == "await_slot":
                            if any(w in low for w in ["10", "morning", "first", "one"]):
                                st.session_state["selected_slot"] = "Tomorrow 10:00 AM"
                                st.session_state["voice_stage"] = "confirmed"
                                st.rerun()
                            elif any(w in low for w in ["3", "afternoon", "second", "two"]):
                                st.session_state["selected_slot"] = "Tomorrow 3:00 PM"
                                st.session_state["voice_stage"] = "confirmed"
                                st.rerun()
                            else:
                                bot_say("Sorry, please say 10 AM or 3 PM.")
                                st.rerun()
                    else:
                        st.session_state["voice_mic_locked"] = False
                        st.session_state["voice_stt_last_sig"] = None
                        st.session_state["voice_mic_epoch"] = int(st.session_state.get("voice_mic_epoch", 0)) + 1
                        st.warning("Could not understand. Please try again or use buttons below.")
                        st.rerun()

    stage = st.session_state.get("voice_stage")

    # Stage: await_yes_no
    if stage == "await_yes_no":
        st.write("**Would you like to proceed?**")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Yes, book a call", key="btn_yes"):
                _append_once("user", "Yes")
                # Speak the next bot prompt *during* the click gesture (so autoplay works).
                bot_say("Great! What would you like to discuss? Choose a topic:")
                st.session_state["voice_stage"] = "await_topic"
                st.rerun()
        with col2:
            if st.button("❌ No thanks", key="btn_no"):
                st.session_state["voice_stage"] = "ended"
                _append_once("user", "No")
                bot_say("No problem! You can type your question under Chat / FAQ. Have a great day!")
                st.rerun()

    # Stage: await_topic (buttons only)
    elif stage == "await_topic":
        topics = [top_theme_label, "Fund Performance / SIP", "Nominee Updates", "Something Else"]
        for topic in topics:
            if st.button(f"📌 {topic}", key=f"topic_{topic}"):
                st.session_state["selected_topic"] = topic
                _append_once("user", topic)
                # Speak slot offer during the click gesture (so autoplay works).
                bot_say(
                    "Perfect. I have two slots available. "
                    "Option 1: Tomorrow at 10 AM. "
                    "Option 2: Tomorrow at 3 PM. "
                    "Which one works for you?"
                )
                st.session_state["voice_stage"] = "await_slot"
                st.rerun()

    # Stage: await_slot
    elif stage == "await_slot":
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🕙 Tomorrow 10:00 AM", key="slot_10"):
                st.session_state["selected_slot"] = "Tomorrow 10:00 AM"
                _append_once("user", "Tomorrow 10:00 AM")
                st.session_state["voice_stage"] = "confirmed"
                st.rerun()
        with col2:
            if st.button("🕒 Tomorrow 3:00 PM", key="slot_3"):
                st.session_state["selected_slot"] = "Tomorrow 3:00 PM"
                _append_once("user", "Tomorrow 3:00 PM")
                st.session_state["voice_stage"] = "confirmed"
                st.rerun()

    # Stage: confirmed (generate booking once, queue HITL once)
    elif stage == "confirmed":
        if not st.session_state.get("voice_confirmed_done", False):
            pulse_obj = st.session_state.get("pulse_obj", None)
            weekly_note = str(st.session_state.get("pulse_weekly_note") or "") or None
            pulse_id = str(st.session_state.get("pulse_id") or "") or None

            topic = str(st.session_state.get("selected_topic") or top_theme_label)
            slot_label = str(st.session_state.get("selected_slot") or "Tomorrow 10:00 AM")

            booking, path = create_voice_booking_artifact(
                topic=topic,
                slot_label=slot_label,
                pulse_theme=top_theme_label,
                pulse_id=pulse_id,
                market_context=weekly_note,
            )
            actions = generate_actions_from_booking(booking, pulse=pulse_obj if isinstance(pulse_obj, dict) else None)
            enqueue_actions(actions)

            st.session_state["booking_code"] = booking["booking_code"]
            st.session_state["booking_path"] = str(path)

            bot_say(
                "Your call is confirmed! "
                f"Your booking code is {booking['booking_code']}. "
                f"An advisor will call you {slot_label}. "
                "You will receive a confirmation shortly. "
                "Have a great day!"
            )

            st.session_state["voice_confirmed_done"] = True
            st.rerun()

        st.success("✅ Booking Confirmed!")
        st.metric("Booking Code", st.session_state.get("booking_code", ""))
        st.info(f"📅 Slot: {st.session_state.get('selected_slot')}")
        st.info(f"📌 Topic: {st.session_state.get('selected_topic')}")
        st.caption("Check Admin → Approval Center to see pending actions.")
        st.caption(f"Saved booking: `{st.session_state.get('booking_path','')}`")

        if st.button("🔄 Start over", key="restart"):
            for key in [
                "voice_stage",
                "voice_transcript_log",
                "selected_topic",
                "selected_slot",
                "booking_code",
                "booking_path",
                "voice_confirmed_done",
                "voice_last_tts",
                "voice_tts_queue",
                "voice_spoken_upto",
                "voice_mic_locked",
                "voice_mic_epoch",
                "voice_stt_last_sig",
                "voice_processing",
            ]:
                st.session_state.pop(key, None)
            st.session_state["voice_stage"] = "idle"
            st.session_state["voice_transcript_log"] = []
            st.session_state["voice_tts_queue"] = []
            st.session_state["voice_spoken_upto"] = 0
            st.session_state["voice_confirmed_done"] = False
            st.rerun()

    # Stage: ended
    elif stage == "ended":
        st.info("No problem! Switch to **Chat / FAQ** above and type your question there.")
        if st.button("🔄 Start over", key="restart_ended"):
            for key in [
                "voice_stage",
                "voice_transcript_log",
                "selected_topic",
                "selected_slot",
                "booking_code",
                "booking_path",
                "voice_confirmed_done",
                "voice_last_tts",
                "voice_tts_queue",
                "voice_spoken_upto",
                "voice_mic_locked",
                "voice_mic_epoch",
                "voice_stt_last_sig",
                "voice_processing",
            ]:
                st.session_state.pop(key, None)
            st.session_state["voice_stage"] = "idle"
            st.session_state["voice_transcript_log"] = []
            st.session_state["voice_tts_queue"] = []
            st.session_state["voice_spoken_upto"] = 0
            st.session_state["voice_confirmed_done"] = False
            st.rerun()


_ws = st.session_state.get("ops_workspace", "chat")
if _ws == "chat":
    _render_chat_faq()
elif _ws == "pulse":
    _render_weekly_pulse_dashboard()
else:
    _render_voice_book_tab()

with st.sidebar:
    st.divider()
    show_admin = st.toggle("Show admin section (pulse / approvals / evals)", value=False)

if show_admin:
    st.divider()
    st.subheader("Admin section")

    with st.expander("Weekly Pulse", expanded=False):
        st.caption("Pulse tab shows the latest saved bundle. CLI: `python phase_2/fetch_reviews.py` → `python scripts/phase2_generate_pulse.py`")
        st.caption("Optional Gemini themes/note: set `USE_GEMINI_PULSE=1` when `GEMINI_API_KEY` is available.")
        pulse = load_latest_pulse()
        if pulse:
            st.success(f"Latest pulse: `{pulse.get('pulse_id')}` · top theme: **{(pulse.get('top_themes') or ['—'])[0]}**")
        else:
            st.info("No pulse saved yet — run `fetch_reviews` / `phase2_generate_pulse` from the repo root.")

    with st.expander("Approval Center (HITL)", expanded=False):
        st.caption("Creates pending actions from latest booking; approve/reject updates local queue.")
        latest_booking = load_latest_booking()
        if latest_booking:
            st.write("Latest booking:")
            st.json(latest_booking)
            if st.button("Create pending actions from latest booking", key="enqueue_from_latest"):
                actions = generate_actions_from_booking(latest_booking)
                paths = enqueue_actions(actions)
                st.success(f"Enqueued {len(paths)} actions.")
        else:
            st.info("No booking found yet. Create one in the Voice & Book tab first.")

        pending = list_queue(status="pending")
        st.write(f"Pending actions: {len(pending)}")
        for item in pending:
            with st.expander(f"{item['id']} — {item['action_type']} — booking={item['payload'].get('booking_code')}"):
                st.json(item)
                cols = st.columns(2)
                if cols[0].button("Approve", key=f"approve_{item['id']}"):
                    set_status(item["id"], "approved")
                    st.rerun()
                if cols[1].button("Reject", key=f"reject_{item['id']}"):
                    set_status(item["id"], "rejected")
                    st.rerun()

    with st.expander("Evals", expanded=False):
        report_path = ROOT / "docs" / "EVALS_REPORT.md"
        if report_path.exists():
            st.success("Found eval report.")
            st.markdown(report_path.read_text(encoding="utf-8"))
        else:
            st.info("No eval report found yet. Run Phase 6.")
            st.code("python phase_6/run_evals.py")

