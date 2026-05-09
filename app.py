"""
Streamlit UI for the LangGraph Compliance Investigation Agent.

Run:
    streamlit run app.py
"""
import uuid
import json
import streamlit as st
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agent.graph import compile_graph
from data.actions import log_decision, create_case, queue_sar, read_audit_log

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Compliance Investigation Agent",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sample transactions ────────────────────────────────────────────────────────

SAMPLE_TRANSACTIONS = {
    "Low Risk — Alice, small domestic ACH ($450)": {
        "id": "TXN-DEMO-001",
        "customer_id": "c001",
        "amount": 450.00,
        "currency": "USD",
        "type": "ACH",
        "recipient_name": "Netflix",
        "recipient_country": "US",
        "cross_border": False,
        "timestamp": "2025-05-09T10:30:00",
        "description": "Monthly subscription payment",
    },
    "Medium Risk — Maria, offshore wire ($8,500)": {
        "id": "TXN-DEMO-002",
        "customer_id": "c002",
        "amount": 8500.00,
        "currency": "USD",
        "type": "Wire",
        "recipient_name": "Unknown Offshore LLC",
        "recipient_country": "Cayman Islands",
        "cross_border": True,
        "timestamp": "2025-05-09T14:15:00",
        "description": "Business consulting services",
    },
    "High Risk — James, structuring + sanctions ($9,800)": {
        "id": "TXN-DEMO-003",
        "customer_id": "c003",
        "amount": 9800.00,
        "currency": "USD",
        "type": "Wire",
        "recipient_name": "Sunrise Financial SA",
        "recipient_country": "Panama",
        "cross_border": True,
        "timestamp": "2025-05-09T09:00:00",
        "description": "Investment transfer",
    },
    "High Risk — Alex, layering pattern ($25,000)": {
        "id": "TXN-DEMO-004",
        "customer_id": "c004",
        "amount": 25000.00,
        "currency": "USD",
        "type": "Wire",
        "recipient_name": "ABC Trading Panama",
        "recipient_country": "Panama",
        "cross_border": True,
        "timestamp": "2025-05-09T11:45:00",
        "description": "Trade finance",
    },
}

NODE_LABELS = {
    "fetch_history":        ("1", "Fetch Customer History",   "📋"),
    "check_sanctions_node": ("2", "Sanctions Check",          "🔍"),
    "analyze_pattern":      ("3", "Pattern Analysis (LLM)",   "🧠"),
    "calculate_risk":       ("4", "Risk Scoring",             "⚖️"),
    "auto_clear":           ("5", "Auto-Clear",               "✅"),
    "draft_report":         ("5", "Draft Report",             "📄"),
    "human_review":         ("6", "Human Review",             "👤"),
    "draft_sar":            ("5", "Draft SAR",                "🚨"),
    "escalate":             ("6", "Escalate / File SAR",      "📤"),
}

DECISION_CONFIG = {
    "cleared":   ("CLEARED",   "#28a745", "✅"),
    "escalated": ("ESCALATED", "#fd7e14", "⚠️"),
    "sar_filed": ("SAR FILED", "#dc3545", "🚨"),
}

# ── Session state init ─────────────────────────────────────────────────────────

def _init_session():
    defaults = {
        "memory": MemorySaver(),
        "thread_id": None,
        "awaiting_human": False,
        "completed_steps": [],    # list of (node_name, node_output_dict)
        "final_state": None,
        "partial_state": None,    # accumulated state when paused at human_review
        "running": False,
        "notification": None,     # toast message to show on next render
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _merge(accumulated: dict, node_output: dict) -> dict:
    """Merge a node's output into the accumulated state dict."""
    for k, v in node_output.items():
        if k == "step_log":
            accumulated["step_log"] = accumulated.get("step_log", []) + v
        else:
            accumulated[k] = v
    return accumulated


def _pluck(key: str, default=None):
    """
    Scan completed_steps for the last non-empty value of `key`.
    More reliable than reading from final_state/partial_state because
    completed_steps is populated directly from stream events.
    """
    result = default
    for _, output in st.session_state.completed_steps:
        v = output.get(key)
        if v is not None and v != "" and v != 0 and v != 0.0 and v != {}:
            result = v
    return result


_init_session()


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🏦 Compliance Agent")
    st.markdown("---")

    mode = st.radio("Transaction input", ["Pick a sample", "Paste JSON"], index=0)

    if mode == "Pick a sample":
        selected = st.selectbox("Sample transaction", list(SAMPLE_TRANSACTIONS.keys()))
        tx = SAMPLE_TRANSACTIONS[selected]
        st.json(tx, expanded=False)
    else:
        raw = st.text_area(
            "Transaction JSON",
            height=220,
            value=json.dumps(SAMPLE_TRANSACTIONS["Medium Risk — Maria, offshore wire ($8,500)"], indent=2),
        )
        try:
            tx = json.loads(raw)
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")
            st.stop()

    st.markdown("---")
    run_btn = st.button("Run Investigation", type="primary", use_container_width=True)

    if st.session_state.awaiting_human:
        st.warning("⏸ Awaiting analyst decision")

    if st.button("Reset", use_container_width=True):
        for k in ["thread_id", "awaiting_human", "running"]:
            st.session_state[k] = False if k == "awaiting_human" else None
        st.session_state.completed_steps = []
        st.session_state.final_state = None
        st.session_state.partial_state = None
        st.session_state.memory = MemorySaver()
        st.rerun()

    st.markdown("---")
    st.markdown(
        "**Graph flow:**\n"
        "```\nSTART\n"
        "  └─► fetch_history\n"
        "       └─► check_sanctions\n"
        "            └─► analyze_pattern\n"
        "                 └─► calculate_risk\n"
        "                      ├─[low]────► auto_clear\n"
        "                      ├─[medium]─► draft_report\n"
        "                      │             └─► human_review\n"
        "                      └─[high]───► draft_sar\n"
        "                                    └─► escalate\n"
        "```"
    )

# ── Toast notification (persisted across st.rerun) ────────────────────────────

if st.session_state.notification:
    st.toast(st.session_state.notification, icon="🔔")
    st.session_state.notification = None

# ── Header ─────────────────────────────────────────────────────────────────────

st.markdown("# 🏦 LangGraph Compliance Investigation Agent")
st.markdown(
    "An AI workflow that mirrors a bank investigator's step-by-step process: "
    "pull history → check sanctions → analyze patterns → score risk → decide."
)
st.markdown("---")

# ── Run investigation ──────────────────────────────────────────────────────────

app = compile_graph(checkpointer=st.session_state.memory)

if run_btn and not st.session_state.awaiting_human:
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.completed_steps = []
    st.session_state.final_state = None
    st.session_state.awaiting_human = False

    initial_state = {
        "transaction": tx,
        "customer_info": {},
        "customer_history": [],
        "velocity_metrics": {},
        "sanctions_result": {},
        "pattern_analysis": "",
        "risk_score": 0.0,
        "risk_level": "",
        "decision": "",
        "report": "",
        "sar_text": "",
        "sanctions_retries": 0,
        "error": None,
        "step_log": [],
    }
    config = {"configurable": {"thread_id": st.session_state.thread_id}}

    # Build accumulated state ourselves — get_state() doesn't reliably
    # carry mid-graph fields (risk_score, risk_level) after streaming.
    accumulated = {**initial_state, "step_log": []}

    with st.spinner("Running investigation workflow..."):
        try:
            for event in app.stream(initial_state, config, stream_mode="updates"):
                interrupted = False
                for raw_key, node_output in event.items():
                    # LangGraph 1.x may use tuple keys like ("", "node_name")
                    node_name = raw_key[-1] if isinstance(raw_key, tuple) else raw_key
                    if node_name == "__interrupt__":
                        # Mark but keep processing — node outputs may be
                        # batched in the same event dict as the interrupt signal.
                        interrupted = True
                    else:
                        st.session_state.completed_steps.append((node_name, node_output))
                        accumulated = _merge(accumulated, node_output)
                if interrupted:
                    st.session_state.awaiting_human = True
                    break
        except Exception as e:
            err = str(e)
            if "interrupt" in err.lower() or "GraphInterrupt" in type(e).__name__:
                st.session_state.awaiting_human = True
            else:
                st.error(f"Workflow error: {e}")

    # Always fetch the checkpoint — it is the authoritative source of state
    # because LangGraph saves to it before raising GraphInterrupt or ending.
    snap = app.get_state(config)

    # Detect interrupt via snapshot (covers versions that raise before yielding events)
    if not st.session_state.awaiting_human and snap and getattr(snap, "next", None):
        st.session_state.awaiting_human = True

    if st.session_state.awaiting_human:
        # Merge checkpoint values into accumulated so we always have risk_score,
        # risk_level, report, etc. even when the stream raised before yielding them.
        if snap and snap.values:
            sv = snap.values
            for k, v in sv.items():
                if k == "step_log":
                    if len(v) > len(accumulated.get("step_log", [])):
                        st.write("step_log in accumulated:", accumulated.get("step_log"))
                        accumulated["step_log"] = v
                elif v not in (None, "", 0, 0.0, {}, []):
                    accumulated[k] = v

            # Final fallback: parse risk_score/risk_level directly from step_log.
            # step_log uses operator.add so LangGraph always accumulates it correctly,
            # unlike plain fields (risk_score) which may be 0.0 in the checkpoint.
            if accumulated.get("risk_score", 0.0) == 0.0:
                import re as _re
                st.write("accumulated risk_score:", accumulated.get("risk_score"))
                st.write("step_log:", accumulated.get("step_log"))
                st.write("snap.values:", snap.values if snap else None)
                for _entry in accumulated.get("step_log", []):
                    _m = _re.search(r"\[calculate_risk\] Score: (\d+)/100 → (\w+)", _entry)
                    if _m:
                        accumulated["risk_score"] = float(_m.group(1))
                        if not accumulated.get("risk_level"):
                            accumulated["risk_level"] = _m.group(2).lower()
                        break

            # Fill in any nodes whose events weren't yielded before the interrupt
            # (e.g. calculate_risk may be in the checkpoint but not in the stream).
            if True:
                import re
                _NODE_FIELDS = {
                    "fetch_history":       ("customer_info", "customer_history", "velocity_metrics"),
                    "check_sanctions_node":("sanctions_result",),
                    "analyze_pattern":     ("pattern_analysis",),
                    "calculate_risk":      ("risk_score", "risk_level"),
                    "draft_report":        ("report",),
                    "draft_sar":           ("sar_text",),
                    "escalate":            ("decision",),
                    "auto_clear":          ("decision", "report"),
                }
                for log_entry in sv.get("step_log", []):
                    m = re.match(r"\[(\w+)\]", log_entry)
                    if not m:
                        continue
                    node_key = m.group(1)
                    fields = _NODE_FIELDS.get(node_key, ())
                    node_out = {f: sv[f] for f in fields if f in sv}
                    node_out["step_log"] = [log_entry]
                    already = [n for n, _ in st.session_state.completed_steps]
                    if node_key not in already:
                        st.session_state.completed_steps.append((node_key, node_out))

        st.session_state.partial_state = accumulated
    else:
        # Parse risk_score/risk_level from step_log as fallback (same as interrupt path).
        if accumulated.get("risk_score", 0.0) == 0.0:
            import re as _re
            for _entry in accumulated.get("step_log", []):
                _m = _re.search(r"\[calculate_risk\] Score: (\d+)/100 → (\w+)", _entry)
                if _m:
                    accumulated["risk_score"] = float(_m.group(1))
                    if not accumulated.get("risk_level"):
                        accumulated["risk_level"] = _m.group(2).lower()
                    break

        st.session_state.final_state = accumulated
        tx_id      = accumulated.get("transaction", {}).get("id", "TXN-?")
        customer   = accumulated.get("customer_info", {}).get("name", "Unknown")
        decision   = _pluck("decision",    default=accumulated.get("decision", ""))
        risk_score = accumulated.get("risk_score", 0.0)
        risk_level = accumulated.get("risk_level", "")
        if decision:
            log_decision(
                tx_id, customer, decision,
                risk_score, risk_level,
                analyst="system (auto)",
            )
            if decision == "sar_filed":
                queue_sar(
                    tx_id, customer, risk_score,
                    _pluck("sar_text", default="") or _pluck("report", default=""),
                )
                st.session_state.notification = (
                    f"🚨 High-risk transaction auto-escalated. "
                    f"SAR queued for **{tx_id}**."
                )
            elif decision == "cleared":
                st.session_state.notification = (
                    f"✅ Transaction **{tx_id}** auto-cleared (low risk)."
                )

    st.rerun()


# ── Step timeline ──────────────────────────────────────────────────────────────

if st.session_state.completed_steps:
    st.subheader("Investigation Timeline")

    for node_name, node_output in st.session_state.completed_steps:
        if node_name not in NODE_LABELS:
            continue
        step_num, label, icon = NODE_LABELS[node_name]
        logs = node_output.get("step_log", [])
        raw_log = logs[-1] if logs else ""
        log_text = raw_log.split("] ", 1)[-1] if "] " in raw_log else raw_log

        with st.expander(f"{icon} Step {step_num}: {label}", expanded=False):
            # Show the relevant output fields for this node
            skip = {"step_log", "customer_history"}  # too verbose to show raw
            display = {k: v for k, v in node_output.items() if k not in skip}

            if node_name == "fetch_history":
                info = node_output.get("customer_info", {})
                vel = node_output.get("velocity_metrics", {})
                hist = node_output.get("customer_history", [])
                c1, c2, c3 = st.columns(3)
                c1.metric("Customer", info.get("name", "Unknown"))
                c2.metric("Account Age (days)", info.get("account_age_days", "?"))
                c3.metric("Transactions (7d)", vel.get("tx_count_7d", 0))
                c1.metric("Avg Amount", f"${vel.get('avg_amount', 0):,.2f}")
                c2.metric("Total 7d", f"${vel.get('total_7d', 0):,.2f}")
                c3.metric("Cross-border txns", vel.get("cross_border_count", 0))
                if vel.get("structuring_flag"):
                    st.warning("Structuring pattern detected in history (amounts near $10,000 threshold)")

            elif node_name == "check_sanctions_node":
                sr = node_output.get("sanctions_result", {})
                if sr.get("error"):
                    st.warning(f"API error: {sr['error']} — retrying...")
                elif sr.get("match"):
                    st.error(
                        f"SANCTIONS HIT: '{sr['matched_entity']}' on {sr['list']} list\n\n"
                        f"Reason: {sr['reason']}"
                    )
                else:
                    st.success("No sanctions match found.")

            elif node_name == "analyze_pattern":
                analysis = node_output.get("pattern_analysis", "")
                st.markdown(analysis)

            elif node_name == "calculate_risk":
                score = node_output.get("risk_score", 0)
                level = node_output.get("risk_level", "")
                colour = {"low": "green", "medium": "orange", "high": "red"}.get(level, "gray")
                st.markdown(
                    f"**Risk Score:** `{score:.0f} / 100`  "
                    f"**Level:** :{colour}[{level.upper()}]"
                )
                st.progress(int(score) / 100)

            elif node_name in ("draft_report", "auto_clear"):
                report = node_output.get("report", "")
                if report:
                    st.markdown(report)

            elif node_name == "draft_sar":
                sar = node_output.get("sar_text", "")
                if sar:
                    st.markdown(sar)

            elif node_name == "escalate":
                st.error("Transaction escalated. SAR queued for FinCEN submission.")

            st.caption(log_text)


# ── Human-in-the-loop panel ───────────────────────────────────────────────────

if st.session_state.awaiting_human:
    st.markdown("---")
    st.subheader("👤 Analyst Review Required")

    # Read from partial_state (built by _merge during streaming — reliable regardless
    # of how LangGraph formats stream event keys).
    _ps        = st.session_state.partial_state or {}
    risk_score = _ps.get("risk_score", 0.0)
    risk_level = _ps.get("risk_level", "medium").upper()
    report_text = _ps.get("report", "")

    st.info(f"Risk score: **{risk_score:.0f}/100** ({risk_level}) — analyst decision required.")
    st.markdown("#### Investigation Report")
    st.markdown(report_text or "_Report not available._")

    st.markdown("#### Your Decision")
    col1, col2, col3 = st.columns(3)

    def _resume(decision_value: str, spinner_label: str) -> dict:
        """Resume the paused graph and return the updated accumulated state."""
        config  = {"configurable": {"thread_id": st.session_state.thread_id}}
        resumed = dict(st.session_state.partial_state or {})
        with st.spinner(spinner_label):
            try:
                for event in app.stream(Command(resume=decision_value), config, stream_mode="updates"):
                    interrupted = False
                    for raw_key, node_output in event.items():
                        node_name = raw_key[-1] if isinstance(raw_key, tuple) else raw_key
                        if node_name == "__interrupt__":
                            interrupted = True
                        else:
                            st.session_state.completed_steps.append((node_name, node_output))
                            resumed = _merge(resumed, node_output)
                    if interrupted:
                        break
            except Exception:
                pass
        st.session_state.awaiting_human = False
        st.session_state.final_state = resumed
        return resumed

    tx_id         = _ps.get("transaction", {}).get("id", "TXN-?")
    customer      = _ps.get("customer_info", {}).get("name", "Unknown")
    sar_narrative = _ps.get("sar_text", "")

    with col1:
        if st.button("✅ Clear Transaction", use_container_width=True):
            _resume("cleared", "Clearing transaction...")
            log_decision(tx_id, customer, "cleared", risk_score, risk_level)
            st.session_state.notification = (
                f"✅ Transaction **{tx_id}** cleared. Decision written to audit log."
            )
            st.rerun()

    with col2:
        if st.button("⚠️ Escalate to Supervisor", use_container_width=True):
            _resume("escalated", "Escalating...")
            case_file = create_case(tx_id, customer, risk_score, report_text)
            log_decision(tx_id, customer, "escalated", risk_score, risk_level)
            st.session_state.notification = (
                f"⚠️ Case **{case_file.stem}** created. "
                "Email sent to senior_analyst@bank.com."
            )
            st.rerun()

    with col3:
        if st.button("🚨 File SAR", use_container_width=True):
            _resume("sar_filed", "Filing SAR...")
            sar_file = queue_sar(tx_id, customer, risk_score,
                                 sar_narrative or report_text)
            log_decision(tx_id, customer, "sar_filed", risk_score, risk_level)
            st.session_state.notification = (
                f"🚨 SAR **{sar_file.stem}** queued for FinCEN submission. "
                "Account flagged for enhanced monitoring."
            )
            st.rerun()


# ── Final result banner ────────────────────────────────────────────────────────

if st.session_state.final_state:
    st.markdown("---")
    state = st.session_state.final_state
    decision = state.get("decision", "")
    label, colour, icon = DECISION_CONFIG.get(decision, (decision.upper(), "#6c757d", "•"))

    st.markdown(
        f"""
        <div style="
            background:{colour}22;
            border:2px solid {colour};
            border-radius:10px;
            padding:24px;
            text-align:center;
        ">
            <h2 style="color:{colour};margin:0">{icon} {label}</h2>
            <p style="margin:8px 0 0;color:#555">
                Risk score: <strong>{state.get('risk_score', 0):.0f}/100</strong>
                &nbsp;|&nbsp;
                Level: <strong>{state.get('risk_level', '').upper()}</strong>
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Audit log
    with st.expander("Full audit log", expanded=False):
        for entry in state.get("step_log", []):
            clean = entry.split("] ", 1)[-1] if "] " in entry else entry
            st.markdown(f"- {clean}")


# ── Recent Actions panel ───────────────────────────────────────────────────────

col_title, col_btn = st.columns([5, 1])
col_title.subheader("Recent Actions")

if col_btn.button("🗑 Clear Log", use_container_width=True):
    DATA_DIR = __import__("pathlib").Path("data")
    for f in [DATA_DIR / "audit_log.json"] + \
              list((DATA_DIR / "cases").glob("*.json")) + \
              list((DATA_DIR / "sar_queue").glob("*.json")):
        f.unlink(missing_ok=True)
    st.session_state.notification = "🗑 Audit log, cases, and SAR queue cleared."
    st.rerun()

audit_records = read_audit_log()

if not audit_records:
    st.caption("No decisions recorded yet. Run an investigation and make a decision above.")
else:
    import pandas as pd

    df = pd.DataFrame(audit_records[::-1])   # newest first
    df["risk_score"] = df["risk_score"].apply(lambda x: f"{x:.0f}")

    DECISION_BADGE = {
        "cleared":   "✅ Cleared",
        "escalated": "⚠️ Escalated",
        "sar_filed": "🚨 SAR Filed",
    }
    df["decision"] = df["decision"].map(lambda d: DECISION_BADGE.get(d, d))
    df = df.rename(columns={
        "timestamp":     "Time (UTC)",
        "tx_id":         "Transaction ID",
        "customer_name": "Customer",
        "risk_score":    "Score",
        "risk_level":    "Level",
        "decision":      "Decision",
        "analyst":       "Analyst",
    })

    st.dataframe(
        df[["Time (UTC)", "Transaction ID", "Customer", "Score", "Level", "Decision", "Analyst"]],
        use_container_width=True,
        hide_index=True,
    )

    col_a, col_b, col_c = st.columns(3)
    cases_dir  = __import__("pathlib").Path("data/cases")
    sar_dir    = __import__("pathlib").Path("data/sar_queue")
    case_files = sorted(cases_dir.glob("*.json"), reverse=True) if cases_dir.exists() else []
    sar_files  = sorted(sar_dir.glob("*.json"),   reverse=True) if sar_dir.exists()   else []

    col_a.metric("Total Decisions", len(audit_records))
    col_b.metric("Open Cases",      len(case_files))
    col_c.metric("SAR Queue",       len(sar_files))

    if case_files:
        with st.expander(f"Case files ({len(case_files)})", expanded=False):
            for f in case_files[:5]:
                data = __import__("json").loads(f.read_text(encoding="utf-8"))
                st.markdown(
                    f"**{data['case_id']}** — {data['customer_name']} — "
                    f"Score {data['risk_score']:.0f} — `{data['status']}`"
                )
                for action in data.get("_mock_actions", []):
                    st.caption(f"  → {action}")

    if sar_files:
        with st.expander(f"SAR queue ({len(sar_files)})", expanded=False):
            for f in sar_files[:5]:
                data = __import__("json").loads(f.read_text(encoding="utf-8"))
                st.markdown(
                    f"**{data['sar_id']}** — {data['customer_name']} — "
                    f"Score {data['risk_score']:.0f} — `{data['fincen_submission']}`"
                )
                for action in data.get("_mock_actions", []):
                    st.caption(f"  → {action}")
