from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from core.mcp.hitl import enqueue_actions, generate_actions_from_booking, list_queue, load_latest_booking, set_status
from core.pulse.load import load_latest_pulse
from core.rag.smartsync import answer_question, answer_question_gemini
from core.stt.elevenlabs import transcribe_audio_bytes
from core.tts.elevenlabs import tts_mp3_bytes
from core.voice.booking import run_text_booking_session, theme_aware_greeting


ROOT = Path(__file__).resolve().parents[1]

def _load_dotenv_fallback(path: Path) -> None:
    """
    Minimal .env loader (avoids extra dependency on python-dotenv).
    Only sets vars that are not already present in the process env.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv_fallback(ROOT / ".env")

def _has_env(key: str) -> bool:
    return bool(os.environ.get(key, "").strip())

st.set_page_config(page_title="Investor Ops & Intelligence Suite", layout="wide")

with st.sidebar:
    st.subheader("Runtime status")
    st.write(
        {
            "GEMINI_API_KEY": "set" if _has_env("GEMINI_API_KEY") else "missing",
            "ELEVENLABS_API_KEY": "set" if _has_env("ELEVENLABS_API_KEY") else "missing",
            "GEMINI_MODEL": os.environ.get("GEMINI_MODEL", "gemini-1.5-flash"),
            "ELEVENLABS_VOICE_ID": os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
        }
    )

st.title("Investor Ops & Intelligence Suite (INDMoney)")
st.caption("Facts-only mutual fund ops dashboard: Smart‑Sync Q&A, Weekly Pulse, Booking, HITL approvals, Evals.")

def _intent_is_booking(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in ["book", "booking", "schedule", "call", "advisor", "appointment"])


def _render_chat() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Hi — I’m your INDMoney Investor Ops assistant.\n\n"
                    "You can ask factual HDFC scheme questions (exit load, expense ratio, minimum SIP, lock-in). "
                    "Or say “book an advisor call” to schedule a tentative slot."
                ),
            }
        ]
    if "mode" not in st.session_state:
        st.session_state.mode = "qa"  # qa | booking
    if "pending_user_text" not in st.session_state:
        st.session_state.pending_user_text = ""

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    with st.expander("Voice (talk) — records and transcribes", expanded=True):
        audio = st.audio_input("Hold to record, then release")
        if audio is not None:
            if not _has_env("ELEVENLABS_API_KEY"):
                st.warning("Voice recorded, but voice transcription is disabled until ELEVENLABS_API_KEY is set.")
            else:
                try:
                    raw = audio.getvalue()
                    txt = transcribe_audio_bytes(audio_bytes=raw, filename="question.wav", language_code="eng")
                except Exception as e:
                    st.error(f"Transcription failed: {e}")
                else:
                    if txt.strip():
                        st.session_state.pending_user_text = txt.strip()
                        st.success(f"Transcribed: {txt.strip()}")
                    else:
                        st.warning("Could not transcribe audio. Try again or type your question.")

    user_text = st.chat_input("Ask a question, or say: book an advisor call")
    if user_text is None:
        user_text = ""
    user_text = (user_text or "").strip()
    if not user_text and st.session_state.pending_user_text:
        user_text = st.session_state.pending_user_text
        st.session_state.pending_user_text = ""

    if user_text:
        st.session_state.messages.append({"role": "user", "content": user_text})
        with st.chat_message("user"):
            st.markdown(user_text)

        # Route: booking intent switches to booking mode (still in same chat).
        if _intent_is_booking(user_text):
            st.session_state.mode = "booking"
            greeting, pulse_id, top_theme = theme_aware_greeting()
            booking_intro = greeting
            if pulse_id:
                booking_intro += f"\n\n(Briefed by weekly pulse `{pulse_id}` — top theme: **{top_theme}**.)"
            booking_intro += "\n\nTell me the topic and pick a slot below."
            st.session_state.messages.append({"role": "assistant", "content": booking_intro})
            with st.chat_message("assistant"):
                st.markdown(booking_intro)
            st.rerun()

        # QA mode (Smart‑Sync)
        use_llm = _has_env("GEMINI_API_KEY") and st.session_state.get("use_gemini", False)
        ans = answer_question_gemini(user_text) if use_llm else answer_question(user_text)
        st.session_state.messages.append({"role": "assistant", "content": ans.text})
        with st.chat_message("assistant"):
            st.markdown(ans.text)
            if _has_env("ELEVENLABS_API_KEY") and st.session_state.get("use_tts", False):
                try:
                    st.audio(tts_mp3_bytes(ans.text), format="audio/mp3")
                except Exception as e:
                    st.error(f"TTS failed: {e}")


def _render_booking_controls() -> None:
    if st.session_state.get("mode") != "booking":
        return
    st.divider()
    st.subheader("Booking (inside chat)")
    st.caption("This simulates a compliant pre-booking flow (no PII).")

    topic = st.selectbox("Topic", ["Nominee update", "Login issues", "Statements / Tax Docs", "SIP / Mandates"])
    slot = st.radio("Choose slot", [1, 2], horizontal=True)
    time_pref = st.text_input("Optional time preference (no PII)", value="")

    cols = st.columns([1, 1, 3])
    if cols[0].button("Confirm booking", type="primary"):
        try:
            res = run_text_booking_session(user_topic=topic, user_time_preference=time_pref, user_slot_choice=int(slot))
        except Exception as e:
            msg = f"Booking failed: {e}"
            st.session_state.messages.append({"role": "assistant", "content": msg})
            with st.chat_message("assistant"):
                st.error(msg)
        else:
            msg = (
                f"Booking confirmed: **{res.booking_code}**\n\n"
                f"- Topic: {res.topic}\n"
                f"- Slot (IST): {res.slot_ist}\n"
                f"- Saved: `{res.persisted_path}`\n\n"
                "If you want, say “create approvals” to generate HITL actions in the Approval Center tab."
            )
            st.session_state.messages.append({"role": "assistant", "content": msg})
            with st.chat_message("assistant"):
                st.markdown(msg)
            st.session_state.mode = "qa"
            st.rerun()
    if cols[1].button("Cancel booking"):
        st.session_state.mode = "qa"
        st.session_state.messages.append({"role": "assistant", "content": "Okay — cancelled booking flow. Ask me any fund question."})
        st.rerun()


tabs = st.tabs(["Voice Chat Bot", "Weekly Pulse", "Approval Center", "Evals"])

with tabs[0]:
    st.subheader("One unified assistant (voice + chat)")
    st.caption("Answers facts-only HDFC scheme questions and can schedule an advisor booking in the same conversation.")

    c = st.columns([1, 1, 2])
    st.session_state.use_gemini = c[0].toggle("Gemini rewrite", value=bool(st.session_state.get("use_gemini", False)), disabled=not _has_env("GEMINI_API_KEY"))
    st.session_state.use_tts = c[1].toggle("ElevenLabs voice", value=bool(st.session_state.get("use_tts", False)), disabled=not _has_env("ELEVENLABS_API_KEY"))
    if c[2].button("Reset chat"):
        for k in ["messages", "mode", "pending_user_text"]:
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()

    _render_chat()
    _render_booking_controls()

with tabs[1]:
    st.subheader("Weekly Pulse")
    st.caption("To enable Gemini pulse generation set `USE_GEMINI_PULSE=1` in Railway variables.")
    pulse = load_latest_pulse()
    if pulse:
        st.success(f"Loaded latest pulse: {pulse.get('pulse_id')}")
        st.json(pulse)
    else:
        st.info("No pulse found yet. Run Phase 2 to fetch reviews and generate a pulse.")
        st.code("python phase_2/fetch_reviews.py\npython phase_2/run_pulse.py")


with tabs[2]:
    st.subheader("Human-in-the-Loop Approval Center (mock)")
    st.caption("Creates pending actions from latest booking; approve/reject updates local queue.")

    latest_booking = load_latest_booking()
    if latest_booking:
        st.write("Latest booking:")
        st.json(latest_booking)
        if st.button("Create pending actions from latest booking"):
            actions = generate_actions_from_booking(latest_booking)
            paths = enqueue_actions(actions)
            st.success(f"Enqueued {len(paths)} actions.")
    else:
        st.info("No booking found yet. Create one in the Booking tab first.")

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


with tabs[3]:
    st.subheader("Evals")
    report_path = ROOT / "docs" / "EVALS_REPORT.md"
    if report_path.exists():
        st.success("Found eval report.")
        st.markdown(report_path.read_text(encoding="utf-8"))
    else:
        st.info("No eval report found yet. Run Phase 6.")
        st.code("python phase_6/run_evals.py")

