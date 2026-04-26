from __future__ import annotations

import json
import os
import base64
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from core.mcp.hitl import enqueue_actions, generate_actions_from_booking, list_queue, load_latest_booking, set_status
from core.pulse.load import load_latest_pulse
from core.rag.smartsync import answer_question, answer_question_gemini
from core.stt.elevenlabs import transcribe_audio_bytes
from core.tts.elevenlabs import tts_mp3_bytes
from core.voice.booking import create_voice_booking_artifact, theme_aware_greeting


ROOT = Path(__file__).resolve().parents[1]

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

st.set_page_config(page_title="Investor Ops & Intelligence Suite", layout="wide")

with st.sidebar:
    st.subheader("Admin")
    with st.expander("Runtime status", expanded=False):
        env_text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
        env_has_eleven_line = any(ln.strip().startswith("ELEVENLABS_API_KEY=") for ln in env_text.splitlines())
        st.write(
            {
                "env_file_exists": ENV_PATH.exists(),
                "env_file_has_ELEVENLABS_API_KEY_line": env_has_eleven_line,
                "GEMINI_API_KEY": "set" if _has_env("GEMINI_API_KEY") else "missing",
                "ELEVENLABS_API_KEY": "set" if _has_env("ELEVENLABS_API_KEY") else "missing",
                "ELEVENLABS_API_KEY_len": len(_get_env("ELEVENLABS_API_KEY")),
                "GEMINI_MODEL": _get_env("GEMINI_MODEL") or "gemini-1.5-flash",
                "ELEVENLABS_VOICE_ID": _get_env("ELEVENLABS_VOICE_ID") or "21m00Tcm4TlvDq8ikWAM",
            }
        )

st.title("Investor Ops & Intelligence Suite (INDMoney)")
st.caption("Facts-only mutual fund ops dashboard: Smart‑Sync Q&A, Weekly Pulse, Booking, HITL approvals, Evals.")

def _intent_is_booking(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in ["book", "booking", "schedule", "call", "advisor", "appointment"])


def _render_chat_faq() -> None:
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

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    user_text = st.chat_input("Ask a question about HDFC schemes (facts-only)")
    if user_text is None:
        user_text = ""
    user_text = (user_text or "").strip()

    if user_text:
        st.session_state.messages.append({"role": "user", "content": user_text})
        with st.chat_message("user"):
            st.markdown(user_text)

        # Smart‑Sync Q&A only (booking happens in the Voice & Book tab).
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


left, right = st.tabs(["💬 Chat / FAQ", "📞 Voice & Book"])

with left:
    st.subheader("Smart‑Sync Unified Search (HDFC schemes)")
    c = st.columns([1, 1, 2])
    st.session_state.use_gemini = c[0].toggle(
        "Gemini rewrite",
        value=bool(st.session_state.get("use_gemini", False)),
        disabled=not _has_env("GEMINI_API_KEY"),
    )
    st.session_state.use_tts = c[1].toggle(
        "Speak answer",
        value=bool(st.session_state.get("use_tts", False)),
        disabled=not _has_env("ELEVENLABS_API_KEY"),
    )
    if c[2].button("Reset chat"):
        for k in ["messages"]:
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()

    _render_chat_faq()

with right:
    st.subheader("Voice assistant")

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
        st.session_state["voice_stage"] = "greeting"
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

    # UI: speaking/listening indicators
    st.markdown(
        """
        <style>
          .va-ind { display:flex; justify-content:center; align-items:center; gap:10px; margin: 6px 0 14px 0; font-weight: 700; }
          .va-dot { width:10px; height:10px; border-radius:999px; background:#ff3b30; animation: va_pulse 1.2s infinite; }
          .va-dots span{ display:inline-block; width:6px; height:6px; margin:0 2px; background:#333; border-radius:999px; animation: va_bounce 1.2s infinite; opacity:0.5;}
          .va-dots span:nth-child(2){ animation-delay: 0.2s;}
          .va-dots span:nth-child(3){ animation-delay: 0.4s;}
          @keyframes va_pulse { 0%{ transform:scale(0.9); opacity:0.5;} 50%{ transform:scale(1.1); opacity:1;} 100%{ transform:scale(0.9); opacity:0.5;} }
          @keyframes va_bounce { 0%,80%,100%{ transform:translateY(0); opacity:0.4;} 40%{ transform:translateY(-6px); opacity:1;} }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _stage_ind = st.session_state.get("voice_stage")
    _mic_stages_ind = ("await_yes_no", "await_topic", "await_slot")
    _mic_eligible = _has_env("ELEVENLABS_API_KEY") and _stage_ind in _mic_stages_ind

    indicator = st.empty()
    if st.session_state.voice_processing:
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
                                bot_say("No problem! You can type your question in the Chat tab. Have a great day!")
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
                bot_say("No problem! You can type your question in the Chat tab. Have a great day!")
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
            ]:
                st.session_state.pop(key, None)
            st.rerun()

    # Stage: ended
    elif stage == "ended":
        st.info("No problem! You can type your question in the Chat tab.")
        if st.button("🔄 Start over", key="restart_ended"):
            for key in ["voice_stage", "voice_transcript_log", "selected_topic", "selected_slot", "booking_code", "booking_path", "voice_confirmed_done", "voice_last_tts"]:
                st.session_state.pop(key, None)
            st.rerun()

with st.sidebar:
    st.divider()
    show_admin = st.toggle("Show admin section (pulse / approvals / evals)", value=False)

if show_admin:
    st.divider()
    st.subheader("Admin section")

    with st.expander("Weekly Pulse", expanded=False):
        st.caption("To enable Gemini pulse generation set `USE_GEMINI_PULSE=1` in Railway variables.")
        pulse = load_latest_pulse()
        if pulse:
            st.success(f"Loaded latest pulse: {pulse.get('pulse_id')}")
            st.json(pulse)
        else:
            st.info("No pulse found yet. Run Phase 2 to fetch reviews and generate a pulse.")
            st.code("python phase_2/fetch_reviews.py\npython phase_2/run_pulse.py")

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

