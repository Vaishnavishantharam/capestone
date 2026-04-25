from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from core.mcp.hitl import enqueue_actions, generate_actions_from_booking, list_queue, load_latest_booking, set_status
from core.pulse.load import load_latest_pulse
from core.rag.smartsync import answer_question
from core.voice.booking import run_text_booking_session, theme_aware_greeting


ROOT = Path(__file__).resolve().parents[1]


st.set_page_config(page_title="Investor Ops & Intelligence Suite", layout="wide")

st.title("Investor Ops & Intelligence Suite (INDMoney)")
st.caption("Facts-only mutual fund ops dashboard: Smart‑Sync Q&A, Weekly Pulse, Booking, HITL approvals, Evals.")


tabs = st.tabs(["Smart‑Sync Q&A", "Weekly Pulse", "Booking (chat)", "Approval Center", "Evals"])


with tabs[0]:
    st.subheader("Smart‑Sync Unified Search (Exit Load)")
    q = st.text_input(
        "Ask a question (try: “What is the exit load for HDFC Flexi Cap and why was I charged it?”)",
        value="",
    )
    if st.button("Answer", type="primary", disabled=not q.strip()):
        ans = answer_question(q.strip())
        st.text_area("Answer", ans.text, height=260)


with tabs[1]:
    st.subheader("Weekly Pulse")
    pulse = load_latest_pulse()
    if pulse:
        st.success(f"Loaded latest pulse: {pulse.get('pulse_id')}")
        st.json(pulse)
    else:
        st.info("No pulse found yet. Run Phase 2 to fetch reviews and generate a pulse.")
        st.code("python phase_2/fetch_reviews.py\npython phase_2/run_pulse.py")


with tabs[2]:
    st.subheader("Booking agent (chat fallback)")
    greeting, pulse_id, top_theme = theme_aware_greeting()
    st.write(greeting)
    if pulse_id:
        st.caption(f"Using pulse_id={pulse_id}, top_theme={top_theme}")

    topic = st.selectbox("Topic", ["Nominee update", "Login issues", "Statements / Tax Docs", "SIP / Mandates"])
    slot = st.radio("Choose slot", [1, 2], horizontal=True)
    time_pref = st.text_input("Optional time preference (no PII)", value="")

    if st.button("Confirm booking", type="primary"):
        try:
            res = run_text_booking_session(user_topic=topic, user_time_preference=time_pref, user_slot_choice=int(slot))
        except Exception as e:
            st.error(str(e))
        else:
            st.success(f"Booking confirmed: {res.booking_code}")
            st.write({"topic": res.topic, "slot_ist": res.slot_ist, "saved": res.persisted_path})


with tabs[3]:
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


with tabs[4]:
    st.subheader("Evals")
    report_path = ROOT / "docs" / "EVALS_REPORT.md"
    if report_path.exists():
        st.success("Found eval report.")
        st.markdown(report_path.read_text(encoding="utf-8"))
    else:
        st.info("No eval report found yet. Run Phase 6.")
        st.code("python phase_6/run_evals.py")

