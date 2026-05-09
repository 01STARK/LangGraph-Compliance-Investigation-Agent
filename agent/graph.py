"""
Assembles and compiles the LangGraph investigation workflow.

Graph topology:
    START
      └─► fetch_history
            └─► check_sanctions_node ─┐ (retry loop if API error)
                  └─────────────────◄─┘
                        └─► analyze_pattern
                              └─► calculate_risk
                                    ├─► [low]    auto_clear ──────────► END
                                    ├─► [medium] draft_report
                                    │               └─► human_review  ──► (cleared) END
                                    │                         └──────────► (escalated) escalate → END
                                    └─► [high]   draft_sar
                                                    └─► escalate ──────► END
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from agent.state import InvestigationState
from agent.nodes import (
    fetch_history,
    check_sanctions_node,
    analyze_pattern,
    calculate_risk,
    auto_clear,
    draft_report,
    human_review,
    draft_sar,
    escalate,
    route_after_sanctions,
    route_by_risk,
    route_after_human,
)


def build_graph() -> StateGraph:
    g = StateGraph(InvestigationState)

    # Register nodes
    g.add_node("fetch_history",       fetch_history)
    g.add_node("check_sanctions_node", check_sanctions_node)
    g.add_node("analyze_pattern",     analyze_pattern)
    g.add_node("calculate_risk",      calculate_risk)
    g.add_node("auto_clear",          auto_clear)
    g.add_node("draft_report",        draft_report)
    g.add_node("human_review",        human_review)
    g.add_node("draft_sar",           draft_sar)
    g.add_node("escalate",            escalate)

    # Fixed edges
    g.add_edge(START,              "fetch_history")
    g.add_edge("fetch_history",    "check_sanctions_node")
    g.add_edge("analyze_pattern",  "calculate_risk")
    g.add_edge("auto_clear",       END)
    g.add_edge("draft_report",     "human_review")
    g.add_edge("draft_sar",        "escalate")
    g.add_edge("escalate",         END)

    # Conditional: retry sanctions or continue
    g.add_conditional_edges(
        "check_sanctions_node",
        route_after_sanctions,
        {
            "check_sanctions_node": "check_sanctions_node",
            "analyze_pattern":      "analyze_pattern",
        },
    )

    # Conditional: branch by risk level
    g.add_conditional_edges(
        "calculate_risk",
        route_by_risk,
        {
            "auto_clear":  "auto_clear",
            "draft_report": "draft_report",
            "draft_sar":   "draft_sar",
        },
    )

    # Conditional: route after human review decision
    g.add_conditional_edges(
        "human_review",
        route_after_human,
        {
            "__end__": END,
            "escalate": "escalate",
        },
    )

    return g


def compile_graph(checkpointer: MemorySaver | None = None):
    """Return a compiled LangGraph app, optionally with a checkpointer for H-I-T-L."""
    g = build_graph()
    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    return g.compile()
