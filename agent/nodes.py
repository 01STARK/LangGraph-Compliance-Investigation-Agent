"""
LangGraph node functions.
Each function receives the full InvestigationState and returns a dict
of fields to update — LangGraph merges these into the state.
"""
import json
import os
import random

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from agent.state import InvestigationState
from agent.tools import (
    get_customer_info,
    get_customer_history,
    compute_velocity,
    check_sanctions,
)
from agent.prompts import PATTERN_ANALYSIS_PROMPT, REPORT_PROMPT, SAR_PROMPT

load_dotenv()

# ── LLM singleton ──────────────────────────────────────────────────────────────

def _get_llm() -> ChatGroq:
    try:
        import streamlit as st
        api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    except Exception:
        api_key = os.getenv("GROQ_API_KEY")
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0,
        api_key=api_key,
    )


# ── Helper ─────────────────────────────────────────────────────────────────────

def _fmt(obj) -> str:
    """Pretty-print any value for prompt injection."""
    if isinstance(obj, (dict, list)):
        return json.dumps(obj, indent=2, default=str)
    return str(obj)


def _history_summary(history: list[dict]) -> str:
    if not history:
        return "No prior transaction history."
    lines = []
    for t in history[:10]:
        lines.append(
            f"  {t.get('timestamp','?')[:10]}  ${t.get('amount',0):>10,.2f}"
            f"  {t.get('type','?'):<10}  {t.get('recipient_name','?')}"
        )
    suffix = f"\n  ... and {len(history)-10} more" if len(history) > 10 else ""
    return "\n".join(lines) + suffix


# ── Node 1: Fetch customer history ────────────────────────────────────────────

def fetch_history(state: InvestigationState) -> dict:
    tx = state["transaction"]
    customer_id = tx.get("customer_id", "")

    info = get_customer_info(customer_id)
    history = get_customer_history(customer_id)
    velocity = compute_velocity(history)

    log = (
        f"[fetch_history] Customer '{info.get('name', customer_id)}' — "
        f"{len(history)} transactions on record, "
        f"{velocity['tx_count_7d']} in last 7 days."
    )
    return {
        "customer_info": info,
        "customer_history": history,
        "velocity_metrics": velocity,
        "step_log": [log],
    }


# ── Node 2: Sanctions check (with simulated occasional API failure) ───────────

def check_sanctions_node(state: InvestigationState) -> dict:
    tx = state["transaction"]
    retries = state.get("sanctions_retries", 0)

    # Simulate a 25 % API failure on the very first attempt so the retry
    # path is exercised in demo runs; skip simulation on retries.
    if retries == 0 and random.random() < 0.25:
        return {
            "sanctions_result": {"match": False, "error": "Sanctions API timeout (simulated)"},
            "sanctions_retries": 1,
            "step_log": ["[check_sanctions] API timeout — will retry."],
        }

    recipient = tx.get("recipient_name", "")
    country = tx.get("recipient_country", "")
    result = check_sanctions(recipient, country)

    flag = "HIT" if result["match"] else "CLEAR"
    log = f"[check_sanctions] {flag} — '{recipient}'"
    if result["match"]:
        log += f" matched '{result['matched_entity']}' on {result['list']} list."
    return {
        "sanctions_result": result,
        "sanctions_retries": retries,
        "step_log": [log],
    }


# ── Node 3: Pattern analysis via LLM ──────────────────────────────────────────

def analyze_pattern(state: InvestigationState) -> dict:
    llm = _get_llm()
    history_str = _history_summary(state.get("customer_history", []))
    prompt = PATTERN_ANALYSIS_PROMPT.format(
        transaction=_fmt(state["transaction"]),
        customer_info=_fmt(state.get("customer_info", {})),
        history=history_str,
        velocity=_fmt(state.get("velocity_metrics", {})),
        sanctions_result=_fmt(state.get("sanctions_result", {})),
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    analysis = response.content.strip()
    return {
        "pattern_analysis": analysis,
        "step_log": ["[analyze_pattern] LLM analysis complete."],
    }


# ── Node 4: Deterministic risk scoring ────────────────────────────────────────

def calculate_risk(state: InvestigationState) -> dict:
    score = 0
    tx = state["transaction"]
    history = state.get("customer_history", [])
    velocity = state.get("velocity_metrics", {})
    sanctions = state.get("sanctions_result", {})
    analysis = state.get("pattern_analysis", "").lower()
    customer_info = state.get("customer_info", {})

    # Sanctions hit is a major flag
    if sanctions.get("match"):
        score += 45

    # New account (< 90 days) with wire transfers is high-risk
    age = customer_info.get("account_age_days", 365)
    if age < 90:
        score += 20
    elif age < 180:
        score += 8

    # Amount vs customer's average
    if history:
        avg = velocity.get("avg_amount", 0)
        if avg > 0 and tx.get("amount", 0) > avg * 5:
            score += 20
        elif avg > 0 and tx.get("amount", 0) > avg * 2:
            score += 10
    else:
        score += 12  # no history at all is mildly suspicious

    # AML typologies in LLM analysis
    if any(kw in analysis for kw in ("structuring", "smurfing")):
        score += 18
    if "layering" in analysis:
        score += 15
    if any(kw in analysis for kw in ("round-tripping", "round tripping", "circular")):
        score += 12
    if "shell" in analysis:
        score += 10
    if "high-risk jurisdiction" in analysis or "high risk jurisdiction" in analysis:
        score += 8

    # Velocity — unusually busy week
    if velocity.get("tx_count_7d", 0) >= 5:
        score += 10
    elif velocity.get("tx_count_7d", 0) >= 3:
        score += 5

    # Structuring flag from velocity metrics (hard rule)
    if velocity.get("structuring_flag"):
        score += 10

    # Cross-border wire
    if tx.get("cross_border"):
        score += 5

    score = min(score, 100)
    risk_level = "low" if score <= 30 else ("medium" if score <= 65 else "high")

    return {
        "risk_score": float(score),
        "risk_level": risk_level,
        "step_log": [f"[calculate_risk] Score: {score}/100 → {risk_level.upper()}"],
    }


# ── Node 5a: Auto-clear (low risk) ────────────────────────────────────────────

def auto_clear(state: InvestigationState) -> dict:
    tx_id = state["transaction"].get("id", "?")
    return {
        "decision": "cleared",
        "report": (
            f"Transaction {tx_id} automatically cleared. "
            f"Risk score {state['risk_score']:.0f}/100 — below threshold. "
            "No suspicious indicators found."
        ),
        "step_log": ["[auto_clear] Transaction cleared. No further action required."],
    }


# ── Node 5b: Draft investigation report (medium risk) ─────────────────────────

def draft_report(state: InvestigationState) -> dict:
    llm = _get_llm()
    prompt = REPORT_PROMPT.format(
        transaction=_fmt(state["transaction"]),
        risk_score=int(state["risk_score"]),
        customer_info=_fmt(state.get("customer_info", {})),
        sanctions_result=_fmt(state.get("sanctions_result", {})),
        pattern_analysis=state.get("pattern_analysis", ""),
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return {
        "report": response.content.strip(),
        "step_log": ["[draft_report] Investigation report drafted."],
    }


# ── Node 5c: Human review (medium risk — pauses for analyst input) ────────────

def human_review(state: InvestigationState) -> dict:
    """
    LangGraph interrupt: pauses graph execution and surfaces the report
    to an analyst. The caller resumes by passing Command(resume=decision).
    decision must be one of: "cleared" | "escalated" | "sar_filed"
    """
    decision = interrupt({
        "prompt": "Review the report and select a decision.",
        "report": state.get("report", ""),
        "risk_score": state.get("risk_score", 0),
        "transaction": state.get("transaction", {}),
    })
    return {
        "decision": decision,
        "step_log": [f"[human_review] Analyst decision: {decision}"],
    }


# ── Node 6a: Draft SAR (high risk) ────────────────────────────────────────────

def draft_sar(state: InvestigationState) -> dict:
    llm = _get_llm()
    history_summary = _history_summary(state.get("customer_history", []))
    prompt = SAR_PROMPT.format(
        transaction=_fmt(state["transaction"]),
        risk_score=int(state["risk_score"]),
        customer_info=_fmt(state.get("customer_info", {})),
        sanctions_result=_fmt(state.get("sanctions_result", {})),
        pattern_analysis=state.get("pattern_analysis", ""),
    )
    # Enrich prompt with history summary
    full_prompt = prompt + f"\n\nCUSTOMER HISTORY SUMMARY:\n{history_summary}"
    response = llm.invoke([HumanMessage(content=full_prompt)])
    return {
        "sar_text": response.content.strip(),
        "step_log": ["[draft_sar] SAR narrative drafted."],
    }


# ── Node 6b: Escalate / file SAR ──────────────────────────────────────────────

def escalate(state: InvestigationState) -> dict:
    tx_id = state["transaction"].get("id", "?")
    return {
        "decision": "sar_filed",
        "step_log": [
            f"[escalate] Transaction {tx_id} escalated. "
            "SAR queued for FinCEN submission."
        ],
    }


# ── Routing functions (used by conditional edges) ─────────────────────────────

def route_after_sanctions(state: InvestigationState) -> str:
    """Retry sanctions check if the API failed and we haven't exceeded 3 retries."""
    if state["sanctions_result"].get("error") and state.get("sanctions_retries", 0) < 3:
        return "check_sanctions_node"
    return "analyze_pattern"


def route_by_risk(state: InvestigationState) -> str:
    level = state.get("risk_level", "low")
    if level == "low":
        return "auto_clear"
    elif level == "medium":
        return "draft_report"
    else:
        return "draft_sar"


def route_after_human(state: InvestigationState) -> str:
    decision = state.get("decision", "escalated")
    if decision == "cleared":
        return "__end__"
    return "escalate"
