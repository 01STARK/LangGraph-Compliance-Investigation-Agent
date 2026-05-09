"""
CLI demo — runs three representative transactions through the compliance agent.

Usage:
    python demo.py
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

load_dotenv()

# ── Make sure the project root is on the path ──────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from agent.graph import compile_graph

DEMO_TRANSACTIONS = [
    {
        "label": "LOW RISK — Alice, domestic ACH",
        "state": {
            "transaction": {
                "id": "TXN-DEMO-001",
                "customer_id": "c001",
                "amount": 450.00,
                "currency": "USD",
                "type": "ACH",
                "recipient_name": "Netflix",
                "recipient_country": "US",
                "cross_border": False,
                "timestamp": "2025-05-09T10:30:00",
            }
        },
        "human_decision": None,
    },
    {
        "label": "MEDIUM RISK — Maria, offshore wire",
        "state": {
            "transaction": {
                "id": "TXN-DEMO-002",
                "customer_id": "c002",
                "amount": 8500.00,
                "currency": "USD",
                "type": "Wire",
                "recipient_name": "Unknown Offshore LLC",
                "recipient_country": "Cayman Islands",
                "cross_border": True,
                "timestamp": "2025-05-09T14:15:00",
            }
        },
        "human_decision": "escalated",  # analyst escalates
    },
    {
        "label": "HIGH RISK — James, structuring + sanctioned recipient",
        "state": {
            "transaction": {
                "id": "TXN-DEMO-003",
                "customer_id": "c003",
                "amount": 9800.00,
                "currency": "USD",
                "type": "Wire",
                "recipient_name": "Sunrise Financial SA",
                "recipient_country": "Panama",
                "cross_border": True,
                "timestamp": "2025-05-09T09:00:00",
            }
        },
        "human_decision": None,
    },
]

SEPARATOR = "=" * 70

def _empty_state(tx: dict) -> dict:
    return {
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


def run_demo():
    print(f"\n{SEPARATOR}")
    print("  LangGraph Compliance Investigation Agent — CLI Demo")
    print(SEPARATOR)

    memory = MemorySaver()
    app = compile_graph(checkpointer=memory)

    for i, demo in enumerate(DEMO_TRANSACTIONS, 1):
        print(f"\n{'─'*70}")
        print(f"  Case {i}: {demo['label']}")
        print("─" * 70)

        thread_id = f"demo-{i}"
        config = {"configurable": {"thread_id": thread_id}}
        initial = _empty_state(demo["state"]["transaction"])
        awaiting_human = False
        final_state = None

        try:
            for event in app.stream(initial, config, stream_mode="updates"):
                for node_name, node_output in event.items():
                    logs = node_output.get("step_log", [])
                    for log in logs:
                        print(f"  {log}")
        except Exception as e:
            if "interrupt" in str(e).lower() or "GraphInterrupt" in type(e).__name__:
                awaiting_human = True
            else:
                print(f"  ERROR: {e}")
                continue

        if awaiting_human:
            decision = demo.get("human_decision", "escalated")
            print(f"\n  [HUMAN REVIEW] Analyst decision → {decision.upper()}")
            try:
                for event in app.stream(
                    Command(resume=decision), config, stream_mode="updates"
                ):
                    for node_name, node_output in event.items():
                        logs = node_output.get("step_log", [])
                        for log in logs:
                            print(f"  {log}")
            except Exception as e:
                print(f"  ERROR resuming: {e}")

        final_state = app.get_state(config).values

        if final_state:
            decision = final_state.get("decision", "unknown")
            score = final_state.get("risk_score", 0)
            level = final_state.get("risk_level", "")
            print(f"\n  RESULT: {decision.upper()}  |  Score: {score:.0f}/100  |  Level: {level.upper()}")

            if final_state.get("sar_text"):
                print(f"\n  SAR NARRATIVE (excerpt):")
                lines = final_state["sar_text"].split("\n")[:6]
                for line in lines:
                    print(f"    {line}")
                print("    ...")

        print()

    print(SEPARATOR)
    print("  Demo complete.")
    print(SEPARATOR + "\n")


if __name__ == "__main__":
    run_demo()
